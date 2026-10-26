"""
PostParse FastAPI application.

:func:`create_app` builds the application around the same services the CLI
uses (see :mod:`postparse.api.deps`): settings and the TOML config are read
when the app is created, the services (database, query, classification,
extraction, transcription, summarization, enrichment, jobs, cache) are built
once in the lifespan and kept on ``app.state.services``.

``postparse.api.main:app`` is created lazily on first access, reading the
config file named by ``POSTPARSE_CONFIG`` (set by ``postparse serve
--config``) or the standard locations. The API never reads ``.env`` files
itself: ``postparse serve`` loads them (like every CLI command, unless
``POSTPARSE_NO_DOTENV`` is set) and the server processes inherit the
environment; when starting uvicorn directly, export the variables first.

Usage:
    $ postparse --config config/config.toml serve --port 8000
    $ uvicorn postparse.api.main:create_app --factory --port 8000

Example (tests):
    >>> app = create_app(config=config, settings=settings, services=fake_services)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from postparse.api.deps import ApiServices, build_services
from postparse.api.middleware import (
    AuthenticationMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    configure_cors,
)
from postparse.api.routers import (
    classify_router,
    health_router,
    instagram_router,
    items_router,
    jobs_router,
    pipeline_router,
    search_router,
    telegram_router,
)
from postparse.api.routers.health import API_VERSION
from postparse.config import Settings, get_settings
from postparse.llm.exceptions import LLMProviderError
from postparse.services.query import InvalidCursorError

if TYPE_CHECKING:
    from postparse.core.utils.config import ConfigManager

__all__ = ["CONFIG_ENV_VAR", "create_app"]

logger = logging.getLogger(__name__)

#: Environment variable with the config file used by the lazily created ``app``.
CONFIG_ENV_VAR = "POSTPARSE_CONFIG"

_DESCRIPTION = """
PostParse REST API over the schema v2 database (the same services as the CLI).

* **Items**: `/api/v1/items` search with every filter, item detail, transcripts, summaries
* **Telegram / Instagram**: extraction jobs and the saved messages / posts
* **Classification**: ad-hoc and taxonomy classification (optionally persisted), runs
* **Processing jobs**: transcription, summaries, link enrichment
* **Jobs**: `/api/v1/jobs/{id}` status and `/api/v1/jobs/{id}/ws` live progress
* **Stats / health**: `/api/v1/stats`, `/health`, `/health/ready`

