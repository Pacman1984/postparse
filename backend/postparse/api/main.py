"""
PostParse FastAPI application entry point.

This module creates and configures the FastAPI application with:
- Router registration for all endpoints
- Middleware for CORS, authentication, and logging
- Exception handlers for custom errors
- Lifespan events for startup and shutdown
- OpenAPI documentation customization

Usage:
    # Development mode (with auto-reload)
    python -m backend.postparse.api.main

    # Or using uvicorn directly
    uvicorn backend.postparse.api.main:app --reload --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Dict, Any
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

# Load environment variables from config/.env
env_path = Path(__file__).parent.parent.parent.parent / 'config' / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"Loaded environment variables from {env_path}")

from backend.postparse.api.routers import (
    telegram_router,
    instagram_router,
    classify_router,
    search_router,
    health_router,
    jobs_router,
)
from backend.postparse.api.middleware import (
    configure_cors,
    AuthenticationMiddleware,
    RequestLoggingMiddleware,
    RateLimitMiddleware,
)
from backend.postparse.core.utils.config import ConfigManager
from backend.postparse.llm.exceptions import LLMProviderError
from backend.postparse.core.data.database import SocialMediaDatabase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global config instance
config = ConfigManager()


async def job_cleanup_task(config: ConfigManager):
    """
    Background task that periodically cleans up old jobs.

    Runs indefinitely with sleep intervals, calling JobManager.cleanup_old_jobs()
    with configured max_age_hours and cleanup_interval_minutes settings.

    Args:
        config: ConfigManager instance for reading configuration values.

    Example:
        >>> task = asyncio.create_task(job_cleanup_task(config))
    """
    from backend.postparse.api.dependencies import get_job_manager

    # Get configuration values
    max_age_hours = config.get("api.jobs.max_job_age_hours", 24)
    cleanup_interval_minutes = config.get("api.jobs.cleanup_interval_minutes", 60)
    cleanup_interval_seconds = cleanup_interval_minutes * 60

    logger.info(
        f"Job cleanup task started: cleaning jobs older than {max_age_hours} hours "
        f"every {cleanup_interval_minutes} minutes"
    )

    # Get singleton JobManager instance
    job_manager = get_job_manager()

    while True:
        try:
            await asyncio.sleep(cleanup_interval_seconds)
            cleaned_count = job_manager.cleanup_old_jobs(max_age_hours=max_age_hours)
            if cleaned_count > 0:
                logger.info(f"Job cleanup: removed {cleaned_count} old jobs")
        except asyncio.CancelledError:
            logger.info("Job cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in job cleanup task: {e}")
            # Continue running despite errors


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.

    Handles startup and shutdown events for the FastAPI application.

    Startup:
        - Load configuration
        - Initialize database and verify schema
        - Warm up classifiers
        - Start background job cleanup task
        - Log startup message

    Shutdown:
        - Stop background job cleanup task
        - Close database connections
        - Log shutdown message
    """
    # Startup
    logger.info("=" * 60)
    logger.info("Starting PostParse API")
    logger.info("=" * 60)

    cleanup_task = None

    try:
        # Load and verify configuration
        logger.info("Loading configuration...")
        db_path = config.get("database.default_db_path", "data/social_media.db")
        default_provider = config.get("llm.default_provider", "ollama")
        logger.info(f"Database path: {db_path}")
        logger.info(f"Default LLM provider: {default_provider}")

        # Initialize database (creates schema if needed)
        logger.info("Initializing database...")
        # Database uses context manager pattern, connection is managed per-request
        _ = SocialMediaDatabase(db_path)
        logger.info("Database initialized successfully")

        # Warm up classifiers (load models into memory)
        logger.info("Warming up classifiers...")
        from backend.postparse.api.dependencies import _get_cached_recipe_llm_classifier
        # Call cached helper function with provider name (cache key)
        try:
            llm_classifier = _get_cached_recipe_llm_classifier(default_provider)
            logger.info(f"Classifier warmed up successfully (provider: {default_provider})")
        except Exception as e:
            logger.warning(f"Failed to warm up classifier: {e}")
            logger.warning("Classifier will be initialized on first request")

        # Start background job cleanup task
        logger.info("Starting background job cleanup task...")
        cleanup_task = asyncio.create_task(job_cleanup_task(config))

        # Log API configuration
        api_host = config.get("api.host", "0.0.0.0")
        api_port = config.get("api.port", 8000)
        auth_enabled = config.get("api.auth.enabled", False)
        logger.info(f"API server: {api_host}:{api_port}")
        logger.info(f"Authentication: {'enabled' if auth_enabled else 'disabled'}")
        logger.info("=" * 60)
        logger.info("PostParse API is ready!")
        logger.info(f"Documentation: http://{api_host}:{api_port}/docs")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        raise

    yield

    # Shutdown
    logger.info("=" * 60)
    logger.info("Shutting down PostParse API")
    logger.info("=" * 60)

    # Stop background job cleanup task
    if cleanup_task and not cleanup_task.done():
        logger.info("Stopping background job cleanup task...")
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

    logger.info("Cleanup completed successfully")


