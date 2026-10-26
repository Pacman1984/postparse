"""pydantic-ai agent that summarizes caption + transcript (+ linked pages).

Example:
    >>> summarizer = Summarizer.from_provider(provider_cfg)
    >>> outcome = summarizer.summarize("[Caption]\\n...\\n\\n[Transcript]\\n...")
    >>> outcome.summary, outcome.key_points

Tests swap the model with ``summarizer.agent.override(model=TestModel(...))``
or construct the summarizer with a ``FunctionModel``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass

from pydantic_ai import Agent, NativeOutput, PromptedOutput, ToolOutput
from pydantic_ai.models import Model

from postparse.llm.client import (
    OutputMode,
    build_model,
    max_concurrency_for,
    output_mode_for,
    resolve_provider_config,
    run_sync,
)
from postparse.llm.config import ProviderConfig
from postparse.summarization.schemas import SummaryOutput, format_summary_text

__all__ = [
    "DEFAULT_OUTPUT_RETRIES",
    "INSTRUCTIONS",
    "SummarizationError",
    "SummaryOutcome",
    "Summarizer",
]

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_RETRIES = 2

INSTRUCTIONS = """\
You summarize saved social media posts (mostly short videos) for a personal archive.
The input contains labelled sections: the post caption, the transcript of the video's
audio (automatic speech recognition, may contain recognition errors) and sometimes
texts of linked web pages.

Write:
- summary: 2 to 5 sentences describing what the post is about and what the viewer
  learns or gets from it. Be concrete (names, dishes, places, tools, numbers).
- key_points: up to 5 short key points (steps, ingredients, tips, facts). Use an
  empty list if there is nothing specific.

Rules:
- Write in the language of the content (normally the transcript's language; if the
  transcript is missing or empty, the caption's language). Do not translate.
- Use only information from the input; do not invent details. Ignore hashtags,
  calls to like/follow/subscribe and sponsor boilerplate.
- Plain text only, no markdown.
"""


class SummarizationError(RuntimeError):
    """The model call or output validation failed for good."""


@dataclass(frozen=True, slots=True)
class SummaryOutcome:
    """Result of summarizing one text.

    Attributes:
        summary: Summary paragraph.
        key_points: Key points (at most five).
        latency_s: Wall time of the model call(s).
        requests: Model requests (more than one after retries).
    """

    summary: str
    key_points: tuple[str, ...] = ()
    latency_s: float = 0.0
    requests: int = 0

    @property
    def text(self) -> str:
        """Stored representation (summary + bullet list)."""
        return format_summary_text(self.summary, self.key_points)


def prompt_sha256() -> str:
    """Hash of the instructions and the output schema (stored with summaries)."""
    payload = json.dumps(
        {"instructions": INSTRUCTIONS, "schema": SummaryOutput.model_json_schema()},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _output_spec(mode: OutputMode) -> object:
    if mode == "native":
        return NativeOutput(SummaryOutput)
    if mode == "tool":
        return ToolOutput(SummaryOutput, name="submit_summary")
    if mode == "prompted":
        return PromptedOutput(SummaryOutput)
    raise ValueError(f"Unknown output mode: {mode!r}")


class Summarizer:
    """Summarize composed item texts.

    Args:
        model: pydantic-ai model (see :func:`postparse.llm.client.build_model`).
        output_mode: Structured output strategy.
        max_concurrency: Parallel requests in batch runs.
        output_retries: Retries when the output fails validation.
        provider_name: Provider recorded with summaries.
        model_name: Model recorded with summaries (default: the model's name).
    """

    def __init__(
        self,
        model: Model | str,
        output_mode: OutputMode = "native",
        *,
        max_concurrency: int = 1,
        output_retries: int = DEFAULT_OUTPUT_RETRIES,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.output_mode: OutputMode = output_mode
        self.max_concurrency = max_concurrency
        self.provider_name = provider_name
        self.model_name = model_name or getattr(model, "model_name", None) or str(model)
        self.prompt_sha256 = prompt_sha256()
        self.agent: Agent[None, SummaryOutput] = Agent(
            model,
            output_type=_output_spec(output_mode),  # type: ignore[arg-type]
            instructions=INSTRUCTIONS,
            retries={"output": output_retries},
            name="summarize",
        )

    @classmethod
    def from_provider(
        cls, provider: ProviderConfig, *, output_retries: int = DEFAULT_OUTPUT_RETRIES
    ) -> Summarizer:
        """Create a summarizer for a configured provider (output mode / concurrency per provider).

        Raises:
            LLMAuthenticationError: If a cloud provider has no API key.
        """
        resolved = resolve_provider_config(provider)
        return cls(
            build_model(provider),
            output_mode_for(resolved),
            max_concurrency=max_concurrency_for(resolved),
            output_retries=output_retries,
            provider_name=resolved.name,
            model_name=resolved.model,
        )

    async def asummarize(self, text: str) -> SummaryOutcome:
        """Summarize one composed text.

        Raises:
            ValueError: For blank input (the model is not called).
            SummarizationError: If the request fails or the output stays invalid.
        """
        content = (text or "").strip()
        if not content:
            raise ValueError("Nothing to summarize")
        started = time.perf_counter()
        try:
            result = await self.agent.run(content)
        except Exception as exc:
            raise SummarizationError(f"{type(exc).__name__}: {exc}") from exc
        output = result.output
        return SummaryOutcome(
            summary=output.summary,
            key_points=tuple(output.key_points),
            latency_s=time.perf_counter() - started,
            requests=result.usage.requests,
        )

    def summarize(self, text: str) -> SummaryOutcome:
        """Synchronous :meth:`asummarize` (not usable inside a running event loop)."""
        return run_sync(self.asummarize(text))
