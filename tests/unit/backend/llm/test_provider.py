"""Tests for LLM provider implementation."""

from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, patch

import pytest

from backend.postparse.llm.config import LLMConfig, ProviderConfig
from backend.postparse.llm.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMInvalidRequestError,
    LLMModelNotFoundError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseError,
)
from backend.postparse.llm.provider import LiteLLMProvider, get_llm_provider


@pytest.fixture
def mock_provider_config() -> ProviderConfig:
    """Fixture returning a ProviderConfig instance with test values.

    Returns:
        Test provider configuration.
    """
    return ProviderConfig(
        name="test_provider",
        model="test_model",
        api_key="test_api_key",
        timeout=30,
        max_retries=3,
        temperature=0.7,
    )


@pytest.fixture
def mock_llm_config() -> LLMConfig:
    """Fixture returning an LLMConfig instance with multiple providers.

    Returns:
        Test LLM configuration with multiple providers.
    """
    return LLMConfig(
        default_provider="openai",
        enable_fallback=True,
        providers=[
            ProviderConfig(name="openai", model="gpt-4", api_key="test_key_1"),
            ProviderConfig(name="anthropic", model="claude-3", api_key="test_key_2"),
        ],
    )


@pytest.fixture
def mock_litellm_completion() -> MagicMock:
    """Fixture that mocks litellm.completion() to return test responses.

    Returns:
        Mock object for litellm.completion.
    """
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = "Test response"

    with patch("backend.postparse.llm.provider.litellm.completion", return_value=mock_response) as mock:
        yield mock


@pytest.fixture
def mock_litellm_embedding() -> MagicMock:
    """Fixture that mocks litellm.embedding() to return test vectors.

    Returns:
        Mock object for litellm.embedding.
    """
    mock_response = Mock()
    mock_response.data = [{"embedding": [0.1, 0.2, 0.3, 0.4, 0.5]}]

    with patch("backend.postparse.llm.provider.litellm.embedding", return_value=mock_response) as mock:
        yield mock


