"""Service container and FastAPI dependency functions of the API.

The API runs on exactly the services the CLI uses. :func:`build_services`
creates them once (from :class:`~postparse.config.Settings` and the TOML
config) in the application lifespan; they live on ``app.state.services`` as
an :class:`ApiServices` instance. Endpoints receive them through the
``get_*`` dependency functions below, which tests replace with
``app.dependency_overrides`` or by passing ``services=`` to
:func:`postparse.api.main.create_app`.

Example:
    >>> @router.get("/items")
    ... def list_items(query: QueryService = Depends(get_query_service)):
    ...     return query.search(limit=10).items
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from starlette.requests import HTTPConnection

from postparse.api.jobs.runner import JobRunner
from postparse.api.services.cache_manager import CacheManager
from postparse.api.services.job_manager import JobManager
from postparse.api.services.websocket_manager import WebSocketManager
from postparse.config import Settings
from postparse.core.db import Database
from postparse.services.classification import ClassificationService
from postparse.services.enrichment import EnrichmentService
from postparse.services.extraction import ExtractionService
from postparse.services.query import QueryService
from postparse.services.summarization import SummarizationService
from postparse.services.transcription import TranscriptionService

if TYPE_CHECKING:
    from postparse.core.utils.config import ConfigManager

__all__ = [
    "ApiServices",
    "LLMHealthCache",
    "build_services",
    "get_cache_manager",
    "get_classification_service",
    "get_config",
    "get_enrichment_service",
    "get_extraction_service",
    "get_job_manager",
    "get_job_runner",
    "get_query_service",
    "get_services",
    "get_settings",
    "get_summarization_service",
    "get_transcription_service",
    "get_websocket_manager",
]

logger = logging.getLogger(__name__)


class LLMHealthCache:
    """Check the default LLM provider at most once per ``ttl`` seconds.

    Args:
        config: ``ConfigManager`` with ``[llm]`` (``None``: not configured).
        ttl: Seconds a result is reused.
        timeout: Request timeout of the check.
        checker: ``check_provider``-compatible callable (tests pass fakes).
    """

    def __init__(
        self,
        config: Any,
        *,
        ttl: float = 30.0,
        timeout: float = 5.0,
        checker: Any = None,
    ) -> None:
        self.config = config
        self.ttl = ttl
        self.timeout = timeout
        self._checker = checker
        self._lock = threading.Lock()
        self._cached: tuple[float, dict[str, Any]] | None = None

    def check(self) -> dict[str, Any]:
        """Return ``{"status", "provider", "model", "latency_ms", "error", "cached"}``."""
        now = time.monotonic()
        with self._lock:
            if self._cached is not None and now - self._cached[0] < self.ttl:
                return {**self._cached[1], "cached": True}
        result = self._run()
        with self._lock:
            self._cached = (time.monotonic(), result)
        return {**result, "cached": False}

    def _run(self) -> dict[str, Any]:
        from postparse.llm.client import select_provider
        from postparse.llm.config import LLMConfig

        if self.config is None:
            return {
                "status": "not_configured",
                "provider": None,
                "model": None,
                "latency_ms": None,
                "error": "No configuration file",
            }
        try:
            provider = select_provider(LLMConfig.from_config_manager(self.config), None)
        except (ValueError, TypeError) as exc:
            return {
                "status": "not_configured",
                "provider": None,
                "model": None,
                "latency_ms": None,
                "error": str(exc),
            }
        checker = self._checker
        if checker is None:
            from postparse.llm.health import check_provider as checker
        try:
            result = checker(provider, chat=True, timeout=self.timeout)
        except Exception as exc:
            return {
                "status": "error",
                "provider": provider.name,
                "model": provider.model,
                "latency_ms": None,
                "error": str(exc),
            }
        return {
            "status": result.status,
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "error": result.error,
        }


@dataclass
class ApiServices:
    """Everything the endpoints need, created once per application.

    Attributes:
        settings: Paths (database, sessions, downloads, tmp).
        config: ``ConfigManager`` (``None`` without a config file).
        db: Schema v2 database handle.
        query: Read queries (search, detail, tags).
        classification: Taxonomies, ad-hoc and persisted classification.
        extraction: Telegram / Instagram collectors.
        transcription: Media transcription queue.
        summarization: Transcript summaries.
        enrichment: Link enrichment.
        jobs: Job state.
        ws: WebSocket connections.
        cache: Response cache.
        runner: Background job runner.
        llm_health: Cached LLM health check.
    """

    settings: Settings
    config: Any
    db: Database
    query: QueryService
    classification: ClassificationService
    extraction: ExtractionService
    transcription: TranscriptionService
    summarization: SummarizationService
    enrichment: EnrichmentService
    jobs: JobManager
    ws: WebSocketManager
    cache: CacheManager
    runner: JobRunner
    llm_health: LLMHealthCache
    extra: dict[str, Any] = field(default_factory=dict)


def build_services(
    settings: Settings,
    config: ConfigManager | None,
    *,
    db: Database | None = None,
    cache: CacheManager | None = None,
    **overrides: Any,
) -> ApiServices:
    """Create the shared services (what the CLI builds per command).

    Args:
        settings: Resolved settings.
        config: ``ConfigManager`` (``None``: built-in defaults).
        db: Database handle (default: ``Database.open(settings.db_path)``).
        cache: Response cache (default: from ``[api.cache]``).
        **overrides: Replace individual services by attribute name
            (``query=...``, ``transcription=...``; used by tests).

    Returns:
        Service container.
    """
    if db is None:
        assert settings.db_path is not None
        db = Database.open(settings.db_path)
    cache = cache or CacheManager.from_config(config)
    jobs = overrides.pop("jobs", None) or JobManager()
    ws = overrides.pop("ws", None) or WebSocketManager()

    def make(name: str, factory: Any) -> Any:
        return overrides.pop(name) if name in overrides else factory()

    services = ApiServices(
        settings=settings,
        config=config,
        db=db,
        query=make("query", lambda: QueryService(db)),
        classification=make(
            "classification", lambda: ClassificationService(db, settings, config=config)
        ),
        extraction=make("extraction", lambda: ExtractionService(db, settings, config)),
        transcription=make(
            "transcription",
            lambda: TranscriptionService(db, settings, config, interactive=False),
        ),
        summarization=make(
            "summarization", lambda: SummarizationService(db, settings, config=config)
        ),
        enrichment=make("enrichment", lambda: EnrichmentService(db, settings, config)),
        jobs=jobs,
        ws=ws,
        cache=cache,
        runner=make("runner", lambda: JobRunner(jobs, ws, cache)),
        llm_health=make("llm_health", lambda: LLMHealthCache(config)),
    )
    services.extra.update(overrides)
    return services


# ---------------------------------------------------------------------------
# Dependency functions
# ---------------------------------------------------------------------------


def get_services(conn: HTTPConnection) -> ApiServices:
    """Return the service container of the running application.

    Raises:
        HTTPException: 503 while the application has not finished starting.
    """
    services = getattr(conn.app.state, "services", None)
    if services is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Services are not initialized (application lifespan not started)",
        )
    return services


def get_config(conn: HTTPConnection) -> Any:
    """Return the application's ``ConfigManager`` (``None`` without config file)."""
    return getattr(conn.app.state, "config", None)


