"""Health, readiness and metrics endpoints.

* ``GET /health``: always 200 while the process runs; includes a cheap
  database summary once the services are up.
* ``GET /health/ready``: database check on the schema v2 database (schema
  version current, item count, FTS index in sync with ``items``), LLM
  provider check (``llm/health.py``, cached for a short TTL) and the
  transcription backend (checked without loading a model). 503 when the
  database is not usable.
* ``GET /health/live``: liveness probe without any checks.
* ``GET /metrics``: item counts per source and job counts.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request, Response, status

from postparse import __version__
from postparse.api.deps import ApiServices
from postparse.api.schemas import HealthResponse
from postparse.core.db.migrate import latest_version
from postparse.core.db.repos import SearchRepo

logger = logging.getLogger(__name__)

API_VERSION = __version__

router = APIRouter(
    tags=["health"],
    responses={200: {"description": "Service is healthy"}, 503: {"description": "Not ready"}},
)


def _services(request: Request) -> ApiServices | None:
    return getattr(request.app.state, "services", None)


def database_check(services: ApiServices) -> dict[str, Any]:
    """Check the schema v2 database.

    Returns:
        ``{"status": "ok"|"error", "path", "schema_version", "latest_schema_version",
        "items", "fts_indexed", "fts_in_sync", "error"}``.
    """
    info: dict[str, Any] = {"path": str(services.db.path)}
    try:
        with services.db.read() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            items = int(conn.execute("SELECT count(*) FROM items").fetchone()[0])
            indexed = SearchRepo(conn).indexed_count()
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return {**info, "status": "error", "error": str(exc)}
    latest = latest_version()
    ok = version == latest and indexed == items
    return {
        **info,
        "status": "ok" if ok else "degraded",
        "schema_version": version,
        "latest_schema_version": latest,
        "items": items,
        "fts_indexed": indexed,
        "fts_in_sync": indexed == items,
    }


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Basic health check",
    description="Always 200 while the service runs; `details.database` summarizes the database.",
)
def health_check(request: Request) -> HealthResponse:
    """Basic health check."""
    services = _services(request)
    details = {"database": database_check(services)} if services is not None else None
    return HealthResponse(
        status="ok", version=API_VERSION, timestamp=datetime.now(UTC), details=details
    )


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    description="""
    Checks the database, the default LLM provider (`llm=false` skips it;
    results are cached for a few seconds) and the transcription backend.
    Returns 503 when the database is not usable, `degraded` when an optional
    component is unavailable or the database needs maintenance.
    """,
)
def readiness_check(
    request: Request,
    response: Response,
    llm: bool = Query(default=True, description="Also check the LLM provider"),
) -> HealthResponse:
    """Readiness probe checking dependencies."""
    services = _services(request)
    if services is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="error",
            version=API_VERSION,
            timestamp=datetime.now(UTC),
            details={"services": "not initialized"},
        )
    from postparse.api.routers.pipeline import backend_status

    details: dict[str, Any] = {"database": database_check(services)}
    details["llm"] = services.llm_health.check() if llm else {"status": "skipped"}
    details["transcription"] = backend_status(services.transcription)
    details["cache"] = services.cache.backend
    db_status = details["database"]["status"]
    if db_status == "error":
        service_status = "error"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif (
        db_status != "ok"
        or details["llm"]["status"] not in ("available", "skipped")
        or details["transcription"]["status"] != "available"
    ):
        service_status = "degraded"
    else:
        service_status = "ok"
    return HealthResponse(
        status=service_status, version=API_VERSION, timestamp=datetime.now(UTC), details=details
    )


@router.get(
    "/health/live",
    summary="Liveness probe",
    description="Returns 200 OK if the process is running. No dependency checks.",
)
async def liveness_check() -> dict[str, str]:
    """Liveness probe for container orchestration."""
    return {"status": "alive"}


@router.get(
    "/metrics",
    summary="Basic metrics",
    description="Item counts per source and job counts per status.",
)
def get_metrics(request: Request) -> dict[str, Any]:
    """Return basic service metrics."""
    metrics: dict[str, Any] = {
        "database": {"instagram_posts": 0, "telegram_messages": 0, "items": 0},
        "jobs": {},
    }
    services = _services(request)
    if services is None:
        return metrics
    try:
        with services.db.read() as conn:
            for source, n in conn.execute(
                "SELECT source, count(*) FROM items GROUP BY source"
            ).fetchall():
                key = "instagram_posts" if source == "instagram" else "telegram_messages"
                metrics["database"][key] = int(n)
                metrics["database"]["items"] += int(n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Metrics database query failed: %s", exc)
    for job in services.jobs.list_jobs():
        bucket = metrics["jobs"].setdefault(job.job_type or "unknown", {})
        bucket[job.status.value] = bucket.get(job.status.value, 0) + 1
    return metrics