class TestProviderConfig:
    """Tests for ProviderConfig model."""

    def test_provider_config_creation(self) -> None:
        """Test creating ProviderConfig with valid data."""
        config = ProviderConfig(
            name="openai",
            model="gpt-4",
            api_key="test_key",
            temperature=0.8,
        )

        assert config.name == "openai"
        assert config.model == "gpt-4"
        assert config.api_key == "test_key"
        assert config.temperature == 0.8
        assert config.timeout == 30  # default
        assert config.max_retries == 3  # default

    def test_provider_config_validation(self) -> None:
        """Test validation (temperature range, required fields)."""
        # Test invalid temperature (too low)
        with pytest.raises(ValueError, match="Temperature must be between"):
            ProviderConfig(name="test", model="test", temperature=-0.1)

        # Test invalid temperature (too high)
        with pytest.raises(ValueError, match="Temperature must be between"):
            ProviderConfig(name="test", model="test", temperature=2.1)

        # Test valid temperature boundaries
        config_min = ProviderConfig(name="test", model="test", temperature=0.0)
        assert config_min.temperature == 0.0

        config_max = ProviderConfig(name="test", model="test", temperature=2.0)
        assert config_max.temperature == 2.0

    def test_provider_config_env_var_loading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test API key loading from environment variables."""
        # Test OpenAI
        monkeypatch.setenv("OPENAI_API_KEY", "env_openai_key")
        config_openai = ProviderConfig(name="openai", model="gpt-4")
        assert config_openai.api_key == "env_openai_key"

        # Test Anthropic
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env_anthropic_key")
        config_anthropic = ProviderConfig(name="anthropic", model="claude-3")
        assert config_anthropic.api_key == "env_anthropic_key"

        # Test LM Studio (uses OPENAI_API_KEY)
        config_lm = ProviderConfig(name="lm_studio", model="local-model")
        assert config_lm.api_key == "env_openai_key"

        # Test Ollama (no API key needed)
        config_ollama = ProviderConfig(name="ollama", model="llama2")
        assert config_ollama.api_key == "env_openai_key" or config_ollama.api_key is None

    def test_provider_config_defaults(self) -> None:
        """Test default values for optional fields."""
        config = ProviderConfig(name="test", model="test")

        assert config.timeout == 30
        assert config.max_retries == 3
        assert config.temperature == 0.7
        assert config.max_tokens is None
        assert config.api_key is None
        assert config.api_base is None
        assert config.custom_params == {}


class TestLLMConfig:
    """Tests for LLMConfig model."""

    def test_llm_config_creation(self) -> None:
        """Test creating LLMConfig with provider list."""
        providers = [
            ProviderConfig(name="openai", model="gpt-4"),
            ProviderConfig(name="anthropic", model="claude-3"),
        ]

        config = LLMConfig(
            default_provider="openai",
            enable_fallback=True,
            providers=providers,
        )

        assert config.default_provider == "openai"
        assert config.enable_fallback is True
        assert len(config.providers) == 2

    def test_llm_config_default_provider_validation(self) -> None:
        """Test that default_provider must exist in providers."""
        providers = [
            ProviderConfig(name="openai", model="gpt-4"),
        ]

        # Should raise error if default_provider not in providers
        with pytest.raises(ValueError, match="default_provider 'nonexistent' not found"):
            LLMConfig(
                default_provider="nonexistent",
                providers=providers,
            )

    def test_get_provider_config(self, mock_llm_config: LLMConfig) -> None:
        """Test retrieving specific provider by name."""
        openai = mock_llm_config.get_provider("openai")
        assert openai is not None
        assert openai.name == "openai"
        assert openai.model == "gpt-4"

        anthropic = mock_llm_config.get_provider("anthropic")
        assert anthropic is not None
        assert anthropic.name == "anthropic"

        # Test nonexistent provider
        nonexistent = mock_llm_config.get_provider("nonexistent")
        assert nonexistent is None

    def test_llm_config_from_config_manager(self) -> None:
        """Test loading from ConfigManager (mock config.toml)."""
        # Create a mock ConfigManager
        mock_config_manager = Mock()
        mock_config_manager.get_section.return_value = {
            "default_provider": "openai",
            "enable_fallback": True,
            "providers": [
                {"name": "openai", "model": "gpt-4", "api_key": "test_key"},
                {"name": "anthropic", "model": "claude-3", "api_key": "test_key2"},
            ],
        }

        config = LLMConfig.from_config_manager(mock_config_manager)

        assert config.default_provider == "openai"
        assert config.enable_fallback is True
        assert len(config.providers) == 2
        assert config.providers[0].name == "openai"

    def test_llm_config_from_config_manager_missing_section(self) -> None:
        """Test error when [llm] section is missing."""
        mock_config_manager = Mock()
        mock_config_manager.get_section.return_value = {}

        with pytest.raises(ValueError, match="No \\[llm\\] section found"):
            LLMConfig.from_config_manager(mock_config_manager)


class TestLiteLLMProvider:
    """Tests for LiteLLMProvider implementation."""

    def test_provider_initialization(self, mock_provider_config: ProviderConfig) -> None:
        """Test LiteLLMProvider initialization with config."""
        provider = LiteLLMProvider(mock_provider_config)

        assert provider.config == mock_provider_config
        assert provider.get_provider_name() == "test_provider"
        assert provider.get_model_name() == "test_model"

    def test_chat_success(
        self,
        mock_provider_config: ProviderConfig,
        mock_litellm_completion: MagicMock,
    ) -> None:
        """Test successful chat completion with mocked response."""
        provider = LiteLLMProvider(mock_provider_config)
        messages = [{"role": "user", "content": "Hello"}]

        response = provider.chat(messages)

        assert response == "Test response"
        mock_litellm_completion.assert_called_once()

        # Verify the call includes expected parameters
        call_kwargs = mock_litellm_completion.call_args[1]
        assert call_kwargs["model"] == "test_model"
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["messages"] == messages

    def test_chat_with_custom_params(
        self,
        mock_provider_config: ProviderConfig,
        mock_litellm_completion: MagicMock,
    ) -> None:
        """Test passing custom parameters (temperature, max_tokens)."""
        provider = LiteLLMProvider(mock_provider_config)
        messages = [{"role": "user", "content": "Hello"}]

        response = provider.chat(messages, temperature=0.9, max_tokens=500)

        assert response == "Test response"

        # Verify custom parameters were passed through
        call_kwargs = mock_litellm_completion.call_args[1]
        assert call_kwargs["temperature"] == 0.9
        assert call_kwargs["max_tokens"] == 500

    def test_complete_success(
        self,
        mock_provider_config: ProviderConfig,
        mock_litellm_completion: MagicMock,
    ) -> None:
        """Test successful text completion."""
        provider = LiteLLMProvider(mock_provider_config)

        response = provider.complete("Once upon a time")

        assert response == "Test response"
        mock_litellm_completion.assert_called_once()

        # Verify prompt was converted to message format
        call_kwargs = mock_litellm_completion.call_args[1]
        assert call_kwargs["messages"] == [{"role": "user", "content": "Once upon a time"}]

    def test_embed_success(
        self,
        mock_provider_config: ProviderConfig,
        mock_litellm_embedding: MagicMock,
    ) -> None:
        """Test successful embedding generation."""
        provider = LiteLLMProvider(mock_provider_config)

        embedding = provider.embed("Test text")

        assert embedding == [0.1, 0.2, 0.3, 0.4, 0.5]
        mock_litellm_embedding.assert_called_once()

        # Verify the call
        call_kwargs = mock_litellm_embedding.call_args[1]
        assert call_kwargs["model"] == "test_model"
        assert call_kwargs["input"] == ["Test text"]

    def test_get_provider_name(self, mock_provider_config: ProviderConfig) -> None:
        """Test provider name retrieval."""
        provider = LiteLLMProvider(mock_provider_config)
        assert provider.get_provider_name() == "test_provider"

    def test_get_model_name(self, mock_provider_config: ProviderConfig) -> None:
        """Test model name retrieval."""
        provider = LiteLLMProvider(mock_provider_config)
        assert provider.get_model_name() == "test_model"

    def test_is_available_success(
        self,
        mock_provider_config: ProviderConfig,
        mock_litellm_completion: MagicMock,
    ) -> None:
        """Test availability check when provider is reachable."""
        provider = LiteLLMProvider(mock_provider_config)

        is_available = provider.is_available()

        assert is_available is True
        mock_litellm_completion.assert_called_once()

    def test_is_available_failure(
        self,
        mock_provider_config: ProviderConfig,
    ) -> None:
        """Test availability check when provider is unreachable."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            mock_completion.side_effect = Exception("Connection failed")

            is_available = provider.is_available()

            assert is_available is False


