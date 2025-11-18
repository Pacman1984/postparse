"""Custom exceptions for LLM provider abstraction."""

from typing import Any, Optional


class LLMProviderError(Exception):
    """Base exception for all LLM provider errors.

    This is the base class for all exceptions raised by the LLM provider
    abstraction layer. It provides context about which provider and model
    encountered the error.

    Attributes:
        provider_name: Name of the LLM provider that raised the error.
        model_name: Name of the model that was being used.
        original_error: The original exception that caused this error.
    """

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        """Initialize the exception.

        Args:
            message: Human-readable error message.
            provider_name: Name of the provider that raised the error.
            model_name: Name of the model being used.
            original_error: Original exception that caused this error.
        """
        self.provider_name = provider_name
        self.model_name = model_name
        self.original_error = original_error
        super().__init__(message)

        # Chain the original error for better debugging
        if original_error is not None:
            self.__cause__ = original_error

    def __str__(self) -> str:
        """Return detailed error message with context."""
        parts = [super().__str__()]

        if self.provider_name:
            parts.append(f"Provider: {self.provider_name}")

        if self.model_name:
            parts.append(f"Model: {self.model_name}")

        if self.original_error:
            parts.append(f"Original error: {type(self.original_error).__name__}")

        return " | ".join(parts)


class LLMConnectionError(LLMProviderError):
    """Raised when connection to LLM service fails.

    This exception is raised when there are network issues, timeouts,
    or when the service is unavailable.

    Examples:
        - Network timeout
        - Service unavailable (500, 503 errors)
        - DNS resolution failure
        - Connection refused
    """

    def __init__(
        self,
        message: str = "Failed to connect to LLM service",
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        """Initialize the connection error."""
        super().__init__(message, provider_name, model_name, original_error)


class LLMAuthenticationError(LLMProviderError):
    """Raised when API key is invalid or missing.

    This exception is raised when authentication fails, typically due to:
    - Missing API key
    - Invalid or expired API key
    - Insufficient permissions

    Examples:
        - OPENAI_API_KEY environment variable not set
        - Invalid API key format
        - API key revoked or expired
    """

    def __init__(
        self,
        message: str = "Authentication failed - check your API key",
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        """Initialize the authentication error."""
        super().__init__(message, provider_name, model_name, original_error)


class LLMRateLimitError(LLMProviderError):
    """Raised when rate limits are exceeded.

    This exception is raised when the provider's rate limit is exceeded.
    Some providers include a retry_after value indicating when to retry.

    Attributes:
        retry_after: Optional number of seconds to wait before retrying.
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        original_error: Optional[Exception] = None,
        retry_after: Optional[int] = None,
    ) -> None:
        """Initialize the rate limit error.

        Args:
            message: Human-readable error message.
            provider_name: Name of the provider.
            model_name: Name of the model.
            original_error: Original exception.
            retry_after: Seconds to wait before retrying (if provided by API).
        """
        self.retry_after = retry_after
        super().__init__(message, provider_name, model_name, original_error)

    def __str__(self) -> str:
        """Return detailed error message with retry information."""
        base_msg = super().__str__()
        if self.retry_after:
            return f"{base_msg} | Retry after: {self.retry_after}s"
        return base_msg


class LLMModelNotFoundError(LLMProviderError):
    """Raised when specified model doesn't exist or isn't available.

    This exception is raised when:
    - Model name is incorrect or misspelled
    - Model is not available in the current region
    - Model has been deprecated
    - Account doesn't have access to the model

    Examples:
        - Typo in model name: "gpt-4o-mnii" instead of "gpt-4o-mini"
        - Trying to use a model without proper access
    """

    def __init__(
        self,
        message: str = "Model not found or not available",
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        """Initialize the model not found error."""
        super().__init__(message, provider_name, model_name, original_error)


class LLMInvalidRequestError(LLMProviderError):
    """Raised for invalid parameters or malformed requests.

    This exception is raised when the request to the LLM provider contains
    invalid parameters or is malformed.

    Examples:
        - Invalid temperature value (outside 0.0-2.0 range)
        - Prompt exceeds maximum length
        - Invalid message format
        - Unsupported parameter for the model
    """

    def __init__(
        self,
        message: str = "Invalid request parameters",
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        """Initialize the invalid request error."""
        super().__init__(message, provider_name, model_name, original_error)


class LLMResponseError(LLMProviderError):
    """Raised when response parsing fails or is malformed.

    This exception is raised when the LLM provider returns a response that
    cannot be parsed or is in an unexpected format.

    Examples:
        - Response is not valid JSON when JSON was expected
        - Response structure doesn't match expected format
        - Response is empty or truncated
        - Response contains invalid encoding
    """

    def __init__(
        self,
        message: str = "Failed to parse LLM response",
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        """Initialize the response error."""
        super().__init__(message, provider_name, model_name, original_error)

