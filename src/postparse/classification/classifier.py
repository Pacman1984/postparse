"""Generic LLM classifier for any :class:`TaxonomySpec` (pydantic-ai based).

Example:
    >>> spec = TaxonomySpec.adhoc(["recipe", "travel", "tech"], mode="multi")
    >>> clf = TaxonomyClassifier.from_provider(spec, provider_cfg)
    >>> outcome = clf.classify("Spaghetti Carbonara: 200 g Guanciale, 4 Eigelb ...")
    >>> outcome.labels, outcome.confidence
    (('recipe',), 0.97)

Tests swap the model with ``clf.agent.override(model=TestModel(...))``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput, PromptedOutput, ToolOutput
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from postparse.classification.prompts import (
    build_instructions,
    build_user_prompt,
    prompt_sha256,
)
from postparse.classification.schemas import build_output_model, output_labels
from postparse.classification.taxonomy import TaxonomySpec
from postparse.llm.client import (
    OutputMode,
    build_model,
    max_concurrency_for,
    output_mode_for,
    resolve_provider_config,
    run_sync,
)
from postparse.llm.config import ProviderConfig

__all__ = [
    "DEFAULT_OUTPUT_RETRIES",
    "ClassificationError",
    "ClassificationOutcome",
    "OutcomeStatus",
    "TaxonomyClassifier",
]

logger = logging.getLogger(__name__)

#: Output validation retries (invalid JSON / unknown label → ask the model again).
DEFAULT_OUTPUT_RETRIES = 2

OutcomeStatus = Literal["ok", "no_labels", "empty", "error"]


class ClassificationError(RuntimeError):
    """Raised when the model call or output validation fails for good."""


@dataclass(frozen=True, slots=True)
class ClassificationOutcome:
    """Result of classifying one text.

    Attributes:
        status: ``ok`` (labels assigned), ``no_labels`` (multi: none applies),
            ``empty`` (no input; the model was not called) or ``error``.
        labels: Assigned labels (one for single-label taxonomies).
        confidence: Overall confidence in ``[0, 1]``.
        reasoning: Short model explanation.
        error: Error message for ``error`` outcomes.
        latency_s: Wall time of the model call(s) in seconds.
        requests: Number of model requests (more than one after retries).
    """

    status: OutcomeStatus
    labels: tuple[str, ...] = ()
    confidence: float | None = None
    reasoning: str | None = None
    error: str | None = None
    latency_s: float = 0.0
    requests: int = 0

    @property
    def label(self) -> str | None:
        """First (for single-label taxonomies: the) label, or ``None``."""
        return self.labels[0] if self.labels else None

    @property
    def succeeded(self) -> bool:
        """True for ``ok`` and ``no_labels``."""
        return self.status in ("ok", "no_labels")

    def label_scores(self) -> list[tuple[str, float | None]]:
        """Return ``(label, confidence)`` pairs (overall confidence per label)."""
        return [(label, self.confidence) for label in self.labels]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "status": self.status,
            "labels": list(self.labels),
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "error": self.error,
            "latency_s": round(self.latency_s, 3),
            "requests": self.requests,
        }


def _output_spec(output_model: type[BaseModel], mode: OutputMode) -> Any:
    """Wrap the output model in the pydantic-ai marker for ``mode``."""
    if mode == "native":
        return NativeOutput(output_model)
    if mode == "tool":
        return ToolOutput(output_model, name="submit_classification")
    if mode == "prompted":
        return PromptedOutput(output_model)
    raise ValueError(f"Unknown output mode: {mode!r}")


class TaxonomyClassifier:
    """Classify texts into the labels of one taxonomy.

    Attributes:
        spec: Taxonomy specification.
        output_mode: ``native``, ``tool`` or ``prompted``.
        max_concurrency: Parallel requests in :meth:`aclassify_many`.
        provider_name: Provider name recorded with results (informational).
        model_name: Model name recorded with results (informational).
        output_model: Generated pydantic output model.
        instructions: System instructions sent to the model.
        prompt_sha256: Hash of instructions + schema (see :mod:`.prompts`).
        agent: The underlying ``pydantic_ai.Agent``.
    """

    def __init__(
        self,
        spec: TaxonomySpec,
        model: Model | str,
        output_mode: OutputMode = "native",
        *,
        max_concurrency: int = 1,
        output_retries: int = DEFAULT_OUTPUT_RETRIES,
        model_settings: ModelSettings | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> None:
        """Create a classifier.

        Args:
            spec: Taxonomy specification.
            model: pydantic-ai model (see :func:`postparse.llm.client.build_model`).
            output_mode: Structured output strategy.
            max_concurrency: Parallel requests for batch classification.
            output_retries: Retries when the output fails validation.
            model_settings: Extra per-run model settings.
            provider_name: Provider name for bookkeeping.
            model_name: Model name for bookkeeping (default: the model's name).
        """
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.spec = spec
        self.output_mode: OutputMode = output_mode
        self.max_concurrency = max_concurrency
        self.provider_name = provider_name
        self.model_name = model_name or getattr(model, "model_name", None) or str(model)
        self.output_model = build_output_model(spec)
        self.instructions = build_instructions(spec)
        self.prompt_sha256 = prompt_sha256(spec)
        self.agent: Agent[None, Any] = Agent(
            model,
            output_type=_output_spec(self.output_model, output_mode),
            instructions=self.instructions,
            retries={"output": output_retries},
            model_settings=model_settings,
            name=f"classify-{spec.name}",
        )

    @classmethod
    def from_provider(
        cls,
        spec: TaxonomySpec,
        provider: ProviderConfig,
        *,
        output_retries: int = DEFAULT_OUTPUT_RETRIES,
    ) -> TaxonomyClassifier:
        """Create a classifier for a configured provider.

        The served model is discovered once per provider configuration; output
        mode and concurrency follow the provider (see :mod:`postparse.llm.client`).

        Args:
            spec: Taxonomy specification.
            provider: Provider configuration.
            output_retries: Retries when the output fails validation.

        Returns:
            Ready classifier.

        Raises:
            LLMAuthenticationError: If a cloud provider has no API key.
        """
        resolved = resolve_provider_config(provider)
        return cls(
            spec,
            build_model(provider),
            output_mode_for(resolved),
            max_concurrency=max_concurrency_for(resolved),
            output_retries=output_retries,
            provider_name=resolved.name,
            model_name=resolved.model,
        )

    def describe(self) -> dict[str, Any]:
        """Return non-sensitive metadata (for runs and API listings)."""
        return {
            "taxonomy": self.spec.name,
            "mode": self.spec.mode,
            "labels": list(self.spec.label_names),
            "provider": self.provider_name,
            "model": self.model_name,
            "output_mode": self.output_mode,
            "max_concurrency": self.max_concurrency,
            "prompt_sha256": self.prompt_sha256,
            "label_set_sha256": self.spec.label_set_sha256,
        }

    # -- single text ----------------------------------------------------------

    async def aclassify(self, text: str | None) -> ClassificationOutcome:
        """Classify one text.

        Args:
            text: Content; blank input returns an ``empty`` outcome without
                calling the model.

        Returns:
            Outcome with status ``ok``, ``no_labels`` or ``empty``.

        Raises:
            ClassificationError: If the request fails or the output stays
                invalid after the configured retries.
        """
        content = (text or "").strip()
        if not content:
            return ClassificationOutcome(status="empty")
        started = time.perf_counter()
        try:
            result = await self.agent.run(build_user_prompt(content))
        except Exception as exc:
            raise ClassificationError(f"{type(exc).__name__}: {exc}") from exc
        elapsed = time.perf_counter() - started
        output = result.output
        labels = output_labels(output)
        return ClassificationOutcome(
            status="ok" if labels else "no_labels",
            labels=labels,
            confidence=float(output.confidence),
            reasoning=output.reasoning or None,
            latency_s=elapsed,
            requests=result.usage.requests,
        )

    def classify(self, text: str | None) -> ClassificationOutcome:
        """Synchronous :meth:`aclassify` (not usable inside a running event loop)."""
        if not (text or "").strip():
            return ClassificationOutcome(status="empty")
        return run_sync(self.aclassify(text))

    # -- batches --------------------------------------------------------------

    async def aclassify_many(
        self,
        texts: Sequence[str | None],
        *,
        max_concurrency: int | None = None,
        on_result: Callable[[int, ClassificationOutcome], None] | None = None,
    ) -> list[ClassificationOutcome]:
        """Classify several texts with bounded concurrency.

        Failures do not abort the batch; they become ``error`` outcomes.

        Args:
            texts: Contents in order.
            max_concurrency: Override :attr:`max_concurrency`.
            on_result: Called with ``(index, outcome)`` as results arrive.

        Returns:
            Outcomes in input order.
        """
        semaphore = asyncio.Semaphore(max_concurrency or self.max_concurrency)

        async def one(index: int, text: str | None) -> ClassificationOutcome:
            async with semaphore:
                try:
                    outcome = await self.aclassify(text)
                except ClassificationError as exc:
                    logger.warning("Classification of input %d failed: %s", index, exc)
                    outcome = ClassificationOutcome(status="error", error=str(exc))
            if on_result is not None:
                on_result(index, outcome)
            return outcome

        return list(await asyncio.gather(*(one(i, t) for i, t in enumerate(texts))))

    def classify_many(
        self,
        texts: Sequence[str | None],
        *,
        max_concurrency: int | None = None,
    ) -> list[ClassificationOutcome]:
        """Synchronous :meth:`aclassify_many`."""
        return run_sync(self.aclassify_many(texts, max_concurrency=max_concurrency))
