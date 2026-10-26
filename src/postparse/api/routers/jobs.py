"""Unified job endpoints: status, list and live progress for every job kind.

``GET /api/v1/jobs/{job_id}`` and ``WS /api/v1/jobs/{job_id}/ws`` work for all
kinds (``telegram_extract``, ``instagram_extract``, ``transcribe``,
``summarize``, ``enrich``, ``classify``). The older WebSocket path
``/api/v1/jobs/ws/progress/{job_id}`` and the platform-specific routes are
kept as aliases.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket

from postparse.api.dependencies import (
    get_current_websocket_user,
    get_job_manager,
    get_optional_auth,
    get_websocket_manager,
)
from postparse.api.routers._common import job_or_404, serve_job_websocket
from postparse.api.schemas import JobStatusResponse
from postparse.api.services.job_manager import JobManager
from postparse.api.services.websocket_manager import WebSocketManager

router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["jobs"],
    responses={404: {"description": "Job not found"}},
)


@router.get(
    "",
    response_model=list[JobStatusResponse],
    summary="List recent jobs",
    description="All jobs kept in memory (newest first), optionally of one kind.",
)
def list_jobs(
    job_type: str | None = Query(default=None, description="Only jobs of this kind"),
    jobs: JobManager = Depends(get_job_manager),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> list[JobStatusResponse]:
    """List jobs."""
    selected = [j for j in jobs.list_jobs() if job_type is None or j.job_type == job_type]
    selected.sort(key=lambda j: j.start_time, reverse=True)
    return [JobStatusResponse.from_job(j) for j in selected]


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Check job status",
    description="""
    Status of any background job. Failed jobs carry an `error_code`
    (`auth_required`, `credentials_missing`, `rate_limited`, `suspected_block`,
    `backend_unavailable`, `llm_error`, `invalid_request`, `cancelled`,
    `internal_error`); finished jobs carry the service report in `result`.
    """,
)
def get_job_status(
    job_id: str,
    jobs: JobManager = Depends(get_job_manager),
    user: dict[str, Any] | None = Depends(get_optional_auth),
) -> JobStatusResponse:
    """Return the status of one job."""
    return JobStatusResponse.from_job(job_or_404(jobs, job_id))


@router.websocket("/{job_id}/ws")
async def job_websocket(
    websocket: WebSocket,
    job_id: str,
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    jobs: JobManager = Depends(get_job_manager),
    user: dict[str, Any] | None = Depends(get_current_websocket_user),
) -> None:
    """Live progress of a job (JSON events: the job status plus ``timestamp``)."""
    await serve_job_websocket(websocket, job_id, ws_manager, jobs)


@router.websocket("/ws/progress/{job_id}")
async def websocket_progress(
    websocket: WebSocket,
    job_id: str,
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    jobs: JobManager = Depends(get_job_manager),
    user: dict[str, Any] | None = Depends(get_current_websocket_user),
) -> None:
    """Alias of ``/api/v1/jobs/{job_id}/ws`` (older path)."""
    await serve_job_websocket(websocket, job_id, ws_manager, jobs)
