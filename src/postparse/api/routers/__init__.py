"""
FastAPI routers for PostParse API endpoints.

This module exports all router instances for registration in the main app.
"""

from .classify import router as classify_router
from .health import router as health_router
from .instagram import router as instagram_router
from .items import router as items_router
from .jobs import router as jobs_router
from .pipeline import router as pipeline_router
from .search import router as search_router
from .telegram import router as telegram_router

__all__ = [
    "classify_router",
    "health_router",
    "instagram_router",
    "items_router",
    "jobs_router",
    "pipeline_router",
    "search_router",
    "telegram_router",
]
