"""
Simple API tests that don't require full app initialization.

These tests validate the core functionality without requiring external dependencies.
"""

import pytest
from datetime import datetime

from backend.postparse.api.schemas.common import (
    HealthResponse,
    ErrorResponse,
    PaginationParams,
)
from backend.postparse.api.schemas.classify import (
    ClassifyRequest,
    ClassifyResponse,
    ClassifierType,
)


class TestSchemas:
    """Test Pydantic schemas without app initialization."""

    def test_health_response_creation(self):
        """Test creating a HealthResponse."""
        response = HealthResponse(
            status="ok",
            version="0.1.0",
            timestamp=datetime.now()
        )
        
        assert response.status == "ok"
        assert response.version == "0.1.0"
        assert isinstance(response.timestamp, datetime)

    def test_error_response_creation(self):
        """Test creating an ErrorResponse."""
        response = ErrorResponse(
            error_code="TEST_ERROR",
            message="Test message"
        )
        
        assert response.error_code == "TEST_ERROR"
        assert response.message == "Test message"

    def test_pagination_params_defaults(self):
        """Test PaginationParams default values."""
        params = PaginationParams()
        
        assert params.limit == 50
        assert params.offset == 0

    def test_classify_request_validation(self):
        """Test ClassifyRequest validation."""
        # Valid request
        request = ClassifyRequest(
            text="Test recipe text",
            classifier_type=ClassifierType.LLM
        )
        
        assert request.text == "Test recipe text"
        assert request.classifier_type == ClassifierType.LLM

    def test_classify_response_serialization(self):
        """Test ClassifyResponse can be created."""
        response = ClassifyResponse(
            label="recipe",
            confidence=0.95,
            details={"cuisine": "italian"},
            processing_time=0.5,
            classifier_used="llm"
        )
        
        assert response.label == "recipe"
        assert response.confidence == 0.95
        assert response.processing_time == 0.5


if __name__ == "__main__":
    # Run tests when executed directly
    pytest.main([__file__, "-v"])

