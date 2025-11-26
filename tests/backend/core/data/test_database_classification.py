"""Tests for database classification storage methods.

Tests for save_classification_result, get_classification_results,
and has_classification methods in SocialMediaDatabase.
"""
import pytest
import tempfile
import os
import uuid
from pathlib import Path
from typing import Dict, Any

from backend.postparse.core.data.database import SocialMediaDatabase


@pytest.fixture
def temp_db() -> SocialMediaDatabase:
    """Create a temporary database for testing.

    Yields:
        SocialMediaDatabase: A fresh database instance with tables created.

    Example:
        >>> def test_something(temp_db):
        ...     temp_db.save_classification_result(...)
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_classification.db")
        db = SocialMediaDatabase(db_path)
        yield db


@pytest.fixture
def sample_classification_result() -> Dict[str, Any]:
    """Create sample classification result data.

    Returns:
        Dict with label, confidence, and details.
    """
    return {
        "label": "recipe",
        "confidence": 0.95,
        "details": {
            "cuisine_type": "italian",
            "difficulty": "easy",
            "meal_type": "dinner"
        }
    }


class TestSaveClassificationResult:
    """Tests for save_classification_result method."""

    def test_save_basic_classification(self, temp_db: SocialMediaDatabase) -> None:
        """Test saving a basic classification without details.

        Example:
            >>> db.save_classification_result(1, 'instagram', 'recipe_llm', 'recipe', 0.9)
        """
        analysis_id = temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95
        )

        assert analysis_id is not None
        assert analysis_id > 0

    def test_save_classification_with_details(
        self,
        temp_db: SocialMediaDatabase,
        sample_classification_result: Dict[str, Any]
    ) -> None:
        """Test saving a classification with details dictionary.

        Example:
            >>> db.save_classification_result(
            ...     1, 'instagram', 'recipe_llm', 'recipe', 0.95,
            ...     details={'cuisine_type': 'italian'}
            ... )
        """
        analysis_id = temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label=sample_classification_result["label"],
            confidence=sample_classification_result["confidence"],
            details=sample_classification_result["details"]
        )

        assert analysis_id is not None

        # Verify details were saved
        results = temp_db.get_classification_results(1, "instagram")
        assert len(results) == 1
        assert results[0]["details"]["cuisine_type"] == "italian"
        assert results[0]["details"]["difficulty"] == "easy"

    def test_save_classification_telegram_source(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test saving classification for telegram content."""
        analysis_id = temp_db.save_classification_result(
            content_id=42,
            content_source="telegram",
            classifier_name="recipe_llm",
            label="non_recipe",
            confidence=0.88
        )

        assert analysis_id is not None
        results = temp_db.get_classification_results(42, "telegram")
        assert len(results) == 1
        assert results[0]["label"] == "non_recipe"

    def test_save_multiple_classifications_same_content(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test saving multiple classifications for the same content.

        Different classifiers can classify the same content.
        """
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95
        )

        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="multi_class",
            label="tech_news",
            confidence=0.72
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert len(results) == 2


class TestGetClassificationResults:
    """Tests for get_classification_results method."""

    def test_get_results_empty(self, temp_db: SocialMediaDatabase) -> None:
        """Test getting results when none exist."""
        results = temp_db.get_classification_results(999, "instagram")
        assert results == []

    def test_get_results_filter_by_classifier(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test filtering results by classifier name."""
        # Save two classifications with different classifiers
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95
        )

        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="multi_class",
            label="other",
            confidence=0.60
        )

        # Get only recipe_llm results
        results = temp_db.get_classification_results(
            1, "instagram", classifier_name="recipe_llm"
        )
        assert len(results) == 1
        assert results[0]["classifier_name"] == "recipe_llm"
        assert results[0]["label"] == "recipe"

    def test_get_results_includes_all_fields(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test that retrieved results include all expected fields."""
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95,
            details={"key": "value"}
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert len(results) == 1

        result = results[0]
        assert "id" in result
        assert "classifier_name" in result
        assert "classification_type" in result
        assert "run_id" in result
        assert "label" in result
        assert "confidence" in result
        assert "llm_metadata" in result
        assert "analyzed_at" in result
        assert "details" in result
        assert result["details"]["key"] == "value"
        assert result["classification_type"] == "single"
        assert result["run_id"] is None
        assert result["llm_metadata"] is None  # Not provided in this test


class TestHasClassification:
    """Tests for has_classification method."""

    def test_has_classification_returns_false_when_not_exists(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test that has_classification returns False for non-existent."""
        result = temp_db.has_classification(
            content_id=999,
            content_source="instagram",
            classifier_name="recipe_llm"
        )
        assert result is False

    def test_has_classification_returns_true_when_exists(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test that has_classification returns True after saving."""
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95
        )

        result = temp_db.has_classification(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm"
        )
        assert result is True

    def test_has_classification_different_classifier(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test has_classification with different classifier name."""
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95
        )

        # Different classifier should return False
        result = temp_db.has_classification(
            content_id=1,
            content_source="instagram",
            classifier_name="multi_class"
        )
        assert result is False

    def test_has_classification_different_source(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test has_classification with different content source."""
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95
        )

        # Different source should return False
        result = temp_db.has_classification(
            content_id=1,
            content_source="telegram",
            classifier_name="recipe_llm"
        )
        assert result is False


class TestNestedDetails:
    """Tests for nested details handling."""

    def test_save_nested_details(self, temp_db: SocialMediaDatabase) -> None:
        """Test saving classification with nested details dictionary.

        Nested keys should be flattened with dot notation.
        """
        nested_details = {
            "ingredients": {
                "count": 5,
                "main": "pasta"
            },
            "rating": 4.5
        }

        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95,
            details=nested_details
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert len(results) == 1

        details = results[0]["details"]
        # Nested keys should be flattened with dot notation
        assert details["ingredients.count"] == 5
        assert details["ingredients.main"] == "pasta"
        assert details["rating"] == 4.5


class TestMultiLabelClassification:
    """Tests for multi-label classification support."""

    def test_save_multi_label_with_run_id(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test saving multiple labels for same content with run_id grouping.

        Example:
            A post could be labeled as both 'recipe' and 'italian'.
        """
        run_id = str(uuid.uuid4())

        # Save first label
        temp_db.save_classification_result(
            content_id=42,
            content_source="instagram",
            classifier_name="multi_label_llm",
            label="recipe",
            confidence=0.95,
            classification_type="multi_label",
            run_id=run_id
        )

        # Save second label
        temp_db.save_classification_result(
            content_id=42,
            content_source="instagram",
            classifier_name="multi_label_llm",
            label="italian",
            confidence=0.88,
            classification_type="multi_label",
            run_id=run_id
        )

        # Save third label
        temp_db.save_classification_result(
            content_id=42,
            content_source="instagram",
            classifier_name="multi_label_llm",
            label="vegetarian",
            confidence=0.72,
            classification_type="multi_label",
            run_id=run_id
        )

        results = temp_db.get_classification_results(42, "instagram")
        assert len(results) == 3

        # All should have same run_id and classification_type
        for r in results:
            assert r["classification_type"] == "multi_label"
            assert r["run_id"] == run_id

        # Check labels
        labels = {r["label"] for r in results}
        assert labels == {"recipe", "italian", "vegetarian"}

    def test_filter_by_run_id(self, temp_db: SocialMediaDatabase) -> None:
        """Test filtering results by run_id."""
        run_id_1 = str(uuid.uuid4())
        run_id_2 = str(uuid.uuid4())

        # First classification run
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="multi_label_llm", label="recipe",
            confidence=0.95, classification_type="multi_label", run_id=run_id_1
        )
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="multi_label_llm", label="healthy",
            confidence=0.80, classification_type="multi_label", run_id=run_id_1
        )

        # Second classification run (different run_id)
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="multi_label_llm", label="quick_meal",
            confidence=0.70, classification_type="multi_label", run_id=run_id_2
        )

        # Get only first run
        results_run1 = temp_db.get_classification_results(
            1, "instagram", run_id=run_id_1
        )
        assert len(results_run1) == 2
        assert {r["label"] for r in results_run1} == {"recipe", "healthy"}

        # Get only second run
        results_run2 = temp_db.get_classification_results(
            1, "instagram", run_id=run_id_2
        )
        assert len(results_run2) == 1
        assert results_run2[0]["label"] == "quick_meal"

    def test_mixed_single_and_multi_label(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test content with both single-label and multi-label classifications."""
        run_id = str(uuid.uuid4())

        # Single-label classification
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="recipe",
            confidence=0.95, classification_type="single"
        )

        # Multi-label classification
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="multi_label_llm", label="italian",
            confidence=0.88, classification_type="multi_label", run_id=run_id
        )
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="multi_label_llm", label="pasta",
            confidence=0.92, classification_type="multi_label", run_id=run_id
        )

        # Get all results
        all_results = temp_db.get_classification_results(1, "instagram")
        assert len(all_results) == 3

        # Filter by classifier
        recipe_results = temp_db.get_classification_results(
            1, "instagram", classifier_name="recipe_llm"
        )
        assert len(recipe_results) == 1
        assert recipe_results[0]["classification_type"] == "single"

        multi_results = temp_db.get_classification_results(
            1, "instagram", classifier_name="multi_label_llm"
        )
        assert len(multi_results) == 2
        for r in multi_results:
            assert r["classification_type"] == "multi_label"


class TestClassificationTypeField:
    """Tests for classification_type field behavior."""

    def test_default_classification_type_is_single(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test that default classification_type is 'single'."""
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert results[0]["classification_type"] == "single"

    def test_explicit_single_classification_type(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test explicitly setting classification_type='single'."""
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="multi_class_llm",
            label="tech_news",
            confidence=0.85,
            classification_type="single"
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert results[0]["classification_type"] == "single"
        assert results[0]["run_id"] is None


class TestLLMMetadata:
    """Tests for LLM metadata storage."""

    def test_save_with_llm_metadata(self, temp_db: SocialMediaDatabase) -> None:
        """Test saving classification with LLM metadata."""
        llm_metadata = {
            "provider": "lm_studio",
            "model": "qwen/qwen3-vl-8b",
            "temperature": 0.7,
            "max_tokens": 1000
        }

        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95,
            llm_metadata=llm_metadata
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert len(results) == 1
        assert results[0]["llm_metadata"] is not None
        assert results[0]["llm_metadata"]["provider"] == "lm_studio"
        assert results[0]["llm_metadata"]["model"] == "qwen/qwen3-vl-8b"
        assert results[0]["llm_metadata"]["temperature"] == 0.7
        assert results[0]["llm_metadata"]["max_tokens"] == 1000

    def test_save_without_llm_metadata(self, temp_db: SocialMediaDatabase) -> None:
        """Test saving classification without LLM metadata (default None)."""
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert results[0]["llm_metadata"] is None

    def test_llm_metadata_with_nested_config(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test LLM metadata with nested configuration."""
        llm_metadata = {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "config": {
                "temperature": 0.5,
                "max_tokens": 500,
                "top_p": 0.9
            },
            "api_base": "https://api.openai.com/v1"
        }

        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="multi_class_llm",
            label="tech_news",
            confidence=0.88,
            llm_metadata=llm_metadata
        )

        results = temp_db.get_classification_results(1, "instagram")
        metadata = results[0]["llm_metadata"]
        assert metadata["provider"] == "openai"
        assert metadata["config"]["temperature"] == 0.5
        assert metadata["config"]["top_p"] == 0.9

    def test_llm_metadata_multi_label_same_metadata(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test that multi-label results can have same LLM metadata."""
        run_id = str(uuid.uuid4())
        llm_metadata = {
            "provider": "anthropic",
            "model": "claude-3-5-sonnet",
            "temperature": 0.3
        }

        # Save multiple labels with same metadata
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="multi_label_llm", label="recipe",
            confidence=0.95, classification_type="multi_label",
            run_id=run_id, llm_metadata=llm_metadata
        )
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="multi_label_llm", label="italian",
            confidence=0.88, classification_type="multi_label",
            run_id=run_id, llm_metadata=llm_metadata
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert len(results) == 2

        # Both should have same metadata
        for r in results:
            assert r["llm_metadata"]["provider"] == "anthropic"
            assert r["llm_metadata"]["model"] == "claude-3-5-sonnet"

    def test_llm_metadata_complete_example(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test complete classification with all metadata fields.

        Example of a full classification record with all information tracked.
        """
        llm_metadata = {
            "provider": "lm_studio",
            "model": "qwen/qwen3-vl-8b",
            "temperature": 0.7,
            "max_tokens": 1000,
            "timeout": 60,
            "api_base": "http://localhost:1234/v1"
        }

        temp_db.save_classification_result(
            content_id=42,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95,
            details={
                "cuisine_type": "italian",
                "difficulty": "easy",
                "reasoning": "Contains pasta cooking instructions"
            },
            classification_type="single",
            llm_metadata=llm_metadata
        )

        results = temp_db.get_classification_results(42, "instagram")
        result = results[0]

        # Verify all fields
        assert result["label"] == "recipe"
        assert result["confidence"] == 0.95
        assert result["classification_type"] == "single"
        assert result["details"]["cuisine_type"] == "italian"
        assert result["llm_metadata"]["provider"] == "lm_studio"
        assert result["llm_metadata"]["model"] == "qwen/qwen3-vl-8b"


class TestLLMProviderAndModelColumns:
    """Tests for llm_provider and llm_model dedicated columns."""

    def test_save_populates_llm_provider_and_model(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test that llm_provider and llm_model are extracted from llm_metadata."""
        llm_metadata = {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0.7
        }

        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95,
            llm_metadata=llm_metadata
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert len(results) == 1
        assert results[0]["llm_provider"] == "openai"
        assert results[0]["llm_model"] == "gpt-4o-mini"

    def test_save_without_llm_metadata_has_null_columns(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test that llm_provider and llm_model are None without metadata."""
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert results[0]["llm_provider"] is None
        assert results[0]["llm_model"] is None

    def test_filter_results_by_llm_model(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test filtering classification results by llm_model."""
        # Save with gpt-4o
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="recipe", confidence=0.95,
            llm_metadata={"provider": "openai", "model": "gpt-4o"}
        )
        # Save with gpt-4o-mini
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="not_recipe", confidence=0.88,
            llm_metadata={"provider": "openai", "model": "gpt-4o-mini"}
        )

        # Filter by model
        results = temp_db.get_classification_results(
            1, "instagram", llm_model="gpt-4o"
        )
        assert len(results) == 1
        assert results[0]["llm_model"] == "gpt-4o"
        assert results[0]["label"] == "recipe"


class TestHasClassificationWithModel:
    """Tests for has_classification with llm_model parameter."""

    def test_has_classification_without_model_matches_any(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test has_classification without model returns True for any model."""
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="recipe", confidence=0.95,
            llm_metadata={"provider": "openai", "model": "gpt-4o"}
        )

        # Without model parameter - should find it
        assert temp_db.has_classification(1, "instagram", "recipe_llm") is True

    def test_has_classification_with_matching_model(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test has_classification with matching model returns True."""
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="recipe", confidence=0.95,
            llm_metadata={"provider": "openai", "model": "gpt-4o"}
        )

        # With matching model - should find it
        assert temp_db.has_classification(
            1, "instagram", "recipe_llm", llm_model="gpt-4o"
        ) is True

    def test_has_classification_with_different_model(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test has_classification with different model returns False."""
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="recipe", confidence=0.95,
            llm_metadata={"provider": "openai", "model": "gpt-4o"}
        )

        # With different model - should not find it
        assert temp_db.has_classification(
            1, "instagram", "recipe_llm", llm_model="gpt-4o-mini"
        ) is False


class TestGetClassificationId:
    """Tests for get_classification_id method."""

    def test_get_classification_id_returns_id(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test get_classification_id returns existing ID."""
        analysis_id = temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="recipe", confidence=0.95,
            llm_metadata={"provider": "openai", "model": "gpt-4o"}
        )

        found_id = temp_db.get_classification_id(
            1, "instagram", "recipe_llm", llm_model="gpt-4o"
        )
        assert found_id == analysis_id

    def test_get_classification_id_returns_none_when_not_found(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test get_classification_id returns None when not found."""
        found_id = temp_db.get_classification_id(
            999, "instagram", "recipe_llm", llm_model="gpt-4o"
        )
        assert found_id is None

    def test_get_classification_id_without_model(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test get_classification_id without model parameter."""
        analysis_id = temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="recipe", confidence=0.95
        )

        found_id = temp_db.get_classification_id(1, "instagram", "recipe_llm")
        assert found_id == analysis_id

    def test_get_classification_id_returns_latest(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test get_classification_id returns most recent when multiple exist."""
        # Save first classification
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="recipe", confidence=0.85
        )
        # Save second (more recent) classification
        latest_id = temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="not_recipe", confidence=0.95
        )

        found_id = temp_db.get_classification_id(1, "instagram", "recipe_llm")
        assert found_id == latest_id


class TestUpdateClassification:
    """Tests for update_classification method."""

    def test_update_classification_basic(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test basic classification update."""
        analysis_id = temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="recipe", confidence=0.85
        )

        temp_db.update_classification(
            analysis_id=analysis_id,
            label="not_recipe",
            confidence=0.95,
            reasoning="Updated reasoning"
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert len(results) == 1
        assert results[0]["label"] == "not_recipe"
        assert results[0]["confidence"] == 0.95
        assert results[0]["reasoning"] == "Updated reasoning"

    def test_update_classification_with_llm_metadata(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test update classification with new LLM metadata."""
        analysis_id = temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="recipe", confidence=0.85,
            llm_metadata={"provider": "openai", "model": "gpt-4o-mini"}
        )

        new_metadata = {"provider": "anthropic", "model": "claude-3-sonnet"}
        temp_db.update_classification(
            analysis_id=analysis_id,
            label="not_recipe",
            confidence=0.92,
            llm_metadata=new_metadata
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert results[0]["llm_provider"] == "anthropic"
        assert results[0]["llm_model"] == "claude-3-sonnet"
        assert results[0]["llm_metadata"]["provider"] == "anthropic"

    def test_update_classification_replaces_details(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test that update replaces existing details."""
        analysis_id = temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="recipe_llm", label="recipe", confidence=0.85,
            details={"cuisine_type": "italian", "old_key": "old_value"}
        )

        temp_db.update_classification(
            analysis_id=analysis_id,
            label="recipe",
            confidence=0.95,
            details={"cuisine_type": "mexican", "new_key": "new_value"}
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert results[0]["details"]["cuisine_type"] == "mexican"
        assert results[0]["details"]["new_key"] == "new_value"
        assert "old_key" not in results[0]["details"]


class TestReasoningColumn:
    """Tests for reasoning column in content_analysis."""

    def test_save_with_reasoning(self, temp_db: SocialMediaDatabase) -> None:
        """Test saving classification with reasoning.

        Example:
            >>> db.save_classification_result(
            ...     1, 'instagram', 'multi_class_llm', 'tech_news', 0.92,
            ...     reasoning='Discusses new software release'
            ... )
        """
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="multi_class_llm",
            label="tech_news",
            confidence=0.92,
            reasoning="Discusses new software release and updates"
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert len(results) == 1
        assert results[0]["reasoning"] == "Discusses new software release and updates"

    def test_save_without_reasoning(self, temp_db: SocialMediaDatabase) -> None:
        """Test saving classification without reasoning (default None)."""
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="recipe_llm",
            label="recipe",
            confidence=0.95
        )

        results = temp_db.get_classification_results(1, "instagram")
        assert results[0]["reasoning"] is None

    def test_reasoning_with_details(self, temp_db: SocialMediaDatabase) -> None:
        """Test saving classification with both reasoning and details.

        Reasoning is stored in the main table, details in the key-value table.
        """
        temp_db.save_classification_result(
            content_id=1,
            content_source="instagram",
            classifier_name="multi_class_llm",
            label="recipe",
            confidence=0.85,
            details={"available_classes": ["recipe", "tech_news", "other"]},
            reasoning="Contains cooking instructions and ingredient list"
        )

        results = temp_db.get_classification_results(1, "instagram")
        result = results[0]

        # Reasoning in main table
        assert result["reasoning"] == "Contains cooking instructions and ingredient list"
        # Details in key-value table
        assert result["details"]["available_classes"] == ["recipe", "tech_news", "other"]

    def test_reasoning_with_full_metadata(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test complete classification with reasoning and all fields."""
        llm_metadata = {
            "provider": "lm_studio",
            "model": "qwen/qwen3-vl-8b",
            "temperature": 0.7
        }

        temp_db.save_classification_result(
            content_id=42,
            content_source="telegram",
            classifier_name="multi_class_llm",
            label="tech_news",
            confidence=0.89,
            details={"available_classes": ["tech_news", "recipe", "other"]},
            reasoning="Post discusses AI and machine learning developments",
            llm_metadata=llm_metadata
        )

        results = temp_db.get_classification_results(42, "telegram")
        result = results[0]

        assert result["label"] == "tech_news"
        assert result["confidence"] == 0.89
        assert result["reasoning"] == "Post discusses AI and machine learning developments"
        assert result["llm_metadata"]["model"] == "qwen/qwen3-vl-8b"
        assert result["details"]["available_classes"] == ["tech_news", "recipe", "other"]

    def test_multi_label_with_shared_reasoning(
        self, temp_db: SocialMediaDatabase
    ) -> None:
        """Test multi-label classification where each label has reasoning."""
        run_id = str(uuid.uuid4())

        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="multi_label_llm", label="recipe",
            confidence=0.95, classification_type="multi_label",
            run_id=run_id,
            reasoning="Contains cooking instructions"
        )
        temp_db.save_classification_result(
            content_id=1, content_source="instagram",
            classifier_name="multi_label_llm", label="italian",
            confidence=0.88, classification_type="multi_label",
            run_id=run_id,
            reasoning="Mentions Italian ingredients like pasta and parmesan"
        )

        results = temp_db.get_classification_results(1, "instagram", run_id=run_id)
        assert len(results) == 2

        reasonings = {r["label"]: r["reasoning"] for r in results}
        assert reasonings["recipe"] == "Contains cooking instructions"
        assert reasonings["italian"] == "Mentions Italian ingredients like pasta and parmesan"