# Create FastAPI application
app = FastAPI(
    title="PostParse API",
    version="0.1.0",
    description="""
    PostParse REST API for social media content extraction and analysis.

    ## Features

    * **Telegram Extraction**: Extract messages from Telegram channels
    * **Instagram Extraction**: Extract posts from Instagram profiles
    * **Recipe Classification**: Classify content as recipe or non-recipe using LLM
    * **Search & Filter**: Search posts and messages with various filters
    * **Health Monitoring**: Health checks and basic metrics

    ## Authentication

    Authentication is optional and can be enabled via configuration.
    When enabled, include JWT token in requests:

    ```
    Authorization: Bearer YOUR_JWT_TOKEN
    ```

    ## Rate Limiting

    Rate limiting can be enabled via configuration to prevent abuse.
    """,
    contact={
        "name": "PostParse",
        "url": "https://github.com/yourusername/postparse",
    },
    license_info={
        "name": "MIT",
    },
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "telegram",
            "description": "Telegram message extraction and retrieval",
        },
        {
            "name": "instagram",
            "description": "Instagram post extraction and retrieval",
        },
        {
            "name": "classify",
            "description": "Recipe classification using LLM",
        },
        {
            "name": "search",
            "description": "Search posts and messages with filters",
        },
        {
            "name": "jobs",
            "description": "Unified job status tracking for all platforms",
        },
        {
            "name": "health",
            "description": "Health checks and metrics",
        },
    ],
)

# Configure CORS
configure_cors(app, config)

# Add middleware (order matters: last added = first executed)
app.add_middleware(RateLimitMiddleware, config=config)
app.add_middleware(RequestLoggingMiddleware, config=config)
app.add_middleware(AuthenticationMiddleware, config=config)

# Register routers
app.include_router(health_router)  # No prefix, mounted at /health
app.include_router(telegram_router)
app.include_router(instagram_router)
app.include_router(classify_router)
app.include_router(search_router)
app.include_router(jobs_router)


# Exception handlers
@app.exception_handler(LLMProviderError)
async def llm_provider_error_handler(request: Request, exc: LLMProviderError) -> JSONResponse:
    """
    Handle LLM provider errors.

    Returns 503 Service Unavailable when LLM provider is not available.
    """
    logger.error(f"LLM provider error: {exc}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error_code": "LLM_PROVIDER_ERROR",
            "message": "LLM service is currently unavailable",
            "details": {"error": str(exc)},
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Handle HTTP exceptions.

    Returns appropriate status code with standardized error format.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": f"HTTP_{exc.status_code}",
            "detail": exc.detail,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handle request validation errors.

    Returns 422 Unprocessable Entity with detailed validation error information.
    Sanitizes error context to ensure JSON serializability (removes non-serializable
    objects like ValueError instances from the 'ctx' field).
    """
    # Sanitize errors to ensure JSON serializability
    # Pydantic errors can contain ValueError objects in 'ctx' which aren't serializable
    sanitized_errors = []
    for error in exc.errors():
        sanitized_error = {
            "type": error.get("type"),
            "loc": error.get("loc"),
            "msg": error.get("msg"),
            "input": error.get("input"),
        }
        # Convert ctx values to strings if they exist and contain non-serializable objects
        if "ctx" in error:
            ctx = error["ctx"]
            sanitized_ctx = {}
            for key, value in ctx.items():
                if isinstance(value, Exception):
                    sanitized_ctx[key] = str(value)
                else:
                    try:
                        # Test if value is JSON serializable
                        import json
                        json.dumps(value)
                        sanitized_ctx[key] = value
                    except (TypeError, ValueError):
                        sanitized_ctx[key] = str(value)
            sanitized_error["ctx"] = sanitized_ctx
        sanitized_errors.append(sanitized_error)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error_code": "VALIDATION_ERROR",
            "detail": "Request validation failed",
            "errors": sanitized_errors,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle generic exceptions.

    Returns 500 Internal Server Error with sanitized error message.
    In production, internal details are hidden.
    """
    logger.exception(f"Unhandled exception: {exc}")

    # In production, hide internal error details
    is_production = config.get("api.environment", "development") == "production"
    error_detail = "Internal server error" if is_production else str(exc)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error_code": "INTERNAL_ERROR",
            "message": error_detail,
        },
    )


# Root endpoint
@app.get(
    "/",
    tags=["root"],
    summary="API root",
    description="Welcome endpoint with links to documentation",
)
async def root() -> Dict[str, Any]:
    """
    API root endpoint.

    Returns welcome message and links to documentation.
    """
    return {
        "message": "Welcome to PostParse API",
        "version": "0.1.0",
        "documentation": {
            "swagger": "/docs",
            "redoc": "/redoc",
            "openapi": "/openapi.json",
        },
        "endpoints": {
            "telegram": "/api/v1/telegram",
            "instagram": "/api/v1/instagram",
            "classify": "/api/v1/classify",
            "search": "/api/v1/search",
            "jobs": "/api/v1/jobs",
            "health": "/health",
        },
    }


# Main entry point for direct execution
if __name__ == "__main__":
    import uvicorn

    # Get configuration
    host = config.get("api.host", "0.0.0.0")
    port = config.get("api.port", 8000)
    reload = config.get("api.reload", True)
    workers = config.get("api.workers", 1)
    log_level = config.get("api.log_level", "info")

    # Run server
    uvicorn.run(
        "backend.postparse.api.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,  # Workers can't be used with reload
        log_level=log_level,
    )

