"""Deterministic fake LLM for tests (pydantic-ai FunctionModel, no network).

``keyword_model()`` answers any taxonomy schema: it reads the label enum from
the native-output JSON schema and picks the labels whose keywords occur in the
prompt. ``fake_classifier_factory()`` plugs it into code that expects a
``(spec, provider_name) -> TaxonomyClassifier`` factory (API dependency
``get_classifier_factory``, ``ClassificationService(classifier_factory=...)``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from postparse.classification import TaxonomyClassifier, TaxonomySpec

#: Extra keywords per label (the label name itself always counts).
DEFAULT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "recipe": ("recipe", "ingredient", "cook", "bake", "boil", "pasta", "flour", "sauce"),
    "python_package": ("python", "pip ", "library", "fastapi", "package"),
    "movie_review": ("movie", "film", "cinema"),
    "tech": ("python", "software", "laptop", "release"),
    "travel": ("travel", "trip", "hotel", "beach"),
}

#: A prompt containing this marker makes the fake model raise.
FAIL_MARKER = "EXPLODE"


def _prompt(messages: list[ModelMessage]) -> str:
    """Return the text of the first user prompt."""
    return str(messages[0].parts[-1].content)  # type: ignore[union-attr]


def _schema(info: AgentInfo) -> dict[str, Any]:
    """Return the output JSON schema of the request (native or tool mode)."""
    params = info.model_request_parameters
    if params.output_object is not None:
        return params.output_object.json_schema
    return info.output_tools[0].parameters_json_schema


def keyword_model(
    keywords: Mapping[str, Sequence[str]] | None = None,
    *,
    confidence: float = 0.9,
    calls: list[str] | None = None,
) -> FunctionModel:
    """Create a FunctionModel that classifies by keywords.

    Args:
        keywords: Extra keywords per label (merged with :data:`DEFAULT_KEYWORDS`).
        confidence: Confidence to report.
        calls: Optional list collecting every prompt.

    Returns:
        FunctionModel usable with native, tool or prompted output.
    """
    table = {**DEFAULT_KEYWORDS, **{k: tuple(v) for k, v in (keywords or {}).items()}}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = _prompt(messages)
        if calls is not None:
            calls.append(prompt)
        if FAIL_MARKER in prompt:
            raise ConnectionError("fake LLM unavailable")
        lowered = prompt.lower()
        props = _schema(info)["properties"]
        multi = "labels" in props
        enum = props["labels"]["items"]["enum"] if multi else props["label"]["enum"]
        matches = [
            label for label in enum
            if label.lower() in lowered
            or any(word in lowered for word in table.get(label, ()))
        ]
        # "not_recipe" contains "recipe": prefer the more specific positive label.
        matches = [m for m in matches if not (m.startswith("not_") and m[4:] in matches)]
        payload: dict[str, Any] = {"reasoning": "keyword match", "confidence": confidence}
        if multi:
            payload["labels"] = matches
        else:
            negatives = [label for label in enum if label.startswith(("not_", "other"))]
            payload["label"] = matches[0] if matches else (negatives or list(enum))[-1]
        return ModelResponse(parts=[TextPart(json.dumps(payload))])

    return FunctionModel(respond)


def fake_classifier_factory(
    model: FunctionModel | None = None,
    *,
    provider_name: str = "fake",
    model_name: str = "fake-model",
    max_concurrency: int = 2,
):
    """Return a ``(spec, provider_name) -> TaxonomyClassifier`` factory using the fake model.

    Unknown provider names (``"missing"``) raise ``ValueError`` like the real factory.
    """
    shared = model or keyword_model()

    def factory(spec: TaxonomySpec, provider: str | None = None) -> TaxonomyClassifier:
        if provider == "missing":
            raise ValueError("Provider 'missing' not found. Available: fake")
        return TaxonomyClassifier(
            spec, shared, "native", max_concurrency=max_concurrency,
            provider_name=provider or provider_name, model_name=model_name,
        )

    return factory
