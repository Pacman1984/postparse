"""Runtime-built pydantic output models for a taxonomy.

The label set is only known at runtime, so the structured output model is
created with :func:`pydantic.create_model`:

* ``single`` → ``label: Literal[<labels>]``
* ``multi``  → ``labels: list[Literal[<labels>]]`` (``max_length`` = ``max_labels``)

Both carry ``confidence`` (0..1) and a short ``reasoning``. Because the labels
are a ``Literal``, the JSON schema contains an ``enum``; llama.cpp compiles it
into a grammar and pydantic rejects anything else (which triggers an output
retry in pydantic-ai).

Example:
    >>> Output = build_output_model(TaxonomySpec.adhoc(["a", "b"], mode="single"))
    >>> Output(label="a", confidence=0.9, reasoning="...").label
    'a'
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from postparse.classification.taxonomy import TaxonomySpec

__all__ = ["REASONING_MAX_CHARS", "build_output_model", "output_labels"]

#: Reasoning longer than this is truncated after validation.
REASONING_MAX_CHARS = 500


class _OutputBase(BaseModel):
    """Common configuration of generated output models."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("reasoning", mode="after", check_fields=False)
    @classmethod
    def _shorten_reasoning(cls, value: str) -> str:
        """Collapse whitespace and cap the reasoning length."""
        value = " ".join(value.split())
        if len(value) > REASONING_MAX_CHARS:
            value = value[: REASONING_MAX_CHARS - 3] + "..."
        return value

    @field_validator("labels", mode="after", check_fields=False)
    @classmethod
    def _dedupe_labels(cls, value: list[str]) -> list[str]:
        """Drop repeated labels, keeping the first occurrence."""
        return list(dict.fromkeys(value))


def _model_name(spec: TaxonomySpec) -> str:
    """Return a valid class name for the spec (used as the schema title)."""
    words = re.split(r"[^0-9A-Za-z]+", spec.name)
    stem = "".join(word[:1].upper() + word[1:] for word in words if word) or "Taxonomy"
    if stem[0].isdigit():
        stem = "T" + stem
    return f"{stem}Classification"


@lru_cache(maxsize=128)
def build_output_model(spec: TaxonomySpec) -> type[BaseModel]:
    """Create the structured output model for a taxonomy (cached per spec).

    Args:
        spec: Taxonomy specification.

    Returns:
        A pydantic model class with ``reasoning``, ``label``/``labels`` and
        ``confidence`` fields.
    """
    names = spec.label_names
    label_type: Any = Literal[names]
    reasoning = (
        str,
        Field(description="One short sentence explaining the decision."),
    )
    confidence = (
        float,
        Field(ge=0.0, le=1.0, description="Confidence between 0.0 and 1.0."),
    )
    if spec.mode == "single":
        description = "Classification of the content into exactly one label."
        fields: dict[str, Any] = {
            "reasoning": reasoning,
            "label": (label_type, Field(description="The single best matching label.")),
            "confidence": confidence,
        }
    else:
        description = "Classification of the content into all matching labels (possibly none)."
        constraints: dict[str, Any] = {}
        if spec.max_labels is not None:
            constraints["max_length"] = spec.max_labels
        fields = {
            "reasoning": reasoning,
            "labels": (
                list[label_type],
                Field(
                    description="Every label that applies; an empty list if none applies.",
                    **constraints,
                ),
            ),
            "confidence": confidence,
        }
    model = create_model(_model_name(spec), __base__=_OutputBase, **fields)
    model.__doc__ = description
    return model


def output_labels(output: BaseModel) -> tuple[str, ...]:
    """Return the labels of a validated output instance (single or multi).

    Args:
        output: Instance of a model from :func:`build_output_model`.

    Returns:
        Label names (one for single, zero or more for multi).
    """
    fields = dict(output)  # field name -> value
    if "labels" in fields:
        return tuple(fields["labels"])
    return (fields["label"],)
