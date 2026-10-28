"""Extraction service: run the Telegram/Instagram collectors against the v2 database.

The service is the one entry point used by the CLI (and later the API). It
reads credentials from the environment, builds the collectors and turns every
outcome (including rate limits and missing logins) into an
:class:`ExtractionReport`, so callers never lose the counts of a partial run.

Example:
    >>> service = ExtractionService(Database.open(settings.db_path), settings)
    >>> report = service.telegram(limit=100)
    >>> report.new, report.stopped_reason
    (12, 'end_of_feed')
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from postparse.collectors.base import (
    AuthRequired,
    CollectStats,
    InstagramFeedUnavailable,
    ProgressCallback,
    RateLimited,
    StopReason,
)
from postparse.collectors.credentials import instagram_credentials, telegram_credentials
from postparse.config import Settings
from postparse.core.db import Database

__all__ = ["ExtractionReport", "ExtractionService"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExtractionReport:
    """Outcome of one extraction run.

    Attributes:
        source: ``telegram`` or ``instagram``.
        new: Items inserted.
        updated: Existing items updated.
        known_skipped: Known items skipped (Instagram incremental runs).
        media_downloaded: Files downloaded (Telegram).
        dates_refreshed: Instagram dates re-fetched.
        processed: Items written or queued (new + updated).
        batches_committed: Write transactions committed.
        last_external_id: Last committed item (how far the run got).
        errors: Non-fatal per-item problems plus the fatal error, if any.
        stopped_reason: ``early_stop``, ``limit``, ``end_of_feed``,
            ``rate_limited``, ``auth_required`` or ``feed_unavailable``
            (Instagram refused the saved feed; ``None`` after an unexpected
            error).
        error: Message of the error that ended the run, if any.
        duration_s: Wall-clock duration in seconds.
    """

    source: str
    new: int = 0
    updated: int = 0
    known_skipped: int = 0
    media_downloaded: int = 0
    dates_refreshed: int = 0
    processed: int = 0
    batches_committed: int = 0
    last_external_id: str | None = None
    errors: list[str] = field(default_factory=list)
    stopped_reason: StopReason | None = None
    error: str | None = None
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        """True if the run ended normally (feed end, early stop or limit)."""
        return self.stopped_reason in ("early_stop", "limit", "end_of_feed")

    @classmethod
    def from_stats(cls, stats: CollectStats, duration_s: float) -> ExtractionReport:
        """Build a report from collector statistics."""
        return cls(
            source=stats.source,
            new=stats.new,
            updated=stats.updated,
            known_skipped=stats.known_skipped,
            media_downloaded=stats.media_downloaded,
            dates_refreshed=stats.dates_refreshed,
            processed=stats.new + stats.updated,
            batches_committed=stats.batches_committed,
            last_external_id=stats.last_external_id,
            errors=list(stats.errors),
            stopped_reason=stats.stopped_reason,
            duration_s=duration_s,
        )


class ExtractionService:
    """Run collectors and report what they did.

    Args:
        db: Schema v2 database.
        settings: Application paths.
        config: ``ConfigManager`` with ``[telegram]``/``[instagram]`` tunables
            (``None``: built-in defaults).
        env: Environment to read credentials from (default ``os.environ``).
        telegram_overrides: Extra keyword arguments for
            :class:`~postparse.collectors.telegram.TelegramCollector`
            (e.g. ``client_factory``, ``sleep``; used by tests).
        instagram_overrides: Extra keyword arguments for
            :class:`~postparse.collectors.instagram.InstagramCollector`
            (e.g. ``loader_factory``, ``saved_posts``, ``prompt``, ``sleep``).
    """

    def __init__(
        self,
        db: Database,
        settings: Settings,
        config: Any = None,
        *,
        env: Mapping[str, str] | None = None,
        telegram_overrides: Mapping[str, Any] | None = None,
        instagram_overrides: Mapping[str, Any] | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.config = config
        self.env = env
        self.telegram_overrides = dict(telegram_overrides or {})
        self.instagram_overrides = dict(instagram_overrides or {})

    # -- Telegram --------------------------------------------------------

    def telegram(
        self,
        limit: int | None = None,
        full: bool = False,
        interactive: bool = True,
        session: str | Path | None = None,
        progress: ProgressCallback | None = None,
    ) -> ExtractionReport:
        """Collect Telegram Saved Messages (blocking wrapper around :meth:`telegram_async`).

        Must not be called from a running event loop; use :meth:`telegram_async` there.
        """
        return asyncio.run(
            self.telegram_async(
                limit=limit,
                full=full,
                interactive=interactive,
                session=session,
                progress=progress,
            )
        )

    async def telegram_async(
        self,
        limit: int | None = None,
        full: bool = False,
        interactive: bool = True,
        session: str | Path | None = None,
        progress: ProgressCallback | None = None,
    ) -> ExtractionReport:
        """Collect Telegram Saved Messages.

        Args:
            limit: Maximum messages to process.
            full: Re-read and update all messages instead of only new ones.
            interactive: Allow login prompts in the terminal.
            session: Session file override.
            progress: Progress callback.

        Returns:
            Report (also for rate limits and missing logins).
        """
        from postparse.collectors.telegram import TelegramCollector, TelegramOptions

        started = time.monotonic()
        collector: TelegramCollector | None = None
        try:
            credentials = telegram_credentials(self.env)
            collector = TelegramCollector(
                self.db,
                self.settings,
                credentials,
                TelegramOptions.from_config(self.config),
                interactive=interactive,
                session=session,
                **self.telegram_overrides,
            )
            async with collector:
                await collector.collect(limit=limit, full=full, progress=progress)
        except (AuthRequired, RateLimited) as exc:
            return self._failed(collector.stats if collector else None, "telegram", exc, started)
        return ExtractionReport.from_stats(collector.stats, time.monotonic() - started)

    # -- Instagram -------------------------------------------------------

    def instagram(
        self,
        limit: int | None = None,
        stop_after_known: int | None = 20,
        batch_size: int = 25,
        refresh_dates: bool = False,
        interactive: bool = True,
        session: str | Path | None = None,
        progress: ProgressCallback | None = None,
        *,
        username: str | None = None,
        refresh_limit: int | None = None,
    ) -> ExtractionReport:
        """Collect saved Instagram posts.

        Args:
            limit: Maximum posts to write.
            stop_after_known: Stop after this many consecutive known posts
                (``None``: walk the whole feed and update known posts).
            batch_size: Posts per write transaction.
            refresh_dates: Afterwards re-fetch dates of unverified (v1) posts.
            interactive: Allow prompting for a two-factor code.
            session: Session file override.
            progress: Progress callback.
            username: Username override (default ``INSTAGRAM_USERNAME``).
            refresh_limit: Maximum posts for the date refresh.

        Returns:
            Report (also for rate limits and missing logins).
        """
        from postparse.collectors.instagram import InstagramCollector, InstagramOptions

        started = time.monotonic()
        collector: InstagramCollector | None = None
        try:
            credentials = instagram_credentials(self.env, username)
            collector = InstagramCollector(
                self.db,
                self.settings,
                credentials,
                InstagramOptions.from_config(self.config),
                interactive=interactive,
                session=session,
                # Collection never logs in with the password (Instagram checkpoints);
                # only `postparse check instagram --login` does, interactively
                # (`--import-session` takes the browser session instead).
                **{"progress": progress, **self.instagram_overrides, "allow_password_login": False},
            )
            with collector:
                collector.collect_saved(
                    stop_after_known=stop_after_known,
                    limit=limit,
                    batch_size=batch_size,
                    progress=progress,
                )
                if refresh_dates:
                    reason = collector.stats.stopped_reason
                    collector.refresh_dates(refresh_limit, progress=progress)
                    collector.stats.stopped_reason = reason
        except (AuthRequired, RateLimited) as exc:
            return self._failed(collector.stats if collector else None, "instagram", exc, started)
        return ExtractionReport.from_stats(collector.stats, time.monotonic() - started)

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _failed(
        stats: CollectStats | None, source: str, exc: Exception, started: float
    ) -> ExtractionReport:
        """Build the report of a run that ended with a typed collector error."""
        duration = time.monotonic() - started
        report = (
            ExtractionReport.from_stats(stats, duration)
            if stats is not None
            else ExtractionReport(source=source, duration_s=duration)
        )
        if isinstance(exc, InstagramFeedUnavailable):
            report.stopped_reason = "feed_unavailable"
        elif isinstance(exc, RateLimited):
            report.stopped_reason = "rate_limited"
        else:
            report.stopped_reason = "auth_required"
        report.error = str(exc)
        report.errors.append(str(exc))
        logger.warning("%s extraction stopped: %s", source, exc)
        return report
