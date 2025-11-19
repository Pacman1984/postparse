"""
Common Pydantic schemas used across PostParse API.

This module provides reusable schema classes for:
- Health check responses
- Error handling
- Pagination
- Generic success responses

All schemas use Pydantic v2 syntax with comprehensive validation and examples.
"""

from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field, ConfigDict

# Generic type for paginated responses
T = TypeVar("T")


class HealthResponse(BaseModel):
    """
    Health check response schema.

    Used by health endpoints to indicate service status and version information.

    Attributes:
        status: Service status ('ok', 'degraded', 'error').
        version: Application version string.
        timestamp: Current server timestamp.
        details: Optional dictionary with component-specific health info.

    Example:
        {
            "status": "ok",
            "version": "0.1.0",
            "timestamp": "2025-11-19T10:30:00Z",
            "details": {
                "database": "connected",
                "llm_provider": "available"
            }
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "status": "ok",
                "version": "0.1.0",
                "timestamp": "2025-11-19T10:30:00Z",
                "details": {"database": "connected", "llm_provider": "available"}
            }
        ]
    })

    status: str = Field(
        ...,
        description="Service health status",
        examples=["ok", "degraded", "error"]
    )
    version: str = Field(
        ...,
        description="Application version",
        examples=["0.1.0"]
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Current server timestamp"
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional health check details"
    )


class ErrorResponse(BaseModel):
    """
    Standardized error response schema.

    Provides consistent error information across all API endpoints.

    Attributes:
        error_code: Machine-readable error code (e.g., 'INVALID_REQUEST').
        message: Human-readable error message.
        details: Optional dictionary with additional error context.

    Example:
        {
            "error_code": "INVALID_REQUEST",
            "message": "Text field is required",
            "details": {"field": "text", "issue": "missing"}
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "error_code": "INVALID_REQUEST",
                "message": "Text field is required",
                "details": {"field": "text", "issue": "missing"}
            },
            {
                "error_code": "LLM_PROVIDER_ERROR",
                "message": "Failed to connect to LLM provider",
                "details": {"provider": "ollama", "error": "Connection timeout"}
            }
        ]
    })

    error_code: str = Field(
        ...,
        description="Machine-readable error code",
        examples=["INVALID_REQUEST", "NOT_FOUND", "INTERNAL_ERROR"]
    )
    message: str = Field(
        ...,
        description="Human-readable error message",
        examples=["Text field is required", "Resource not found"]
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional error context"
    )


class SuccessResponse(BaseModel):
    """
    Generic success response schema.

    Used for endpoints that don't return specific data structures.

    Attributes:
        message: Success message.
        data: Optional dictionary with additional response data.

    Example:
        {
            "message": "Operation completed successfully",
            "data": {"items_processed": 42}
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "message": "Operation completed successfully",
                "data": {"items_processed": 42}
            }
        ]
    })

    message: str = Field(
        ...,
        description="Success message",
        examples=["Operation completed successfully"]
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional response data"
    )


class PaginationParams(BaseModel):
    """
    Query parameters for pagination.

    Supports both offset-based and cursor-based pagination.

    Attributes:
        limit: Maximum number of items to return (default: 50).
        offset: Number of items to skip (for offset-based pagination).
        cursor: Cursor for next page (for cursor-based pagination).

    Example:
        # Offset-based
        ?limit=20&offset=40

        # Cursor-based
        ?limit=20&cursor=eyJpZCI6MTIzfQ==
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {"limit": 20, "offset": 0},
            {"limit": 50, "cursor": "eyJpZCI6MTIzfQ=="}
        ]
    })

    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of items to return"
    )
    offset: Optional[int] = Field(
        default=0,
        ge=0,
        description="Number of items to skip (offset-based pagination)"
    )
    cursor: Optional[str] = Field(
        default=None,
        description="Cursor for next page (cursor-based pagination)"
    )


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Generic paginated response schema.

    Wraps a list of items with pagination metadata.

    Type Parameters:
        T: Type of items in the response.

    Attributes:
        items: List of items for current page.
        total: Total number of items across all pages.
        limit: Maximum items per page (from request).
        offset: Current offset (for offset-based pagination).
        next_cursor: Cursor for next page (for cursor-based pagination).
        has_more: Whether more items are available.

    Example:
        {
            "items": [...],
            "total": 150,
            "limit": 50,
            "offset": 0,
            "next_cursor": null,
            "has_more": true
        }
    """

    model_config = ConfigDict(from_attributes=True, json_schema_extra={
        "examples": [
            {
                "items": [],
                "total": 150,
                "limit": 50,
                "offset": 0,
                "next_cursor": None,
                "has_more": True
            }
        ]
    })

    items: List[T] = Field(
        ...,
        description="List of items for current page"
    )
    total: int = Field(
        ...,
        ge=0,
        description="Total number of items across all pages"
    )
    limit: int = Field(
        ...,
        ge=1,
        description="Maximum items per page"
    )
    offset: Optional[int] = Field(
        default=None,
        ge=0,
        description="Current offset (offset-based pagination)"
    )
    next_cursor: Optional[str] = Field(
        default=None,
        description="Cursor for next page (cursor-based pagination)"
    )
    has_more: bool = Field(
        ...,
        description="Whether more items are available"
    )


