"""Unit tests for local LLM model discovery."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.postparse.llm.config import ProviderConfig
from backend.postparse.llm.model_discovery import (
    discover_openai_compatible_model,
    discover_served_model,
    resolve_provider_model,
)


class TestDiscoverOpenAICompatibleModel:
    """Tests for OpenAI-compatible model discovery."""

    def test_discovers_single_served_model(self) -> None:
        """Return the only model reported by /v1/models."""
        config = ProviderConfig(
            name="lama.cpp",
            model="stale-model",
            api_base="http://localhost:1235/v1",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"id": "actual-model-name"}],
        }
        mock_response.raise_for_status.return_value = None

        with patch(
            "backend.postparse.llm.model_discovery.httpx.get",
            return_value=mock_response,
        ) as mock_get:
            model = discover_openai_compatible_model(config)

        assert model == "actual-model-name"
        mock_get.assert_called_once_with(
            "http://localhost:1235/v1/models",
            headers={},
            timeout=5.0,
        )

    def test_prefers_configured_model_when_present(self) -> None:
        """Keep configured model when it is listed by the server."""
        config = ProviderConfig(
            name="lm_studio",
            model="preferred-model",
            api_base="http://localhost:1234/v1",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "other-model"},
                {"id": "preferred-model"},
            ],
        }
        mock_response.raise_for_status.return_value = None

        with patch(
            "backend.postparse.llm.model_discovery.httpx.get",
            return_value=mock_response,
        ):
            model = discover_openai_compatible_model(config)

        assert model == "preferred-model"

    def test_returns_none_on_request_failure(self) -> None:
        """Return None when the models endpoint is unreachable."""
        config = ProviderConfig(
            name="lama.cpp",
            model="stale-model",
            api_base="http://localhost:1235/v1",
        )

        with patch(
            "backend.postparse.llm.model_discovery.httpx.get",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            model = discover_openai_compatible_model(config)

        assert model is None


class TestResolveProviderModel:
    """Tests for provider model resolution."""

    def test_updates_local_provider_with_served_model(self) -> None:
        """Replace stale config model with served model for local providers."""
        config = ProviderConfig(
            name="lama.cpp",
            model="unsloth/Qwen3.5-35B-A3B",
            api_base="http://localhost:1235/v1",
        )

        with patch(
            "backend.postparse.llm.model_discovery.discover_served_model",
            return_value="my-actual-model",
        ):
            resolved = resolve_provider_model(config)

        assert resolved.model == "my-actual-model"
        assert resolved.name == "lama.cpp"

    def test_keeps_cloud_provider_unchanged(self) -> None:
        """Do not change cloud provider configuration."""
        config = ProviderConfig(
            name="openai",
            model="gpt-4o-mini",
        )

        with patch(
            "backend.postparse.llm.model_discovery.discover_served_model",
            return_value=None,
        ):
            resolved = resolve_provider_model(config)

        assert resolved is config
        assert resolved.model == "gpt-4o-mini"


class TestDiscoverServedModel:
    """Tests for provider-type routing during discovery."""

    def test_routes_ollama_to_running_model_lookup(self) -> None:
        """Use Ollama /api/ps for running model discovery."""
        config = ProviderConfig(
            name="ollama",
            model="qwen3:14b",
            api_base="http://localhost:11434",
        )

        with patch(
            "backend.postparse.llm.model_discovery.discover_ollama_model",
            return_value="qwen3:14b",
        ) as mock_discover:
            model = discover_served_model(config)

        assert model == "qwen3:14b"
        mock_discover.assert_called_once_with(config, timeout=5.0)

    def test_skips_cloud_providers(self) -> None:
        """Return None for non-local providers."""
        config = ProviderConfig(
            name="openai",
            model="gpt-4o-mini",
        )

        assert discover_served_model(config) is None
