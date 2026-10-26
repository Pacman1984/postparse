"""Tests for provider health checks on the openai SDK (no network)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest

from postparse.llm.config import ProviderConfig
from postparse.llm.health import check_provider

LLAMA = ProviderConfig(name="llama_cpp", model="served", api_base="http://127.0.0.1:9/v1")
_REQUEST = httpx2.Request("GET", "http://127.0.0.1:9/v1/models")


class FakeOpenAI:
    """Stand-in for ``openai.OpenAI`` recording calls."""

    instances: list[FakeOpenAI] = []
    models_error: Exception | None = None
    chat_error: Exception | None = None
    embeddings_error: Exception | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.chat_calls: list[dict[str, Any]] = []
        FakeOpenAI.instances.append(self)
        self.models = SimpleNamespace(list=self._list)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _list(self) -> Any:
        if FakeOpenAI.models_error:
            raise FakeOpenAI.models_error
        return SimpleNamespace(data=[SimpleNamespace(id="served"), SimpleNamespace(id="emb")])

    def _chat(self, **kwargs: Any) -> Any:
        self.chat_calls.append(kwargs)
        if FakeOpenAI.chat_error:
            raise FakeOpenAI.chat_error
        return SimpleNamespace(choices=[])

    def _embed(self, **kwargs: Any) -> Any:
        if FakeOpenAI.embeddings_error:
            raise FakeOpenAI.embeddings_error
        return SimpleNamespace(data=[])


@pytest.fixture(autouse=True)
def fake_openai(monkeypatch: pytest.MonkeyPatch) -> type[FakeOpenAI]:
    FakeOpenAI.instances = []
    FakeOpenAI.models_error = FakeOpenAI.chat_error = FakeOpenAI.embeddings_error = None
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    return FakeOpenAI


def test_available_provider() -> None:
    result = check_provider(LLAMA, embeddings=True, embedding_model="emb")
    assert result.ok
    assert result.status == "available"
    assert result.models == ["served", "emb"]
    assert result.chat_ok and result.embeddings_ok
    assert result.latency_ms is not None
    client = FakeOpenAI.instances[0]
    assert client.kwargs["base_url"] == "http://127.0.0.1:9/v1"
    assert client.kwargs["api_key"] == "not-needed"
    assert client.kwargs["max_retries"] == 0
    assert client.chat_calls[0]["max_tokens"] == 1
    assert client.chat_calls[0]["model"] == "served"


def test_unreachable_server() -> None:
    FakeOpenAI.models_error = openai.APIConnectionError(request=_REQUEST)
    result = check_provider(LLAMA)
    assert not result.ok
    assert result.status == "unavailable"
    assert "Connection error" in (result.error or "")


def test_auth_error() -> None:
    response = httpx2.Response(401, request=_REQUEST)
    FakeOpenAI.chat_error = openai.AuthenticationError("bad key", response=response, body=None)
    result = check_provider(LLAMA)
    assert result.status == "auth_error"


def test_missing_models_endpoint_is_tolerated() -> None:
    FakeOpenAI.models_error = RuntimeError("404 not supported")
    result = check_provider(LLAMA)
    assert result.ok
    assert result.models == []


def test_embeddings_failure_does_not_fail_check() -> None:
    FakeOpenAI.embeddings_error = RuntimeError("no embeddings")
    result = check_provider(LLAMA, embeddings=True)
    assert result.ok
    assert result.embeddings_ok is False


def test_cloud_provider_without_key() -> None:
    result = check_provider(ProviderConfig(name="openai", model="gpt-4o-mini"))
    assert result.status == "no_api_key"
    assert FakeOpenAI.instances == []
