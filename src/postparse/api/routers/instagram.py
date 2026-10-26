"""Instagram endpoints: extraction jobs and saved posts (schema v2 items).

* ``POST /extract`` starts an ``instagram_extract`` job
  (:meth:`ExtractionService.instagram`, never interactive). Credentials come
  from the request or ``INSTAGRAM_USERNAME`` / ``INSTAGRAM_PASSWORD``; the
  session file lives in ``Settings.sessions_dir`` like for the CLI.
* ``GET /posts`` lists posts with filters and keyset pagination (``cursor``);
  ``offset`` is deprecated and translated into a cursor.
* ``GET /jobs/{job_id}`` and ``WS /ws/progress/{job_id}`` are aliases of the
  unified job endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, status

from postparse.api.dependencies import (
    get_current_websocket_user,
    get_extraction_service,
    get_job_manager,
    get_job_runner,
    get_optional_auth,
    get_query_service,
    get_websocket_manager,
)
from postparse.api.jobs.kinds import instagram_extract_job, with_credentials
from postparse.api.jobs.runner import JobRunner
from postparse.api.routers._common import (
    item_filter_or_400,
    job_or_404,
    resolve_cursor,
    serve_job_websocket,
)
from postparse.api.routers._views import instagram_post
from postparse.api.schemas import (
    ExtractionStatus,
    InstagramExtractRequest,
    InstagramExtractResponse,
    InstagramPostSchema,
    JobStatusResponse,
    PaginatedResponse,
)
from postparse.api.services.job_manager import JobManager
from postparse.api.services.websocket_manager import WebSocketManager
from postparse.services.extraction import ExtractionService
from postparse.services.query import QueryService

router = APIRouter(
    prefix="/api/v1/instagram",
    tags=["instagram"],
    responses={
        400: {"description": "Invalid request"},
        401: {"description": "Unauthorized"},
        404: {"description": "Resource not found"},
    },
)


@router.post(
    "/extract",
    response_model=InstagramExtractResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an Instagram extraction job",
    description="""
    Collect saved Instagram posts into the database in the background.

    `force_update=true` walks the whole saved feed and updates known posts;
    otherwise the run stops after `stop_after_known` consecutive known posts.
    A missing or expired login fails the job with `error_code=auth_required`
    (log in once with `postparse extract instagram` in a terminal); rate limits
    fail it with `rate_limited`. Counts of partial runs are kept in `result`.
    """,
)
async def extract_posts(
    request: InstagramExtractRequest,
    extraction: ExtractionService = Depends(get_extraction_service),
    runner: JobRunner = Depends(get_job_runner),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> InstagramExtractResponse:
    """Start the extraction job and return its id."""
    if request.use_api:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Instagram API-based extraction (use_api=true) is not supported; "
            "use use_api=false (Instaloader).",
        )
    service = with_credentials(
        extraction,
        {
            "INSTAGRAM_USERNAME": request.username,
            "INSTAGRAM_PASSWORD": (
                request.password.get_secret_value() if request.password else None
            ),
        },
    )
    stop_after_known = None if request.force_update else request.stop_after_known
    params = {
        "username": request.username,
        "limit": request.limit,
        "force_update": request.force_update,
        "stop_after_known": stop_after_known,
        "refresh_dates": request.refresh_dates,
    }
    job_id = runner.submit(
        "instagram_extract",
        params,
        instagram_extract_job(
            service,
            limit=request.limit,
            stop_after_known=stop_after_known,
            username=request.username,
            refresh_dates=request.refresh_dates,
        ),
        total=request.limit,
    )
    return InstagramExtractResponse(
        job_id=job_id, status=ExtractionStatus.PENDING, post_count=0, estimated_time=None
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Check extraction job status",
    description="Alias of `GET /api/v1/jobs/{job_id}`.",
)
def get_job_status(
    job_id: str,
    jobs: JobManager = Depends(get_job_manager),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> JobStatusResponse:
    """Return the status of a job."""
    return JobStatusResponse.from_job(job_or_404(jobs, job_id))


@router.get(
    "/posts",
    response_model=PaginatedResponse[InstagramPostSchema],
    summary="List saved Instagram posts",
    description="""
    Newest first (`created_at`, falling back to the collection time for posts
    without a date). Filters: `owner_username`, `tags` (any of; `#tag`,
    `@mention` or a bare name), `q` (full text). Paginate with `next_cursor`;
    `offset` is deprecated (translated into a cursor, 400 together with `cursor`).
    """,
)
def get_posts(
    limit: int = Query(default=50, ge=1, le=100, description="Maximum results to return"),
    offset: int = Query(
        default=0,
        ge=0,
        deprecated=True,
        description="Deprecated: number of results to skip; use cursor",
    ),
    owner_username: str | None = Query(default=None, description="Filter by owner"),
    cursor: str | None = Query(default=None, description="next_cursor of the previous page"),
    tags: list[str] = Query(default=[], description="Tag filter (any of)"),
    q: str | None = Query(default=None, description="Full-text query"),
    query: QueryService = Depends(get_query_service),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> PaginatedResponse[InstagramPostSchema]:
    """List posts."""
    item_filter = item_filter_or_400(
        source="instagram", q=q, tags=tags, authors=[owner_username] if owner_username else []
    )
    position, exhausted = resolve_cursor(query, item_filter, cursor, offset)
    total = query.count(item_filter)
    if exhausted:
        return PaginatedResponse(
            items=[], total=total, limit=limit, offset=offset, next_cursor=None, has_more=False
        )
    page = query.search(item_filter, cursor=position, limit=limit)
    details = query.source_details([v.id for v in page.items])
    posts = [instagram_post(v, details[v.id][0], details[v.id][2]) for v in page.items]
    return PaginatedResponse(
        items=posts,
        total=total,
        limit=limit,
        offset=offset,
        next_cursor=page.next_cursor,
        has_more=page.next_cursor is not None,
    )


@router.get(
    "/posts/{shortcode}",
    response_model=InstagramPostSchema,
    summary="Get one Instagram post",
    description="Look up a post by shortcode (`metadata.item_id` links to `/api/v1/items/{id}`).",
)
def get_post(
    shortcode: str,
    query: QueryService = Depends(get_query_service),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> InstagramPostSchema:
    """Return one post."""
    item_id = query.item_id_for("instagram", shortcode)
    detail = query.get_item(item_id) if item_id is not None else None
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post with shortcode {shortcode} not found",
        )
    return instagram_post(detail.item, detail.instagram, [m.media for m in detail.media])


@router.websocket("/ws/progress/{job_id}")
async def websocket_progress(
    websocket: WebSocket,
    job_id: str,
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    jobs: JobManager = Depends(get_job_manager),
    user: dict[str, Any] | None = Depends(get_current_websocket_user),
) -> None:
    """Alias of ``WS /api/v1/jobs/{job_id}/ws``."""
    await serve_job_websocket(websocket, job_id, ws_manager, jobs)
