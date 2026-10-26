"""Shared building blocks of the collectors: errors, progress, stats and batching.

Collectors read items from a source (Telegram, Instagram) and write them to the
schema v2 database in small transactions, so an interrupted run keeps every
completed batch.
"""

from __future__ import annotations

import logging
import random
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from postparse.core.db import Database
from postparse.core.db.models import ItemUpsert, Source
from postparse.core.db.repos import ItemsRepo

__all__ = [
    "AuthRequired",
    "BatchWriter",
    "CollectStats",
    "CollectorError",
    "CredentialsMissing",
    "InstagramAuthRequired",
    "InstagramFeedUnavailable",
    "InstagramRateLimited",
    "InstagramSessionCheckFailed",
    "ProgressCallback",
    "ProgressEvent",
    "RateLimited",
    "StopReason",
    "TelegramAuthRequired",
    "TelegramRateLimited",
    "jitter",
    "safe_filename",
]

logger = logging.getLogger(__name__)

StopReason = Literal[
    "early_stop", "limit", "end_of_feed", "rate_limited", "auth_required", "feed_unavailable"
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CollectorError(RuntimeError):
    """Base class of all collector errors."""


class AuthRequired(CollectorError):
    """The source needs a (new) login before collection can continue."""


class CredentialsMissing(AuthRequired):
    """Required credentials are not configured.

    Attributes:
        missing: Names of the missing environment variables.
    """

    def __init__(self, source: str, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(
            f"{source} credentials missing: set {', '.join(missing)} (environment or config/.env)."
        )


class TelegramAuthRequired(AuthRequired):
    """Telegram session is missing or no longer authorized."""

    def __init__(self, detail: str | None = None) -> None:
        message = (
            "Telegram login required. Run `postparse extract telegram` in a terminal once "
            "to log in (you will be asked for the code Telegram sends you)."
        )
        super().__init__(f"{detail} {message}" if detail else message)


class InstagramAuthRequired(AuthRequired):
    """Instagram session is invalid and no automatic login was possible."""

    def __init__(self, detail: str | None = None) -> None:
        message = (
            "Instagram login required. If Instagram asks for a confirmation, confirm the "
            "login in the Instagram app, then retry `postparse extract instagram` in a terminal."
        )
        super().__init__(f"{detail} {message}" if detail else message)


class RateLimited(CollectorError):
    """The source asked us to slow down.

    Attributes:
        retry_after: Seconds to wait before retrying, if known.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class InstagramRateLimited(RateLimited):
    """Instagram returned 429 / "please wait a few minutes"."""

    def __init__(self, detail: str | None = None, retry_after: float | None = None) -> None:
        message = "Instagram rate limit hit; wait a while (ideally hours) before retrying."
        super().__init__(f"{message} ({detail})" if detail else message, retry_after)


class InstagramSessionCheckFailed(InstagramRateLimited):
    """The saved Instagram session could not be verified (throttled or unreachable).

    Raised instead of falling back to a password login: Instagram answered the
    session check with a throttle ("please wait a few minutes", 401/429) or did
    not answer at all, which says nothing about the session itself. Repeated
    scripted password logins are what triggers checkpoints, so none is tried.
    """

    def __init__(self, detail: str | None = None, retry_after: float | None = None) -> None:
        message = (
            "Instagram did not confirm the saved session (throttled or unreachable). "
            "No password login was attempted, the session file was kept and nothing "
            "was lost; wait a while (ideally hours) before retrying."
        )
        RateLimited.__init__(self, f"{message} ({detail})" if detail else message, retry_after)


class InstagramFeedUnavailable(RateLimited):
    """Instagram refused the saved-feed request with a ``"fail"`` status.

    The session was verified before (no password login is attempted), so the
    answer (typically "We're sorry, but something went wrong") is about the way
    the feed was requested, not about the login. The page is not retried. A
    :class:`RateLimited` subclass: like a throttle it means "stop now, retry
    later", and everything committed so far is kept.

    Attributes:
        feed_api: The ``instagram.feed_api`` that was used (``web``/``iphone``).
    """

    def __init__(self, feed_api: str, detail: str | None = None) -> None:
        self.feed_api = feed_api
        other = "iphone" if feed_api == "web" else "web"
        message = (
            f"Instagram refused the saved feed ({feed_api} API)"
            + (f': "{detail}"' if detail else "")
            + ". The session is fine (no password login was attempted) and nothing stored "
            f'was lost. Retry later, or set instagram.feed_api = "{other}" in the config.'
        )
        super().__init__(message)


class TelegramRateLimited(RateLimited):
    """Telegram FloodWait longer than the client's ``flood_sleep_threshold``."""

    def __init__(self, seconds: float | None = None) -> None:
        wait = f" for {int(seconds)} s" if seconds is not None else ""
        super().__init__(f"Telegram asked to wait{wait} (FloodWait); retry later.", seconds)


# ---------------------------------------------------------------------------
# Progress and stats
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CollectStats:
    """Counters of one collection run (updated live while the run progresses).

    Attributes:
        source: Source collected.
        processed: Items read from the source and queued for writing.
        new: Items inserted.
        updated: Existing items updated.
        known_skipped: Known items skipped without detail work (Instagram).
        media_downloaded: Files downloaded.
        dates_refreshed: Instagram dates re-fetched (``refresh_dates``).
        batches_committed: Committed write transactions.
        last_external_id: External id of the last committed item.
        stopped_reason: Why the run ended (``None`` while running).
        errors: Non-fatal per-item problems (download failures, ...).
    """

    source: Source
    processed: int = 0
    new: int = 0
    updated: int = 0
    known_skipped: int = 0
    media_downloaded: int = 0
    dates_refreshed: int = 0
    batches_committed: int = 0
    last_external_id: str | None = None
    stopped_reason: StopReason | None = None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """Snapshot sent to a :data:`ProgressCallback`.

    Attributes:
        source: Source being collected.
        phase: ``collect`` or ``refresh_dates``.
        processed: Items handled so far (including known/skipped ones).
        new: Items inserted so far (committed).
        updated: Items updated so far (committed).
        known_skipped: Known items skipped so far.
        total: Expected total, if known.
        message: Short human-readable status.
    """

    source: Source
    phase: str
    processed: int
    new: int
    updated: int
    known_skipped: int
    total: int | None = None
    message: str | None = None


ProgressCallback = Callable[[ProgressEvent], None]


def emit(
    progress: ProgressCallback | None,
    stats: CollectStats,
    *,
    phase: str = "collect",
    seen: int | None = None,
    total: int | None = None,
    message: str | None = None,
) -> None:
    """Send a progress snapshot (errors in the callback are logged, not raised)."""
    if progress is None:
        return
    event = ProgressEvent(
        source=stats.source,
        phase=phase,
        processed=seen if seen is not None else stats.processed + stats.known_skipped,
        new=stats.new,
        updated=stats.updated,
        known_skipped=stats.known_skipped,
        total=total,
        message=message,
    )
    try:
        progress(event)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Progress callback failed")


# ---------------------------------------------------------------------------
# Batched writes
# ---------------------------------------------------------------------------


class BatchWriter:
    """Collect :class:`ItemUpsert` objects and write them in transactions.

    Each :meth:`flush` writes the pending items in one ``BEGIN IMMEDIATE``
    transaction; a failure rolls back only that batch.

    Args:
        db: Target database.
        stats: Counters to update (``new``/``updated``/``batches_committed``).
        batch_size: Items per transaction.
    """

    def __init__(self, db: Database, stats: CollectStats, batch_size: int) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self.db = db
        self.stats = stats
        self.batch_size = batch_size
        self.pending: list[ItemUpsert] = []

    def add(self, item: ItemUpsert) -> bool:
        """Queue an item; flush when the batch is full.

        Returns:
            True if a batch was committed.
        """
        self.pending.append(item)
        self.stats.processed += 1
        if len(self.pending) >= self.batch_size:
            self.flush()
            return True
        return False

    def flush(self) -> None:
        """Write all pending items in one transaction (no-op when empty)."""
        if not self.pending:
            return
        batch, self.pending = self.pending, []
        new = updated = 0
        try:
            with self.db.transaction() as conn:
                repo = ItemsRepo(conn)
                for item in batch:
                    _, created = repo.upsert(item)
                    if created:
                        new += 1
                    else:
                        updated += 1
        except BaseException:
            # The whole batch was rolled back.
            self.stats.processed -= len(batch)
            raise
        self.stats.new += new
        self.stats.updated += updated
        self.stats.batches_committed += 1
        self.stats.last_external_id = batch[-1].external_id
        logger.debug(
            "Committed %s batch of %d (new=%d, updated=%d)",
            self.stats.source,
            len(batch),
            new,
            updated,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME = 100


def safe_filename(name: str | None, fallback: str = "file") -> str:
    """Return a portable file name (ASCII letters, digits, ``._-``).

    Accents are transliterated where possible, other characters become ``_``,
    leading dots are removed and the stem is shortened so the whole name stays
    within 100 characters (the extension is kept).

    Args:
        name: Original file name (may be ``None`` or contain path parts).
        fallback: Name used when nothing usable remains.

    Returns:
        Sanitized file name.
    """
    raw = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    ascii_name = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE_CHARS.sub("_", ascii_name).strip("._ ")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned or cleaned.strip("_") == "":
        cleaned = fallback
    if len(cleaned) > _MAX_NAME:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            cleaned = stem[: _MAX_NAME - len(ext) - 1] + "." + ext
        else:
            cleaned = cleaned[:_MAX_NAME]
    return cleaned


def jitter(low: float, high: float) -> float:
    """Return a random delay in ``[low, high]`` (order-insensitive, never negative)."""
    low, high = sorted((max(0.0, float(low)), max(0.0, float(high))))
    return random.uniform(low, high)
