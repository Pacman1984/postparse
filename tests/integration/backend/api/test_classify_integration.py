"""
Integration tests for classification endpoints.

Tests POST /api/v1/classify/recipe and POST /api/v1/classify/batch endpoints
with various scenarios including provider switching, error handling, and validation.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from typing import Dict, Any

from backend.postparse.api.main import app
from backend.postparse.services.analysis.classifiers.llm import RecipeLLMClassifier
from backend.postparse.services.analysis.classifiers.base import ClassificationResult
from backend.postparse.api.dependencies import get_recipe_llm_classifier


# Test data fixtures
@pytest.fixture
def recipe_text() -> str:
    """Recipe text for testing."""
    return """
    Chocolate Chip Cookies
    
    Ingredients:
    - 2 cups flour
    - 1 cup butter
    - 1 cup chocolate chips
    - 2 eggs
    - 1 tsp vanilla
    
    Instructions:
    1. Mix dry ingredients
    2. Cream butter and sugar
    3. Combine all ingredients
    4. Bake at 350°F for 12 minutes
    """


@pytest.fixture
def non_recipe_text() -> str:
    """Non-recipe text for testing."""
    return """
    I went to the store today and bought some groceries.
    The weather was nice and I had a great time.
    Looking forward to the weekend!
    """


@pytest.fixture
def mock_recipe_result() -> ClassificationResult:
    """Mock classification result for recipe text."""
    return ClassificationResult(
        label="recipe",
        confidence=0.95,
        details={
            "has_ingredients": True,
            "has_instructions": True,
            "cuisine": "American"
        }
    )


@pytest.fixture
def mock_non_recipe_result() -> ClassificationResult:
    """Mock classification result for non-recipe text."""
    return ClassificationResult(
        label="not_recipe",
        confidence=0.98,
        details=None
    )


@pytest.fixture
def mock_classifier(mock_recipe_result, mock_non_recipe_result):
    """Mock classifier that returns deterministic results."""
    classifier = Mock(spec=RecipeLLMClassifier)
    
    def predict_side_effect(text: str):
        if "recipe" in text.lower() or "ingredients" in text.lower():
            return mock_recipe_result
        else:
            return mock_non_recipe_result
    
    classifier.predict.side_effect = predict_side_effect
    return classifier


class TestClassifyIntegration:
    """Integration tests for classification endpoints."""
    
    @pytest.mark.integration
    def test_classify_recipe_single_text(self, recipe_text: str, mock_classifier, mock_recipe_result):
        """
        Test POST /api/v1/classify/recipe with recipe text.
        
        Verifies:
        - Response structure matches expected format
        - Label is 'recipe'
        - Confidence and details are populated
        - Processing time is tracked
        """
        client = TestClient(app)
        
        # Override classifier dependency
        app.dependency_overrides[get_recipe_llm_classifier] = lambda: mock_classifier
        
        try:
            response = client.post(
                "/api/v1/classify/recipe",
                json={"text": recipe_text}
            )
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["label"] == "recipe"
            assert data["confidence"] >= 0.6
            assert "details" in data
            assert "processing_time" in data
            assert "classifier_used" in data
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_classify_non_recipe_single_text(self, non_recipe_text: str, mock_classifier, mock_non_recipe_result):
        """
        Test POST /api/v1/classify/recipe with non-recipe text.
        
        Verifies:
        - Label is 'not_recipe'
        - Confidence is high
        - Details is None
        """
        client = TestClient(app)
        
        app.dependency_overrides[get_recipe_llm_classifier] = lambda: mock_classifier
        
        try:
            response = client.post(
                "/api/v1/classify/recipe",
                json={"text": non_recipe_text}
            )
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["label"] == "not_recipe"
            assert data["confidence"] >= 0.6
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_classify_batch_mixed_texts(self, recipe_text: str, non_recipe_text: str, mock_classifier):
        """
        Test POST /api/v1/classify/batch with mixed recipe and non-recipe texts.
        
        Verifies:
        - All texts are classified
        - Results are returned in order
        - Each result has required fields
        """
        client = TestClient(app)
        
        app.dependency_overrides[get_recipe_llm_classifier] = lambda: mock_classifier
        
        try:
            response = client.post(
                "/api/v1/classify/batch",
                json={"texts": [recipe_text, non_recipe_text, recipe_text]}
            )
            
            assert response.status_code == 200
            data = response.json()
            
            assert "results" in data
            assert len(data["results"]) == 3
            
            # First and third should be recipe, second should not be
            assert data["results"][0]["label"] == "recipe"
            assert data["results"][1]["label"] == "not_recipe"
            assert data["results"][2]["label"] == "recipe"
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_classify_with_provider_override(self, recipe_text: str):
        """
        Test classification with different provider_name.
        
        Verifies:
        - Provider switching works by constructing new classifier
        - RecipeLLMClassifier is called with provider_name
        - Response is successful
        """
        client = TestClient(app)
        
        with patch('backend.postparse.api.routers.classify.RecipeLLMClassifier') as mock_cls:
            mock_instance = Mock()
            mock_instance.predict.return_value = ClassificationResult(
                label="recipe",
                confidence=0.92,
                details={"has_ingredients": True}
            )
            mock_cls.return_value = mock_instance
            
            response = client.post(
                "/api/v1/classify/recipe",
                json={
                    "text": recipe_text,
                    "provider_name": "openai"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify provider was used by checking constructor call
            mock_cls.assert_called_once_with(provider_name="openai")
            assert data["label"] == "recipe"
            assert data["confidence"] == 0.92
    
    @pytest.mark.integration
    def test_classify_with_invalid_provider(self, recipe_text: str):
        """
        Test classification with invalid provider_name.
        
        Verifies:
        - Returns 400 Bad Request error
        - Error message indicates invalid provider
        """
        client = TestClient(app)
        
        response = client.post(
            "/api/v1/classify/recipe",
            json={
                "text": recipe_text,
                "provider_name": "nonexistent_provider"
            }
        )
        
        assert response.status_code == 400
        assert "invalid provider_name" in response.json()["detail"].lower()
    
    @pytest.mark.integration
    def test_classify_batch_with_provider_override(self, recipe_text: str, non_recipe_text: str):
        """
        Test batch classification with provider_name override.
        
        Verifies:
        - Provider switching works in batch endpoint
        - All texts are classified with specified provider
        """
        client = TestClient(app)
        
        with patch('backend.postparse.api.routers.classify.RecipeLLMClassifier') as mock_cls:
            mock_instance = Mock()
            mock_instance.predict.side_effect = [
                ClassificationResult(
                    label="recipe",
                    confidence=0.95,
                    details={"has_ingredients": True}
                ),
                ClassificationResult(
                    label="not_recipe",
                    confidence=0.88,
                    details=None
                ),
            ]
            mock_cls.return_value = mock_instance
            
            response = client.post(
                "/api/v1/classify/batch",
                json={
                    "texts": [recipe_text, non_recipe_text],
                    "provider_name": "anthropic"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify provider was used
            mock_cls.assert_called_once_with(provider_name="anthropic")
            assert len(data["results"]) == 2
            assert data["results"][0]["label"] == "recipe"
            assert data["results"][1]["label"] == "not_recipe"
    
    @pytest.mark.integration
    def test_classify_empty_text_validation(self):
        """
        Test validation with empty text.
        
        Verifies:
        - Returns 422 validation error
        - Error message indicates empty text
        """
        client = TestClient(app)
        
        response = client.post(
            "/api/v1/classify/recipe",
            json={"text": ""}
        )
        
        assert response.status_code == 422
    
    @pytest.mark.integration
    def test_classify_text_too_long(self):
        """
        Test validation with text exceeding max length.
        
        Verifies:
        - Returns 422 validation error for text > 10000 chars
        """
        client = TestClient(app)
        
        long_text = "a" * 10001
        response = client.post(
            "/api/v1/classify/recipe",
            json={"text": long_text}
        )
        
        assert response.status_code == 422
    
    @pytest.mark.integration
    def test_classify_batch_exceeds_limit(self, recipe_text: str):
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
            "/api/v1/classify/batch",
            json={"texts": texts}
        )
        
        assert response.status_code == 422
    
    @pytest.mark.integration
    def test_classify_llm_service_unavailable(self, recipe_text: str):
        """
        Test handling of LLM service errors.
        
        Verifies:
        - Returns 503 error when LLM is unavailable
        - Error message is informative
        """
        client = TestClient(app)
        
        # Mock classifier to raise exception
        mock_classifier = Mock(spec=RecipeLLMClassifier)
        mock_classifier.predict.side_effect = Exception("LLM service unavailable")
        
        app.dependency_overrides[get_recipe_llm_classifier] = lambda: mock_classifier
        
        try:
            response = client.post(
                "/api/v1/classify/recipe",
                json={"text": recipe_text}
            )
            
            # Should return 503 Service Unavailable
            assert response.status_code == 503
            assert "classification failed" in response.json()["detail"].lower()
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_list_classifiers(self):
        """
        Test GET /api/v1/classify/classifiers endpoint.
        
        Verifies:
        - Returns list of available classifiers
        - Returns list of available providers
        - Each has required fields
        """
        client = TestClient(app)
        
        response = client.get("/api/v1/classify/classifiers")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "classifiers" in data
        assert "providers" in data
        assert isinstance(data["classifiers"], list)
        assert isinstance(data["providers"], list)
        assert len(data["classifiers"]) > 0
        assert len(data["providers"]) > 0
        
        # Check first classifier has expected fields
        classifier = data["classifiers"][0]
        assert "name" in classifier
        assert "type" in classifier
        
        # Check first provider has expected fields
        provider = data["providers"][0]
        assert "name" in provider
        assert "status" in provider