class TestLiteLLMProviderErrorHandling:
    """Tests for LiteLLM provider error handling."""

    def test_authentication_error(self, mock_provider_config: ProviderConfig) -> None:
        """Test that authentication errors are properly converted to LLMAuthenticationError."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            from litellm import AuthenticationError
            import httpx

            # Create properly formatted LiteLLM authentication exception with request
            mock_request = httpx.Request(method="POST", url="http://test")
            mock_response = httpx.Response(
                status_code=401,
                content=b"Invalid API key",
                request=mock_request,
            )
            mock_completion.side_effect = AuthenticationError(
                message="Invalid API key",
                llm_provider="test_provider",
                model="test_model",
                response=mock_response,
            )

            with pytest.raises(LLMAuthenticationError) as exc_info:
                provider.chat([{"role": "user", "content": "test"}])

            assert "Invalid API key" in str(exc_info.value)
            assert exc_info.value.provider_name == "test_provider"

    def test_rate_limit_error(self, mock_provider_config: ProviderConfig) -> None:
        """Mock litellm.RateLimitError and verify LLMRateLimitError is raised."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            from litellm import RateLimitError
            import httpx

            # Create properly formatted LiteLLM exception
            mock_response = httpx.Response(status_code=429, content="Rate limit exceeded")
            mock_completion.side_effect = RateLimitError(
                message="Rate limit exceeded",
                llm_provider="test_provider",
                model="test_model",
                response=mock_response,
            )

            with pytest.raises(LLMRateLimitError) as exc_info:
                provider.chat([{"role": "user", "content": "test"}])

            assert "Rate limit exceeded" in str(exc_info.value)
            assert exc_info.value.provider_name == "test_provider"

    def test_model_not_found_error(self, mock_provider_config: ProviderConfig) -> None:
        """Test that model not found errors are properly converted to LLMModelNotFoundError."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            from litellm import NotFoundError
            import httpx

            # Create properly formatted LiteLLM not found exception with request
            mock_request = httpx.Request(method="POST", url="http://test")
            mock_response = httpx.Response(
                status_code=404,
                content=b"Model not found",
                request=mock_request,
            )
            mock_completion.side_effect = NotFoundError(
                message="Model not found",
                llm_provider="test_provider",
                model="test_model",
                response=mock_response,
            )

            with pytest.raises(LLMModelNotFoundError) as exc_info:
                provider.chat([{"role": "user", "content": "test"}])

            assert "Model not found" in str(exc_info.value)
            assert exc_info.value.provider_name == "test_provider"

    def test_connection_error(self, mock_provider_config: ProviderConfig) -> None:
        """Mock litellm.APIConnectionError and verify LLMConnectionError is raised."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            from litellm import APIConnectionError
            import httpx

            # Create properly formatted LiteLLM exception
            mock_response = httpx.Response(status_code=503, content="Service unavailable")
            mock_completion.side_effect = APIConnectionError(
                message="Connection failed",
                llm_provider="test_provider",
                model="test_model",
                request=httpx.Request(method="POST", url="http://test"),
            )

            with pytest.raises(LLMConnectionError) as exc_info:
                provider.chat([{"role": "user", "content": "test"}])

            assert "Connection failed" in str(exc_info.value)

    def test_invalid_request_error(self, mock_provider_config: ProviderConfig) -> None:
        """Test that invalid request errors are properly converted to LLMInvalidRequestError."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            from litellm import InvalidRequestError

            # Create LiteLLM invalid request exception (simpler signature)
            mock_completion.side_effect = InvalidRequestError(
                message="Invalid request parameters",
                model="test_model",
                llm_provider="test_provider",
            )

            with pytest.raises(LLMInvalidRequestError) as exc_info:
                provider.chat([{"role": "user", "content": "test"}])

            assert "Invalid request" in str(exc_info.value)
            assert exc_info.value.provider_name == "test_provider"

    def test_generic_error(self, mock_provider_config: ProviderConfig) -> None:
        """Mock generic exception and verify LLMProviderError is raised."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            mock_completion.side_effect = Exception("Unexpected error")

            with pytest.raises(LLMProviderError) as exc_info:
                provider.chat([{"role": "user", "content": "test"}])

            assert "LLM request failed" in str(exc_info.value)

    def test_error_preserves_original(self, mock_provider_config: ProviderConfig) -> None:
        """Verify original exception is preserved in __cause__."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            original_error = ValueError("Original error")
            mock_completion.side_effect = original_error

            with pytest.raises(LLMProviderError) as exc_info:
                provider.chat([{"role": "user", "content": "test"}])

            assert exc_info.value.original_error is original_error
            assert exc_info.value.__cause__ is original_error

    def test_empty_response_error(self, mock_provider_config: ProviderConfig) -> None:
        """Test handling of empty/None response content."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            mock_response = Mock()
            mock_response.choices = [Mock()]
            mock_response.choices[0].message.content = None  # Empty content
            mock_completion.return_value = mock_response

            with pytest.raises(LLMResponseError) as exc_info:
                provider.chat([{"role": "user", "content": "test"}])

            assert "empty response" in str(exc_info.value).lower()


