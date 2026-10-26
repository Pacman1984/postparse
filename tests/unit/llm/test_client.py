"""Tests for building pydantic-ai models from provider configuration."""

from __future__ import annotations

import pytest
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel

from postparse.llm import client
from postparse.llm.client import (
    api_type_for,
    build_model,
    max_concurrency_for,
    model_settings_for,
    openai_base_url,
    output_mode_for,
    resolve_provider_config,
    run_sync,
    select_provider,
)
from postparse.llm.config import LLMConfig, ProviderConfig
from postparse.llm.exceptions import LLMAuthenticationError
from postparse.llm.model_discovery import is_self_hosted_url

LLAMA = ProviderConfig(name="llama_cpp", model="cfg-model", api_base="http://192.168.1.20:1235/v1")
OLLAMA = ProviderConfig(name="ollama", model="qwen3", api_base="http://127.0.0.1:11434")
OPENAI = ProviderConfig(name="openai", model="gpt-4o-mini", api_key="sk-test")
ANTHROPIC = ProviderConfig(name="anthropic", model="claude-x", api_key="sk-ant-test")


@pytest.mark.parametrize(
    ("cfg", "api_type", "mode", "concurrency"),
    [
        (LLAMA, "openai", "native", 1),
        (OLLAMA, "openai", "native", 1),
        (OPENAI, "openai", "tool", 4),
        (ANTHROPIC, "anthropic", "tool", 4),
    ],
)
def test_defaults_per_provider(cfg: ProviderConfig, api_type: str, mode: str,
                               concurrency: int) -> None:
    assert api_type_for(cfg) == api_type
    assert output_mode_for(cfg) == mode
    assert max_concurrency_for(cfg) == concurrency


def test_explicit_settings_win() -> None:
    cfg = LLAMA.model_copy(update={"output_mode": "tool", "max_concurrency": 3,
                                   "api_type": "openai"})
    assert output_mode_for(cfg) == "tool"
    assert max_concurrency_for(cfg) == 3
    gateway = ProviderConfig(name="claude_gateway", model="m", api_type="openai",
                             api_base="https://gw.example.com/v1")
    assert api_type_for(gateway) == "openai"
    assert output_mode_for(gateway) == "native"
    assert max_concurrency_for(gateway) == 4


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:1234/v1", True),
        ("http://127.0.0.1:9/v1", True),
        ("http://192.168.188.119:1235/v1", True),
        ("http://10.0.0.5:8080", True),
        ("http://gpu-box:8080/v1", True),
        ("http://llm.lan/v1", True),
        ("https://api.openai.com/v1", False),
        ("https://8.8.8.8/v1", False),
        (None, False),
    ],
)
def test_self_hosted_detection(url: str | None, expected: bool) -> None:
    assert is_self_hosted_url(url) is expected


def test_model_settings() -> None:
    cfg = LLAMA.model_copy(update={"temperature": 0.1, "timeout": 60, "max_retries": 2,
                                   "max_tokens": 256, "custom_params": {"top_k": 20}})
    settings = model_settings_for(cfg)
    assert settings == {"temperature": 0.1, "timeout": 60, "max_retries": 2,
                        "max_tokens": 256, "extra_body": {"top_k": 20}}
    assert "max_tokens" not in model_settings_for(OPENAI)


def test_openai_base_url() -> None:
    assert openai_base_url(LLAMA) == "http://192.168.1.20:1235/v1"
    assert openai_base_url(OLLAMA) == "http://127.0.0.1:11434/v1"
    assert openai_base_url(OPENAI) is None


def test_discovery_runs_once_per_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_resolve(cfg: ProviderConfig) -> ProviderConfig:
        calls.append(cfg.name)
        return cfg.model_copy(update={"model": "unsloth/Qwen3.8-27B"})

    monkeypatch.setattr(client, "resolve_provider_model", fake_resolve)
    first = build_model(LLAMA)
    second = build_model(LLAMA)
    assert first is second
    assert resolve_provider_config(LLAMA).model == "unsloth/Qwen3.8-27B"
    assert calls == ["llama_cpp"]
    assert isinstance(first, OpenAIChatModel)
    assert first.model_name == "unsloth/Qwen3.8-27B"
    assert first.settings is not None and first.settings["temperature"] == LLAMA.temperature

    client.clear_model_cache()
    build_model(LLAMA)
    assert calls == ["llama_cpp", "llama_cpp"]


def test_build_cloud_models() -> None:
    assert isinstance(build_model(OPENAI), OpenAIChatModel)
    assert isinstance(build_model(ANTHROPIC), AnthropicModel)


def test_missing_cloud_api_key_raises() -> None:
    with pytest.raises(LLMAuthenticationError):
        build_model(ProviderConfig(name="openai", model="gpt-4o-mini"))


def test_select_provider() -> None:
    cfg = LLMConfig(providers=[LLAMA, OPENAI], default_provider="llama_cpp")
    assert select_provider(cfg).name == "llama_cpp"
    assert select_provider(cfg, "OpenAI").name == "openai"
    with pytest.raises(ValueError, match="not found"):
        select_provider(cfg, "missing")


def test_run_sync_reuses_the_thread_loop() -> None:
    import asyncio

    async def current_loop() -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    assert run_sync(current_loop()) is run_sync(current_loop())
