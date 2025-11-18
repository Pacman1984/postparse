"""LLM provider abstraction with LiteLLM implementation."""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import litellm
from litellm import (
    APIConnectionError,
    AuthenticationError,
    InvalidRequestError,
    NotFoundError,
    RateLimitError,
)

from postparse.core.utils.config import ConfigManager
from postparse.llm.config import LLMConfig, ProviderConfig, get_provider_config
from postparse.llm.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMInvalidRequestError,
    LLMModelNotFoundError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseError,
)

# Configure logging
logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    This defines the interface that all LLM provider implementations must follow.
    Subclasses should implement methods for chat completion, text completion,
    and embeddings.

    Attributes:
        config: Provider configuration.
    """

    def __init__(self, config: ProviderConfig) -> None:
        """Initialize the provider with configuration.

        Args:
            config: Provider configuration instance.
        """
        self.config = config

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        """Perform chat completion with the LLM.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys.
                Example: [{"role": "user", "content": "Hello"}]
            **kwargs: Additional parameters to pass to the LLM.

        Returns:
            The LLM's response as a string.

        Raises:
            LLMProviderError: If the request fails.
        """
        pass

    @abstractmethod
    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Perform text completion with the LLM.

        Args:
            prompt: The text prompt to complete.
            **kwargs: Additional parameters to pass to the LLM.

        Returns:
            The LLM's completion as a string.

        Raises:
            LLMProviderError: If the request fails.
        """
        pass

    @abstractmethod
    def embed(self, text: str, **kwargs: Any) -> List[float]:
        """Generate embeddings for the given text.

        Args:
            text: Text to generate embeddings for.
            **kwargs: Additional parameters to pass to the embedding model.

        Returns:
            Embedding vector as a list of floats.

        Raises:
            LLMProviderError: If the request fails.
        """
        pass

    def get_provider_name(self) -> str:
        """Get the name of this provider.

        Returns:
            Provider name.
        """
        return self.config.name

    def get_model_name(self) -> str:
        """Get the model name used by this provider.

        Returns:
            Model name.
        """
        return self.config.model

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is available and can be used.

        Returns:
            True if provider is available, False otherwise.
        """
        pass


class LiteLLMProvider(LLMProvider):
    """LLM provider implementation using LiteLLM SDK.

    LiteLLM provides a unified interface to multiple LLM providers including
    OpenAI, Anthropic, Ollama, LM Studio, and many others.

    Examples:
        ```python
        config = ProviderConfig(
            name="openai",
            model="gpt-4o-mini",
            temperature=0.7
        )
        provider = LiteLLMProvider(config)

        response = provider.chat([
            {"role": "user", "content": "What is 2+2?"}
        ])
        print(response)  # "4"
        ```
    """

    def __init__(self, config: ProviderConfig) -> None:
        """Initialize LiteLLM provider.

        Args:
            config: Provider configuration.
        """
        super().__init__(config)

        # Configure LiteLLM logging
        litellm.suppress_debug_info = True

        # Configure custom API base if provided (for local endpoints)
        if config.api_base:
            logger.debug(f"Using custom API base: {config.api_base}")

    def _build_litellm_kwargs(self, **override_kwargs: Any) -> Dict[str, Any]:
        """Build kwargs dictionary for LiteLLM calls.

        Args:
            **override_kwargs: Additional kwargs to override defaults.

        Returns:
            Dictionary of kwargs for LiteLLM.
        """
        kwargs: Dict[str, Any] = {
            "model": self.config.model,  # Use model name as-is
            "temperature": self.config.temperature,
            "timeout": self.config.timeout,
        }

        # Add API key if available
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key

        # Add custom API base if configured
        if self.config.api_base:
            kwargs["api_base"] = self.config.api_base
            # For custom endpoints (LM Studio, local Ollama, etc.), explicitly set the provider
            # This tells LiteLLM to use OpenAI-compatible format
            if "lm_studio" in self.config.name.lower() or "1234" in self.config.api_base:
                kwargs["custom_llm_provider"] = "openai"
            elif "ollama" in self.config.name.lower() or "11434" in self.config.api_base:
                kwargs["custom_llm_provider"] = "ollama"

        # Add max_tokens if configured
        if self.config.max_tokens:
            kwargs["max_tokens"] = self.config.max_tokens

        # Add custom parameters
        kwargs.update(self.config.custom_params)

        # Override with any additional kwargs
        kwargs.update(override_kwargs)

        return kwargs

    def _map_litellm_error(self, error: Exception) -> LLMProviderError:
        """Map LiteLLM exceptions to custom exceptions without raising.

        Args:
            error: Original LiteLLM exception.

        Returns:
            Mapped custom exception instance.
        """
        provider_name = self.config.name
        model_name = self.config.model

        if isinstance(error, AuthenticationError):
            return LLMAuthenticationError(
                message=f"Authentication failed: {str(error)}",
                provider_name=provider_name,
                model_name=model_name,
                original_error=error,
            )

        if isinstance(error, RateLimitError):
            # Try to extract retry_after from error if available
            retry_after = getattr(error, "retry_after", None)
            return LLMRateLimitError(
                message=f"Rate limit exceeded: {str(error)}",
                provider_name=provider_name,
                model_name=model_name,
                original_error=error,
                retry_after=retry_after,
            )

        if isinstance(error, NotFoundError):
            return LLMModelNotFoundError(
                message=f"Model not found: {str(error)}",
                provider_name=provider_name,
                model_name=model_name,
                original_error=error,
            )

        if isinstance(error, APIConnectionError):
            return LLMConnectionError(
                message=f"Connection failed: {str(error)}",
                provider_name=provider_name,
                model_name=model_name,
                original_error=error,
            )

        if isinstance(error, InvalidRequestError):
            return LLMInvalidRequestError(
                message=f"Invalid request: {str(error)}",
                provider_name=provider_name,
                model_name=model_name,
                original_error=error,
            )

        # Generic error
        return LLMProviderError(
            message=f"LLM request failed: {str(error)}",
            provider_name=provider_name,
            model_name=model_name,
            original_error=error,
        )

    def _handle_litellm_error(self, error: Exception) -> None:
        """Convert LiteLLM exceptions to custom exceptions.

        Args:
            error: Original LiteLLM exception.

        Raises:
            LLMAuthenticationError: For authentication failures.
            LLMRateLimitError: For rate limit errors.
            LLMModelNotFoundError: For model not found errors.
            LLMConnectionError: For connection errors.
            LLMInvalidRequestError: For invalid request errors.
            LLMProviderError: For other errors.
        """
        raise self._map_litellm_error(error)

    def _retry_with_backoff(self, func: callable, *args: Any, **kwargs: Any) -> Any:
        """Retry a function with exponential backoff.

        This method catches raw LiteLLM exceptions, maps them to custom exceptions,
        and retries only transient errors (connection and rate limit errors) with
        exponential backoff. Non-transient errors are raised immediately without retry.

        Args:
            func: Function to retry.
            *args: Positional arguments to pass to func.
            **kwargs: Keyword arguments to pass to func.

        Returns:
            Result of successful function call.

        Raises:
            LLMProviderError: If all retry attempts fail or for non-transient errors.
        """
        max_retries = self.config.max_retries
        base_delay = 1.0  # Start with 1 second

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # If exception is already a custom LLM exception, use it directly
                # Otherwise, map raw LiteLLM exceptions to custom exceptions
                if isinstance(e, LLMProviderError):
                    mapped_exception = e
                else:
                    mapped_exception = self._map_litellm_error(e)

                # Only retry transient errors (connection and rate limit errors)
                if isinstance(mapped_exception, (LLMConnectionError, LLMRateLimitError)):
                    if attempt == max_retries - 1:
                        # Last attempt, raise the mapped exception
                        raise mapped_exception

                    # Calculate delay with exponential backoff
                    delay = base_delay * (2 ** attempt)

                    # If rate limit error includes retry_after, use that instead
                    if isinstance(mapped_exception, LLMRateLimitError) and mapped_exception.retry_after:
                        delay = mapped_exception.retry_after

                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries} failed: {str(mapped_exception)}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                else:
                    # For non-transient errors (auth, invalid request, model not found, etc.),
                    # raise immediately without retry
                    raise mapped_exception

    def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        """Perform chat completion using LiteLLM.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys.
            **kwargs: Additional parameters to override defaults.

        Returns:
            The LLM's response as a string.

        Raises:
            LLMProviderError: If the request fails.

        Examples:
            ```python
            response = provider.chat([
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is the capital of France?"}
            ])
            ```
        """
        litellm_kwargs = self._build_litellm_kwargs(**kwargs)

        logger.debug(
            f"Calling {self.config.name}/{self.config.model} with "
            f"{len(messages)} messages"
        )

        def _make_request() -> str:
            response = litellm.completion(messages=messages, **litellm_kwargs)
            content = response.choices[0].message.content

            if content is None:
                raise LLMResponseError(
                    message="LLM returned empty response",
                    provider_name=self.config.name,
                    model_name=self.config.model,
                )

            return content

        result = self._retry_with_backoff(_make_request)
        logger.debug(f"Received response of length {len(result)}")
        return result

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Perform text completion by converting to chat format.

        Args:
            prompt: The text prompt to complete.
            **kwargs: Additional parameters to override defaults.

        Returns:
            The LLM's completion as a string.

        Raises:
            LLMProviderError: If the request fails.

        Examples:
            ```python
            response = provider.complete("Once upon a time,")
            ```
        """
        # Convert prompt to chat message format
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, **kwargs)

    def embed(self, text: str, **kwargs: Any) -> List[float]:
        """Generate embeddings using LiteLLM.

        Args:
            text: Text to generate embeddings for.
            **kwargs: Additional parameters to override defaults.

        Returns:
            Embedding vector as a list of floats.

        Raises:
            LLMProviderError: If the request fails.

        Examples:
            ```python
            embedding = provider.embed("Hello, world!")
            print(f"Embedding dimension: {len(embedding)}")
            ```
        """
        litellm_kwargs = self._build_litellm_kwargs(**kwargs)

        # Remove parameters not supported by embedding API
        litellm_kwargs.pop("temperature", None)
        litellm_kwargs.pop("max_tokens", None)

        logger.debug(
            f"Generating embedding with {self.config.name}/{self.config.model}"
        )

        def _make_request() -> List[float]:
            response = litellm.embedding(input=[text], **litellm_kwargs)

            if not response.data or len(response.data) == 0:
                raise LLMResponseError(
                    message="LLM returned empty embedding",
                    provider_name=self.config.name,
                    model_name=self.config.model,
                )

            return response.data[0]["embedding"]

        result = self._retry_with_backoff(_make_request)
        logger.debug(f"Generated embedding of dimension {len(result)}")
        return result

    def is_available(self) -> bool:
        """Check if the provider is available by making a minimal test request.

        Returns:
            True if provider is available and responding, False otherwise.

        Examples:
            ```python
            if provider.is_available():
                response = provider.chat([{"role": "user", "content": "Hello"}])
            else:
                print("Provider is not available")
            ```
        """
        try:
            # Try a minimal chat request
            self.chat(
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,
            )
            return True
        except LLMProviderError as e:
            logger.debug(f"Provider {self.config.name} is not available: {e}")
            return False
        except Exception as e:
            logger.debug(f"Provider {self.config.name} availability check failed: {e}")
            return False


