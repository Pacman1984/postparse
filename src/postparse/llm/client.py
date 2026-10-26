"""Build pydantic-ai models from :class:`~postparse.llm.config.ProviderConfig`.

The provider configuration decides three things:

* the client protocol (:func:`api_type_for`): ``openai`` for OpenAI and every
  OpenAI-compatible server (llama.cpp, LM Studio, Ollama, vLLM, ...), or
  ``anthropic``;
* the structured-output strategy (:func:`output_mode_for`): ``native`` JSON
  schema output for OpenAI-compatible endpoints (llama.cpp compiles it into a
  grammar), ``tool`` calls for cloud APIs;
* the request concurrency (:func:`max_concurrency_for`): 1 for self-hosted
  servers, which usually have a single slot.

The served model of self-hosted endpoints is discovered once per provider
configuration (:func:`resolve_provider_config`) and cached for the process.

Example:
    >>> cfg = llm_config.get_provider("llama_cpp")
    >>> model = build_model(cfg)
    >>> agent = Agent(model, output_type=NativeOutput(MyOutput))
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import warnings
from collections.abc import Coroutine
from typing import Any, Literal, TypeVar

import pydantic_ai
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from postparse.llm.config import LLMConfig, ProviderConfig
from postparse.llm.exceptions import LLMAuthenticationError
from postparse.llm.model_discovery import (
    is_local_provider,
    is_ollama_provider,
    resolve_provider_model,
)

__all__ = [
    "DEFAULT_CLOUD_CONCURRENCY",
    "DEFAULT_LOCAL_CONCURRENCY",
    "NO_API_KEY",
    "ApiType",
    "OutputMode",
    "api_type_for",
    "build_model",
    "clear_model_cache",
    "max_concurrency_for",
    "model_settings_for",
    "openai_base_url",
    "output_mode_for",
    "resolve_provider_config",
    "run_sync",
    "select_provider",
]

logger = logging.getLogger(__name__)

# PostParse owns its terminal output (rich CLI, JSON logs); never print the
# pydantic-ai first-run banner.
pydantic_ai.BANNER_ENABLED = False

OutputMode = Literal["native", "tool", "prompted"]
ApiType = Literal["openai", "anthropic"]

#: Parallel requests for self-hosted servers (llama.cpp usually has one slot).
DEFAULT_LOCAL_CONCURRENCY = 1
#: Parallel requests for cloud APIs.
DEFAULT_CLOUD_CONCURRENCY = 4
#: Placeholder key for OpenAI-compatible servers that do not check keys.
NO_API_KEY = "not-needed"

T = TypeVar("T")

_cache_lock = threading.Lock()
_resolved_cache: dict[str, ProviderConfig] = {}
_model_cache: dict[str, Model] = {}


def _cache_key(cfg: ProviderConfig) -> str:
    """Return a stable cache key for a provider configuration."""
    return cfg.model_dump_json()


def api_type_for(cfg: ProviderConfig) -> ApiType:
    """Return the client protocol for a provider.

    Args:
        cfg: Provider configuration.

    Returns:
        ``cfg.api_type`` when set, ``anthropic`` for providers named
        ``anthropic*`` / ``claude*``, otherwise ``openai``.
    """
    if cfg.api_type is not None:
        return cfg.api_type
    name = cfg.name.lower()
    if name.startswith(("anthropic", "claude")):
        return "anthropic"
    return "openai"


def output_mode_for(cfg: ProviderConfig) -> OutputMode:
    """Return the structured-output strategy for a provider.

    Args:
        cfg: Provider configuration.

    Returns:
        ``cfg.output_mode`` when set; ``native`` for OpenAI-compatible
        endpoints with a custom ``api_base`` (llama.cpp, LM Studio, Ollama:
        ``response_format`` json_schema); ``tool`` for cloud APIs where tool
        calling is the most reliable option.
    """
    if cfg.output_mode is not None:
        return cfg.output_mode
    if api_type_for(cfg) == "openai" and cfg.api_base:
        return "native"
    return "tool"


def max_concurrency_for(cfg: ProviderConfig) -> int:
    """Return the maximum number of parallel requests for a provider.

    Args:
        cfg: Provider configuration.

    Returns:
        ``cfg.max_concurrency`` when set, otherwise
        :data:`DEFAULT_LOCAL_CONCURRENCY` for self-hosted endpoints and
        :data:`DEFAULT_CLOUD_CONCURRENCY` for cloud APIs.
    """
    if cfg.max_concurrency is not None:
        return cfg.max_concurrency
    return DEFAULT_LOCAL_CONCURRENCY if is_local_provider(cfg) else DEFAULT_CLOUD_CONCURRENCY


def model_settings_for(cfg: ProviderConfig) -> ModelSettings:
    """Translate provider options into pydantic-ai model settings.

    Args:
        cfg: Provider configuration.

    Returns:
        Settings with temperature, timeout, SDK retries and (when configured)
        ``max_tokens``; ``custom_params`` become ``extra_body`` for
        OpenAI-compatible servers.
    """
    settings = ModelSettings(
        temperature=cfg.temperature,
        timeout=cfg.timeout,
        max_retries=cfg.max_retries,
    )
    if cfg.max_tokens:
        settings["max_tokens"] = cfg.max_tokens
    if cfg.custom_params and api_type_for(cfg) == "openai":
        settings["extra_body"] = dict(cfg.custom_params)
    return settings


def openai_base_url(cfg: ProviderConfig) -> str | None:
    """Return the OpenAI-compatible base URL (``/v1`` appended for Ollama).

    Args:
        cfg: Provider configuration.

    Returns:
        Base URL, or ``None`` for the public OpenAI API.
    """
    if not cfg.api_base:
        return None
    base = cfg.api_base.rstrip("/")
    if is_ollama_provider(cfg) and not base.endswith("/v1"):
        base += "/v1"
    return base


def resolve_provider_config(cfg: ProviderConfig) -> ProviderConfig:
    """Return ``cfg`` with the served model filled in, discovered once per config.

    Discovery (:func:`~postparse.llm.model_discovery.resolve_provider_model`)
    talks to the server only the first time a configuration is seen; later
    calls return the cached result.

    Args:
        cfg: Provider configuration.

    Returns:
        Provider configuration with the served model (or ``cfg`` unchanged).
    """
    key = _cache_key(cfg)
    with _cache_lock:
        cached = _resolved_cache.get(key)
    if cached is not None:
        return cached
    resolved = resolve_provider_model(cfg)
    with _cache_lock:
        return _resolved_cache.setdefault(key, resolved)


def build_model(cfg: ProviderConfig, *, resolve: bool = True) -> Model:
    """Create (or return the cached) pydantic-ai model for a provider.

    Args:
        cfg: Provider configuration.
        resolve: Discover the served model first (cached per configuration).

    Returns:
        ``OpenAIChatModel`` for OpenAI/OpenAI-compatible providers or
        ``AnthropicModel`` for Anthropic, with default settings from
        :func:`model_settings_for`.

    Raises:
        LLMAuthenticationError: If a cloud provider has no API key.
    """
    key = _cache_key(cfg) + ("|resolved" if resolve else "")
    with _cache_lock:
        cached = _model_cache.get(key)
    if cached is not None:
        return cached

    resolved = resolve_provider_config(cfg) if resolve else cfg
    settings = model_settings_for(resolved)
    try:
        if api_type_for(resolved) == "anthropic":
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider

            anthropic_provider = AnthropicProvider(
                api_key=resolved.api_key, base_url=resolved.api_base
            )
            model: Model = AnthropicModel(
                resolved.model, provider=anthropic_provider, settings=settings
            )
        else:
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider

            base_url = openai_base_url(resolved)
            api_key = resolved.api_key or (NO_API_KEY if base_url else None)
            openai_provider = OpenAIProvider(base_url=base_url, api_key=api_key)
            model = OpenAIChatModel(resolved.model, provider=openai_provider, settings=settings)
    except UserError as exc:
        raise LLMAuthenticationError(
            f"Cannot create model for provider '{resolved.name}': {exc}",
            provider_name=resolved.name,
            model_name=resolved.model,
            original_error=exc,
        ) from exc

    logger.debug(
        "Built %s model '%s' for provider '%s'",
        api_type_for(resolved),
        resolved.model,
        resolved.name,
    )
    with _cache_lock:
        return _model_cache.setdefault(key, model)


def clear_model_cache() -> None:
    """Forget discovered models and built model instances."""
    with _cache_lock:
        _resolved_cache.clear()
        _model_cache.clear()


def select_provider(llm_config: LLMConfig, name: str | None = None) -> ProviderConfig:
    """Return the named provider, or the default provider when ``name`` is None.

    Args:
        llm_config: LLM configuration.
        name: Provider name (case-insensitive).

    Returns:
        Provider configuration.

    Raises:
        ValueError: If the provider is not configured.
    """
    wanted = name or llm_config.default_provider
    for provider in llm_config.providers:
        if provider.name.lower() == wanted.lower():
            return provider
    available = ", ".join(p.name for p in llm_config.providers) or "none"
    raise ValueError(f"Provider '{wanted}' not found. Available: {available}")


def _thread_event_loop() -> asyncio.AbstractEventLoop:
    """Return this thread's persistent event loop (the one pydantic-ai's run_sync uses)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def run_sync(coro: Coroutine[Any, Any, T]) -> T:  # noqa: UP047 - keep pre-PEP 695 syntax
    """Run a coroutine to completion from synchronous code.

    Uses the thread's persistent event loop (like ``Agent.run_sync``) so that
    pooled HTTP connections stay bound to one loop across calls.

    Args:
        coro: Coroutine to run.

    Returns:
        The coroutine's result.

    Raises:
        RuntimeError: If called while an event loop is running in this thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        coro.close()
        raise RuntimeError("run_sync() cannot be used inside a running event loop; await instead")
    loop = _thread_event_loop()
    task = loop.create_task(coro)
    try:
        return loop.run_until_complete(task)
    except BaseException:
        # Ctrl-C (or another BaseException) can leave the task suspended; cancel it
        # and let its cleanup (finally blocks) run before re-raising.
        if not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):  # the original exception wins
                loop.run_until_complete(task)
        raise
