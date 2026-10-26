"""
Pydantic schemas for PostParse API request/response validation.

This module exports all schema classes for easy importing throughout the API.
"""

from .common import (
    HealthResponse,
    ErrorResponse,
    SuccessResponse,
    PaginationParams,
    PaginatedResponse,
)
from .telegram import (
    TelegramExtractRequest,
    TelegramExtractResponse,
    TelegramMessageSchema,
    ExtractionStatus,
    JobStatusResponse,
)
from .instagram import (
    InstagramExtractRequest,
    InstagramExtractResponse,
    InstagramPostSchema,
)
from .classify import (
    ClassifyRequest,
    ClassifyResponse,
    BatchClassifyRequest,
    BatchClassifyResponse,
    ClassifierType,
)
from .search import (
    SearchPostsRequest,
    SearchMessagesRequest,
    SearchResponse,
    PostSearchResult,
    MessageSearchResult,
    DateRangeFilter,
    ContentTypeFilter,
    PaginationMetadata,
)

__all__ = [
    # Common
    "HealthResponse",
    "ErrorResponse",
    "SuccessResponse",
    "PaginationParams",
    "PaginatedResponse",
    # Telegram
    "TelegramExtractRequest",
    "TelegramExtractResponse",
    "TelegramMessageSchema",
    "ExtractionStatus",
    "JobStatusResponse",
    # Instagram
    "InstagramExtractRequest",
    "InstagramExtractResponse",
    "InstagramPostSchema",
    # Classify
    "ClassifyRequest",
    "ClassifyResponse",
    "BatchClassifyRequest",
    "BatchClassifyResponse",
    "ClassifierType",
    # Search
    "SearchPostsRequest",
    "SearchMessagesRequest",
    "SearchResponse",
    "PostSearchResult",
    "MessageSearchResult",
    "DateRangeFilter",
    "ContentTypeFilter",
    "PaginationMetadata",
]


