"""Schemas of the unified ``/api/v1/items`` endpoints (schema v2 items)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "ClassificationSchema",
    "ItemDetailResponse",
    "ItemListResponse",
    "ItemSchema",
    "LinkSchema",
    "MediaSchema",
    "SummaryResponse",
    "TranscriptMediaSchema",
    "TranscriptResponse",
    "TranscriptSchema",
]


class ItemSchema(BaseModel):
    """An item as shown in lists.

    Attributes:
        tags: ``#hashtag`` / ``@mention`` display names.
        labels: ``{taxonomy: [current labels]}``.
        snippet: Highlighted match for text queries (``[term]`` markers).
    """

    id: int
    source: str
    external_id: str
    kind: str
    text: str | None = None
    author: str | None = None
    url: str | None = None
    created_at: datetime | None = None
    collected_at: datetime
    sort_at: datetime
    tags: list[str] = Field(default_factory=list)
    labels: dict[str, list[str]] = Field(default_factory=dict)
    snippet: str | None = None


class ItemListResponse(BaseModel):
    """One page of items (keyset pagination, newest first)."""

    items: list[ItemSchema]
    total: int | None = Field(default=None, description="Matching items (omitted with count=false)")
    limit: int
    cursor: str | None = None
    next_cursor: str | None = None
    has_more: bool


class TranscriptSchema(BaseModel):
    """Current transcript of one media file."""

    id: int
    backend: str
    model: str
    language: str | None = None
    text: str
    segments: Any = None
    duration_s: float | None = None
    created_at: datetime


class MediaSchema(BaseModel):
    """A media attachment with its transcript state."""

    id: int
    position: int
    media_type: str
    local_path: str | None = None
    remote_url: str | None = None
    mime: str | None = None
    duration_s: float | None = None
    transcript_status: str
    attempts: int = 0
    last_error: str | None = None
    has_transcript: bool = False


class LinkSchema(BaseModel):
    """A linked URL with its newest successful fetch."""

    id: int
    url: str
    domain: str
    fetcher: str | None = None
    status: str | None = None
    title: str | None = None
    text: str | None = None
    fetched_at: datetime | None = None


class ClassificationSchema(BaseModel):
    """Current classification of the item in one taxonomy."""

    taxonomy: str
    status: str
    labels: list[str]
    confidence: float | None = None
    reasoning: str | None = None
    provider: str | None = None
    model: str | None = None
    run_id: int
    result_id: int
    created_at: datetime


class SummaryResponse(BaseModel):
    """Latest summary of an item, split into summary text and key points."""

    item_id: int
    summary: str
    key_points: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    created_at: datetime


class ItemDetailResponse(ItemSchema):
    """Everything known about one item."""

    detail: dict[str, Any] | None = Field(
        default=None, description="Instagram / Telegram specific fields"
    )
    media: list[MediaSchema] = Field(default_factory=list)
    transcript: str | None = Field(default=None, description="All current transcripts joined")
    transcript_segments: list[Any] = Field(default_factory=list)
    summary: SummaryResponse | None = None
    links: list[LinkSchema] = Field(default_factory=list)
    classifications: list[ClassificationSchema] = Field(default_factory=list)


class TranscriptMediaSchema(BaseModel):
    """Transcript state of one media file."""

    media_id: int
    position: int
    media_type: str
    transcript_status: str
    transcript: TranscriptSchema | None = None


class TranscriptResponse(BaseModel):
    """Transcripts of all media of an item."""

    item_id: int
    text: str | None = None
    media: list[TranscriptMediaSchema] = Field(default_factory=list)
