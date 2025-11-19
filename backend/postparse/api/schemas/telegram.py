"""
Pydantic schemas for Telegram extraction endpoints.

This module defines request/response models for Telegram message extraction,
compatible with the database schema and parser implementations.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator


class ExtractionStatus(str, Enum):
    """
    Status of an extraction job.

    Values:
        PENDING: Job is queued but not started.
        RUNNING: Job is currently executing.
        COMPLETED: Job finished successfully.
        FAILED: Job encountered an error.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TelegramExtractRequest(BaseModel):
    """
    Request schema for triggering Telegram message extraction.

    Attributes:
        api_id: Telegram API ID (from my.telegram.org).
        api_hash: Telegram API hash.
        phone: Phone number in international format (optional for session reuse).
        limit: Maximum number of messages to extract per channel.
        force_update: Whether to re-extract already processed messages.
        max_requests_per_session: Rate limiting parameter for Telegram API.

    Example:
        {
            "api_id": "12345678",
            "api_hash": "0123456789abcdef0123456789abcdef",
            "phone": "+1234567890",
            "limit": 100,
            "force_update": false,
            "max_requests_per_session": 5
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "api_id": "12345678",
                "api_hash": "0123456789abcdef0123456789abcdef",
                "phone": "+1234567890",
                "limit": 100,
                "force_update": False,
                "max_requests_per_session": 5
            }
        ]
    })

    api_id: str = Field(
        ...,
        description="Telegram API ID",
        examples=["12345678"]
    )
    api_hash: str = Field(
        ...,
        min_length=32,
        max_length=32,
        description="Telegram API hash (32 characters)",
        examples=["0123456789abcdef0123456789abcdef"]
    )
    phone: Optional[str] = Field(
        default=None,
        pattern=r"^\+?[1-9]\d{1,14}$",
        description="Phone number in international format (E.164)",
        examples=["+1234567890"]
    )
    limit: Optional[int] = Field(
        default=100,
        ge=1,
        le=10000,
        description="Maximum messages to extract per channel"
    )
    force_update: bool = Field(
        default=False,
        description="Re-extract already processed messages"
    )
    max_requests_per_session: Optional[int] = Field(
        default=5,
        ge=1,
        le=20,
        description="Rate limiting: max API requests per session"
    )


class TelegramExtractResponse(BaseModel):
    """
    Response schema for Telegram extraction job initiation.

    Attributes:
        job_id: Unique identifier for tracking the extraction job.
        status: Current job status.
        message_count: Estimated number of messages to process.
        estimated_time: Estimated completion time in seconds.

    Example:
        {
            "job_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "pending",
            "message_count": 0,
            "estimated_time": 60
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "pending",
                "message_count": 0,
                "estimated_time": 60
            }
        ]
    })

    job_id: str = Field(
        ...,
        description="Unique job identifier",
        examples=["550e8400-e29b-41d4-a716-446655440000"]
    )
    status: ExtractionStatus = Field(
        ...,
        description="Current job status"
    )
    message_count: int = Field(
        default=0,
        ge=0,
        description="Estimated messages to process"
    )
    estimated_time: Optional[int] = Field(
        default=None,
        ge=0,
        description="Estimated completion time (seconds)"
    )


class TelegramMessageSchema(BaseModel):
    """
    Schema representing a single Telegram message.

    Matches the database schema for telegram_messages table.

    Attributes:
        message_id: Telegram message ID.
        channel_username: Channel username (without @).
        content: Message text content.
        content_type: Type of content (text, photo, video, document, etc.).
        media_urls: List of media URLs from the message.
        hashtags: List of extracted hashtags (without #).
        mentions: List of mentioned usernames (without @).
        created_at: Message creation timestamp.
        extracted_at: When the message was extracted.
        metadata: Additional message metadata.

    Example:
        {
            "message_id": 12345,
            "channel_username": "cooking_channel",
            "content": "Delicious pasta recipe! #italian #pasta",
            "content_type": "text",
            "media_urls": [],
            "hashtags": ["italian", "pasta"],
            "mentions": [],
            "created_at": "2025-11-19T10:00:00Z",
            "extracted_at": "2025-11-19T10:30:00Z",
            "metadata": {}
        }
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "message_id": 12345,
                    "channel_username": "cooking_channel",
                    "content": "Delicious pasta recipe! #italian #pasta",
                    "content_type": "text",
                    "media_urls": [],
                    "hashtags": ["italian", "pasta"],
                    "mentions": [],
                    "created_at": "2025-11-19T10:00:00Z",
                    "extracted_at": "2025-11-19T10:30:00Z",
                    "metadata": {}
                }
            ]
        }
    )

    message_id: int = Field(
        ...,
        description="Telegram message ID"
    )
    channel_username: Optional[str] = Field(
        default=None,
        description="Channel username (without @)"
    )
    content: Optional[str] = Field(
        default=None,
        description="Message text content"
    )
    content_type: str = Field(
        default="text",
        description="Type of content",
        examples=["text", "photo", "video", "document"]
    )
    media_urls: List[str] = Field(
        default_factory=list,
        description="List of media URLs"
    )
    hashtags: List[str] = Field(
        default_factory=list,
        description="Extracted hashtags (without #)"
    )
    mentions: List[str] = Field(
        default_factory=list,
        description="Mentioned usernames (without @)"
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Message creation timestamp"
    )
    extracted_at: Optional[datetime] = Field(
        default=None,
        description="Extraction timestamp"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional message metadata"
    )


class JobStatusResponse(BaseModel):
    """
    Response schema for extraction job status queries.

    Attributes:
        job_id: Unique job identifier.
        status: Current job status.
        progress: Completion percentage (0-100).
        messages_processed: Number of messages processed so far.
        errors: List of error messages encountered during extraction.

    Example:
        {
            "job_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "running",
            "progress": 65,
            "messages_processed": 65,
            "errors": []
        }
    """

    model_config = ConfigDict(json_schema_extra={
        "examples": [
            {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "running",
                "progress": 65,
                "messages_processed": 65,
                "errors": []
            },
            {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "completed",
                "progress": 100,
                "messages_processed": 100,
                "errors": []
            }
        ]
    })

    job_id: str = Field(
        ...,
        description="Unique job identifier"
    )
    status: ExtractionStatus = Field(
        ...,
        description="Current job status"
    )
    progress: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Completion percentage"
    )
    messages_processed: int = Field(
        default=0,
        ge=0,
        description="Messages processed so far"
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Error messages encountered"
    )


