"""
Tests for API Pydantic schemas.

This module tests the request/response schemas for validation and serialization.
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from backend.postparse.api.schemas import (
    HealthResponse,
    ErrorResponse,
    PaginationParams,
    TelegramExtractRequest,
    TelegramMessageSchema,
    ExtractionStatus,
    ClassifyRequest,
    ClassifyResponse,
    ClassifierType,
)


class TestHealthResponse:
    """Test HealthResponse schema."""

    def test_health_response_valid(self):
        """Test creating a valid HealthResponse."""
        response = HealthResponse(
            status="ok",
            version="0.1.0",
            timestamp=datetime.now()
        )
        
        assert response.status == "ok"
        assert response.version == "0.1.0"
        assert isinstance(response.timestamp, datetime)


class TestErrorResponse:
    """Test ErrorResponse schema."""

    def test_error_response_valid(self):
        """Test creating a valid ErrorResponse."""
        response = ErrorResponse(
            error_code="TEST_ERROR",
            message="Test error message",
            details={"key": "value"}
        )
        
        assert response.error_code == "TEST_ERROR"
        assert response.message == "Test error message"
        assert response.details == {"key": "value"}


class TestPaginationParams:
    """Test PaginationParams schema."""

    def test_pagination_params_defaults(self):
        """Test PaginationParams with default values."""
        params = PaginationParams()
        
        assert params.limit == 50
        assert params.offset == 0
        assert params.cursor is None

    def test_pagination_params_validation(self):
        """Test PaginationParams validation."""
        # Valid params
        params = PaginationParams(limit=20, offset=10)
        assert params.limit == 20
        assert params.offset == 10
        
        # Invalid limit (too high)
        with pytest.raises(ValidationError):
            PaginationParams(limit=200)


class TestTelegramExtractRequest:
    """Test TelegramExtractRequest schema."""

    def test_telegram_extract_request_valid(self):
        """Test creating a valid TelegramExtractRequest."""
        request = TelegramExtractRequest(
            api_id=12345678,
            api_hash="0123456789abcdef0123456789abcdef",
            phone="+1234567890",
            limit=100
        )
        
        assert request.api_id == 12345678
        assert request.limit == 100

    def test_telegram_extract_request_phone_validation(self):
        """Test phone number validation."""
        # Valid phone
        request = TelegramExtractRequest(
            api_id=12345678,
            api_hash="0123456789abcdef0123456789abcdef",
            phone="+1234567890"
        )
        assert request.phone == "+1234567890"
        
        # Invalid phone
        with pytest.raises(ValidationError):
            TelegramExtractRequest(
                api_id=12345678,
                api_hash="0123456789abcdef0123456789abcdef",
                phone="invalid"
            )


class TestClassifyRequest:
    """Test ClassifyRequest schema."""

    def test_classify_request_valid(self):
        """Test creating a valid ClassifyRequest."""
        request = ClassifyRequest(
            text="Boil pasta for 10 minutes",
            classifier_type=ClassifierType.LLM,
            provider_name="ollama"
        )
        
        assert request.text == "Boil pasta for 10 minutes"
        assert request.classifier_type == ClassifierType.LLM
        assert request.provider_name == "ollama"

    def test_classify_request_text_validation(self):
        """Test text validation."""
        # Empty text should raise error
        with pytest.raises(ValidationError):
            ClassifyRequest(text="")
        
        # Whitespace-only text should raise error
        with pytest.raises(ValidationError):
            ClassifyRequest(text="   ")


class TestClassifyResponse:
    """Test ClassifyResponse schema."""

    def test_classify_response_valid(self):
        """Test creating a valid ClassifyResponse."""
        response = ClassifyResponse(
            label="recipe",
            confidence=0.95,
            details={"cuisine_type": "italian"},
            processing_time=0.234,
            classifier_used="llm"
        )
        
        assert response.label == "recipe"
        assert response.confidence == 0.95
        assert response.details == {"cuisine_type": "italian"}
        assert response.processing_time == 0.234


class TestExtractionStatus:
    """Test ExtractionStatus enum."""

    def test_extraction_status_values(self):
        """Test ExtractionStatus enum values."""
        assert ExtractionStatus.PENDING == "pending"
        assert ExtractionStatus.RUNNING == "running"
        assert ExtractionStatus.COMPLETED == "completed"
        assert ExtractionStatus.FAILED == "failed"

