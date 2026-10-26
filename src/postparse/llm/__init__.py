"""LLM provider layer on pydantic-ai and the official provider SDKs.

- :mod:`.config` — :class:`ProviderConfig` / :class:`LLMConfig` from ``[llm]``
- :mod:`.model_discovery` — served-model discovery for self-hosted servers
- :mod:`.client` — :func:`build_model` (pydantic-ai models), output mode and
  concurrency per provider
- :mod:`.health` — :func:`check_provider` used by ``postparse check llm``

Example:
    ```python
    from postparse.llm import build_model, load_llm_config, select_provider

    llm_config = load_llm_config(ConfigManager())
    model = build_model(select_provider(llm_config))  # default provider
    ```

Classification on top of this lives in :mod:`postparse.classification`.
"""

from postparse.llm.client import (
    build_model,
    max_concurrency_for,
    output_mode_for,
    resolve_provider_config,
    select_provider,
)
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
from postparse.llm.health import HealthResult, check_provider

__all__ = [
    # Models
    "build_model",
    "max_concurrency_for",
    "output_mode_for",
    "resolve_provider_config",
    "select_provider",
    # Health
    "HealthResult",
    "check_provider",
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
