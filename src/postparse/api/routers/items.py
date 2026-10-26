"""Unified item endpoints over schema v2 (both sources).

``GET /api/v1/items`` accepts every :class:`~postparse.core.db.models.ItemFilter`
field as query parameters (the CLI's ``search`` options):

* ``q`` full text (snippets in ``snippet`` with ``[term]`` markers)
* ``source`` (``instagram`` / ``telegram``), ``tag``, ``author``, ``kind``
  (repeatable, any of)
* ``label`` (repeatable ``taxonomy[:label]``, one taxonomy per query)
* ``date_from`` / ``date_to`` (``YYYY-MM-DD``, inclusive, UTC)
* ``has_transcript`` (``true`` / ``false``)

Pagination is keyset based: pass ``next_cursor`` back as ``cursor``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from postparse.api.dependencies import get_cache_manager, get_optional_auth, get_query_service
from postparse.api.routers._common import item_filter_or_400, resolve_cursor
from postparse.api.routers._views import (
    item_detail,
    item_schema,
    summary_response,
    transcript_response,
)
from postparse.api.schemas.items import (
    ItemDetailResponse,
    ItemListResponse,
    SummaryResponse,
    TranscriptResponse,
)
from postparse.api.services.cache_manager import CacheManager
from postparse.services.query import MAX_PAGE_SIZE, ItemDetail, QueryService

router = APIRouter(
    prefix="/api/v1/items",
    tags=["items"],
    responses={400: {"description": "Invalid filter"}, 404: {"description": "Item not found"}},
)


def _detail_or_404(query: QueryService, item_id: int) -> ItemDetail:
    detail = query.get_item(item_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Item {item_id} not found"
        )
    return detail


@router.get(
    "",
    response_model=ItemListResponse,
    summary="List and search items",
    description=__doc__,
)
def list_items(
    response: Response,
    q: str | None = Query(default=None, description="Full-text query"),
    source: str | None = Query(default=None, pattern="^(instagram|telegram|all)$"),
    tag: list[str] = Query(default=[], description="Tag (any of): #hashtag, @mention, name"),
    author: list[str] = Query(default=[], description="Author (any of, exact)"),
    kind: list[str] = Query(default=[], description="Item kind (any of)"),
    label: list[str] = Query(default=[], description="taxonomy[:label] (one taxonomy)"),
    date_from: str | None = Query(default=None, description="YYYY-MM-DD (inclusive)"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD (inclusive)"),
    has_transcript: bool | None = Query(default=None),
    cursor: str | None = Query(default=None, description="next_cursor of the previous page"),
    offset: int = Query(
        default=0,
        ge=0,
        deprecated=True,
        description="Deprecated row offset (translated into a cursor)",
    ),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    count: bool = Query(default=True, description="Include the total number of matches"),
    query: QueryService = Depends(get_query_service),
    cache: CacheManager = Depends(get_cache_manager),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> dict[str, Any]:
    """Return one page of matching items, newest first."""
    item_filter = item_filter_or_400(
        q=q,
        source=source,
        tags=tag,
        authors=author,
        kinds=kind,
        labels=label,
        date_from=date_from,
        date_to=date_to,
        has_transcript=has_transcript,
    )
    key = cache.key(
        "items",
        q=q,
        source=source,
        tag=tag,
        author=author,
        kind=kind,
        label=label,
        date_from=date_from,
        date_to=date_to,
        has_transcript=has_transcript,
        cursor=cursor,
        offset=offset or None,
        limit=limit,
        count=count,
    )
    cached = cache.get(key)
    if cached is not None:
        response.headers["X-Cache-Status"] = "HIT"
        return cached
    response.headers["X-Cache-Status"] = "MISS"
    position, exhausted = resolve_cursor(query, item_filter, cursor, offset)
    total = query.count(item_filter) if count else None
    if exhausted:
        payload = ItemListResponse(
            items=[], total=total, limit=limit, cursor=cursor, next_cursor=None, has_more=False
        )
    else:
        page = query.search(item_filter, cursor=position, limit=limit)
        payload = ItemListResponse(
            items=[item_schema(v) for v in page.items],
            total=total,
            limit=limit,
            cursor=cursor,
            next_cursor=page.next_cursor,
            has_more=page.next_cursor is not None,
        )
    data = payload.model_dump(mode="json")
    cache.set(key, data, ttl=cache.search_ttl)
    return data


@router.get(
    "/{item_id}",
    response_model=ItemDetailResponse,
    summary="Get one item with everything known about it",
    description="""
    Tags, media with transcript status, transcript text and segments, the
    latest summary (split into `summary` and `key_points`), links with their
    newest successful fetch and the current classifications.
    """,
)
def get_item(
    item_id: int,
    query: QueryService = Depends(get_query_service),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> ItemDetailResponse:
    """Return the detail of one item."""
    return item_detail(_detail_or_404(query, item_id))


@router.get(
    "/{item_id}/transcript",
    response_model=TranscriptResponse,
    summary="Get the transcripts of an item",
    description="Current transcript (text and segments) per media; `text` joins all of them.",
)
def get_transcript(
    item_id: int,
    query: QueryService = Depends(get_query_service),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> TranscriptResponse:
    """Return the transcripts of one item."""
    return transcript_response(_detail_or_404(query, item_id))


@router.get(
    "/{item_id}/summary",
    response_model=SummaryResponse,
    summary="Get the latest summary of an item",
    description="404 when the item does not exist or has no summary yet.",
)
def get_summary(
    item_id: int,
    query: QueryService = Depends(get_query_service),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> SummaryResponse:
    """Return the latest summary."""
    detail = _detail_or_404(query, item_id)
    if detail.summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Item {item_id} has no summary"
        )
    return summary_response(detail.summary)
