"""Health checks for configured LLM providers (used by ``postparse check llm``).

Talks to providers with the official ``openai`` SDK (OpenAI and every
OpenAI-compatible server) or the ``anthropic`` SDK:

1. list models (``GET /v1/models``),
2. a one-token chat completion ping,
3. optionally an embeddings ping.

Example:
    >>> result = check_provider(llm_config.get_provider("llama_cpp"))
    >>> result.ok, result.status, result.latency_ms
    (True, 'available', 412.0)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

from postparse.llm.client import NO_API_KEY, api_type_for, openai_base_url
from postparse.llm.config import ProviderConfig

__all__ = ["HealthResult", "HealthStatus", "check_provider"]

logger = logging.getLogger(__name__)

HealthStatus = Literal[
    "available", "unavailable", "auth_error", "model_not_found", "no_api_key", "error"
]


@dataclass(slots=True)
class HealthResult:
    """Outcome of a provider health check.

    Attributes:
        provider: Provider name.
        model: Model that was pinged.
        status: Overall status.
        models: Model ids reported by the server (may be empty).
        chat_ok: Whether the chat ping succeeded.
        embeddings_ok: Embeddings ping result, ``None`` when not requested.
        latency_ms: Chat ping latency in milliseconds.
        error: Short error description for failed checks.
    """

    provider: str
    model: str
    status: HealthStatus = "error"
    models: list[str] = field(default_factory=list)
    chat_ok: bool = False
    embeddings_ok: bool | None = None
    latency_ms: float | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True when the chat ping succeeded."""
        return self.status == "available"


def _classify_error(exc: Exception) -> HealthStatus:
    """Map an SDK exception to a health status."""
    name = type(exc).__name__
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return "auth_error"
    if name == "NotFoundError":
        return "model_not_found"
    if name in ("APIConnectionError", "APITimeoutError", "ConnectError", "TimeoutException"):
        return "unavailable"
    return "error"


def _short(exc: Exception, limit: int = 160) -> str:
    """Return a one-line, length-limited error message."""
    text = " ".join(str(exc).split()) or type(exc).__name__
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _check_openai(
    cfg: ProviderConfig,
    result: HealthResult,
    *,
    chat: bool,
    embeddings: bool,
    embedding_model: str | None,
    timeout: float,
) -> None:
    """Run the checks against an OpenAI(-compatible) endpoint."""
    import openai

    base_url = openai_base_url(cfg)
    client = openai.OpenAI(
        base_url=base_url,
        api_key=cfg.api_key or NO_API_KEY,
        timeout=timeout,
        max_retries=0,
    )
    try:
        result.models = [m.id for m in client.models.list().data]
    except Exception as exc:
        logger.debug("Listing models of %s failed: %s", cfg.name, exc)
        if _classify_error(exc) in ("unavailable", "auth_error"):
            result.status = _classify_error(exc)
            result.error = _short(exc)
            return
    if chat:
        started = time.perf_counter()
        client.chat.completions.create(
            model=cfg.model, messages=[{"role": "user", "content": "ping"}], max_tokens=1
        )
        result.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        result.chat_ok = True
    if embeddings:
        try:
            client.embeddings.create(model=embedding_model or cfg.model, input="ping")
            result.embeddings_ok = True
        except Exception as exc:
            logger.debug("Embeddings ping of %s failed: %s", cfg.name, exc)
            result.embeddings_ok = False


def _check_anthropic(
    cfg: ProviderConfig, result: HealthResult, *, chat: bool, timeout: float
) -> None:
    """Run the checks against the Anthropic API."""
    import anthropic

    client = anthropic.Anthropic(
        api_key=cfg.api_key, base_url=cfg.api_base, timeout=timeout, max_retries=0
    )
    try:
        result.models = [m.id for m in client.models.list().data]
    except Exception as exc:
        logger.debug("Listing Anthropic models failed: %s", exc)
    if chat:
        started = time.perf_counter()
        client.messages.create(
            model=cfg.model, max_tokens=1, messages=[{"role": "user", "content": "ping"}]
        )
        result.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        result.chat_ok = True


def check_provider(
    cfg: ProviderConfig,
    *,
    chat: bool = True,
    embeddings: bool = False,
    embedding_model: str | None = None,
    timeout: float | None = None,
) -> HealthResult:
    """Check whether a provider answers.

    Never raises for provider failures; they are reported in the result.

    Args:
        cfg: Provider configuration (already resolved to the served model).
        chat: Send a one-token chat completion.
        embeddings: Also try an embeddings request.
        embedding_model: Model for the embeddings ping (default: ``cfg.model``).
        timeout: Request timeout in seconds (default: ``cfg.timeout``).

    Returns:
        Health result; ``status == 'available'`` when the chat ping worked
        (or, with ``chat=False``, when the model list could be read).
    """
    result = HealthResult(provider=cfg.name, model=cfg.model)
    request_timeout = float(timeout if timeout is not None else cfg.timeout)
    api_type = api_type_for(cfg)
    if not cfg.api_key and not cfg.api_base:
        result.status = "no_api_key"
        result.error = "API key not configured"
        return result
    try:
        if api_type == "anthropic":
            _check_anthropic(cfg, result, chat=chat, timeout=request_timeout)
        else:
            _check_openai(
                cfg,
                result,
                chat=chat,
                embeddings=embeddings,
                embedding_model=embedding_model,
                timeout=request_timeout,
            )
    except Exception as exc:
        result.status = _classify_error(exc)
        result.error = _short(exc)
        logger.debug("Health check of %s failed: %s", cfg.name, exc)
        return result
    if result.error is None:
        result.status = "available" if (result.chat_ok or not chat) else "error"
    return result
