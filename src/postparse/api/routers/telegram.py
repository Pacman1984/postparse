"""Telegram endpoints: extraction jobs and saved messages (schema v2 items).

* ``POST /extract`` starts a ``telegram_extract`` job
  (:meth:`ExtractionService.telegram_async`, never interactive). Request
  credentials override ``TELEGRAM_API_ID`` / ``TELEGRAM_API_HASH`` /
  ``TELEGRAM_PHONE``; the session file lives in ``Settings.sessions_dir`` like
  for the CLI, so a login done with ``postparse extract telegram`` is reused.
* ``GET /messages`` lists messages with filters and keyset pagination;
  ``channel_username`` filters on the item author (the forwarded-from name).
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
from postparse.api.jobs.kinds import telegram_extract_job, with_credentials
from postparse.api.jobs.runner import JobRunner
from postparse.api.routers._common import (
    item_filter_or_400,
    job_or_404,
    resolve_cursor,
    serve_job_websocket,
)
from postparse.api.routers._views import telegram_message
from postparse.api.schemas import (
    ExtractionStatus,
    JobStatusResponse,
    PaginatedResponse,
    TelegramExtractRequest,
    TelegramExtractResponse,
    TelegramMessageSchema,
)
from postparse.api.services.job_manager import JobManager
from postparse.api.services.websocket_manager import WebSocketManager
from postparse.services.extraction import ExtractionService
from postparse.services.query import QueryService

router = APIRouter(
    prefix="/api/v1/telegram",
    tags=["telegram"],
    responses={
        400: {"description": "Invalid request"},
        401: {"description": "Unauthorized"},
        404: {"description": "Resource not found"},
    },
)


@router.post(
    "/extract",
    response_model=TelegramExtractResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a Telegram extraction job",
    description="""
    Collect Telegram Saved Messages into the database in the background.

    Only new messages are read unless `force_update=true` (re-read and update
    everything). The API never prompts for a login code: without an authorized
    session the job fails with `error_code=auth_required` (log in once with
    `postparse extract telegram` in a terminal). FloodWaits fail it with
    `rate_limited`. `max_requests_per_session` is accepted for compatibility
    and ignored.
    """,
)
async def extract_messages(
    request: TelegramExtractRequest,
    extraction: ExtractionService = Depends(get_extraction_service),
    runner: JobRunner = Depends(get_job_runner),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> TelegramExtractResponse:
    """Start the extraction job and return its id."""
    service = with_credentials(
        extraction,
        {
            "TELEGRAM_API_ID": str(request.api_id),
            "TELEGRAM_API_HASH": request.api_hash,
            "TELEGRAM_PHONE": request.phone,
        },
    )
    params = {
        "limit": request.limit,
        "force_update": request.force_update,
        "max_requests_per_session": request.max_requests_per_session,
        "has_phone": bool(request.phone),
    }
    job_id = runner.submit(
        "telegram_extract",
        params,
        telegram_extract_job(service, limit=request.limit, full=request.force_update),
        total=request.limit,
    )
    return TelegramExtractResponse(
        job_id=job_id, status=ExtractionStatus.PENDING, message_count=0, estimated_time=None
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
    "/messages",
    response_model=PaginatedResponse[TelegramMessageSchema],
    summary="List saved Telegram messages",
    description="""
    Newest first. Filters: `channel_username` (item author, i.e. the
    forwarded-from channel/user name), `tags` (any of), `q` (full text).
    Paginate with `next_cursor`; `offset` is deprecated (translated into a
    cursor, 400 together with `cursor`).
    """,
)
def get_messages(
    limit: int = Query(default=50, ge=1, le=100, description="Maximum results to return"),
    offset: int = Query(
        default=0,
        ge=0,
        deprecated=True,
        description="Deprecated: number of results to skip; use cursor",
    ),
    channel_username: str | None = Query(default=None, description="Filter by author/channel"),
    cursor: str | None = Query(default=None, description="next_cursor of the previous page"),
    tags: list[str] = Query(default=[], description="Tag filter (any of)"),
    q: str | None = Query(default=None, description="Full-text query"),
    query: QueryService = Depends(get_query_service),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> PaginatedResponse[TelegramMessageSchema]:
    """List messages."""
    item_filter = item_filter_or_400(
        source="telegram",
        q=q,
        tags=tags,
        authors=[channel_username.lstrip("@")] if channel_username else [],
    )
    position, exhausted = resolve_cursor(query, item_filter, cursor, offset)
    total = query.count(item_filter)
    if exhausted:
        return PaginatedResponse(
            items=[], total=total, limit=limit, offset=offset, next_cursor=None, has_more=False
        )
    page = query.search(item_filter, cursor=position, limit=limit)
    details = query.source_details([v.id for v in page.items])
    messages = [telegram_message(v, details[v.id][1], details[v.id][2]) for v in page.items]
    return PaginatedResponse(
        items=messages,
        total=total,
        limit=limit,
        offset=offset,
        next_cursor=page.next_cursor,
        has_more=page.next_cursor is not None,
    )


@router.get(
    "/messages/{message_id}",
    response_model=TelegramMessageSchema,
    summary="Get one Telegram message",
    description="""
    Look up a message by Telegram message id (newest match; pass `chat_id`
    to disambiguate). `metadata.item_id` links to `/api/v1/items/{id}`.
    """,
)
def get_message(
    message_id: int,
    chat_id: int | None = Query(default=None, description="Restrict to one chat"),
    query: QueryService = Depends(get_query_service),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> TelegramMessageSchema:
    """Return one message."""
    item_id = query.telegram_item_id(message_id, chat_id)
    detail = query.get_item(item_id) if item_id is not None else None
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Message with ID {message_id} not found",
        )
    return telegram_message(detail.item, detail.telegram, [m.media for m in detail.media])


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
