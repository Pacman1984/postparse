"""Schemas of the job endpoints (transcription, summaries, enrichment, classify runs)
and of the taxonomy classification endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from postparse.api.schemas.classify import BatchItemResult
from postparse.api.schemas.telegram import ExtractionStatus

__all__ = [
    "ClassifyRunRequest",
    "EnrichmentRunRequest",
    "ItemFilterBody",
    "JobAcceptedResponse",
    "LabelScore",
    "PersistedInfo",
    "SummariesRunRequest",
    "TaxonomyBatchRequest",
    "TaxonomyBatchResponse",
    "TaxonomyClassifyRequest",
    "TaxonomyClassifyResponse",
    "TranscriptionRunRequest",
]


class JobAcceptedResponse(BaseModel):
    """A background job was started; poll ``/api/v1/jobs/{job_id}`` or open the WebSocket."""

    job_id: str
    job_type: str
    status: ExtractionStatus = ExtractionStatus.PENDING
    status_url: str
    websocket_url: str


class ItemFilterBody(BaseModel):
    """Item filter (same fields as the ``/api/v1/items`` query parameters).

    ``labels`` entries are ``taxonomy`` or ``taxonomy:label``, all for one
    taxonomy; dates are ``YYYY-MM-DD`` (inclusive, UTC).
    """

    q: str | None = None
    source: Literal["instagram", "telegram", "all"] | None = None
    tags: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    has_transcript: bool | None = None


class TranscriptionRunRequest(BaseModel):
    """Start a transcription job (``postparse transcribe run``)."""

    source: Literal["instagram", "telegram", "all"] = "instagram"
    limit: int | None = Field(default=50, ge=1, le=10000)
    backend: Literal["local", "api"] | None = None
    refetch: bool = Field(default=True, description="Re-fetch Instagram posts with stale URLs")
    item_ids: list[int] | None = Field(default=None, description="Only media of these items")


class SummariesRunRequest(BaseModel):
    """Start a summarization job (``postparse summarize run``)."""

    limit: int | None = Field(default=20, ge=1, le=10000)
    provider: str | None = None
    force: bool = False
    item_ids: list[int] | None = None


class EnrichmentRunRequest(BaseModel):
    """Start a link enrichment job (``postparse enrich run``)."""

    source: Literal["all", "telegram", "instagram"] = "all"
    limit: int | None = Field(default=100, ge=1, le=100000)
    force: bool = False
    refresh_legacy: bool = True
    domains: list[str] | None = None


class ClassifyRunRequest(BaseModel):
    """Start a persisted classification run (``postparse classify run``)."""

    taxonomy: str = Field(..., min_length=1)
    scope: Literal["default", "backfill", "reprocess"] = "default"
    limit: int | None = Field(default=None, ge=1)
    provider: str | None = None
    wait_for_transcripts: bool = True
    filters: ItemFilterBody | None = None


class LabelScore(BaseModel):
    """A label with the answer's confidence."""

    label: str
    confidence: float | None = None


class PersistedInfo(BaseModel):
    """Where persisted results were stored."""

    run_id: int
    result_ids: list[int | None] = Field(default_factory=list)


class TaxonomyClassifyRequest(BaseModel):
    """Classify one text into a configured (or stored) taxonomy."""

    text: str = Field(..., min_length=1, max_length=20000)
    provider_name: str | None = None
    persist: bool = Field(default=False, description="Store the result for item_id")
    item_id: int | None = Field(default=None, description="Item the result belongs to")


class TaxonomyClassifyResponse(BaseModel):
    """Result of a taxonomy classification."""

    taxonomy: str
    mode: str
    status: str
    label: str | None = None
    labels: list[LabelScore] = Field(default_factory=list)
    confidence: float | None = None
    reasoning: str | None = None
    available_labels: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    processing_time: float = 0.0
    persisted: PersistedInfo | None = None


class TaxonomyBatchRequest(BaseModel):
    """Classify up to 100 texts; ``item_ids`` (same length) are needed for ``persist``."""

    texts: list[str] = Field(..., min_length=1, max_length=100)
    item_ids: list[int] | None = None
    provider_name: str | None = None
    persist: bool = False


class TaxonomyBatchResponse(BaseModel):
    """Per-input outcomes of a taxonomy batch (never a 500 for one bad input)."""

    taxonomy: str
    results: list[BatchItemResult]
    total_processed: int
    failed_count: int
    total_processing_time: float
    persisted: PersistedInfo | None = None


def drop_none(data: dict[str, Any]) -> dict[str, Any]:
    """Return ``data`` without ``None`` values (job metadata)."""
    return {k: v for k, v in data.items() if v is not None}
