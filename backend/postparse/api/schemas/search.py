"""
Pydantic schemas for search endpoints.

This module defines request/response models for searching Instagram posts
and Telegram messages with various filters.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, Generic, TypeVar
from pydantic import BaseModel, Field, ConfigDict, field_validator

T = TypeVar("T")


class ContentTypeFilter(str, Enum):
    """
    Content type filter for posts/messages.

    Values:
        TEXT: Text-only content.
        IMAGE: Image/photo content.
        VIDEO: Video content.
        DOCUMENT: Document/file content.
    """

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"


class DateRangeFilter(BaseModel):
    """
    Date range filter for temporal queries.

    Attributes:
        start_date: Start of date range (inclusive).
        end_date: End of date range (inclusive).

    Example:
        {
            "start_date": "2025-01-01T00:00:00Z",
            "end_date": "2025-11-19T23:59:59Z"
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "start_date": "2025-01-01T00:00:00Z",
                "end_date": "2025-11-19T23:59:59Z"
            }
        ]
    })

    start_date: datetime = Field(
        ...,
        description="Start of date range (inclusive)"
    )
    end_date: datetime = Field(
        ...,
        description="End of date range (inclusive)"
    )

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v: datetime, info) -> datetime:
        """Validate that end_date is after start_date."""
        if "start_date" in info.data and v < info.data["start_date"]:
            raise ValueError("end_date must be after start_date")
        return v


class SearchPostsRequest(BaseModel):
    """
    Query parameters for Instagram post search.

    Attributes:
        hashtags: List of hashtags to filter by (OR logic).
        date_range: Date range filter.
        content_type: Content type filter.
        owner_username: Filter by post owner username.
        limit: Maximum results to return.
        offset: Number of results to skip.

    Example:
        {
            "hashtags": ["recipe", "cooking"],
            "date_range": {
                "start_date": "2025-01-01T00:00:00Z",
                "end_date": "2025-11-19T23:59:59Z"
            },
            "content_type": "image",
            "owner_username": null,
            "limit": 50,
            "offset": 0
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "hashtags": ["recipe", "cooking"],
                "date_range": {
                    "start_date": "2025-01-01T00:00:00Z",
                    "end_date": "2025-11-19T23:59:59Z"
                },
                "content_type": "image",
                "owner_username": None,
                "limit": 50,
                "offset": 0
            }
        ]
    })

    hashtags: Optional[List[str]] = Field(
        default=None,
        description="Hashtags to filter by (OR logic)",
        examples=[["recipe", "cooking"]]
    )
    date_range: Optional[DateRangeFilter] = Field(
        default=None,
        description="Date range filter"
    )
    content_type: Optional[ContentTypeFilter] = Field(
        default=None,
        description="Content type filter"
    )
    owner_username: Optional[str] = Field(
        default=None,
        description="Filter by post owner",
        examples=["cooking_profile"]
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum results to return"
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of results to skip"
    )


class SearchMessagesRequest(BaseModel):
    """
    Query parameters for Telegram message search.

    Attributes:
        hashtags: List of hashtags to filter by (OR logic).
        date_range: Date range filter.
        content_type: Content type filter.
        channel_username: Filter by channel username.
        limit: Maximum results to return.
        offset: Number of results to skip.

    Example:
        {
            "hashtags": ["recipe"],
            "date_range": null,
            "content_type": "text",
            "channel_username": "cooking_channel",
            "limit": 50,
            "offset": 0
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "hashtags": ["recipe"],
                "date_range": None,
                "content_type": "text",
                "channel_username": "cooking_channel",
                "limit": 50,
                "offset": 0
            }
        ]
    })

    hashtags: Optional[List[str]] = Field(
        default=None,
        description="Hashtags to filter by (OR logic)",
        examples=[["recipe"]]
    )
    date_range: Optional[DateRangeFilter] = Field(
        default=None,
        description="Date range filter"
    )
    content_type: Optional[ContentTypeFilter] = Field(
        default=None,
        description="Content type filter"
    )
    channel_username: Optional[str] = Field(
        default=None,
        description="Filter by channel",
        examples=["cooking_channel"]
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum results to return"
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of results to skip"
    )


class PostSearchResult(BaseModel):
    """
    Simplified Instagram post representation for search results.

    Contains a subset of InstagramPostSchema fields for efficient search responses.

    Attributes:
        shortcode: Instagram post shortcode.
        owner_username: Post owner username.
        caption: Post caption (truncated to 200 chars).
        is_video: Whether post contains video.
        likes: Number of likes.
        hashtags: Extracted hashtags.
        created_at: Post creation timestamp (None if unavailable).
    """

    model_config = ConfigDict(from_attributes=True)

    shortcode: str
    owner_username: str
    caption: Optional[str] = None
    is_video: bool = False
    likes: int = 0
    hashtags: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class MessageSearchResult(BaseModel):
    """
    Simplified Telegram message representation for search results.

    Contains a subset of TelegramMessageSchema fields for efficient search responses.

    Attributes:
        message_id: Telegram message ID.
        channel_username: Channel username.
        content: Message content (truncated to 200 chars).
        content_type: Content type.
        hashtags: Extracted hashtags.
        created_at: Message creation timestamp (None if unavailable).
    """

    model_config = ConfigDict(from_attributes=True)

    message_id: int
    channel_username: str
    content: Optional[str] = None
    content_type: str = "text"
    hashtags: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class SearchResponse(BaseModel, Generic[T]):
    """
    Generic search response schema.

    Attributes:
        results: List of search results.
        total_count: Total matching results (before pagination).
        filters_applied: Dictionary of filters that were applied.
        pagination: Pagination metadata.

    Example:
        {
            "results": [...],
            "total_count": 150,
            "filters_applied": {
                "hashtags": ["recipe"],
                "content_type": "image"
            },
            "pagination": {
                "limit": 50,
                "offset": 0,
                "next_offset": 50,
                "prev_offset": null
            }
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "results": [],
                "total_count": 150,
                "filters_applied": {
                    "hashtags": ["recipe"],
                    "content_type": "image"
                },
                "pagination": {
                    "limit": 50,
                    "offset": 0,
                    "next_offset": 50,
                    "prev_offset": None
                }
            }
        ]
    })

    results: List[T] = Field(
        ...,
        description="List of search results"
    )
    total_count: int = Field(
        ...,
        ge=0,
        description="Total matching results"
    )
    filters_applied: Dict[str, Any] = Field(
        default_factory=dict,
        description="Filters that were applied"
    )
    pagination: Dict[str, Optional[int]] = Field(
        default_factory=dict,
        description="Pagination metadata"
    )

