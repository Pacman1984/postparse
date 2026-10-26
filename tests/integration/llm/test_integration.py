"""Live tests against a real OpenAI-compatible LLM server (skipped by default).

Run with ``pytest --run-live`` and point ``POSTPARSE_LIVE_LLM_BASE`` at a server,
e.g. ``http://192.168.188.119:1235/v1`` (llama.cpp) or ``http://localhost:1234/v1``
(LM Studio). The served model is discovered automatically.
"""

from __future__ import annotations

import os

import pytest

from postparse.classification import TaxonomyClassifier, TaxonomySpec
from postparse.llm.client import resolve_provider_config
from postparse.llm.config import ProviderConfig
from postparse.llm.health import check_provider

pytestmark = [pytest.mark.live, pytest.mark.integration]


@pytest.fixture
def live_provider() -> ProviderConfig:
    """Provider configuration for the live server."""
    base = os.getenv("POSTPARSE_LIVE_LLM_BASE")
    if not base:
        pytest.skip("Set POSTPARSE_LIVE_LLM_BASE to run live LLM tests")
    return ProviderConfig(
        name="live",
        model=os.getenv("POSTPARSE_LIVE_LLM_MODEL", "auto"),
        api_base=base,
        api_key=os.getenv("POSTPARSE_LIVE_LLM_KEY"),
        discover_model=True,
        timeout=180,
        temperature=0.0,
    )


def test_health_check(live_provider: ProviderConfig) -> None:
    result = check_provider(resolve_provider_config(live_provider))
    assert result.ok, result.error
    assert result.models


def test_single_and_multi_label_classification(live_provider: ProviderConfig) -> None:
    text = "Spaghetti Carbonara: 200 g Guanciale, 4 Eigelb, Pecorino, Pfeffer"
    multi = TaxonomyClassifier.from_provider(
        TaxonomySpec.adhoc(["recipe", "travel", "tech"], mode="multi"), live_provider
    )
    outcome = multi.classify(text)
    assert "recipe" in outcome.labels

    single = TaxonomyClassifier.from_provider(
        TaxonomySpec.adhoc(["recipe", "travel", "tech"], mode="single"), live_provider
    )
    assert single.classify(text).label == "recipe"
