"""Unit tests for the enrichment service skeleton.

Tests the EnrichmentResult model, BaseEnricher interface, and
content_enrichments database methods.
"""

import json
import os
import sqlite3
import tempfile
from typing import Optional

import pytest

from backend.postparse.services.enrichment.base import (
    BaseEnricher,
    EnrichmentResult,
)
from backend.postparse.core.data.database import SocialMediaDatabase


# ============================================================================
# EnrichmentResult Model Tests
# ============================================================================


class TestEnrichmentResult:
    """Test EnrichmentResult Pydantic model."""

    def test_create_enrichment_result(self) -> None:
        """Create a full EnrichmentResult."""
        result = EnrichmentResult(
            enrichment_type="summary",
            enricher_name="youtube_analyzer",
            generated_text="Tutorial on fine-tuning Qwen3 with LoRA",
            source_url="https://youtube.com/watch?v=abc",
            metadata={"duration_seconds": 600, "language": "en"},
        )
        assert result.enrichment_type == "summary"
        assert result.enricher_name == "youtube_analyzer"
        assert result.generated_text.startswith("Tutorial")
        assert result.source_url == "https://youtube.com/watch?v=abc"
        assert result.metadata["duration_seconds"] == 600

    def test_create_minimal_enrichment_result(self) -> None:
        """Create EnrichmentResult with only required fields."""
        result = EnrichmentResult(
            enrichment_type="description",
            enricher_name="caption_enhancer",
            generated_text="Better description of the post",
        )
        assert result.source_url is None
        assert result.metadata is None

    def test_enrichment_result_serialization(self) -> None:
        """EnrichmentResult serializes to dict correctly."""
        result = EnrichmentResult(
            enrichment_type="transcript",
            enricher_name="whisper",
            generated_text="Hello world",
        )
        data = result.model_dump()
        assert isinstance(data, dict)
        assert data["enrichment_type"] == "transcript"


# ============================================================================
# BaseEnricher Interface Tests
# ============================================================================


class _DummyEnricher(BaseEnricher):
    """Concrete implementation for testing the abstract interface."""

    def enrich(
        self, content: str, source_url: Optional[str] = None
    ) -> EnrichmentResult:
        return EnrichmentResult(
            enrichment_type="summary",
            enricher_name="dummy",
            generated_text=f"Summary of: {content[:20]}",
            source_url=source_url,
        )


class TestBaseEnricher:
    """Test BaseEnricher abstract class."""

    def test_concrete_enricher_can_be_instantiated(self) -> None:
        """A concrete subclass of BaseEnricher can be created."""
        enricher = _DummyEnricher()
        assert enricher is not None

    def test_concrete_enricher_returns_result(self) -> None:
        """enrich() returns an EnrichmentResult."""
        enricher = _DummyEnricher()
        result = enricher.enrich("Some content", source_url="https://example.com")
        assert isinstance(result, EnrichmentResult)
        assert result.enrichment_type == "summary"
        assert result.source_url == "https://example.com"

    def test_cannot_instantiate_base_directly(self) -> None:
        """BaseEnricher cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseEnricher()


# ============================================================================
# Database Enrichment Methods Tests
# ============================================================================


class TestDatabaseEnrichmentMethods:
    """Test content_enrichments table and DB methods."""

    @pytest.fixture
    def db(self, tmp_path) -> SocialMediaDatabase:
        """Create a temporary database for testing."""
        db_path = str(tmp_path / "test_enrichment.db")
        return SocialMediaDatabase(db_path)

    def test_content_enrichments_table_exists(self, db: SocialMediaDatabase) -> None:
        """content_enrichments table is created on init."""
        with db as d:
            d._cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='content_enrichments'"
            )
            assert d._cursor.fetchone() is not None

    def test_save_enrichment(self, db: SocialMediaDatabase) -> None:
        """save_enrichment inserts a row and returns its ID."""
        eid = db.save_enrichment(
            content_id=42,
            content_source="telegram",
            enrichment_type="summary",
            enricher_name="youtube_analyzer",
            generated_text="Tutorial on fine-tuning",
            source_url="https://youtube.com/watch?v=abc",
            metadata={"duration": 600},
            llm_metadata={"provider": "openai", "model": "gpt-4o"},
        )
        assert isinstance(eid, int)
        assert eid > 0

    def test_get_enrichments(self, db: SocialMediaDatabase) -> None:
        """get_enrichments retrieves saved enrichments."""
        db.save_enrichment(
            content_id=42,
            content_source="telegram",
            enrichment_type="summary",
            enricher_name="youtube_analyzer",
            generated_text="Summary text",
        )
        db.save_enrichment(
            content_id=42,
            content_source="telegram",
            enrichment_type="transcript",
            enricher_name="whisper",
            generated_text="Full transcript",
        )

        results = db.get_enrichments(42, "telegram")
        assert len(results) == 2
        types = {r["enrichment_type"] for r in results}
        assert types == {"summary", "transcript"}

    def test_get_enrichments_with_type_filter(self, db: SocialMediaDatabase) -> None:
        """get_enrichments filters by enrichment_type."""
        db.save_enrichment(
            content_id=42, content_source="telegram",
            enrichment_type="summary", enricher_name="a",
            generated_text="s",
        )
        db.save_enrichment(
            content_id=42, content_source="telegram",
            enrichment_type="transcript", enricher_name="b",
            generated_text="t",
        )

        results = db.get_enrichments(42, "telegram", enrichment_type="summary")
        assert len(results) == 1
        assert results[0]["enrichment_type"] == "summary"

    def test_has_enrichment_true(self, db: SocialMediaDatabase) -> None:
        """has_enrichment returns True when enrichment exists."""
        db.save_enrichment(
            content_id=42, content_source="telegram",
            enrichment_type="summary", enricher_name="yt",
            generated_text="text",
        )
        assert db.has_enrichment(42, "telegram", "summary", "yt") is True

    def test_has_enrichment_false(self, db: SocialMediaDatabase) -> None:
        """has_enrichment returns False when enrichment doesn't exist."""
        assert db.has_enrichment(99, "instagram", "summary", "yt") is False

    def test_get_enrichments_empty(self, db: SocialMediaDatabase) -> None:
        """get_enrichments returns empty list for nonexistent content."""
        results = db.get_enrichments(999, "telegram")
        assert results == []
