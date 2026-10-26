"""Search endpoints over schema v2 items (via :class:`QueryService`).

``/posts`` (Instagram) and ``/messages`` (Telegram) keep their response
format; filters are query parameters: ``hashtags``/``tags`` (repeatable, any
of), ``start_date``/``end_date`` (``YYYY-MM-DD`` or ISO datetime, inclusive),
``content_type``, ``owner_username``/``channel_username`` (author), ``q``
(full text) plus keyset pagination with ``cursor``. Results are cached when
``[api.cache] enabled`` (``X-Cache-Status: HIT|MISS``); jobs and persisted
classifications invalidate the cache.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from postparse.api.dependencies import get_cache_manager, get_optional_auth, get_query_service
from postparse.api.routers._common import CONTENT_TYPE_KINDS, item_filter_or_400
from postparse.api.schemas import (
    ContentTypeFilter,
    MessageSearchResult,
    PaginationMetadata,
    PostSearchResult,
    SearchResponse,
)
from postparse.api.services.cache_manager import CacheManager
from postparse.core.db.models import ItemFilter
from postparse.services.query import InvalidCursorError, ItemView, QueryService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/search",
    tags=["search"],
    responses={400: {"description": "Invalid request"}, 401: {"description": "Unauthorized"}},
)


def _parse_bound(value: str | None, name: str) -> date | datetime | None:
    """Parse ``YYYY-MM-DD`` (whole day) or an ISO datetime (naive = UTC)."""
    if not value:
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {name} {value!r}; use YYYY-MM-DD or an ISO datetime",
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _as_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _build_filter(
    source: str,
    *,
    tags: list[str],
    authors: list[str],
    content_type: ContentTypeFilter | None,
    start_date: str | None,
    end_date: str | None,
    q: str | None,
) -> ItemFilter:
    kinds = CONTENT_TYPE_KINDS[content_type.value] if content_type else ()
    base = item_filter_or_400(source=source, tags=tags, authors=authors, kinds=kinds, q=q)
    start = _parse_bound(start_date, "start_date")
    end = _parse_bound(end_date, "end_date")
    if start is not None and end is not None and _as_datetime(start) > _as_datetime(end):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="start_date is after end_date"
        )
    return dataclasses.replace(base, date_from=start, date_to=end)


def _filters_applied(**values: Any) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v not in (None, [], "")}


def _search(
    resource: str,
    response: Response,
    cache: CacheManager,
    query: QueryService,
    item_filter: ItemFilter,
    *,
    cursor: str | None,
    limit: int,
    filters_applied: dict[str, Any],
    convert: Callable[[list[ItemView], QueryService], list[Any]],
) -> dict[str, Any]:
    """Run (or fetch from cache) one search and return the response payload."""
    key = cache.key(resource, filters=filters_applied, cursor=cursor, limit=limit)
    cached = cache.get(key)
    if cached is not None:
        response.headers["X-Cache-Status"] = "HIT"
        return cached
    response.headers["X-Cache-Status"] = "MISS"
    try:
        page = query.search(item_filter, cursor=cursor, limit=limit)
    except InvalidCursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid cursor: {exc}"
        ) from exc
    payload = SearchResponse[Any](
        results=convert(page.items, query),
        total_count=query.count(item_filter),
        filters_applied=filters_applied,
        pagination=PaginationMetadata(
            cursor=cursor,
            next_cursor=page.next_cursor,
            has_more=page.next_cursor is not None,
            limit=limit,
        ),
    ).model_dump(mode="json")
    cache.set(key, payload, ttl=cache.search_ttl)
    return payload


def _hashtags(view: ItemView) -> list[str]:
    return [t[1:] for t in view.tags if t.startswith("#")]


def _posts(views: list[ItemView], query: QueryService) -> list[PostSearchResult]:
    details = query.source_details([v.id for v in views])
    results = []
    for v in views:
        ig, _, media = details[v.id]
        results.append(
            PostSearchResult(
                shortcode=ig.shortcode if ig else v.external_id,
                owner_username=v.author or "",
                caption=v.text[:200] if v.text else None,
                is_video=v.kind == "video" or any(m.media_type == "video" for m in media),
                likes=max(0, (ig.likes if ig else 0) or 0),
                hashtags=_hashtags(v),
                created_at=v.created_at,
                item_id=v.id,
                snippet=v.snippet,
            )
        )
    return results


def _messages(views: list[ItemView], query: QueryService) -> list[MessageSearchResult]:
    details = query.source_details([v.id for v in views])
    results = []
    for v in views:
        _, tg, _ = details[v.id]
        tail = v.external_id.rpartition(":")[2]
        results.append(
            MessageSearchResult(
                message_id=tg.message_id if tg else (int(tail) if tail.isdigit() else 0),
                chat_id=tg.chat_id if tg else None,
                channel_username=v.author,
                content=v.text[:200] if v.text else None,
                content_type=v.kind,
                hashtags=_hashtags(v),
                created_at=v.created_at,
                item_id=v.id,
                snippet=v.snippet,
            )
        )
    return results


@router.get(
    "/posts",
    response_model=SearchResponse[PostSearchResult],
    summary="Search Instagram posts",
    description="""
    Filters (all combined with AND): `hashtags`/`tags` (repeatable, any of),
    `start_date`/`end_date`, `content_type` (`image` includes carousels),
    `owner_username`, `q` (full text; quoted phrases and `prefix*`). Results
    are newest first; posts without a date sort by collection time.
    """,
)
def search_posts(
    response: Response,
    hashtags: list[str] = Query(default=[], description="Hashtags (any of)"),
    tags: list[str] = Query(default=[], description="Tags: #hashtag, @mention or name"),
    start_date: str | None = Query(default=None, description="From (inclusive)"),
    end_date: str | None = Query(default=None, description="To (inclusive)"),
    content_type: ContentTypeFilter | None = Query(default=None),
    owner_username: str | None = Query(default=None, description="Post owner"),
    q: str | None = Query(default=None, description="Full-text query"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, description="next_cursor of the previous page"),
    query: QueryService = Depends(get_query_service),
    cache: CacheManager = Depends(get_cache_manager),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> dict[str, Any]:
    """Search Instagram posts."""
    all_tags = [*hashtags, *tags]
    item_filter = _build_filter(
        "instagram",
        tags=all_tags,
        authors=[owner_username] if owner_username else [],
        content_type=content_type,
        start_date=start_date,
        end_date=end_date,
        q=q,
    )
    applied = _filters_applied(
        hashtags=all_tags,
        date_range=(
            {"start_date": start_date, "end_date": end_date} if start_date or end_date else None
        ),
        content_type=content_type.value if content_type else None,
        owner_username=owner_username,
        q=q,
    )
    return _search(
        "search:posts",
        response,
        cache,
        query,
        item_filter,
        cursor=cursor,
        limit=limit,
        filters_applied=applied,
        convert=_posts,
    )


@router.get(
    "/messages",
    response_model=SearchResponse[MessageSearchResult],
    summary="Search Telegram messages",
    description="""
    Filters (all combined with AND): `hashtags`/`tags`, `start_date`/`end_date`,
    `content_type`, `channel_username` (author: forwarded-from name), `q`.
    """,
)
def search_messages(
    response: Response,
    hashtags: list[str] = Query(default=[], description="Hashtags (any of)"),
    tags: list[str] = Query(default=[], description="Tags: #hashtag, @mention or name"),
    start_date: str | None = Query(default=None, description="From (inclusive)"),
    end_date: str | None = Query(default=None, description="To (inclusive)"),
    content_type: ContentTypeFilter | None = Query(default=None),
    channel_username: str | None = Query(default=None, description="Author / channel"),
    q: str | None = Query(default=None, description="Full-text query"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, description="next_cursor of the previous page"),
    query: QueryService = Depends(get_query_service),
    cache: CacheManager = Depends(get_cache_manager),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> dict[str, Any]:
    """Search Telegram messages."""
    all_tags = [*hashtags, *tags]
    author = channel_username.lstrip("@") if channel_username else None
    item_filter = _build_filter(
        "telegram",
        tags=all_tags,
        authors=[author] if author else [],
        content_type=content_type,
        start_date=start_date,
        end_date=end_date,
        q=q,
    )
    applied = _filters_applied(
        hashtags=all_tags,
        date_range=(
            {"start_date": start_date, "end_date": end_date} if start_date or end_date else None
        ),
        content_type=content_type.value if content_type else None,
        channel_username=author,
        q=q,
    )
    return _search(
        "search:messages",
        response,
        cache,
        query,
        item_filter,
        cursor=cursor,
        limit=limit,
        filters_applied=applied,
        convert=_messages,
    )


@router.get(
    "/hashtags",
    response_model=dict[str, list[dict[str, Any]]],
    summary="List hashtags with usage counts",
    description="""
    Most used hashtags across both sources: `{"tag", "count", "source"}` with
    `source` = `instagram`, `telegram` or `both`, plus per-source counts.
    """,
)
def list_hashtags(
    limit: int = Query(default=100, ge=1, le=500, description="Maximum hashtags to return"),
    query: QueryService = Depends(get_query_service),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> dict[str, list[dict[str, Any]]]:
    """List hashtags."""
    rows = query.tag_counts_by_source("hashtag", limit=limit)
    hashtags = []
    for row in rows:
        ig, tg = int(row["instagram"]), int(row["telegram"])
        source = "both" if ig and tg else ("instagram" if ig else "telegram")
        hashtags.append(
            {
                "tag": row["tag"],
                "count": row["count"],
                "source": source,
                "instagram": ig,
                "telegram": tg,
            }
        )
    return {"hashtags": hashtags}
