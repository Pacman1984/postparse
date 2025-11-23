"""
FastAPI routers for PostParse API endpoints.

This module exports all router instances for registration in the main app.
"""

from .telegram import router as telegram_router
from .instagram import router as instagram_router
from .classify import router as classify_router
from .search import router as search_router
from .health import router as health_router
from .jobs import router as jobs_router

__all__ = [
    "telegram_router",
    "instagram_router",
    "classify_router",
    "search_router",
    "health_router",
    "jobs_router",
]


