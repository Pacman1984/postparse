"""Helpers shared by the API routers (filters, pagination, jobs, WebSockets)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import click
from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status

from postparse.api.schemas.pipeline import JobAcceptedResponse
from postparse.api.services.job_manager import JobManager
from postparse.api.services.websocket_manager import WebSocketManager
from postparse.cli.filters import KINDS, build_item_filter
from postparse.core.db.models import ItemFilter
from postparse.services.query import InvalidCursorError, QueryService, decode_cursor

__all__ = [
    "CONTENT_TYPE_KINDS",
    "accepted",
    "job_or_404",
    "item_filter_or_400",
    "resolve_cursor",
    "serve_job_websocket",
]

logger = logging.getLogger(__name__)

#: Old ``content_type`` filter values mapped onto schema v2 item kinds.
CONTENT_TYPE_KINDS: dict[str, tuple[str, ...]] = {
    "text": ("text",),
    "image": ("image", "carousel"),
    "photo": ("image", "carousel"),
    "video": ("video",),
    "document": ("document",),
    "audio": ("audio",),
    "carousel": ("carousel",),
    "other": ("other",),
}


def item_filter_or_400(
    *,
    q: str | None = None,
    source: str | None = None,
    tags: Sequence[str] = (),
    authors: Sequence[str] = (),
    kinds: Sequence[str] = (),
    labels: Sequence[str] = (),
    date_from: str | None = None,
    date_to: str | None = None,
    has_transcript: bool | None = None,
) -> ItemFilter:
    """Build an :class:`ItemFilter` exactly like the CLI (``build_item_filter``).

    Raises:
        HTTPException: 400 for invalid dates/labels or unknown kinds.
    """
    unknown = sorted(set(kinds) - set(KINDS))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown kind(s): {', '.join(unknown)}",
        )
    try:
        return build_item_filter(
            q=q, source=source, tags=tags, authors=authors, kinds=kinds, labels=labels,
            date_from=date_from, date_to=date_to, has_transcript=has_transcript,
        )
    except click.BadParameter as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.format_message()
        ) from exc


def resolve_cursor(
    query: QueryService, item_filter: ItemFilter, cursor: str | None, offset: int | None
) -> tuple[str | None, bool]:
    """Validate ``cursor`` or translate the deprecated ``offset`` into one.

    Returns:
        ``(cursor, exhausted)``; ``exhausted`` means the offset lies past the
        last item (the page is empty).

    Raises:
        HTTPException: 400 for an invalid cursor or ``cursor`` combined with
            a non-zero ``offset``.
    """
    if cursor and offset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'offset' is deprecated and cannot be combined with 'cursor'",
        )
    if cursor:
        try:
            decode_cursor(cursor)
        except InvalidCursorError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid cursor: {exc}"
            ) from exc
        return cursor, False
    if offset:
        return query.cursor_after(item_filter, offset)
    return None, False


def accepted(job_id: str, job_type: str) -> JobAcceptedResponse:
    """Build the 202 response of a job endpoint."""
    return JobAcceptedResponse(
        job_id=job_id,
        job_type=job_type,
        status_url=f"/api/v1/jobs/{job_id}",
        websocket_url=f"/api/v1/jobs/{job_id}/ws",
    )


def job_or_404(jobs: JobManager, job_id: str) -> Any:
    """Return the job or raise 404."""
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found")
    return job


async def serve_job_websocket(
    websocket: WebSocket, job_id: str, ws_manager: WebSocketManager, jobs: JobManager
) -> None:
    """Stream progress events of one job until the client disconnects.

    Sends the current state right after connecting, then every event of the
    job runner. Unknown jobs get one error message and the socket is closed.
    """
    job = jobs.get_job(job_id)
    if job is None:
        await websocket.accept()
        await websocket.send_json({"error": f"Job {job_id} not found", "job_id": job_id})
        await websocket.close()
        return
    await ws_manager.connect(job_id, websocket)
    await ws_manager.send_job_update(job_id, job)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - any socket error ends the stream
        logger.debug("WebSocket for job %s closed with an error", job_id, exc_info=True)
    finally:
        await ws_manager.disconnect(job_id, websocket)