def get_settings(conn: HTTPConnection) -> Settings:
    """Return the application's settings."""
    return get_services(conn).settings


def get_query_service(conn: HTTPConnection) -> QueryService:
    """Return the shared :class:`QueryService`."""
    return get_services(conn).query


def get_classification_service(conn: HTTPConnection) -> ClassificationService:
    """Return the shared :class:`ClassificationService`."""
    return get_services(conn).classification


def get_extraction_service(conn: HTTPConnection) -> ExtractionService:
    """Return the shared :class:`ExtractionService`."""
    return get_services(conn).extraction


def get_transcription_service(conn: HTTPConnection) -> TranscriptionService:
    """Return the shared :class:`TranscriptionService`."""
    return get_services(conn).transcription


def get_summarization_service(conn: HTTPConnection) -> SummarizationService:
    """Return the shared :class:`SummarizationService`."""
    return get_services(conn).summarization


def get_enrichment_service(conn: HTTPConnection) -> EnrichmentService:
    """Return the shared :class:`EnrichmentService`."""
    return get_services(conn).enrichment


def get_job_manager(conn: HTTPConnection) -> JobManager:
    """Return the job state store."""
    return get_services(conn).jobs


def get_websocket_manager(conn: HTTPConnection) -> WebSocketManager:
    """Return the WebSocket connection manager."""
    return get_services(conn).ws


def get_job_runner(conn: HTTPConnection) -> JobRunner:
    """Return the background job runner."""
    return get_services(conn).runner


def get_cache_manager(conn: HTTPConnection) -> CacheManager:
    """Return the response cache."""
    return get_services(conn).cache
