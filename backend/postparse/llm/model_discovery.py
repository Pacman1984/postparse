"""Discover the model currently served by local LLM endpoints."""

import logging
from typing import List, Optional
from urllib.parse import urljoin

import httpx

from backend.postparse.llm.config import ProviderConfig

logger = logging.getLogger(__name__)


def is_local_provider(config: ProviderConfig) -> bool:
    """Return True when the provider points at a local endpoint.

    Args:
        config: Provider configuration.

    Returns:
        True for localhost/127.0.0.1 endpoints.
    """
    if not config.api_base:
        return False
    return "localhost" in config.api_base or "127.0.0.1" in config.api_base


def is_ollama_provider(config: ProviderConfig) -> bool:
    """Return True when the provider uses Ollama.

    Args:
        config: Provider configuration.

    Returns:
        True for Ollama providers/endpoints.
    """
    api_base = config.api_base or ""
    return config.name.lower() == "ollama" or "11434" in api_base


def _models_url(api_base: str) -> str:
    """Build the OpenAI-compatible /v1/models URL."""
    base = api_base.rstrip("/") + "/"
    if base.endswith("/v1/"):
        return urljoin(base, "models")
    return urljoin(base, "v1/models")


def _ollama_base_url(api_base: str) -> str:
    """Normalize an Ollama base URL without the /v1 suffix."""
    base = api_base.rstrip("/")
    if base.endswith("/v1"):
        return base[:-3]
    return base


def _pick_model_id(model_ids: List[str], configured_model: str) -> str:
    """Choose the best model id from a server response.

    Args:
        model_ids: Model ids reported by the server.
        configured_model: Model name from config.toml.

    Returns:
        Selected model id.
    """
    if len(model_ids) == 1:
        return model_ids[0]

    if configured_model in model_ids:
        return configured_model

    configured_tail = configured_model.split("/")[-1]
    for model_id in model_ids:
        if model_id.split("/")[-1] == configured_tail:
            return model_id

    return model_ids[0]


def discover_openai_compatible_model(
    config: ProviderConfig,
    timeout: float = 5.0,
) -> Optional[str]:
    """Discover the model served by an OpenAI-compatible local server.

    Works with LM Studio, llama.cpp, and similar servers exposing /v1/models.

    Args:
        config: Provider configuration with ``api_base`` set.
        timeout: HTTP request timeout in seconds.

    Returns:
        Served model id, or None if discovery fails.

    Examples:
        >>> cfg = ProviderConfig(
        ...     name="lama.cpp",
        ...     model="stale-model-name",
        ...     api_base="http://localhost:1235/v1",
        ... )
        >>> discover_openai_compatible_model(cfg)
        'actual-loaded-model'
    """
    if not config.api_base:
        return None

    url = _models_url(config.api_base)
    headers = {}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    try:
        response = httpx.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.debug(
            "Failed to discover OpenAI-compatible model from %s: %s",
            url,
            exc,
        )
        return None

    model_ids = [
        item["id"]
        for item in payload.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]
    if not model_ids:
        return None

    return _pick_model_id(model_ids, config.model)


def discover_ollama_model(
    config: ProviderConfig,
    timeout: float = 5.0,
) -> Optional[str]:
    """Discover a running Ollama model, falling back to configured model.

    Args:
        config: Provider configuration.
        timeout: HTTP request timeout in seconds.

    Returns:
        Running model name, or None when no running model is found.
    """
    if not config.api_base:
        return None

    base_url = _ollama_base_url(config.api_base)
    ps_url = f"{base_url}/api/ps"

    try:
        response = httpx.get(ps_url, timeout=timeout)
        response.raise_for_status()
        models = response.json().get("models", [])
    except Exception as exc:
        logger.debug("Failed to discover Ollama model from %s: %s", ps_url, exc)
        return None

    for model in models:
        if not isinstance(model, dict):
            continue
        name = model.get("name") or model.get("model")
        if name:
            return name

    return None


def discover_served_model(
    config: ProviderConfig,
    timeout: float = 5.0,
) -> Optional[str]:
    """Discover the model currently served by a local provider.

    Args:
        config: Provider configuration.
        timeout: HTTP request timeout in seconds.

    Returns:
        Served model name/id, or None for cloud providers or failed discovery.
    """
    if not is_local_provider(config):
        return None

    if is_ollama_provider(config):
        return discover_ollama_model(config, timeout=timeout)

    return discover_openai_compatible_model(config, timeout=timeout)


def resolve_provider_model(
    config: ProviderConfig,
    timeout: float = 5.0,
) -> ProviderConfig:
    """Return provider config with the served model when discoverable.

    For local OpenAI-compatible servers, the served model replaces the
    configured model when discovery succeeds. Cloud providers are unchanged.

    Args:
        config: Provider configuration from config.toml.
        timeout: HTTP request timeout in seconds.

    Returns:
        Provider configuration, using the discovered model when available.

    Examples:
        >>> cfg = ProviderConfig(
        ...     name="lama.cpp",
        ...     model="old-name",
        ...     api_base="http://localhost:1235/v1",
        ... )
        >>> resolved = resolve_provider_model(cfg)
        >>> resolved.model
        'actual-loaded-model'
    """
    served_model = discover_served_model(config, timeout=timeout)
    if not served_model or served_model == config.model:
        return config

    logger.info(
        "Using served model '%s' for provider '%s' (configured: '%s')",
        served_model,
        config.name,
        config.model,
    )
    return config.model_copy(update={"model": served_model})
