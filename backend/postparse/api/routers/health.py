"""
FastAPI router for health check and metrics endpoints.

This module provides endpoints for monitoring service health,
readiness, and basic metrics.
"""

from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, Depends, status, Response

from backend.postparse.core.data.database import SocialMediaDatabase
from backend.postparse.api.dependencies import get_db, get_config
from backend.postparse.api.schemas import HealthResponse
from backend.postparse.core.utils.config import ConfigManager

router = APIRouter(
    tags=["health"],
    responses={
        200: {"description": "Service is healthy"},
        503: {"description": "Service unavailable"},
    },
)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Basic health check",
    description="""
    Basic health check endpoint.
    
    Returns service status, version, and timestamp.
    Always returns 200 OK if the service is running.
    """,
)
async def health_check(
    config: ConfigManager = Depends(get_config),
) -> HealthResponse:
    """
    Basic health check.
    
    Args:
        config: ConfigManager instance (injected dependency).
        
    Returns:
        HealthResponse with status, version, and timestamp.
        
    Example:
        GET /health
        
        Response:
        {
            "status": "ok",
            "version": "0.1.0",
            "timestamp": "2025-11-19T10:30:00Z",
            "details": null
        }
    """
    # Get version from package (placeholder for now)
    version = "0.1.0"
    
    return HealthResponse(
        status="ok",
        version=version,
        timestamp=datetime.utcnow(),
        details=None,
    )


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    description="""
    Readiness probe for Kubernetes/Docker health checks.
    
    Checks:
    - Database connectivity
    - LLM provider availability
    
    Returns 200 if ready, 503 if not ready.
    """,
)
async def readiness_check(
    response: Response,
    db: SocialMediaDatabase = Depends(get_db),
    config: ConfigManager = Depends(get_config),
) -> HealthResponse:
    """
    Readiness probe checking dependencies.
    
    Args:
        response: FastAPI Response object for status code control.
        db: Database instance (injected dependency).
        config: ConfigManager instance (injected dependency).
        
    Returns:
        HealthResponse with detailed health information.
        
    Example:
        GET /health/ready
        
        Response (ready):
        {
            "status": "ok",
            "version": "0.1.0",
            "timestamp": "2025-11-19T10:30:00Z",
            "details": {
                "database": "connected",
                "llm_provider": "available"
            }
        }
        
        Response (not ready):
        {
            "status": "error",
            "version": "0.1.0",
            "timestamp": "2025-11-19T10:30:00Z",
            "details": {
                "database": "error",
                "llm_provider": "unavailable"
            }
        }
    """
    version = "0.1.0"
    details = {}
    service_status = "ok"
    
    # Check database connectivity
    try:
        # Try a simple query
        db.get_instagram_posts(limit=1)
        details["database"] = "connected"
    except Exception as e:
        details["database"] = f"error: {str(e)}"
        service_status = "error"
    
    # Check LLM provider availability
    try:
        default_provider = config.get("llm.default_provider", "ollama")
        details["llm_provider"] = f"configured: {default_provider}"
        # TODO: Actually check provider availability with a test call
    except Exception as e:
        details["llm_provider"] = f"error: {str(e)}"
        service_status = "degraded"
    
    # Set response status code
    if service_status == "error":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    
    return HealthResponse(
        status=service_status,
        version=version,
        timestamp=datetime.utcnow(),
        details=details,
    )


@router.get(
    "/health/live",
    summary="Liveness probe",
    description="""
    Liveness probe for Kubernetes/Docker health checks.
    
    Simple endpoint that returns 200 OK if the service is running.
    No dependency checks are performed.
    """,
)
async def liveness_check() -> Dict[str, str]:
    """
    Liveness probe for container orchestration.
    
    Returns:
        Simple status dictionary.
        
    Example:
        GET /health/live
        
        Response:
        {
            "status": "alive"
        }
    """
    return {"status": "alive"}


@router.get(
    "/metrics",
    summary="Basic metrics",
    description="""
    Basic metrics endpoint.
    
    Returns:
    - Request counts (placeholder)
    - Database statistics
    - Classifier usage stats (placeholder)
    
    Note: Full Prometheus integration will be added in future phase.
    """,
)
async def get_metrics(
    db: SocialMediaDatabase = Depends(get_db),
    config: ConfigManager = Depends(get_config),
) -> Dict[str, Any]:
    """
    Get basic service metrics.
    
    Args:
        db: Database instance (injected dependency).
        config: ConfigManager instance (injected dependency).
        
    Returns:
        Dictionary with various metrics.
        
    Example:
        GET /metrics
        
        Response:
        {
            "database": {
                "instagram_posts": 250,
                "telegram_messages": 450
            },
            "classifiers": {
                "total_classifications": 0,
                "recipe_count": 0,
                "non_recipe_count": 0
            },
            "uptime_seconds": 3600
        }
    """
    metrics = {
        "database": {
            "instagram_posts": 0,
            "telegram_messages": 0,
        },
        "classifiers": {
            "total_classifications": 0,
            "recipe_count": 0,
            "non_recipe_count": 0,
        },
        "uptime_seconds": 0,  # TODO: Track actual uptime
    }
    
    # Get database statistics
    try:
        posts = db.get_instagram_posts(limit=1000)
        messages = db.get_telegram_messages(limit=1000)
        metrics["database"]["instagram_posts"] = len(posts)
        metrics["database"]["telegram_messages"] = len(messages)
    except Exception:
        pass
    
    return metrics

