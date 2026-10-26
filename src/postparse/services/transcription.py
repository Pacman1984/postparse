"""Transcription workflow: pending video media -> transcripts in the v2 database.

:class:`TranscriptionService` works through the transcription queue
(``media.transcript_status`` ``pending``/``failed``, see
:meth:`MediaRepo.pending_transcriptions`) one media at a time:

1. create a scratch directory below ``Settings.tmp_dir/transcribe/``;
2. fetch the video (:class:`~postparse.media.fetch.InstagramVideoFetcher`:
   stored URL if fresh, otherwise re-fetch the post; or a kept local file
   below ``downloads_dir`` for media with ``local_path``);
3. probe it (no audio stream -> ``no_audio``);
4. transcribe it (:mod:`postparse.media.transcription`); an empty result
   (no speech) -> ``no_audio``;
5. store the transcript (FTS document refreshed) and mark the media
   ``transcribed`` in one transaction;
6. delete the scratch directory -- always, also after errors and Ctrl-C.

Each media is committed on its own, so an interrupted run keeps its progress.
Failures are recorded with exponential backoff (``mark_failed``); deleted or
private posts and over-long media are marked ``skipped`` with the reason in
``last_error``. Instagram rate limits / missing logins end the run cleanly
(``stopped_reason``), leaving the current media untouched.

Configuration: ``[transcription]`` (see :mod:`postparse.media.options`).

Example:
    >>> service = TranscriptionService(db, settings, config)
    >>> report = service.run(limit=50)
    >>> report.transcribed, report.stopped_reason
    (47, 'done')
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import shutil
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from postparse.collectors.base import AuthRequired, RateLimited
from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.models import Media, Source
from postparse.core.db.repos import ItemsRepo, MediaRepo, TranscriptsRepo
from postparse.media.audio import probe
from postparse.media.fetch import (
    FetchedMedia,
    InstagramVideoFetcher,
    MediaUnavailable,
    RefetchDisabled,
)
from postparse.media.options import BackendKind, TranscriptionOptions
from postparse.media.transcription import (
    BackendUnavailable,
    TranscriptionBackend,
    build_backend,
)

__all__ = [
    "MediaStatus",
    "TranscriptionProgress",
    "TranscriptionReport",
    "TranscriptionService",
    "TranscriptionStopReason",
]

logger = logging.getLogger(__name__)

TranscriptionStopReason = Literal[
    "done", "rate_limited", "auth_required", "backend_unavailable", "interrupted"
]
MediaStatus = Literal["transcribed", "no_audio", "skipped", "failed", "deferred"]

_MAX_ERROR_SAMPLES = 10
_SCRATCH = "transcribe"

FetcherFactory = Callable[[bool], Any]
BackendFactory = Callable[[BackendKind | None], TranscriptionBackend]


@dataclass(slots=True)
class TranscriptionReport:
    """Outcome of one :meth:`TranscriptionService.run`.

    Attributes:
        source: Source filter (``None``: all).
        backend: Backend identifier.
        model: ASR model.
        candidates: Media selected for this run.
        transcribed: Transcripts stored.
        no_audio: Media without audio stream or without speech.
        skipped: Media marked ``skipped`` (deleted/private post, too long).
        failed: Media marked ``failed`` (retried later with backoff).
        deferred: Media left untouched (stale URL with re-fetch disabled).
        refetched: Instagram posts re-fetched for a fresh URL.
        audio_seconds: Duration of the transcribed audio.
        transcribe_seconds: Time spent inside the ASR backend.
        duration_s: Wall time of the run.
        stopped_reason: ``done`` or why the run ended early.
        error: Message of the error that ended the run, if any.
        errors: Up to ten ``"media <id>: message"`` samples.
        item_ids: Items whose media got a transcript.
    """

    source: str | None = None
    backend: str | None = None
    model: str | None = None
    candidates: int = 0
    transcribed: int = 0
    no_audio: int = 0
    skipped: int = 0
    failed: int = 0
    deferred: int = 0
    refetched: int = 0
    audio_seconds: float = 0.0
    transcribe_seconds: float = 0.0
    duration_s: float = 0.0
    stopped_reason: TranscriptionStopReason | None = None
    error: str | None = None
    errors: list[str] = field(default_factory=list)
    item_ids: list[int] = field(default_factory=list)

    @property
    def handled(self) -> int:
        """Media handled (every outcome except ``deferred``)."""
        return self.transcribed + self.no_audio + self.skipped + self.failed

    @property
    def ok(self) -> bool:
        """True if the run was not stopped early."""
        return self.stopped_reason == "done"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        data = dataclasses.asdict(self)
        data["handled"] = self.handled
        return data


@dataclass(frozen=True, slots=True)
class TranscriptionProgress:
    """Progress callback payload (one per handled media).

    Attributes:
        media_id: Media just handled.
        item_id: Its item.
        status: Outcome.
        index: 1-based position in this run.
        total: Media selected for this run.
        report: Live report.
    """

    media_id: int
    item_id: int
    status: MediaStatus
    index: int
    total: int
    report: TranscriptionReport


class TranscriptionService:
    """Transcribe pending media and store the transcripts.

    Args:
        db: Schema v2 database.
        settings: Paths (``tmp_dir`` for scratch files, ``downloads_dir`` for kept files).
        config: ``ConfigManager`` with ``[transcription]`` / ``[instagram]``
            (``None``: defaults).
        options: Explicit options (override ``config``).
        backend_factory: ``kind -> backend`` (tests pass fakes).
        fetcher_factory: ``refetch -> fetcher`` with the
            :class:`InstagramVideoFetcher` interface (tests pass fakes).
        env: Environment for credentials / API keys (default ``os.environ``).
        instagram_overrides: Extra ``InstagramCollector`` kwargs for re-fetches
            (``loader_factory``, ``post_from_shortcode``, ...).
        interactive: Allow an Instagram 2FA prompt during re-fetch login.
        sleep: Sleep function for the re-fetch throttle.
        clock: Current UTC time.
    """

    def __init__(
        self,
        db: Database,
        settings: Settings,
        config: Any = None,
        *,
        options: TranscriptionOptions | None = None,
        backend_factory: BackendFactory | None = None,
        fetcher_factory: FetcherFactory | None = None,
        env: Mapping[str, str] | None = None,
        instagram_overrides: Mapping[str, Any] | None = None,
        interactive: bool = False,
        sleep: Callable[[float], Any] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.config = config
        self.options = options or TranscriptionOptions.from_config(config)
        self.backend_factory = backend_factory
        self.fetcher_factory = fetcher_factory
        self.env = env
        self.instagram_overrides = dict(instagram_overrides or {})
        self.interactive = interactive
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(UTC))
        self._backends: dict[BackendKind | None, TranscriptionBackend] = {}

    # -- factories -----------------------------------------------------------

    def backend(self, kind: BackendKind | None = None) -> TranscriptionBackend:
        """Return the (cached) backend of ``kind`` (``None``: configured default)."""
        kind = kind or self.options.backend
        cached = self._backends.get(kind)
        if cached is None:
            if self.backend_factory is not None:
                cached = self.backend_factory(kind)
            else:
                cached = build_backend(self.options, kind, env=self.env)
            self._backends[kind] = cached
        return cached

    def _make_collector(self) -> Any:
        from postparse.collectors.credentials import instagram_credentials
        from postparse.collectors.instagram import InstagramCollector, InstagramOptions

        return InstagramCollector(
            self.db,
            self.settings,
            instagram_credentials(self.env),
            InstagramOptions.from_config(self.config),
            interactive=self.interactive,
            **self.instagram_overrides,
        )

    def _fetcher(self, refetch: bool) -> Any:
        if self.fetcher_factory is not None:
            return self.fetcher_factory(refetch)
        return InstagramVideoFetcher(
            self.db,
            self.options,
            collector_factory=self._make_collector,
            refetch=refetch,
            sleep=self._sleep,
            clock=self._clock,
        )

    @property
    def scratch_root(self) -> Path:
        """``<tmp_dir>/transcribe``."""
        assert self.settings.tmp_dir is not None
        return self.settings.tmp_dir / _SCRATCH

    # -- queries -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return queue statistics (see :meth:`MediaRepo.queue_stats`)."""
        with self.db.read() as conn:
            stats = MediaRepo(conn).queue_stats(
                max_attempts=self.options.max_attempts, now=self._clock()
            )
        stats["max_attempts"] = self.options.max_attempts
        return stats

    def items_with_fresh_urls(self, source: Source, since: datetime) -> list[int]:
        """Items with pending media whose URL was seen at/after ``since``."""
        with self.db.read() as conn:
            return MediaRepo(conn).items_with_fresh_urls(source, since)

    def _select(
        self, source: Source | None, limit: int | None, item_ids: Sequence[int] | None
    ) -> list[Media]:
        with self.db.read() as conn:
            repo = MediaRepo(conn)
            if item_ids is not None:
                media = repo.transcribable_for_items(item_ids)
                return media[:limit] if limit is not None else media
            return repo.pending_transcriptions(
                source,
                limit if limit is not None else self.options.limit,
                self._clock(),
                max_attempts=self.options.max_attempts,
            )

    # -- run ----------------------------------------------------------------------

    def run(
        self,
        source: Source | None = "instagram",
        limit: int | None = 50,
        backend: BackendKind | None = None,
        refetch: bool = True,
        item_ids: Sequence[int] | None = None,
        progress: Callable[[TranscriptionProgress], None] | None = None,
    ) -> TranscriptionReport:
        """Transcribe due media.

        Args:
            source: Only media of this source (``None``: all sources).
            limit: Maximum media to process (``None``: ``transcription.limit``).
            backend: ``local`` or ``api`` (``None``: ``transcription.backend``).
            refetch: Re-fetch Instagram posts whose URL is missing/stale; when
                ``False`` such media are left pending (``deferred``).
            item_ids: Only media of these items (backoff/attempts are ignored;
                ``source`` is not applied).
            progress: Called after each media.

        Returns:
            Report; partial runs (rate limit, missing login, missing ASR extra)
            also return a report with ``stopped_reason`` set.

        Raises:
            KeyboardInterrupt: Re-raised after the scratch files are deleted
                (everything committed so far is kept).
        """
        started = time.perf_counter()
        report = TranscriptionReport(source=source if item_ids is None else None)
        try:
            asr = self.backend(backend)
            report.backend, report.model = asr.name, asr.model
            asr.check()
        except (BackendUnavailable, ValueError) as exc:
            report.stopped_reason = "backend_unavailable"
            report.error = str(exc)
            report.duration_s = time.perf_counter() - started
            logger.error("Transcription backend unavailable: %s", exc)
            return report

        candidates = self._select(source, limit, item_ids)
        report.candidates = len(candidates)
        if not candidates:
            report.stopped_reason = "done"
            report.duration_s = time.perf_counter() - started
            return report
        logger.info(
            "Transcribing %d media with %s (%s)", len(candidates), asr.name, asr.model
        )

        fetcher = self._fetcher(refetch)
        try:
            for index, media in enumerate(candidates, start=1):
                status = self._process(media, asr, fetcher, report)
                report.refetched = int(getattr(fetcher, "refetches", 0))
                if status is None:  # run stopped
                    break
                if progress is not None:
                    progress(
                        TranscriptionProgress(
                            media.id, media.item_id, status, index, len(candidates), report
                        )
                    )
            else:
                report.stopped_reason = "done"
        except KeyboardInterrupt:
            report.stopped_reason = "interrupted"
            logger.warning("Transcription interrupted; committed media are kept")
            raise
        finally:
            try:
                fetcher.close()
            finally:
                report.refetched = int(getattr(fetcher, "refetches", 0))
                report.duration_s = time.perf_counter() - started
                self._cleanup_scratch_root()
                logger.info(
                    "Transcription %s: transcribed=%d no_audio=%d skipped=%d failed=%d "
                    "deferred=%d refetched=%d audio=%.0fs in %.1fs",
                    report.stopped_reason, report.transcribed, report.no_audio,
                    report.skipped, report.failed, report.deferred, report.refetched,
                    report.audio_seconds, report.duration_s,
                )
        return report

    def _process(
        self, media: Media, asr: TranscriptionBackend, fetcher: Any, report: TranscriptionReport
    ) -> MediaStatus | None:
        """Handle one media; return its outcome or ``None`` when the run must stop."""
        work = self.scratch_root / f"m{media.id}-{uuid.uuid4().hex[:8]}"
        work.mkdir(parents=True, exist_ok=True)
        try:
            try:
                path = self._fetch(media, fetcher, work)
                info = probe(path)
                if not info.has_audio:
                    self._finish(media, "no_audio", "no audio stream", info.duration)
                    report.no_audio += 1
                    return "no_audio"
                max_s = self.options.max_duration_minutes * 60
                if info.duration is not None and info.duration > max_s:
                    reason = f"too long ({info.duration / 60:.0f} min > {max_s / 60:g} min)"
                    self._finish(media, "skipped", reason, info.duration)
                    report.skipped += 1
                    return "skipped"
                asr_started = time.perf_counter()
                result = asr.transcribe(path, work_dir=work)
                report.transcribe_seconds += time.perf_counter() - asr_started
                duration = result.duration if result.duration is not None else info.duration
                if result.is_empty:
                    self._finish(media, "no_audio", "no speech recognized", duration)
                    report.no_audio += 1
                    return "no_audio"
                with self.db.transaction() as conn:
                    TranscriptsRepo(conn).add(
                        media.id,
                        backend=result.backend or asr.name,
                        model=result.model or asr.model,
                        text=result.text,
                        language=result.language,
                        segments=result.segments_json(),
                        duration_s=duration,
                    )
                    repo = MediaRepo(conn)
                    repo.set_duration(media.id, duration)
                    repo.mark_transcribed(media.id, "transcribed")
                report.transcribed += 1
                report.audio_seconds += duration or 0.0
                if media.item_id not in report.item_ids:
                    report.item_ids.append(media.item_id)
                return "transcribed"
            except RefetchDisabled as exc:
                report.deferred += 1
                logger.debug("Media %d deferred: %s", media.id, exc)
                return "deferred"
            except MediaUnavailable as exc:
                self._finish(media, "skipped", str(exc), None)
                report.skipped += 1
                self._sample(report, media, f"skipped: {exc}")
                return "skipped"
            except RateLimited as exc:
                report.stopped_reason = "rate_limited"
                report.error = str(exc)
                logger.warning("Transcription stopped: %s", exc)
                return None
            except AuthRequired as exc:
                report.stopped_reason = "auth_required"
                report.error = str(exc)
                logger.warning("Transcription stopped: %s", exc)
                return None
            except BackendUnavailable as exc:
                report.stopped_reason = "backend_unavailable"
                report.error = str(exc)
                logger.error("Transcription backend unavailable: %s", exc)
                return None
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                with self.db.transaction() as conn:
                    next_at = MediaRepo(conn).mark_failed(
                        media.id,
                        message[:1000],
                        backoff=self.options.backoff,
                        max_backoff=self.options.max_backoff,
                        now=self._clock(),
                    )
                report.failed += 1
                self._sample(report, media, message)
                logger.warning(
                    "Transcription of media %d failed (retry after %s): %s",
                    media.id, next_at.isoformat(timespec="minutes"), message,
                )
                return "failed"
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _fetch(self, media: Media, fetcher: Any, work: Path) -> Path:
        """Return a local file for ``media`` (kept local file or a scratch download)."""
        if media.local_path:
            assert self.settings.downloads_dir is not None
            local = self.settings.downloads_dir / media.local_path
            if local.is_file():
                return local
        with self.db.read() as conn:
            item = ItemsRepo(conn).get(media.item_id)
        if item is None:  # pragma: no cover - cascade deletes media with the item
            raise MediaUnavailable("item no longer exists")
        if item.source != "instagram":
            raise MediaUnavailable(f"no local file and no fetcher for source {item.source!r}")
        fetched: FetchedMedia = fetcher.fetch(media, item.external_id, work)
        return fetched.path

    def _finish(
        self, media: Media, status: str, reason: str | None, duration: float | None
    ) -> None:
        with self.db.transaction() as conn:
            repo = MediaRepo(conn)
            repo.set_duration(media.id, duration)
            repo.mark_transcribed(media.id, status, reason)

    @staticmethod
    def _sample(report: TranscriptionReport, media: Media, message: str) -> None:
        if len(report.errors) < _MAX_ERROR_SAMPLES:
            report.errors.append(f"media {media.id}: {message}")

    def _cleanup_scratch_root(self) -> None:
        """Remove ``<tmp_dir>/transcribe`` when it is empty."""
        with contextlib.suppress(OSError):
            self.scratch_root.rmdir()
