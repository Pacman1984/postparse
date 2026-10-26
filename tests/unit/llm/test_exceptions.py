"""Tests for LLM provider exception hierarchy."""

import pytest

from postparse.llm.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMInvalidRequestError,
    LLMModelNotFoundError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseError,
)


class TestLLMProviderError:
    """Tests for the base LLMProviderError exception."""

    def test_base_exception_creation(self) -> None:
        """Test creating base LLMProviderError with message and context."""
        error = LLMProviderError(
            message="Test error",
            provider_name="test_provider",
            model_name="test_model",
        )

        assert str(error).startswith("Test error")
        assert "test_provider" in str(error)
        assert "test_model" in str(error)

    def test_base_exception_attributes(self) -> None:
        """Test that provider_name, model_name, and original_error are stored."""
        original = ValueError("Original error")
        error = LLMProviderError(
            message="Test error",
            provider_name="test_provider",
            model_name="test_model",
            original_error=original,
        )

        assert error.provider_name == "test_provider"
        assert error.model_name == "test_model"
        assert error.original_error is original
        assert error.__cause__ is original

    def test_base_exception_str(self) -> None:
        """Test string representation includes provider and model info."""
        error = LLMProviderError(
            message="Test error",
            provider_name="openai",
            model_name="gpt-4",
        )

        error_str = str(error)
        assert "Test error" in error_str
        assert "Provider: openai" in error_str
        assert "Model: gpt-4" in error_str


class TestSpecificExceptions:
    """Tests for specific exception types."""

    def test_connection_error(self) -> None:
        """Test LLMConnectionError creation and message formatting."""
        error = LLMConnectionError(
            message="Connection timeout",
            provider_name="openai",
            model_name="gpt-4",
        )

        assert isinstance(error, LLMProviderError)
        assert "Connection timeout" in str(error)
        assert "openai" in str(error)

    def test_connection_error_default_message(self) -> None:
        """Test LLMConnectionError uses default message when not provided."""
        error = LLMConnectionError(
            provider_name="openai",
            model_name="gpt-4",
        )

        assert "Failed to connect to LLM service" in str(error)

    def test_authentication_error(self) -> None:
        """Test LLMAuthenticationError creation and message formatting."""
        error = LLMAuthenticationError(
            message="Invalid API key",
            provider_name="anthropic",
            model_name="claude-3",
        )

        assert isinstance(error, LLMProviderError)
        assert "Invalid API key" in str(error)
        assert "anthropic" in str(error)

    def test_authentication_error_default_message(self) -> None:
        """Test LLMAuthenticationError uses default message when not provided."""
        error = LLMAuthenticationError(
            provider_name="openai",
            model_name="gpt-4",
        )

        assert "Authentication failed" in str(error)

    def test_rate_limit_error(self) -> None:
        """Test LLMRateLimitError creation with optional retry_after attribute."""
        error = LLMRateLimitError(
            message="Rate limit exceeded",
            provider_name="openai",
            model_name="gpt-4",
            retry_after=60,
        )

        assert isinstance(error, LLMProviderError)
        assert "Rate limit exceeded" in str(error)
        assert error.retry_after == 60
        assert "Retry after: 60s" in str(error)

    def test_rate_limit_error_without_retry_after(self) -> None:
        """Test LLMRateLimitError without retry_after."""
        error = LLMRateLimitError(
            message="Rate limit exceeded",
            provider_name="openai",
            model_name="gpt-4",
        )

        assert error.retry_after is None
        assert "Retry after" not in str(error)

    def test_model_not_found_error(self) -> None:
        """Test LLMModelNotFoundError creation and message formatting."""
        error = LLMModelNotFoundError(
            message="Model 'gpt-5' not found",
            provider_name="openai",
            model_name="gpt-5",
        )

        assert isinstance(error, LLMProviderError)
        assert "Model 'gpt-5' not found" in str(error)

    def test_invalid_request_error(self) -> None:
        """Test LLMInvalidRequestError creation and message formatting."""
        error = LLMInvalidRequestError(
            message="Invalid temperature value",
            provider_name="openai",
            model_name="gpt-4",
        )

        assert isinstance(error, LLMProviderError)
        assert "Invalid temperature value" in str(error)

    def test_response_error(self) -> None:
        """Test LLMResponseError creation and message formatting."""
        error = LLMResponseError(
            message="Failed to parse JSON response",
            provider_name="openai",
            model_name="gpt-4",
        )

        assert isinstance(error, LLMProviderError)
        assert "Failed to parse JSON response" in str(error)


class TestExceptionInheritance:
    """Tests for exception inheritance relationships."""

    def test_all_inherit_from_base(self) -> None:
        """Test that all specific exceptions inherit from LLMProviderError."""
        exceptions = [
            LLMConnectionError,
            LLMAuthenticationError,
            LLMRateLimitError,
            LLMModelNotFoundError,
            LLMInvalidRequestError,
            LLMResponseError,
        ]

        for exc_class in exceptions:
            assert issubclass(exc_class, LLMProviderError)

    def test_can_catch_with_base(self) -> None:
        """Test that catching LLMProviderError catches all specific exceptions."""
        exceptions = [
            LLMConnectionError("test"),
            LLMAuthenticationError("test"),
            LLMRateLimitError("test"),
            LLMModelNotFoundError("test"),
            LLMInvalidRequestError("test"),
            LLMResponseError("test"),
        ]

        for exc in exceptions:
            try:
                raise exc
            except LLMProviderError as caught:
                assert caught is exc


class TestExceptionChaining:
    """Tests for exception chaining and original error preservation."""

    def test_original_error_preserved(self) -> None:
        """Test that original exception is preserved via __cause__."""
        original = ValueError("Original error message")
        error = LLMProviderError(
            message="Wrapped error",
            provider_name="test",
            model_name="test",
            original_error=original,
        )

        assert error.__cause__ is original
        assert error.original_error is original

    def test_exception_chain_traceback(self) -> None:
        """Test that full traceback is available for debugging."""
        original = ValueError("Original error")
        error = LLMConnectionError(
            message="Connection failed",
            provider_name="openai",
            model_name="gpt-4",
            original_error=original,
        )

        # Verify the chain is set up correctly
        assert error.__cause__ is original
        assert isinstance(error, LLMProviderError)

        # Verify we can access the original error type
        assert "ValueError" in str(error)

