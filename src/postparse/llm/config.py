"""Configuration models for LLM providers using Pydantic."""

import os
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from postparse.core.utils.config import ConfigManager


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider.

    Attributes:
        name: Provider identifier (e.g., 'openai', 'anthropic', 'ollama', 'lm_studio').
        model: Model name/identifier.
        api_key: API key for authentication (loaded from env var if not provided).
        api_base: Custom API endpoint for local providers (LM Studio, Ollama).
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts.
        temperature: Sampling temperature (0.0-2.0).
        max_tokens: Maximum tokens in response.
        custom_params: Provider-specific parameters (sent as extra request body
            fields to OpenAI-compatible servers).
        api_type: Client protocol: ``openai`` (OpenAI and every OpenAI-compatible
            server such as llama.cpp, LM Studio, Ollama, vLLM) or ``anthropic``.
            ``None`` derives it from ``name``.
        output_mode: Structured-output strategy: ``native`` (JSON schema via
            ``response_format``; llama.cpp turns it into a grammar), ``tool``
            (forced tool call) or ``prompted`` (schema in the prompt). ``None``
            picks ``native`` for self-hosted endpoints and ``tool`` for cloud APIs.
        max_concurrency: Maximum parallel requests. ``None`` means 1 for
            self-hosted endpoints (one llama.cpp slot) and 4 for cloud APIs.
        discover_model: Ask the server which model it serves (``/v1/models`` or
            Ollama ``/api/ps``). ``None`` enables it for self-hosted endpoints.

    Examples:
        ```python
        # OpenAI configuration
        config = ProviderConfig(
            name="openai",
            model="gpt-4o-mini",
            temperature=0.7
        )

        # Local LM Studio configuration
        config = ProviderConfig(
            name="lm_studio",
            model="qwen/qwen3-vl-8b",
            api_base="http://localhost:1234/v1",
            timeout=60
        )
        ```
    """

    name: str = Field(..., description="Provider identifier")
    model: str = Field(..., description="Model name/identifier")
    api_key: str | None = Field(default=None, description="API key for authentication")
    api_base: str | None = Field(default=None, description="Custom API endpoint")
    timeout: int = Field(default=30, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    temperature: float = Field(default=0.7, description="Sampling temperature")
    max_tokens: int | None = Field(default=None, description="Maximum tokens in response")
    custom_params: dict[str, Any] = Field(
        default_factory=dict, description="Provider-specific parameters"
    )
    api_type: Literal["openai", "anthropic"] | None = Field(
        default=None, description="Client protocol (derived from name when unset)"
    )
    output_mode: Literal["native", "tool", "prompted"] | None = Field(
        default=None, description="Structured output strategy (auto when unset)"
    )
    max_concurrency: int | None = Field(
        default=None, ge=1, description="Maximum parallel requests (auto when unset)"
    )
    discover_model: bool | None = Field(
        default=None, description="Discover the served model (auto when unset)"
    )

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """Validate temperature is in valid range (0.0-2.0)."""
        if not 0.0 <= v <= 2.0:
            raise ValueError(f"Temperature must be between 0.0 and 2.0, got {v}")
        return v

    @model_validator(mode="after")
    def load_api_key_from_env(self) -> "ProviderConfig":
        """Load API key from environment variable if not provided.

        Checks for provider-specific environment variables:
        - openai: OPENAI_API_KEY
        - anthropic: ANTHROPIC_API_KEY
        - lm_studio: OPENAI_API_KEY (uses OpenAI-compatible format)
        - ollama: No API key needed for local deployment
        """
        if self.api_key is None:
            # Map provider names to their environment variable names
            env_var_map = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "lm_studio": "OPENAI_API_KEY",  # LM Studio uses OpenAI-compatible format
            }

            env_var = env_var_map.get(self.name.lower())
            if env_var:
                self.api_key = os.getenv(env_var)

        return self


class LLMConfig(BaseModel):
    """Configuration for LLM provider abstraction.

    Attributes:
        providers: List of provider configurations (first is primary, rest are fallbacks).
        default_provider: Name of the default provider to use.
        enable_fallback: Whether to try fallback providers on failure.
        cache_responses: Whether to cache LLM responses (for future implementation).

    Examples:
        ```python
        config = LLMConfig(
            default_provider="openai",
            enable_fallback=True,
            providers=[
                ProviderConfig(name="openai", model="gpt-4o-mini"),
                ProviderConfig(name="anthropic", model="claude-3-5-sonnet-20241022")
            ]
        )

        # Get specific provider config
        openai_config = config.get_provider("openai")
        ```
    """

    providers: list[ProviderConfig] = Field(..., description="List of provider configurations")
    default_provider: str = Field(..., description="Name of the default provider")
    enable_fallback: bool = Field(default=True, description="Enable automatic fallback")
    cache_responses: bool = Field(default=False, description="Enable response caching")

    @model_validator(mode="after")
    def validate_default_provider(self) -> "LLMConfig":
        """Ensure default_provider exists in providers list."""
        provider_names = [p.name for p in self.providers]
        if self.default_provider not in provider_names:
            raise ValueError(
                f"default_provider '{self.default_provider}' not found in providers list. "
                f"Available providers: {', '.join(provider_names)}"
            )
        return self

    def get_provider(self, name: str) -> ProviderConfig | None:
        """Get provider configuration by name.

        Args:
            name: Provider name to look up.

        Returns:
            Provider configuration if found, None otherwise.

        Examples:
            ```python
            config = LLMConfig(...)
            openai = config.get_provider("openai")
            ```
        """
        for provider in self.providers:
            if provider.name == name:
                return provider
        return None

    @classmethod
    def from_config_manager(cls, config_manager: ConfigManager) -> "LLMConfig":
        """Load LLM configuration from ConfigManager.

        Args:
            config_manager: Configured ConfigManager instance.

        Returns:
            Validated LLMConfig instance.

        Raises:
            ValueError: If configuration is invalid or missing required fields.

        Examples:
            ```python
            config_manager = ConfigManager()
            llm_config = LLMConfig.from_config_manager(config_manager)
            ```
        """
        # Get LLM section from config
        llm_section = config_manager.get_section("llm")

        if not llm_section:
            raise ValueError("No [llm] section found in config.toml")

        # Extract provider configurations
        provider_configs = []
        for provider_data in llm_section.get("providers", []):
            provider_configs.append(ProviderConfig(**provider_data))

        # Build LLMConfig
        # model_validate: a missing default_provider is reported by pydantic.
        return cls.model_validate(
            {
                "providers": provider_configs,
                "default_provider": llm_section.get("default_provider"),
                "enable_fallback": llm_section.get("enable_fallback", True),
                "cache_responses": llm_section.get("cache_responses", False),
            }
        )


def load_llm_config(config_manager: ConfigManager) -> LLMConfig:
    """Load and validate LLM configuration from ConfigManager.

    This is a convenience function that wraps LLMConfig.from_config_manager().

    Args:
        config_manager: Configured ConfigManager instance.

    Returns:
        Validated LLMConfig instance.

    Raises:
        ValueError: If configuration is invalid or missing required fields.

    Examples:
        ```python
        from postparse.core.utils.config import ConfigManager
        from postparse.llm.config import load_llm_config

        config_manager = ConfigManager()
        llm_config = load_llm_config(config_manager)
        ```
    """
    return LLMConfig.from_config_manager(config_manager)


def get_provider_config(llm_config: LLMConfig, provider_name: str) -> ProviderConfig:
    """Get specific provider configuration by name.

    Args:
        llm_config: LLM configuration instance.
        provider_name: Name of the provider to retrieve.

    Returns:
        Provider configuration.

    Raises:
        ValueError: If provider not found in configuration.

    Examples:
        ```python
        llm_config = load_llm_config(config_manager)
        openai_config = get_provider_config(llm_config, "openai")
        ```
    """
    provider = llm_config.get_provider(provider_name)
    if provider is None:
        available = ", ".join(p.name for p in llm_config.providers)
        raise ValueError(
            f"Provider '{provider_name}' not found in configuration. "
            f"Available providers: {available}"
        )
    return provider