Authentication (JWT, `Authorization: Bearer ...`) and rate limiting are optional
(`[api.auth]`, `[api.rate_limiting]`).
"""

_TAGS = [
    {"name": "items", "description": "Unified item search and detail (both sources)"},
    {"name": "telegram", "description": "Telegram extraction and saved messages"},
    {"name": "instagram", "description": "Instagram extraction and saved posts"},
    {"name": "classify", "description": "LLM classification (ad hoc, taxonomies, runs)"},
    {"name": "search", "description": "Search posts and messages with filters"},
    {"name": "pipeline", "description": "Stats, taxonomies, transcription, summaries, enrichment"},
    {"name": "jobs", "description": "Job status and live progress for every job kind"},
    {"name": "health", "description": "Health checks and metrics"},
]


class _NullConfig:
    """Stand-in for a missing config file (every key falls back to its default)."""

    config_path = None

    def get(self, key: str, default: Any = None, env_var: str | None = None) -> Any:
        if env_var and env_var in os.environ:
            return os.environ[env_var]
        return default

    def get_section(self, section: str) -> dict[str, Any]:
        return {}


def _load_config(config_path: str | Path | None) -> Any:
    """Load the TOML config (``None`` when implicit discovery finds nothing)."""
    from postparse.core.utils.config import ConfigManager

    try:
        return ConfigManager(config_path)
    except FileNotFoundError:
        if config_path is not None:
            raise
        logger.warning("No config file found; the API runs with built-in defaults")
        return None


async def _job_cleanup(services: ApiServices, config: Any) -> None:
    """Periodically drop old jobs (``[api.jobs]``)."""
    max_age_hours = config.get("api.jobs.max_job_age_hours", 24)
    interval = max(1, int(config.get("api.jobs.cleanup_interval_minutes", 60))) * 60
    while True:
        await asyncio.sleep(interval)
        try:
            removed = services.jobs.cleanup_old_jobs(max_age_hours=max_age_hours)
            if removed:
                logger.info("Job cleanup: removed %d old jobs", removed)
        except Exception:
            logger.exception("Job cleanup failed")


def create_app(
    config_path: str | Path | None = None,
    *,
    config: Any = None,
    settings: Settings | None = None,
    services: ApiServices | None = None,
) -> FastAPI:
    """Create the FastAPI application.

    Args:
        config_path: TOML config file (``None``: ``POSTPARSE_CONFIG`` or the
            standard locations).
        config: Ready ``ConfigManager`` (skips loading ``config_path``).
        settings: Ready settings (default: :func:`postparse.config.get_settings`).
        services: Prebuilt services (tests); otherwise built in the lifespan.

    Returns:
        Configured application.
    """
    if config_path is None and config is None:
        config_path = os.environ.get(CONFIG_ENV_VAR) or None
    if config is None:
        config = _load_config(config_path)
    # _NullConfig duck-types the ConfigManager.get() the middlewares use.
    effective_config = cast("ConfigManager", config if config is not None else _NullConfig())
    if settings is None:
        settings = services.settings if services is not None else get_settings(config_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state: ApiServices = (
            services
            if services is not None
            else await asyncio.to_thread(build_services, settings, config)
        )
        app.state.services = state
        logger.info(
            "PostParse API ready (database %s, cache %s)", state.db.path, state.cache.backend
        )
        cleanup = asyncio.create_task(_job_cleanup(state, effective_config))
        try:
            yield
        finally:
            cleanup.cancel()
            await asyncio.gather(cleanup, return_exceptions=True)
            await state.runner.shutdown()
            app.state.services = None
            logger.info("PostParse API stopped")

    app = FastAPI(
        title="PostParse API",
        version=API_VERSION,
        description=_DESCRIPTION,
        license_info={"name": "MIT"},
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        openapi_tags=_TAGS,
    )
    app.state.config = config
    app.state.settings = settings
    app.state.services = None

    configure_cors(app, effective_config)
    # Order matters: the last added middleware runs first.
    app.add_middleware(RateLimitMiddleware, config=effective_config)
    app.add_middleware(RequestLoggingMiddleware, config=effective_config)
    app.add_middleware(AuthenticationMiddleware, config=effective_config)

    app.include_router(health_router)
    app.include_router(items_router)
    app.include_router(telegram_router)
    app.include_router(instagram_router)
    app.include_router(classify_router)
    app.include_router(search_router)
    app.include_router(pipeline_router)
    app.include_router(jobs_router)
    _install_handlers(app, effective_config)

    @app.get(
        "/",
        tags=["root"],
        summary="API root",
        description="Welcome endpoint with links to documentation",
    )
    async def root() -> dict[str, Any]:
        return {
            "message": "Welcome to PostParse API",
            "version": API_VERSION,
            "documentation": {"swagger": "/docs", "redoc": "/redoc", "openapi": "/openapi.json"},
            "endpoints": {
                "items": "/api/v1/items",
                "telegram": "/api/v1/telegram",
                "instagram": "/api/v1/instagram",
                "classify": "/api/v1/classify",
                "search": "/api/v1/search",
                "stats": "/api/v1/stats",
                "taxonomies": "/api/v1/taxonomies",
                "jobs": "/api/v1/jobs",
                "health": "/health",
            },
        }

    return app


def _install_handlers(app: FastAPI, config: Any) -> None:
    """Register the exception handlers (uniform error bodies)."""

    @app.exception_handler(LLMProviderError)
    async def llm_provider_error_handler(request: Request, exc: LLMProviderError) -> JSONResponse:
        logger.error("LLM provider error: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error_code": "LLM_PROVIDER_ERROR",
                "message": "LLM service is currently unavailable",
                "details": {"error": str(exc)},
            },
        )

    @app.exception_handler(InvalidCursorError)
    async def invalid_cursor_handler(request: Request, exc: InvalidCursorError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error_code": "HTTP_400", "detail": f"Invalid cursor: {exc}"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error_code": f"HTTP_{exc.status_code}", "detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        sanitized = []
        for error in exc.errors():
            item: dict[str, Any] = {
                "type": error.get("type"),
                "loc": error.get("loc"),
                "msg": error.get("msg"),
                "input": error.get("input"),
            }
            if "ctx" in error:
                ctx: dict[str, Any] = {}
                for key, value in error["ctx"].items():
                    try:
                        json.dumps(value)
                        ctx[key] = value
                    except (TypeError, ValueError):
                        ctx[key] = str(value)
                item["ctx"] = ctx
            sanitized.append(item)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error_code": "VALIDATION_ERROR",
                "detail": "Request validation failed",
                "errors": json.loads(json.dumps(sanitized, default=str)),
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        is_production = config.get("api.environment", "development") == "production"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": "Internal server error" if is_production else str(exc),
            },
        )


_app: FastAPI | None = None


def _default_app() -> FastAPI:
    """Create the module-level app (config from ``POSTPARSE_CONFIG``)."""
    global _app
    if _app is None:
        _app = create_app()
    return _app


def __getattr__(name: str) -> Any:
    """Create ``app`` lazily so importing this module has no side effects."""
    if name == "app":
        return _default_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "postparse.api.main:create_app",
        factory=True,
        host=os.environ.get("POSTPARSE_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("POSTPARSE_API_PORT", "8000")),
    )
