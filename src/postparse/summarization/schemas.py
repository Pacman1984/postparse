"""Output schema of the summarizer and the stored text format.

Summaries are stored in ``summaries.text`` as plain text::

    <summary, 2-5 sentences>

    - <key point 1>
    - <key point 2>

This keeps key points searchable through the existing FTS document (which
indexes ``summaries.text``) without a schema change; :func:`parse_summary_text`
recovers the structure for API consumers.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

__all__ = ["MAX_KEY_POINTS", "SummaryOutput", "format_summary_text", "parse_summary_text"]

#: Upper bound of key points per summary.
MAX_KEY_POINTS = 5
_BULLET = "- "


class SummaryOutput(BaseModel):
    """Structured summary returned by the model."""

    summary: str = Field(
        description=(
            "Summary of the content in 2 to 5 sentences, written in the same language "
            "as the content (transcript/caption)."
        )
    )
    key_points: list[str] = Field(
        default_factory=list,
        max_length=MAX_KEY_POINTS,
        description=(
            f"Up to {MAX_KEY_POINTS} short key points (facts, steps, ingredients, tips), "
            "same language as the content. Empty if there is nothing specific."
        ),
    )

    @field_validator("summary")
    @classmethod
    def _strip_summary(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("summary must not be empty")
        return value

    @field_validator("key_points", mode="before")
    @classmethod
    def _clean_points(cls, value: Any) -> Any:
        """Drop blank points, strip bullets and keep at most five."""
        if not isinstance(value, list):
            return value
        points = []
        for raw in value:
            text = " ".join(str(raw).split()).lstrip("-*• ").strip()
            if text:
                points.append(text)
        return points[:MAX_KEY_POINTS]


def format_summary_text(summary: str, key_points: list[str] | tuple[str, ...] = ()) -> str:
    """Render the stored summary text."""
    text = summary.strip()
    points = [p.strip() for p in key_points if p.strip()]
    if points:
        text += "\n\n" + "\n".join(_BULLET + p for p in points)
    return text


def parse_summary_text(text: str) -> tuple[str, list[str]]:
    """Split a stored summary text into ``(summary, key_points)``.

    Texts without a bullet block (for example legacy summaries) return all
    text as the summary and no key points.
    """
    body, sep, tail = text.strip().rpartition("\n\n")
    if sep:
        lines = [line for line in tail.splitlines() if line.strip()]
        if lines and all(line.startswith(_BULLET) for line in lines):
            return body.strip(), [line[len(_BULLET) :].strip() for line in lines]
    return text.strip(), []
