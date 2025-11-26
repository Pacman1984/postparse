"""
Integration tests for multi-class classification API endpoints.

Tests POST /api/v1/classify/multi and POST /api/v1/classify/multi/batch endpoints
with various scenarios including class definitions, provider switching, and error handling.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from typing import Dict, Any

from backend.postparse.api.main import app
from backend.postparse.services.analysis.classifiers.multi_class import MultiClassLLMClassifier
from backend.postparse.services.analysis.classifiers.base import ClassificationResult


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_classes() -> Dict[str, str]:
    """Sample class definitions for testing."""
    return {
        "recipe": "Cooking instructions or ingredients",
        "python_package": "Python libraries or packages",
        "movie_review": "Movie or film discussion"
    }


@pytest.fixture
def python_package_text() -> str:
    """Python package text for testing."""
    return "Check out this new FastAPI library for building APIs!"


@pytest.fixture
def recipe_text() -> str:
    """Recipe text for testing."""
    return "Boil pasta for 10 minutes, drain, add tomato sauce and basil"


@pytest.fixture
def movie_text() -> str:
    """Movie review text for testing."""
    return "Just watched an amazing thriller last night! The plot twists were incredible."


@pytest.fixture
def mock_multi_result_python() -> ClassificationResult:
    """Mock classification result for python package text."""
    return ClassificationResult(
        label="python_package",
        confidence=0.92,
        details={
            "reasoning": "The text mentions FastAPI library and building APIs",
            "available_classes": ["recipe", "python_package", "movie_review"]
        }
    )


@pytest.fixture
def mock_multi_result_recipe() -> ClassificationResult:
    """Mock classification result for recipe text."""
    return ClassificationResult(
        label="recipe",
        confidence=0.95,
        details={
            "reasoning": "Contains cooking instructions with pasta and sauce",
            "available_classes": ["recipe", "python_package", "movie_review"]
        }
    )


@pytest.fixture
def mock_multi_result_movie() -> ClassificationResult:
    """Mock classification result for movie review text."""
    return ClassificationResult(
        label="movie_review",
        confidence=0.88,
        details={
            "reasoning": "The text discusses watching and reviewing a film",
            "available_classes": ["recipe", "python_package", "movie_review"]
        }
    )


@pytest.fixture
def mock_multi_classifier(
    mock_multi_result_python,
    mock_multi_result_recipe,
    mock_multi_result_movie
):
    """Mock MultiClassLLMClassifier that returns deterministic results."""
    classifier = Mock(spec=MultiClassLLMClassifier)

    def predict_side_effect(text: str):
        text_lower = text.lower()
        if "pasta" in text_lower or "cook" in text_lower or "boil" in text_lower:
            return mock_multi_result_recipe
        elif "fastapi" in text_lower or "library" in text_lower or "python" in text_lower:
            return mock_multi_result_python
        elif "movie" in text_lower or "watch" in text_lower or "film" in text_lower:
            return mock_multi_result_movie
        else:
            return mock_multi_result_python  # Default

    classifier.predict.side_effect = predict_side_effect
    classifier.get_class_names.return_value = ["recipe", "python_package", "movie_review"]
    return classifier


# ============================================================================
# Single Classification Endpoint Tests
# ============================================================================


class TestMultiClassifyEndpoint:
    """Tests for POST /api/v1/classify/multi endpoint."""

    @pytest.mark.integration
    def test_classify_multi_with_runtime_classes(
        self,
        python_package_text: str,
        sample_classes: Dict[str, str],
        mock_multi_result_python: ClassificationResult
    ):
        """
        Test classification with runtime class definitions.

        Verifies:
        - Response structure matches expected format
        - Correct label is returned
        - Available classes are in response
        """
        client = TestClient(app)

        with patch('backend.postparse.api.routers.classify.MultiClassLLMClassifier') as mock_cls:
            mock_instance = Mock()
            mock_instance.predict.return_value = mock_multi_result_python
            mock_cls.return_value = mock_instance

            response = client.post(
                "/api/v1/classify/multi",
                json={
                    "text": python_package_text,
                    "classes": sample_classes,
                }
            )

            assert response.status_code == 200
            data = response.json()

            assert data["label"] == "python_package"
            assert data["confidence"] == 0.92
            assert data["reasoning"] is not None
            assert "available_classes" in data
            assert data["classifier_used"] == "multi_class_llm"
            assert data["processing_time"] >= 0

    @pytest.mark.integration
    def test_classify_multi_with_config_classes(
        self,
        python_package_text: str,
        mock_multi_result_python: ClassificationResult
    ):
        """
        Test classification using classes from config (no runtime classes).

        Verifies:
        - Classification works without providing runtime classes
        - Uses default classes from config.toml
        """
        client = TestClient(app)

        with patch('backend.postparse.api.routers.classify.MultiClassLLMClassifier') as mock_cls:
            mock_instance = Mock()
            mock_instance.predict.return_value = mock_multi_result_python
            mock_cls.return_value = mock_instance

            response = client.post(
                "/api/v1/classify/multi",
                json={
                    "text": python_package_text,
                    # No classes provided - should use config
                }
            )

            assert response.status_code == 200
            data = response.json()

            assert data["label"] == "python_package"
            assert data["classifier_used"] == "multi_class_llm"

    @pytest.mark.integration
    def test_classify_multi_with_provider(
        self,
        python_package_text: str,
        sample_classes: Dict[str, str],
        mock_multi_result_python: ClassificationResult
    ):
        """
        Test classification with specific provider.

        Verifies:
        - Provider name is passed to classifier
        - Classification succeeds with custom provider
        """
        client = TestClient(app)

        with patch('backend.postparse.api.routers.classify.MultiClassLLMClassifier') as mock_cls:
            mock_instance = Mock()
            mock_instance.predict.return_value = mock_multi_result_python
            mock_cls.return_value = mock_instance

            response = client.post(
                "/api/v1/classify/multi",
                json={
                    "text": python_package_text,
                    "classes": sample_classes,
                    "provider_name": "openai"
                }
            )

            assert response.status_code == 200

            # Verify provider was passed to constructor
            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs.get('provider_name') == 'openai'

    @pytest.mark.integration
    def test_classify_multi_invalid_text_empty(self):
        """
        Test validation error for empty text.

        Verifies:
        - Returns 422 validation error
        """
        client = TestClient(app)

        response = client.post(
            "/api/v1/classify/multi",
            json={"text": ""}
        )

        assert response.status_code == 422

    @pytest.mark.integration
    def test_classify_multi_invalid_text_whitespace(self):
        """
        Test validation error for whitespace-only text.

        Verifies:
        - Returns 422 validation error for whitespace text
        """
        client = TestClient(app)

        response = client.post(
            "/api/v1/classify/multi",
            json={"text": "   \n\t  "}
        )

        assert response.status_code == 422

    @pytest.mark.integration
    def test_classify_multi_invalid_classes_single(
        self,
        python_package_text: str
    ):
        """
        Test validation error for single class (need at least 2).

        Verifies:
        - Returns 422 validation error when less than 2 classes
        """
        client = TestClient(app)

        response = client.post(
            "/api/v1/classify/multi",
            json={
                "text": python_package_text,
                "classes": {"only_one": "Single class"}
            }
        )

        assert response.status_code == 422

    @pytest.mark.integration
    def test_classify_multi_invalid_provider(
        self,
        python_package_text: str,
        sample_classes: Dict[str, str]
    ):
        """
        Test error for invalid provider name.

        Verifies:
        - Returns 400 error for non-existent provider
        - Error message indicates invalid provider
        """
        client = TestClient(app)

        with patch('backend.postparse.api.routers.classify.MultiClassLLMClassifier') as mock_cls:
            mock_cls.side_effect = ValueError("Provider 'invalid_provider' not found")

            response = client.post(
                "/api/v1/classify/multi",
                json={
                    "text": python_package_text,
                    "classes": sample_classes,
                    "provider_name": "invalid_provider"
                }
            )

            assert response.status_code == 400
            assert "not found" in response.json()["detail"].lower()

    @pytest.mark.integration
    def test_classify_multi_llm_error(
        self,
        python_package_text: str,
        sample_classes: Dict[str, str]
    ):
        """
        Test handling of LLM service errors.

        Verifies:
        - Returns 503 error when LLM is unavailable
        - Error message is informative
        """
        client = TestClient(app)

        with patch('backend.postparse.api.routers.classify.MultiClassLLMClassifier') as mock_cls:
            mock_instance = Mock()
            mock_instance.predict.side_effect = Exception("LLM service unavailable")
            mock_cls.return_value = mock_instance

            response = client.post(
                "/api/v1/classify/multi",
                json={
                    "text": python_package_text,
                    "classes": sample_classes
                }
            )

            assert response.status_code == 503
            assert "classification failed" in response.json()["detail"].lower()

    @pytest.mark.integration
    def test_classify_multi_response_structure(
        self,
        python_package_text: str,
        sample_classes: Dict[str, str],
        mock_multi_result_python: ClassificationResult
    ):
        """
        Test that response matches expected schema.

        Verifies:
        - All required fields are present
        - Field types are correct
        """
        client = TestClient(app)

        with patch('backend.postparse.api.routers.classify.MultiClassLLMClassifier') as mock_cls:
            mock_instance = Mock()
            mock_instance.predict.return_value = mock_multi_result_python
            mock_cls.return_value = mock_instance

            response = client.post(
                "/api/v1/classify/multi",
                json={
                    "text": python_package_text,
                    "classes": sample_classes
                }
            )

            assert response.status_code == 200
            data = response.json()

            # Required fields
            assert "label" in data
            assert "confidence" in data
            assert "available_classes" in data
            assert "processing_time" in data
            assert "classifier_used" in data

            # Type checks
            assert isinstance(data["label"], str)
            assert isinstance(data["confidence"], float)
            assert isinstance(data["available_classes"], list)
            assert isinstance(data["processing_time"], float)
            assert isinstance(data["classifier_used"], str)

            # Value checks
            assert 0.0 <= data["confidence"] <= 1.0
            assert data["processing_time"] >= 0


# ============================================================================
# Batch Classification Endpoint Tests
# ============================================================================


class TestBatchMultiClassifyEndpoint:
    """Tests for POST /api/v1/classify/multi/batch endpoint."""

    @pytest.mark.integration
    def test_classify_multi_batch_success(
        self,
        recipe_text: str,
        python_package_text: str,
        movie_text: str,
        sample_classes: Dict[str, str],
        mock_multi_classifier
    ):
        """
        Test batch classification with multiple texts.

        Verifies:
        - All texts are classified
        - Results are returned for each text
        - Aggregate statistics are correct
        """
        client = TestClient(app)

        with patch('backend.postparse.api.routers.classify.MultiClassLLMClassifier') as mock_cls:
            mock_cls.return_value = mock_multi_classifier

            response = client.post(
                "/api/v1/classify/multi/batch",
                json={
                    "texts": [recipe_text, python_package_text, movie_text],
                    "classes": sample_classes
                }
            )

            assert response.status_code == 200
            data = response.json()

            assert "results" in data
            assert len(data["results"]) == 3
            assert data["total_processed"] == 3
            assert data["failed_count"] == 0
            assert data["total_processing_time"] >= 0

    @pytest.mark.integration
    def test_classify_multi_batch_with_runtime_classes(
        self,
        recipe_text: str,
        python_package_text: str,
        sample_classes: Dict[str, str],
        mock_multi_classifier
    ):
        """
        Test batch classification with runtime classes.

        Verifies:
        - Runtime classes are passed to classifier
        """
        client = TestClient(app)

        with patch('backend.postparse.api.routers.classify.MultiClassLLMClassifier') as mock_cls:
            mock_cls.return_value = mock_multi_classifier

            response = client.post(
                "/api/v1/classify/multi/batch",
                json={
                    "texts": [recipe_text, python_package_text],
                    "classes": sample_classes
                }
            )

            assert response.status_code == 200

            # Verify classes were passed
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs.get('classes') == sample_classes

    @pytest.mark.integration
    def test_classify_multi_batch_empty_list(self, sample_classes: Dict[str, str]):
        """
        Test validation error for empty texts list.

        Verifies:
        - Returns 422 validation error for empty list
        """
        client = TestClient(app)

        response = client.post(
            "/api/v1/classify/multi/batch",
            json={
                "texts": [],
                "classes": sample_classes
            }
        )

        assert response.status_code == 422

    @pytest.mark.integration
    def test_classify_multi_batch_invalid_text_in_list(
        self,
        recipe_text: str,
        sample_classes: Dict[str, str]
    ):
        """
        Test validation error for invalid text in list.

        Verifies:
        - Returns 422 validation error for empty text in list
        """
        client = TestClient(app)

        response = client.post(
            "/api/v1/classify/multi/batch",
            json={
                "texts": [recipe_text, "", "Another text"],
                "classes": sample_classes
            }
        )

        assert response.status_code == 422

    @pytest.mark.integration
    def test_classify_multi_batch_partial_failure(
        self,
        recipe_text: str,
        python_package_text: str,
        sample_classes: Dict[str, str],
        mock_multi_result_recipe: ClassificationResult
    ):
        """
        Test that batch continues on individual failures.

        Verifies:
        - Batch doesn't fail entirely when one text fails
        - Failed count is incremented
        - Successful results are still returned
        """
        client = TestClient(app)

        with patch('backend.postparse.api.routers.classify.MultiClassLLMClassifier') as mock_cls:
            mock_instance = Mock()
            # First succeeds, second fails, third succeeds
            mock_instance.predict.side_effect = [
                mock_multi_result_recipe,
                Exception("Classification error"),
                mock_multi_result_recipe,
            ]
            mock_instance.get_class_names.return_value = list(sample_classes.keys())
            mock_cls.return_value = mock_instance

            response = client.post(
                "/api/v1/classify/multi/batch",
                json={
                    "texts": [recipe_text, python_package_text, "Third text"],
                    "classes": sample_classes
                }
            )

            assert response.status_code == 200
            data = response.json()

            assert data["total_processed"] == 3
            assert data["failed_count"] == 1
            assert len(data["results"]) == 2  # Only successful ones

    @pytest.mark.integration
    def test_classify_multi_batch_response_structure(
        self,
        recipe_text: str,
        python_package_text: str,
        sample_classes: Dict[str, str],
        mock_multi_classifier
    ):
        """
        Test batch response structure and aggregates.

        Verifies:
        - Response matches expected schema
        - Each result has correct structure
        """
        client = TestClient(app)

        with patch('backend.postparse.api.routers.classify.MultiClassLLMClassifier') as mock_cls:
            mock_cls.return_value = mock_multi_classifier

            response = client.post(
                "/api/v1/classify/multi/batch",
                json={
                    "texts": [recipe_text, python_package_text],
                    "classes": sample_classes
                }
            )

            assert response.status_code == 200
            data = response.json()

            # Response structure
            assert "results" in data
            assert "total_processed" in data
            assert "failed_count" in data
            assert "total_processing_time" in data

            # Each result structure
            for result in data["results"]:
                assert "label" in result
                assert "confidence" in result
                assert "available_classes" in result
                assert "processing_time" in result
                assert "classifier_used" in result
                assert result["classifier_used"] == "multi_class_llm"

    @pytest.mark.integration
    def test_classify_multi_batch_exceeds_limit(
        self,
        recipe_text: str,
        sample_classes: Dict[str, str]
    ):
        """
        Test batch classification with > 100 texts.

        Verifies:
        - Returns 422 validation error
        - Error indicates batch size limit
        """
        client = TestClient(app)

        # Create 101 texts
        texts = [recipe_text] * 101

        response = client.post(
            "/api/v1/classify/multi/batch",
            json={
                "texts": texts,
                "classes": sample_classes
            }
        )

        assert response.status_code == 422


# ============================================================================
# List Classifiers Endpoint Tests
# ============================================================================


class TestListClassifiersEndpoint:
    """Tests for GET /api/v1/classify/classifiers endpoint."""

    @pytest.mark.integration
    def test_list_classifiers_includes_multi_class(self):
        """
        Test that multi-class classifier is listed.

        Verifies:
        - Response includes multi_class_llm classifier
        - Has correct name and type
        """
        client = TestClient(app)

        response = client.get("/api/v1/classify/classifiers")

        assert response.status_code == 200
        data = response.json()

        assert "classifiers" in data
        assert isinstance(data["classifiers"], list)

        # Find multi-class classifier
        multi_class_found = False
        for classifier in data["classifiers"]:
            if classifier.get("type") == "multi_class_llm":
                multi_class_found = True
                assert classifier.get("name") == "MultiClassLLMClassifier"
                assert "description" in classifier
                break

        assert multi_class_found, "MultiClassLLMClassifier not found in classifiers list"

    @pytest.mark.integration
    def test_list_classifiers_includes_both_types(self):
        """
        Test that both classifier types are listed.

        Verifies:
        - Both llm and multi_class_llm are present
        """
        client = TestClient(app)

        response = client.get("/api/v1/classify/classifiers")

        assert response.status_code == 200
        data = response.json()

        classifier_types = [c.get("type") for c in data["classifiers"]]

        assert "llm" in classifier_types
        assert "multi_class_llm" in classifier_types

    @pytest.mark.integration
    def test_list_classifiers_response_structure(self):
        """
        Test classifiers list response structure.

        Verifies:
        - Has classifiers and providers lists
        - Each classifier has type, name, description
        """
        client = TestClient(app)

        response = client.get("/api/v1/classify/classifiers")

        assert response.status_code == 200
        data = response.json()

        assert "classifiers" in data
        assert "providers" in data
        assert isinstance(data["classifiers"], list)
        assert isinstance(data["providers"], list)

        for classifier in data["classifiers"]:
            assert "type" in classifier
            assert "name" in classifier
            assert "description" in classifier

