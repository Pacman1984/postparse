"""Coroutine factories for the API job kinds.

Each function binds a service and request parameters and returns a
:data:`~postparse.api.jobs.runner.CoroFactory`. Service-specific progress
payloads are translated into ``progress(processed, total, message)``.

Threading:

* ``telegram_extract`` awaits :meth:`ExtractionService.telegram_async` on the
  event loop (Telethon is asyncio based; ``interactive=False``).
* ``instagram_extract``, ``transcribe`` and ``enrich`` are blocking and run in
  a worker thread.
* ``classify`` and ``summarize`` await the services' async APIs on the event
  loop, so cached LLM clients stay bound to one loop (the same one the
  ``/classify`` endpoints use).
"""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from postparse.api.jobs.runner import CoroFactory, ProgressSink, in_thread

if TYPE_CHECKING:
    from postparse.core.db.models import ItemFilter
    from postparse.services.classification import ClassificationService
    from postparse.services.enrichment import EnrichmentService
    from postparse.services.extraction import ExtractionService
    from postparse.services.summarization import SummarizationService
    from postparse.services.transcription import TranscriptionService

__all__ = [
    "classify_job",
    "enrich_job",
    "instagram_extract_job",
    "summarize_job",
    "telegram_extract_job",
    "transcribe_job",
    "with_credentials",
]


def with_credentials(
    service: ExtractionService, credentials: Mapping[str, str | None]
) -> ExtractionService:
    """Return a copy of ``service`` whose environment includes request credentials.

    Args:
        service: Shared extraction service.
        credentials: ``{ENV_NAME: value}``; ``None``/empty values are ignored.

    Returns:
        The same service when there is nothing to add, otherwise a shallow copy.
    """
    extra = {k: str(v) for k, v in credentials.items() if v not in (None, "")}
    if not extra:
        return service
    clone = copy.copy(service)
    base = dict(os.environ if service.env is None else service.env)
    base.update(extra)
    clone.env = base
    return clone


def _collector_progress(progress: ProgressSink) -> Any:
    def forward(event: Any) -> None:
        message = event.message or (
            f"{event.phase}: new {event.new}, updated {event.updated}"
            + (f", known {event.known_skipped}" if event.known_skipped else "")
        )
        progress(event.processed, event.total, message)

    return forward


def telegram_extract_job(
    service: ExtractionService, *, limit: int | None, full: bool
) -> CoroFactory:
    """Collect Telegram Saved Messages (never prompts for a login)."""

    async def factory(progress: ProgressSink) -> Any:
        return await service.telegram_async(
            limit=limit, full=full, interactive=False, progress=_collector_progress(progress)
        )

    return factory


def instagram_extract_job(
    service: ExtractionService,
    *,
    limit: int | None,
    stop_after_known: int | None,
    username: str | None,
    refresh_dates: bool = False,
) -> CoroFactory:
    """Collect saved Instagram posts in a worker thread (never prompts)."""

    def run(progress: ProgressSink) -> Any:
        return service.instagram(
            limit=limit,
            stop_after_known=stop_after_known,
            refresh_dates=refresh_dates,
            interactive=False,
            progress=_collector_progress(progress),
            username=username,
        )

    return in_thread(run)


def transcribe_job(
    service: TranscriptionService,
    *,
    source: str | None,
    limit: int | None,
    backend: str | None,
    refetch: bool,
    item_ids: Sequence[int] | None,
) -> CoroFactory:
    """Transcribe due media in a worker thread."""

    def run(progress: ProgressSink) -> Any:
        return service.run(
            source=source,  # type: ignore[arg-type]
            limit=limit,
            backend=backend,  # type: ignore[arg-type]
            refetch=refetch,
            item_ids=item_ids,
            progress=lambda p: progress(p.index, p.total, f"media {p.media_id}: {p.status}"),
        )

    return in_thread(run)


def summarize_job(
    service: SummarizationService,
    *,
    limit: int | None,
    provider: str | None,
    force: bool,
    item_ids: Sequence[int] | None,
) -> CoroFactory:
    """Summarize transcribed items."""

    async def factory(progress: ProgressSink) -> Any:
        return await service.arun(
            limit=limit,
            provider=provider,
            force=force,
            item_ids=item_ids,
            progress=lambda p: progress(p.handled, p.total, f"item {p.item_id}: {p.status}"),
        )

    return factory


def enrich_job(
    service: EnrichmentService,
    *,
    source: str,
    limit: int | None,
    force: bool,
    refresh_legacy: bool,
    domains: Sequence[str] | None,
) -> CoroFactory:
    """Fetch linked pages in a worker thread (own event loop per run)."""

    def run(progress: ProgressSink) -> Any:
        return service.run(
            source,  # type: ignore[arg-type]
            limit,
            force=force,
            refresh_legacy=refresh_legacy,
            domains=domains,
            progress=lambda p: progress(p.index, p.total, f"{p.link.domain}: {p.status}"),
        )

    return in_thread(run)


def classify_job(
    service: ClassificationService,
    *,
    taxonomy: str,
    scope: str,
    filters: ItemFilter | None,
    limit: int | None,
    provider: str | None,
    wait_for_transcripts: bool,
) -> CoroFactory:
    """Classify pending items of a taxonomy and store the results."""

    async def factory(progress: ProgressSink) -> Any:
        return await service.aclassify_pending(
            taxonomy,
            scope=scope,  # type: ignore[arg-type]
            filters=filters,
            limit=limit,
            provider=provider,
            wait_for_transcripts=wait_for_transcripts,
            progress=lambda p: progress(p.handled, p.total, f"item {p.item_id}: {p.status}"),
        )

    return factory