def get_llm_provider(
    provider_name: Optional[str] = None,
    config_path: Optional[str] = None,
) -> LLMProvider:
    """Factory function to create an LLM provider instance.

    This is the recommended way to instantiate LLM providers. It handles
    loading configuration from config.toml and creating the appropriate
    provider instance.

    Args:
        provider_name: Name of the provider to use. If None, uses default from config.
        config_path: Path to config.toml file. If None, uses default path.

    Returns:
        Configured LLMProvider instance.

    Raises:
        ValueError: If provider not found in configuration.
        FileNotFoundError: If config file not found.

    Examples:
        ```python
        # Use default provider from config
        provider = get_llm_provider()

        # Use specific provider
        provider = get_llm_provider("openai")

        # Use custom config file
        provider = get_llm_provider(config_path="/path/to/config.toml")
        ```
    """
    # Load configuration
    config_manager = ConfigManager(config_path=config_path)
    llm_config = LLMConfig.from_config_manager(config_manager)

    # Determine which provider to use
    if provider_name is None:
        provider_name = llm_config.default_provider

    # Get provider configuration
    provider_config = get_provider_config(llm_config, provider_name)

    # Create and return provider instance
    logger.info(f"Creating LLM provider: {provider_name} with model {provider_config.model}")
    return LiteLLMProvider(provider_config)

