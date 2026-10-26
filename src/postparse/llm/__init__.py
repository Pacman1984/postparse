"""LLM Provider Abstraction Layer.

This module provides a clean, framework-agnostic abstraction for interacting with
various LLM providers (OpenAI, Anthropic, Ollama, LM Studio) through a unified
interface backed by LiteLLM.

Basic Usage:
    ```python
    from postparse.llm import get_llm_provider

    # Get default provider from config
    provider = get_llm_provider()

    # Simple chat completion
    response = provider.chat([
        {"role": "user", "content": "Classify this recipe: Chocolate Chip Cookies"}
    ])

    # Or specify a provider explicitly
    provider = get_llm_provider("openai")
    response = provider.complete("What is the capital of France?")
    ```

Features:
    - Multiple provider support with automatic fallback
    - Comprehensive error handling with custom exceptions
    - Configuration via config.toml with environment variable overrides
    - Support for both cloud providers and local endpoints
    - Type-safe configuration with Pydantic models
"""

from postparse.llm.config import LLMConfig, ProviderConfig, load_llm_config
from postparse.llm.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMInvalidRequestError,
    LLMModelNotFoundError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseError,
)
from postparse.llm.provider import LiteLLMProvider, LLMProvider, get_llm_provider

__all__ = [
    # Base classes
    "LLMProvider",
    "LiteLLMProvider",
    # Factory function
    "get_llm_provider",
    # Configuration
    "LLMConfig",
    "ProviderConfig",
    "load_llm_config",
    # Exceptions
    "LLMProviderError",
    "LLMConnectionError",
    "LLMAuthenticationError",
    "LLMRateLimitError",
    "LLMModelNotFoundError",
    "LLMInvalidRequestError",
    "LLMResponseError",
]

