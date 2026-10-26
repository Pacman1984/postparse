"""Summarization workflow: transcribed items -> short LLM summaries.

:class:`SummarizationService` selects items that have at least one transcript
and no summary newer than their newest transcript
(:meth:`SummariesRepo.items_needing_summary`), composes caption + transcript(s)
+ linked page texts, asks a :class:`~postparse.summarization.Summarizer` and
appends one ``summaries`` row per item (``text`` = summary + bullet list, see
:mod:`postparse.summarization.schemas`; ``provider``, ``model`` and
``prompt_sha256`` recorded). Each summary is committed on its own.

Configuration (all optional)::

    [summarization]
    provider = ""             # LLM provider name ([[llm.providers]]); empty = llm.default_provider
    max_input_chars = 12000   # character budget of the composed input
    output_retries = 2        # re-ask the model when the output fails validation

Example:
    >>> service = SummarizationService(db, settings, config=config)
    >>> report = service.run(limit=20)
    >>> report.summarized, report.errors
    (20, 0)
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from postparse.core.db import Database
from postparse.core.db.repos import ItemsRepo, LinksRepo, SummariesRepo, TranscriptsRepo
from postparse.llm.client import run_sync, select_provider
from postparse.llm.config import LLMConfig
from postparse.summarization.summarizer import (
    DEFAULT_OUTPUT_RETRIES,
    SummarizationError,
    Summarizer,
    SummaryOutcome,
)

if TYPE_CHECKING:
    from postparse.config import Settings

__all__ = [
    "DEFAULT_SUMMARY_INPUT_CHARS",
    "SummarizationProgress",
    "SummarizationReport",
    "SummarizationService",
    "compose_summary_input",
]

logger = logging.getLogger(__name__)

DEFAULT_SUMMARY_INPUT_CHARS = 12_000
_CHUNK = 16
_MAX_ERROR_SAMPLES = 10

SummarizerFactory = Callable[[str | None], Summarizer]
SummaryStatus = Literal["summarized", "skipped_empty", "error"]


def _clean(text: str | None) -> str:
    return (text or "").strip()


def compose_summary_input(
    conn: sqlite3.Connection, item_ids: Sequence[int], max_chars: int = DEFAULT_SUMMARY_INPUT_CHARS
) -> dict[int, str]:
    """Build the summarizer input per item: caption, transcript(s), linked pages.

    Existing summaries are deliberately not included. Each linked page gets at
    most a quarter of the budget; the whole text is cut to ``max_chars``.

    Returns:
        ``{item_id: text}`` (empty string when nothing is known).
    """
    ids = list(item_ids)
    if not ids:
        return {}
    items_repo = ItemsRepo(conn)
    transcripts = TranscriptsRepo(conn).current_for_items(ids)
    links_repo = LinksRepo(conn)
    links = links_repo.for_items(ids)
    fetches = links_repo.latest_ok_fetches(
        sorted({link.id for item_links in links.values() for link in item_links})
    )
    result: dict[int, str] = {}
    for item_id in ids:
        item = items_repo.get(item_id)
        if item is None:
            continue
        sections: list[tuple[str, str, int | None]] = []
        if _clean(item.text):
            sections.append(("Caption", _clean(item.text), None))
        for index, transcript in enumerate(transcripts.get(item_id, [])):
            if _clean(transcript.text):
                header = "Transcript" if index == 0 else f"Transcript {index + 1}"
                if transcript.language:
                    header += f" (language: {transcript.language})"
                sections.append((header, _clean(transcript.text), None))
        for link in links.get(item_id, []):
            fetch = fetches.get(link.id)
            if fetch is None or not _clean(fetch.text):
                continue
            title = _clean(fetch.title)
            header = f"Linked page ({link.domain})" + (f": {title}" if title else "")
            sections.append((header, _clean(fetch.text), max(max_chars // 4, 1)))
        parts: list[str] = []
        remaining = max_chars
        for header, text, cap in sections:
            prefix = f"[{header}]\n"
            budget = remaining - len(prefix) - (2 if parts else 0)
            if cap is not None:
                budget = min(budget, cap)
            if budget <= 0:
                break
            if len(text) > budget:
                text = text[: max(budget - 1, 0)].rstrip() + "…"
            block = prefix + text
            parts.append(block)
            remaining -= len(block) + (2 if len(parts) > 1 else 0)
        result[item_id] = "\n\n".join(parts)
    return result


@dataclass(slots=True)
class SummarizationReport:
    """Outcome of :meth:`SummarizationService.run`.

    Attributes:
        provider: Provider name.
        model: Model name.
        candidates: Items selected.
        summarized: Summaries stored.
        skipped_empty: Items without any text (nothing stored).
        errors: Items whose summary failed (they stay due).
        duration_s: Wall time.
        latency_s: Sum of model latencies.
        error_samples: Up to ten ``(item_id, message)`` pairs.
        item_ids: Items that got a summary.
    """

    provider: str | None = None
    model: str | None = None
    candidates: int = 0
    summarized: int = 0
    skipped_empty: int = 0
    errors: int = 0
    duration_s: float = 0.0
    latency_s: float = 0.0
    error_samples: list[tuple[int, str]] = field(default_factory=list)
    item_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return dataclasses.asdict(self)


@dataclass(frozen=True, slots=True)
class SummarizationProgress:
    """Progress payload (one per handled item)."""

    item_id: int
    status: SummaryStatus
    handled: int
    total: int
    report: SummarizationReport


class SummarizationService:
    """Summarize transcribed items and store the summaries.

    Args:
        db: Schema v2 database.
        settings: Application settings (unused for now).
        llm_config: Providers; loaded from ``config`` when omitted.
        config: ``ConfigManager`` (``[llm]`` and ``[summarization]``).
        summarizer_factory: ``provider_name -> Summarizer`` (tests).
        max_input_chars: Input budget (default ``summarization.max_input_chars``).
    """

    def __init__(
        self,
        db: Database,
        settings: Settings | None = None,
        llm_config: LLMConfig | None = None,
        *,
        config: Any = None,
        summarizer_factory: SummarizerFactory | None = None,
        max_input_chars: int | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        section: dict[str, Any] = {}
        if config is not None:
            section = config.get_section("summarization") or {}
        if llm_config is None and config is not None and summarizer_factory is None:
            try:
                llm_config = LLMConfig.from_config_manager(config)
            except (ValueError, TypeError) as exc:
                logger.warning("No usable LLM configuration: %s", exc)
        self.llm_config = llm_config
        self.summarizer_factory = summarizer_factory
        self.default_provider: str | None = section.get("provider") or None
        self.max_input_chars = int(
            max_input_chars or section.get("max_input_chars") or DEFAULT_SUMMARY_INPUT_CHARS
        )
        self.output_retries = int(section.get("output_retries") or DEFAULT_OUTPUT_RETRIES)
        self._summarizers: dict[str | None, Summarizer] = {}

    def summarizer(self, provider: str | None = None) -> Summarizer:
        """Return the (cached) summarizer for a provider (``None``: configured default).

        Raises:
            ValueError: No LLM configuration or unknown provider.
        """
        provider = provider or self.default_provider
        cached = self._summarizers.get(provider)
        if cached is not None:
            return cached
        if self.summarizer_factory is not None:
            summarizer = self.summarizer_factory(provider)
        else:
            if self.llm_config is None:
                raise ValueError("No LLM providers configured ([llm] section missing)")
            summarizer = Summarizer.from_provider(
                select_provider(self.llm_config, provider), output_retries=self.output_retries
            )
        self._summarizers[provider] = summarizer
        return summarizer

    def pending(
        self,
        *,
        limit: int | None = None,
        force: bool = False,
        item_ids: Sequence[int] | None = None,
    ) -> list[int]:
        """Items that need a summary (see :meth:`SummariesRepo.items_needing_summary`)."""
        with self.db.read() as conn:
            return SummariesRepo(conn).items_needing_summary(
                limit=limit, force=force, item_ids=item_ids
            )

    def run(
        self,
        limit: int | None = None,
        provider: str | None = None,
        force: bool = False,
        item_ids: Sequence[int] | None = None,
        progress: Callable[[SummarizationProgress], None] | None = None,
    ) -> SummarizationReport:
        """Summarize due items (synchronous wrapper around :meth:`arun`)."""
        return run_sync(
            self.arun(
                limit=limit,
                provider=provider,
                force=force,
                item_ids=item_ids,
                progress=progress,
            )
        )

    async def arun(
        self,
        limit: int | None = None,
        provider: str | None = None,
        force: bool = False,
        item_ids: Sequence[int] | None = None,
        progress: Callable[[SummarizationProgress], None] | None = None,
    ) -> SummarizationReport:
        """Summarize due items.

        Args:
            limit: Maximum items.
            provider: LLM provider name (default: ``summarization.provider`` or
                the LLM default provider).
            force: Re-summarize items that already have a current summary.
            item_ids: Only these items.
            progress: Called once per handled item.

        Returns:
            Report (model errors are counted, not raised).

        Raises:
            ValueError: No LLM configuration or unknown provider.
        """
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        started = time.perf_counter()
        candidates = self.pending(limit=limit, force=force, item_ids=item_ids)
        report = SummarizationReport(candidates=len(candidates))
        if not candidates:
            report.duration_s = time.perf_counter() - started
            return report
        summarizer = self.summarizer(provider)
        report.provider, report.model = summarizer.provider_name, summarizer.model_name
        logger.info(
            "Summarizing %d items with %s / %s", len(candidates), report.provider, report.model
        )
        handled = 0
        semaphore = asyncio.Semaphore(summarizer.max_concurrency)

        def notify(item_id: int, status: SummaryStatus) -> None:
            nonlocal handled
            handled += 1
            if progress is not None:
                progress(SummarizationProgress(item_id, status, handled, len(candidates), report))

        async def one(item_id: int, text: str) -> None:
            async with semaphore:
                try:
                    outcome = await summarizer.asummarize(text)
                except SummarizationError as exc:
                    report.errors += 1
                    if len(report.error_samples) < _MAX_ERROR_SAMPLES:
                        report.error_samples.append((item_id, str(exc)))
                    logger.warning("Summary of item %d failed: %s", item_id, exc)
                    notify(item_id, "error")
                    return
            self._store(item_id, outcome, summarizer, report)
            notify(item_id, "summarized")

        try:
            for offset in range(0, len(candidates), _CHUNK):
                chunk = candidates[offset : offset + _CHUNK]
                with self.db.read() as conn:
                    texts = compose_summary_input(conn, chunk, self.max_input_chars)
                work = []
                for item_id in chunk:
                    text = texts.get(item_id, "")
                    if not text.strip():
                        report.skipped_empty += 1
                        notify(item_id, "skipped_empty")
                        continue
                    work.append(asyncio.ensure_future(one(item_id, text)))
                try:
                    await asyncio.gather(*work)
                except BaseException:
                    for task in work:
                        task.cancel()
                    await asyncio.gather(*work, return_exceptions=True)
                    raise
        finally:
            report.duration_s = time.perf_counter() - started
            logger.info(
                "Summaries: %d stored, %d empty, %d errors in %.1fs",
                report.summarized,
                report.skipped_empty,
                report.errors,
                report.duration_s,
            )
        return report

    def _store(
        self,
        item_id: int,
        outcome: SummaryOutcome,
        summarizer: Summarizer,
        report: SummarizationReport,
    ) -> None:
        with self.db.transaction() as conn:
            SummariesRepo(conn).add(
                item_id,
                outcome.text,
                provider=summarizer.provider_name,
                model=summarizer.model_name,
                prompt_sha256=summarizer.prompt_sha256,
            )
        report.summarized += 1
        report.latency_s += outcome.latency_s
        report.item_ids.append(item_id)
