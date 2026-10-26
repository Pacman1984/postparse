"""Tests for TaxonomyClassifier (pydantic-ai TestModel / FunctionModel)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from postparse.classification import (
    ClassificationError,
    TaxonomyClassifier,
    TaxonomySpec,
)
from postparse.llm.config import ProviderConfig

SINGLE = TaxonomySpec.adhoc({"recipe": "Cooking", "not_recipe": "Anything else"}, mode="single")
MULTI = TaxonomySpec.adhoc(["recipe", "travel", "tech"], mode="multi")


def json_model(*payloads: dict[str, Any], calls: list[AgentInfo] | None = None) -> FunctionModel:
    """A FunctionModel answering with the given JSON payloads in turn (last one repeats)."""
    seen = calls if calls is not None else []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info)
        payload = payloads[min(len(seen) - 1, len(payloads) - 1)]
        return ModelResponse(parts=[TextPart(json.dumps(payload))])

    return FunctionModel(respond)


def test_native_single_label() -> None:
    calls: list[AgentInfo] = []
    clf = TaxonomyClassifier(
        SINGLE,
        json_model(
            {"reasoning": "ingredients", "label": "recipe", "confidence": 0.92}, calls=calls
        ),
        "native",
    )
    outcome = clf.classify("200 g Guanciale, 4 Eigelb")
    assert outcome.status == "ok"
    assert outcome.label == "recipe"
    assert outcome.labels == ("recipe",)
    assert outcome.confidence == pytest.approx(0.92)
    assert outcome.reasoning == "ingredients"
    assert outcome.requests == 1
    # Native mode: JSON schema output, no output tools; labels are in the instructions.
    assert calls[0].model_request_parameters.output_mode == "native"
    assert calls[0].output_tools == []
    assert "- recipe: Cooking" in (calls[0].instructions or "")


def test_tool_mode_uses_output_tool() -> None:
    clf = TaxonomyClassifier(MULTI, TestModel(), "tool")
    with clf.agent.override(
        model=TestModel(custom_output_args={"reasoning": "x", "labels": ["tech"], "confidence": 1})
    ):
        outcome = clf.classify("New Python release")
    assert outcome.status == "ok"
    assert outcome.labels == ("tech",)


def test_multi_without_labels_is_no_labels() -> None:
    clf = TaxonomyClassifier(
        MULTI, json_model({"reasoning": "none", "labels": [], "confidence": 0.7}), "native"
    )
    outcome = clf.classify("Good morning!")
    assert outcome.status == "no_labels"
    assert outcome.labels == ()
    assert outcome.label is None
    assert outcome.succeeded


@pytest.mark.parametrize("text", ["", "   \n\t", None])
def test_empty_input_never_calls_the_model(text: str | None) -> None:
    def explode(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise AssertionError("model must not be called")

    clf = TaxonomyClassifier(SINGLE, FunctionModel(explode), "native")
    assert clf.classify(text).status == "empty"
    assert clf.classify_many([text, text]) == [clf.classify(text)] * 2


def test_invalid_output_is_retried() -> None:
    calls: list[AgentInfo] = []
    clf = TaxonomyClassifier(
        SINGLE,
        json_model(
            {"reasoning": "?", "label": "pasta", "confidence": 0.5},
            {"reasoning": "?", "label": "recipe", "confidence": 3.0},
            {"reasoning": "ok", "label": "recipe", "confidence": 0.8},
            calls=calls,
        ),
        "native",
    )
    outcome = clf.classify("Carbonara")
    assert outcome.label == "recipe"
    assert outcome.requests == 3
    assert len(calls) == 3


def test_retries_are_limited_to_two() -> None:
    calls: list[AgentInfo] = []
    clf = TaxonomyClassifier(
        SINGLE, json_model({"reasoning": "", "label": "pasta", "confidence": 0.5}, calls=calls),
        "native",
    )
    with pytest.raises(ClassificationError):
        clf.classify("Carbonara")
    assert len(calls) == 3  # first attempt + 2 output retries


def test_model_failure_raises_classification_error() -> None:
    def broken(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise ConnectionError("server down")

    clf = TaxonomyClassifier(SINGLE, FunctionModel(broken), "native")
    with pytest.raises(ClassificationError, match="server down"):
        clf.classify("text")


def test_batch_keeps_order_and_turns_failures_into_error_outcomes() -> None:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = str(messages[0].parts[-1].content)  # type: ignore[union-attr]
        if "boom" in prompt:
            raise RuntimeError("boom")
        label = "recipe" if "pasta" in prompt else "not_recipe"
        return ModelResponse(
            parts=[TextPart(json.dumps({"reasoning": "", "label": label, "confidence": 0.5}))]
        )

    clf = TaxonomyClassifier(SINGLE, FunctionModel(respond), "native", max_concurrency=3)
    seen: list[int] = []
    outcomes = clf.classify_many(["pasta", "news", "boom", ""])
    assert [o.status for o in outcomes] == ["ok", "ok", "error", "empty"]
    assert [o.label for o in outcomes[:2]] == ["recipe", "not_recipe"]
    assert "boom" in (outcomes[2].error or "")

    async def run() -> None:
        await clf.aclassify_many(["pasta", "news"], on_result=lambda i, _: seen.append(i))

    from postparse.llm.client import run_sync

    run_sync(run())
    assert sorted(seen) == [0, 1]


async def test_aclassify_inside_event_loop() -> None:
    clf = TaxonomyClassifier(
        SINGLE, json_model({"reasoning": "", "label": "recipe", "confidence": 1.0}), "native"
    )
    outcome = await clf.aclassify("pasta")
    assert outcome.label == "recipe"
    with pytest.raises(RuntimeError, match="running event loop"):
        clf.classify("pasta")


def test_prompted_mode_and_invalid_mode() -> None:
    clf = TaxonomyClassifier(
        SINGLE, json_model({"reasoning": "", "label": "recipe", "confidence": 1.0}), "prompted"
    )
    assert clf.classify("pasta").label == "recipe"
    with pytest.raises(ValueError, match="Unknown output mode"):
        TaxonomyClassifier(SINGLE, TestModel(), "magic")  # type: ignore[arg-type]


def test_from_provider_uses_provider_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "postparse.llm.client.resolve_provider_model",
        lambda cfg: cfg.model_copy(update={"model": "served-model"}),
    )
    local = ProviderConfig(name="llama_cpp", model="x", api_base="http://127.0.0.1:9/v1")
    clf = TaxonomyClassifier.from_provider(SINGLE, local)
    assert clf.output_mode == "native"
    assert clf.max_concurrency == 1
    assert clf.model_name == "served-model"
    assert clf.provider_name == "llama_cpp"
    info = clf.describe()
    assert info["label_set_sha256"] == SINGLE.label_set_sha256
    assert info["prompt_sha256"] == clf.prompt_sha256

    cloud = ProviderConfig(name="openai", model="gpt-4o-mini", api_key="sk-test")
    cloud_clf = TaxonomyClassifier.from_provider(MULTI, cloud)
    assert cloud_clf.output_mode == "tool"
    assert cloud_clf.max_concurrency == 4


def test_real_model_requests_are_blocked_in_tests() -> None:
    local = ProviderConfig(name="llama_cpp", model="x", api_base="http://127.0.0.1:9/v1",
                           discover_model=False)
    clf = TaxonomyClassifier.from_provider(SINGLE, local)
    with pytest.raises(ClassificationError, match="ALLOW_MODEL_REQUESTS"):
        clf.classify("pasta")

