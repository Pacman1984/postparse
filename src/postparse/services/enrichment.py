"""Link enrichment workflow: linked URLs -> fetched texts in the v2 database.

:class:`EnrichmentService` selects the links that need a fetch, fetches them
through :class:`~postparse.enrichment.fetchers.router.FetchRouter` (per-domain
throttle, bounded concurrency) and stores every result with
:meth:`LinksRepo.add_fetch` in its own transaction (crash-safe; the search
documents of the linking items are refreshed on success).

Selection (``force=False``):

* links without any non-legacy fetch -- this includes the links whose only
  text was migrated from schema v1 (fetcher ``legacy_v1``), so they are
  re-enriched with the new stack (``refresh_legacy=False`` leaves them alone).
  The legacy fetch stays in the database as fallback; search uses the newest
  ``ok`` fetch, so it wins only while no new fetch succeeded;
* links whose newest non-legacy fetch failed and whose retry is due
  (:class:`~postparse.enrichment.fetchers.router.RetryPolicy`: exponential
  backoff from the last attempt, giving up after ``max_attempts`` failures);
* never: links whose newest non-legacy fetch is ``ok`` or ``skipped``.

``force=True`` refetches every link in scope. Never-fetched links come first,
then legacy links, then retries; the queue is interleaved across domains so the
per-domain throttle does not block the other workers.

When all links of an item have a fresh result, the item's
``legacy_expanded_text`` (v1 "expanded text") is deleted and its search
document refreshed.

Configuration: ``[enrichment]`` (see :mod:`postparse.enrichment.options`).

Example:
    >>> report = EnrichmentService(db, settings).run(limit=100)
    >>> report.ok, report.errors_count
    (93, 4)
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.models import Link
from postparse.core.db.repos import ItemsRepo, LinkEnrichmentState, LinksRepo
from postparse.enrichment.fetchers.base import FetchResult
from postparse.enrichment.fetchers.router import FetchRouter, RetryPolicy
from postparse.enrichment.options import EnrichmentOptions

__all__ = [
    "EnrichmentProgress",
    "EnrichmentReport",
    "EnrichmentService",
    "EnrichmentSource",
    "normalize_domain",
]

logger = logging.getLogger(__name__)

EnrichmentSource = Literal["all", "telegram", "instagram"]
EnrichmentStopReason = Literal["done", "interrupted"]
_MAX_ERROR_SAMPLES = 10
RouterFactory = Callable[[EnrichmentOptions], FetchRouter]


def normalize_domain(domain: str) -> str:
    """Lower-case a ``--domain`` value and strip scheme, ``www.`` and paths."""
    value = domain.strip().lower()
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("/", 1)[0]
    return value[4:] if value.startswith("www.") else value


@dataclass(slots=True)
class EnrichmentReport:
    """Outcome of one :meth:`EnrichmentService.run`.

    Attributes:
        source: Source filter (``all``, ``telegram``, ``instagram``).
        candidates: Links selected for this run.
        ok: Links fetched successfully.
        errors_count: Links whose fetch failed (retried later).
        skipped: Links skipped for good (Instagram, unsupported content, ...).
        by_fetcher: ``{fetcher: {status: count}}``.
        legacy_refreshed: Links with a ``legacy_v1`` text that got a new ``ok`` fetch.
        legacy_texts_removed: ``legacy_expanded_text`` rows deleted.
        items_refreshed: Items whose search document was refreshed.
        duration_s: Wall time.
        stopped_reason: ``done`` or ``interrupted``.
        errors: Up to ten ``"<url>: message"`` samples.
    """

    source: str = "all"
    candidates: int = 0
    ok: int = 0
    errors_count: int = 0
    skipped: int = 0
    by_fetcher: dict[str, dict[str, int]] = field(default_factory=dict)
    legacy_refreshed: int = 0
    legacy_texts_removed: int = 0
    items_refreshed: int = 0
    duration_s: float = 0.0
    stopped_reason: EnrichmentStopReason | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def handled(self) -> int:
        """Links handled in this run."""
        return self.ok + self.errors_count + self.skipped

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        data = dataclasses.asdict(self)
        data["handled"] = self.handled
        return data


@dataclass(frozen=True, slots=True)
class EnrichmentProgress:
    """Progress callback payload (one per handled link).

    Attributes:
        link: Link just handled.
        fetcher: Fetcher used.
        status: Outcome.
        index: 1-based count of handled links.
        total: Links selected.
        report: Live report.
    """

    link: Link
    fetcher: str
    status: str
    index: int
    total: int
    report: EnrichmentReport


class EnrichmentService:
    """Fetch linked URLs and store their texts.

    Args:
        db: Schema v2 database.
        settings: Application settings (kept for API symmetry; not needed yet).
        config: ``ConfigManager`` with ``[enrichment]`` (``None``: defaults).
        options: Explicit options (override ``config``).
        router_factory: ``options -> FetchRouter`` (tests pass routers with
            fake fetchers or a mock transport).
        clock: Current UTC time (retry selection).
    """

    def __init__(
        self,
        db: Database,
        settings: Settings | None = None,
        config: Any = None,
        *,
        options: EnrichmentOptions | None = None,
        router_factory: RouterFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.options = options or EnrichmentOptions.from_config(config)
        self.retry = RetryPolicy.from_options(self.options)
        self.router_factory = router_factory or (lambda opts: FetchRouter.default_router(opts))
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- selection ---------------------------------------------------------------

    def _states(
        self, source: EnrichmentSource, domains: Sequence[str] | None
    ) -> list[LinkEnrichmentState]:
        normalized = sorted({normalize_domain(d) for d in domains}) if domains else None
        with self.db.read() as conn:
            return LinksRepo(conn).enrichment_states(
                source=None if source == "all" else source, domains=normalized
            )

    def is_due(
        self,
        state: LinkEnrichmentState,
        now: datetime,
        *,
        force: bool = False,
        refresh_legacy: bool = True,
    ) -> bool:
        """Decide whether ``state`` needs a fetch (see the module docstring)."""
        if force:
            return True
        if not refresh_legacy and state.has_legacy_ok and not state.has_ok:
            return False
        if state.last_status is None:
            return True
        if state.last_status != "error":
            return False
        assert state.last_fetched_at is not None
        return self.retry.is_due(state.failures, state.last_fetched_at, now)

    def select(
        self,
        source: EnrichmentSource = "all",
        limit: int | None = None,
        *,
        force: bool = False,
        refresh_legacy: bool = True,
        domains: Sequence[str] | None = None,
    ) -> list[LinkEnrichmentState]:
        """Return the links to fetch, in processing order."""
        now = self._clock()
        due = [
            s
            for s in self._states(source, domains)
            if self.is_due(s, now, force=force, refresh_legacy=refresh_legacy)
        ]

        def rank(state: LinkEnrichmentState) -> int:
            if state.last_status is None:
                return 1 if state.has_legacy_ok else 0
            return 2

        due.sort(key=lambda s: (rank(s), s.link.id))
        if limit is not None:
            due = due[:limit]
        return _interleave_domains(due)

    def status(self, *, source: EnrichmentSource = "all", top_domains: int = 15) -> dict[str, Any]:
        """Return enrichment statistics.

        Returns:
            ``{"links", "by_state": {(fetcher, status): n}, "domains": [(domain,
            {state: n}), ...], "due", "retry_due", "gave_up", "next_retry_at",
            "legacy_only", "never"}``. States are the newest non-legacy
            ``status`` or ``legacy`` (only a v1 text) / ``never``.
        """
        now = self._clock()
        states = self._states(source, None)
        by_state: dict[tuple[str, str], int] = {}
        domains: dict[str, dict[str, int]] = {}
        due = retry_due = gave_up = 0
        next_retry: datetime | None = None
        for state in states:
            if state.last_status is None:
                key = ("legacy_v1", "legacy") if state.has_legacy_ok else ("-", "never")
            else:
                key = (state.last_fetcher or "-", state.last_status)
            by_state[key] = by_state.get(key, 0) + 1
            bucket = domains.setdefault(state.link.domain, {})
            bucket[key[1]] = bucket.get(key[1], 0) + 1
            if self.is_due(state, now):
                due += 1
            if state.last_status == "error":
                assert state.last_fetched_at is not None
                when = self.retry.next_attempt_at(state.failures, state.last_fetched_at)
                if when is None:
                    gave_up += 1
                elif when <= now:
                    retry_due += 1
                elif next_retry is None or when < next_retry:
                    next_retry = when
        ranked = sorted(domains.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
        return {
            "links": len(states),
            "by_state": by_state,
            "domains": ranked[:top_domains],
            "other_domains": max(len(ranked) - top_domains, 0),
            "due": due,
            "retry_due": retry_due,
            "gave_up": gave_up,
            "next_retry_at": next_retry.isoformat(timespec="minutes") if next_retry else None,
            "max_attempts": self.options.max_attempts,
        }

    # -- run -------------------------------------------------------------------------

    def run(
        self,
        source: EnrichmentSource = "all",
        limit: int | None = None,
        force: bool = False,
        refresh_legacy: bool = True,
        domains: Sequence[str] | None = None,
        progress: Callable[[EnrichmentProgress], None] | None = None,
    ) -> EnrichmentReport:
        """Fetch due links and store the results (blocking; see :meth:`arun`)."""
        return asyncio.run(
            self.arun(
                source,
                limit,
                force=force,
                refresh_legacy=refresh_legacy,
                domains=domains,
                progress=progress,
            )
        )

    async def arun(
        self,
        source: EnrichmentSource = "all",
        limit: int | None = None,
        *,
        force: bool = False,
        refresh_legacy: bool = True,
        domains: Sequence[str] | None = None,
        progress: Callable[[EnrichmentProgress], None] | None = None,
    ) -> EnrichmentReport:
        """Fetch due links and store the results.

        Args:
            source: ``all``, ``telegram`` or ``instagram`` (links of those items).
            limit: Maximum links this run (``None``: all due).
            force: Refetch every link in scope.
            refresh_legacy: Re-enrich links whose only text is a ``legacy_v1`` fetch.
            domains: Only links on these domains.
            progress: Called after each stored link.

        Returns:
            Report. Each link is committed on its own; on cancellation /
            Ctrl-C everything stored so far is kept.
        """
        started = time.perf_counter()
        report = EnrichmentReport(source=source)
        selected = self.select(
            source, limit, force=force, refresh_legacy=refresh_legacy, domains=domains
        )
        report.candidates = len(selected)
        if not selected:
            report.stopped_reason = "done"
            report.duration_s = time.perf_counter() - started
            return report
        logger.info("Enriching %d links", len(selected))
        handled = 0
        refreshed: set[int] = set()
        try:
            async with self.router_factory(self.options) as router:

                async def one(state: LinkEnrichmentState) -> None:
                    nonlocal handled
                    result = await router.fetch(state.link)
                    self._store(state, result, report, refreshed)
                    handled += 1
                    if progress is not None:
                        progress(
                            EnrichmentProgress(
                                state.link,
                                result.fetcher,
                                result.status,
                                handled,
                                len(selected),
                                report,
                            )
                        )

                tasks = [asyncio.create_task(one(state)) for state in selected]
                try:
                    await asyncio.gather(*tasks)
                except BaseException:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
            report.stopped_reason = "done"
        except (KeyboardInterrupt, asyncio.CancelledError):
            report.stopped_reason = "interrupted"
            logger.warning("Enrichment interrupted; stored links are kept")
            raise
        finally:
            report.items_refreshed = len(refreshed)
            report.duration_s = time.perf_counter() - started
            logger.info(
                "Enrichment %s: ok=%d error=%d skipped=%d legacy_refreshed=%d "
                "legacy_texts_removed=%d in %.1fs",
                report.stopped_reason,
                report.ok,
                report.errors_count,
                report.skipped,
                report.legacy_refreshed,
                report.legacy_texts_removed,
                report.duration_s,
            )
        return report

    def _store(
        self,
        state: LinkEnrichmentState,
        result: FetchResult,
        report: EnrichmentReport,
        refreshed: set[int],
    ) -> None:
        """Persist one result (own transaction) and update the report."""
        cap = self.options.max_text_chars
        text = result.text
        metadata = dict(result.metadata)
        if text is not None and len(text) > cap:
            metadata["text_truncated_from"] = len(text)
            text = text[:cap]
        title = result.title[:1000] if result.title else None
        link = state.link
        with self.db.transaction() as conn:
            links = LinksRepo(conn)
            links.add_fetch(
                link.id,
                fetcher=result.fetcher or "unknown",
                status=result.status,
                http_status=result.http_status,
                title=title,
                text=text,
                metadata=metadata or None,
                error=(result.error or None) and result.error[:1000],
                fetched_at=self._clock(),
            )
            item_ids = links.items_for_link(link.id)
            if result.status == "ok":
                refreshed.update(item_ids)
            if result.status in ("ok", "skipped"):
                items = ItemsRepo(conn)
                legacy = items.legacy_expanded_texts(item_ids)
                for item_id in legacy:
                    if links.legacy_text_settled(item_id):
                        items.set_legacy_expanded_text(item_id, None)
                        report.legacy_texts_removed += 1
                        refreshed.add(item_id)
        counts = report.by_fetcher.setdefault(result.fetcher or "unknown", {})
        counts[result.status] = counts.get(result.status, 0) + 1
        if result.status == "ok":
            report.ok += 1
            if state.has_legacy_ok and not state.has_ok:
                report.legacy_refreshed += 1
        elif result.status == "skipped":
            report.skipped += 1
        else:
            report.errors_count += 1
            if len(report.errors) < _MAX_ERROR_SAMPLES:
                report.errors.append(f"{link.url}: {result.error}")
            logger.debug("Fetch of %s failed: %s", link.url, result.error)


def _interleave_domains(states: list[LinkEnrichmentState]) -> list[LinkEnrichmentState]:
    """Round-robin across domains, keeping the order within each domain."""
    queues: OrderedDict[str, list[LinkEnrichmentState]] = OrderedDict()
    for state in states:
        queues.setdefault(state.link.domain, []).append(state)
    result: list[LinkEnrichmentState] = []
    while queues:
        for domain in list(queues):
            queue = queues[domain]
            result.append(queue.pop(0))
            if not queue:
                del queues[domain]
    return result
