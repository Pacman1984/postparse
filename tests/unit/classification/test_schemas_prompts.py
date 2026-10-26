"""Tests for runtime output models and prompts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from postparse.classification.prompts import (
    build_instructions,
    build_user_prompt,
    prompt_sha256,
)
from postparse.classification.schemas import (
    REASONING_MAX_CHARS,
    build_output_model,
    output_labels,
)
from postparse.classification.taxonomy import TaxonomySpec

SINGLE = TaxonomySpec.adhoc({"recipe": "Cooking", "not_recipe": "Anything else"}, mode="single")
MULTI = TaxonomySpec.adhoc(["recipe", "travel", "tech"], mode="multi", max_labels=2)


def test_single_schema_accepts_known_label() -> None:
    model = build_output_model(SINGLE)
    out = model.model_validate({"reasoning": "food", "label": "recipe", "confidence": 0.8})
    assert output_labels(out) == ("recipe",)
    schema = model.model_json_schema()
    assert schema["properties"]["label"]["enum"] == ["recipe", "not_recipe"]
    assert set(schema["required"]) == {"reasoning", "label", "confidence"}
    assert schema["additionalProperties"] is False


def test_single_schema_rejects_unknown_label() -> None:
    model = build_output_model(SINGLE)
    with pytest.raises(ValidationError):
        model.model_validate({"reasoning": "", "label": "pasta", "confidence": 0.5})


@pytest.mark.parametrize("confidence", [-0.1, 1.5])
def test_confidence_must_be_between_zero_and_one(confidence: float) -> None:
    model = build_output_model(SINGLE)
    with pytest.raises(ValidationError):
        model.model_validate({"reasoning": "", "label": "recipe", "confidence": confidence})


def test_multi_schema_lists_labels_and_dedupes() -> None:
    model = build_output_model(MULTI)
    out = model.model_validate(
        {"reasoning": "r", "labels": ["travel", "travel"], "confidence": 0.4}
    )
    assert output_labels(out) == ("travel",)
    empty = model.model_validate({"reasoning": "r", "labels": [], "confidence": 0.9})
    assert output_labels(empty) == ()
    schema = model.model_json_schema()["properties"]["labels"]
    assert schema["items"]["enum"] == ["recipe", "travel", "tech"]
    assert schema["maxItems"] == 2


def test_multi_schema_rejects_unknown_and_too_many_labels() -> None:
    model = build_output_model(MULTI)
    with pytest.raises(ValidationError):
        model.model_validate({"reasoning": "", "labels": ["food"], "confidence": 0.5})
    with pytest.raises(ValidationError):
        model.model_validate(
            {"reasoning": "", "labels": ["recipe", "travel", "tech"], "confidence": 0.5}
        )


def test_extra_fields_are_rejected_and_reasoning_is_shortened() -> None:
    model = build_output_model(SINGLE)
    with pytest.raises(ValidationError):
        model.model_validate(
            {"reasoning": "", "label": "recipe", "confidence": 0.5, "cuisine": "it"}
        )
    out = model.model_validate({"reasoning": "x  " * 400, "label": "recipe", "confidence": 0.5})
    assert len(out.reasoning) == REASONING_MAX_CHARS


def test_output_model_is_cached_per_spec() -> None:
    assert build_output_model(SINGLE) is build_output_model(
        TaxonomySpec.adhoc({"recipe": "Cooking", "not_recipe": "Anything else"}, mode="single")
    )
    assert build_output_model(SINGLE).__name__ == "AdhocClassification"


def test_instructions_list_labels_with_descriptions() -> None:
    text = build_instructions(SINGLE)
    assert "exactly ONE label" in text
    assert "- recipe: Cooking" in text
    assert "- not_recipe: Anything else" in text
    multi = build_instructions(MULTI)
    assert "EVERY label" in multi and "at most 2" in multi
    assert "- travel\n" in multi
    custom = TaxonomySpec.adhoc(["a", "b"], instructions="Posts are German.")
    assert build_instructions(custom).endswith("Posts are German.")


def test_user_prompt_wraps_content() -> None:
    assert build_user_prompt("hello").endswith("<content>\nhello\n</content>")


def test_prompt_hash_is_stable_and_sensitive() -> None:
    again = TaxonomySpec.adhoc({"recipe": "Cooking", "not_recipe": "Anything else"}, mode="single")
    assert prompt_sha256(SINGLE) == prompt_sha256(again)
    changed = TaxonomySpec.adhoc({"recipe": "Food", "not_recipe": "Anything else"}, mode="single")
    assert prompt_sha256(changed) != prompt_sha256(SINGLE)
    assert len(prompt_sha256(SINGLE)) == 64