class TestRetryLogic:
    """Tests for retry/backoff logic with transient errors."""

    def test_rate_limit_retry_with_backoff(self, mock_provider_config: ProviderConfig) -> None:
        """Test that RateLimitError triggers multiple retry attempts with exponential backoff."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            with patch("backend.postparse.llm.provider.time.sleep") as mock_sleep:
                from litellm import RateLimitError
                import httpx

                # Create properly formatted LiteLLM exception
                mock_response = httpx.Response(status_code=429, content="Rate limit exceeded")
                mock_completion.side_effect = RateLimitError(
                    message="Rate limit exceeded",
                    llm_provider="test_provider",
                    model="test_model",
                    response=mock_response,
                )

                with pytest.raises(LLMRateLimitError):
                    provider.chat([{"role": "user", "content": "test"}])

                # Verify retry attempts (max_retries=3)
                assert mock_completion.call_count == 3

                # Verify exponential backoff: 1s, 2s (since max_retries=3, we get 2 sleeps)
                assert mock_sleep.call_count == 2
                sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                assert sleep_calls[0] == 1.0  # 2^0 = 1
                assert sleep_calls[1] == 2.0  # 2^1 = 2

    def test_connection_error_retry_with_backoff(self, mock_provider_config: ProviderConfig) -> None:
        """Test that APIConnectionError triggers multiple retry attempts with exponential backoff."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            with patch("backend.postparse.llm.provider.time.sleep") as mock_sleep:
                from litellm import APIConnectionError
                import httpx

                # Create properly formatted LiteLLM exception
                mock_completion.side_effect = APIConnectionError(
                    message="Connection failed",
                    llm_provider="test_provider",
                    model="test_model",
                    request=httpx.Request(method="POST", url="http://test"),
                )

                with pytest.raises(LLMConnectionError):
                    provider.chat([{"role": "user", "content": "test"}])

                # Verify retry attempts
                assert mock_completion.call_count == 3

                # Verify exponential backoff
                assert mock_sleep.call_count == 2
                sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                assert sleep_calls[0] == 1.0
                assert sleep_calls[1] == 2.0

    def test_rate_limit_with_retry_after(self, mock_provider_config: ProviderConfig) -> None:
        """Test that rate limit with retry_after uses that value instead of exponential backoff."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            with patch("backend.postparse.llm.provider.time.sleep") as mock_sleep:
                from litellm import RateLimitError
                import httpx

                # Create RateLimitError with retry_after
                mock_response = httpx.Response(status_code=429, content="Rate limit exceeded")
                error = RateLimitError(
                    message="Rate limit exceeded",
                    llm_provider="test_provider",
                    model="test_model",
                    response=mock_response,
                )
                error.retry_after = 5  # Custom retry_after value
                mock_completion.side_effect = error

                with pytest.raises(LLMRateLimitError):
                    provider.chat([{"role": "user", "content": "test"}])

                # Verify retry attempts
                assert mock_completion.call_count == 3

                # Verify retry_after was used instead of exponential backoff
                assert mock_sleep.call_count == 2
                sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                assert sleep_calls[0] == 5  # Uses retry_after
                assert sleep_calls[1] == 5  # Uses retry_after

    def test_non_transient_errors_no_retry(self, mock_provider_config: ProviderConfig) -> None:
        """Test that non-transient errors (auth, invalid request, model not found) are not retried."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            with patch("backend.postparse.llm.provider.time.sleep") as mock_sleep:
                # Use a generic exception that will be mapped to LLMProviderError
                # and should not be retried (since it's not a ConnectionError or RateLimitError)
                mock_completion.side_effect = ValueError("Invalid parameter value")

                with pytest.raises(LLMProviderError) as exc_info:
                    provider.chat([{"role": "user", "content": "test"}])

                # Verify only one attempt (no retry for non-transient errors)
                assert mock_completion.call_count == 1

                # Verify no sleep calls (no backoff)
                assert mock_sleep.call_count == 0

                # Verify the error message contains expected content
                assert "LLM request failed" in str(exc_info.value)

    def test_successful_retry_after_failures(self, mock_provider_config: ProviderConfig) -> None:
        """Test that successful response after transient failures returns correctly."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.completion") as mock_completion:
            with patch("backend.postparse.llm.provider.time.sleep") as mock_sleep:
                from litellm import APIConnectionError
                import httpx

                # First two calls fail, third succeeds
                mock_success = Mock()
                mock_success.choices = [Mock()]
                mock_success.choices[0].message.content = "Success!"

                connection_error = APIConnectionError(
                    message="Connection failed",
                    llm_provider="test_provider",
                    model="test_model",
                    request=httpx.Request(method="POST", url="http://test"),
                )

                mock_completion.side_effect = [
                    connection_error,
                    connection_error,
                    mock_success,
                ]

                result = provider.chat([{"role": "user", "content": "test"}])

                # Verify result is from successful attempt
                assert result == "Success!"

                # Verify 3 attempts were made
                assert mock_completion.call_count == 3

                # Verify backoff delays
                assert mock_sleep.call_count == 2
                sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                assert sleep_calls[0] == 1.0
                assert sleep_calls[1] == 2.0

    def test_embed_retry_logic(self, mock_provider_config: ProviderConfig) -> None:
        """Test that embed() also benefits from retry logic."""
        provider = LiteLLMProvider(mock_provider_config)

        with patch("backend.postparse.llm.provider.litellm.embedding") as mock_embedding:
            with patch("backend.postparse.llm.provider.time.sleep") as mock_sleep:
                from litellm import APIConnectionError
                import httpx

                connection_error = APIConnectionError(
                    message="Connection failed",
                    llm_provider="test_provider",
                    model="test_model",
                    request=httpx.Request(method="POST", url="http://test"),
                )

                mock_embedding.side_effect = connection_error

                with pytest.raises(LLMConnectionError):
                    provider.embed("test text")

                # Verify retry attempts
                assert mock_embedding.call_count == 3

                # Verify exponential backoff
                assert mock_sleep.call_count == 2


class TestFactoryFunction:
    """Tests for the get_llm_provider factory function."""

    def test_get_llm_provider_default(self) -> None:
        """Test factory function with default provider."""
        # Mock ConfigManager to return test config
        with patch("backend.postparse.llm.provider.ConfigManager") as mock_cm_class:
            mock_cm = Mock()
            mock_cm_class.return_value = mock_cm
            mock_cm.get_section.return_value = {
                "default_provider": "openai",
                "enable_fallback": True,
                "providers": [
                    {"name": "openai", "model": "gpt-4", "api_key": "test_key"},
                ],
            }

            provider = get_llm_provider()

            assert isinstance(provider, LiteLLMProvider)
            assert provider.get_provider_name() == "openai"
            assert provider.get_model_name() == "gpt-4"

    def test_get_llm_provider_specific(self) -> None:
        """Test factory function with specific provider name."""
        with patch("backend.postparse.llm.provider.ConfigManager") as mock_cm_class:
            mock_cm = Mock()
            mock_cm_class.return_value = mock_cm
            mock_cm.get_section.return_value = {
                "default_provider": "openai",
                "enable_fallback": True,
                "providers": [
                    {"name": "openai", "model": "gpt-4"},
                    {"name": "anthropic", "model": "claude-3"},
                ],
            }

            provider = get_llm_provider("anthropic")

            assert provider.get_provider_name() == "anthropic"
            assert provider.get_model_name() == "claude-3"

    def test_get_llm_provider_invalid(self) -> None:
        """Test factory function with invalid provider name raises ValueError."""
        with patch("backend.postparse.llm.provider.ConfigManager") as mock_cm_class:
            mock_cm = Mock()
            mock_cm_class.return_value = mock_cm
            mock_cm.get_section.return_value = {
                "default_provider": "openai",
                "enable_fallback": True,
                "providers": [
                    {"name": "openai", "model": "gpt-4"},
                ],
            }

            with pytest.raises(ValueError, match="Provider 'nonexistent' not found"):
                get_llm_provider("nonexistent")

    def test_get_llm_provider_custom_config(self) -> None:
        """Test factory function with custom config path."""
        with patch("backend.postparse.llm.provider.ConfigManager") as mock_cm_class:
            mock_cm = Mock()
            mock_cm_class.return_value = mock_cm
            mock_cm.get_section.return_value = {
                "default_provider": "openai",
                "enable_fallback": True,
                "providers": [
                    {"name": "openai", "model": "gpt-4"},
                ],
            }

            provider = get_llm_provider(config_path="/custom/config.toml")

            # Verify ConfigManager was called with custom path
            mock_cm_class.assert_called_once_with(config_path="/custom/config.toml")
            assert isinstance(provider, LiteLLMProvider)

