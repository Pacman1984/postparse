"""
Pydantic schemas for PostParse API request/response validation.

This module exports all schema classes for easy importing throughout the API.
"""

from .classify import (
    BatchClassifyRequest,
    BatchClassifyResponse,
    ClassifierType,
    ClassifyRequest,
    ClassifyResponse,
)
from .common import (
    ErrorResponse,
    HealthResponse,
    PaginatedResponse,
    PaginationParams,
    SuccessResponse,
)
from .instagram import (
    InstagramExtractRequest,
    InstagramExtractResponse,
    InstagramPostSchema,
)
from .search import (
    ContentTypeFilter,
    DateRangeFilter,
    MessageSearchResult,
    PaginationMetadata,
    PostSearchResult,
    SearchMessagesRequest,
    SearchPostsRequest,
    SearchResponse,
)
from .telegram import (
    ExtractionStatus,
    JobStatusResponse,
    TelegramExtractRequest,
    TelegramExtractResponse,
    TelegramMessageSchema,
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
