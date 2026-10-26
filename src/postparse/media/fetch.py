"""Fetch Instagram videos into a scratch directory for transcription.

Instagram video URLs are signed CDN links that expire after a while. For a
pending media row the fetcher therefore

1. downloads ``media.remote_url`` directly when it was seen less than
   ``transcription.remote_url_max_age_hours`` ago (default 6 h), otherwise
2. re-fetches the post (``instaloader.Post.from_shortcode``, one Instagram
   request) through a logged-in :class:`~postparse.collectors.instagram.InstagramCollector`,
   stores the fresh ``video_url`` (``MediaRepo.set_remote_url``) and downloads it.

Re-fetches are throttled with a jittered pause (``refetch_min_delay`` ..
``refetch_max_delay``, default 20-60 s) and share one login per fetcher. Rate
limits and invalid sessions surface as :class:`InstagramRateLimited` /
:class:`InstagramAuthRequired`, which end the whole run. Deleted or inaccessible
posts (``QueryReturnedNotFoundException`` / ``ProfileNotExistsException``, or a
post without a video at the media position) raise :class:`MediaUnavailable`
(the caller marks the media ``skipped``). Every other re-fetch failure --
including instaloader's ``BadResponseException("... metadata failed")``, which
Instagram also returns when it soft-blocks a session -- raises
:class:`RefetchError` (retried with backoff; the service stops the run after
several in a row, see ``max_consecutive_refetch_failures``).

Downloads are streamed with a size cap and a timeout. Nothing is kept: the
caller deletes the scratch directory after transcription.

Example:
    >>> with InstagramVideoFetcher(db, options, collector_factory=make_collector) as fetcher:
    ...     fetched = fetcher.fetch(media, "C0dEx", work_dir)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from postparse.collectors.base import CollectorError, jitter
from postparse.core.db import Database
from postparse.core.db.models import Media
from postparse.core.db.repos import MediaRepo
from postparse.media.options import TranscriptionOptions

__all__ = [
    "FetchError",
    "FetchedMedia",
    "InstagramVideoFetcher",
    "MediaUnavailable",
    "RefetchDisabled",
    "RefetchError",
    "video_url_for",
]

logger = logging.getLogger(__name__)

#: instaloader errors meaning the post is gone or not accessible for this account.
_UNAVAILABLE_ERRORS = ("QueryReturnedNotFoundException", "ProfileNotExistsException")
_EXPIRED_STATUS = (403, 404, 410)
_CHUNK = 1 << 16
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)

CollectorFactory = Callable[[], Any]


class FetchError(RuntimeError):
    """Download or re-fetch failed (the media is retried later with backoff)."""


class RefetchError(FetchError):
    """Re-fetching the post from Instagram failed (possibly a soft block; retry later)."""


class MediaUnavailable(RuntimeError):
    """The post/video no longer exists or is not accessible (mark ``skipped``)."""


class RefetchDisabled(RuntimeError):
    """The stored URL is missing/stale and re-fetching is disabled (leave pending)."""


class _UrlExpired(FetchError):
    """The CDN refused a stored URL (expired signature)."""


@dataclass(frozen=True, slots=True)
class FetchedMedia:
    """A media file ready for transcription.

    Attributes:
        path: Local file.
        refetched: The post was re-fetched from Instagram for a fresh URL.
        size_bytes: Downloaded bytes.
    """

    path: Path
    refetched: bool = False
    size_bytes: int = 0


def video_url_for(post: Any, position: int) -> str | None:
    """Return the video URL of ``post`` at media ``position``.

    Args:
        post: instaloader ``Post`` with full metadata.
        position: ``media.position`` (0 for single videos, the child index for sidecars).

    Returns:
        URL, or ``None`` when there is no video at that position.
    """
    if getattr(post, "typename", None) == "GraphSidecar":
        nodes = list(post.get_sidecar_nodes())
        if 0 <= position < len(nodes) and nodes[position].is_video:
            return nodes[position].video_url or None
        return None
    if position != 0 or not getattr(post, "is_video", False):
        return None
    return post.video_url or None


class InstagramVideoFetcher:
    """Download Instagram videos, re-fetching posts whose URL expired.

    Args:
        db: Database (fresh URLs are stored immediately).
        options: Transcription options (URL age, delays, size cap, timeout).
        collector_factory: Returns a not-yet-entered ``InstagramCollector``;
            called once, on the first re-fetch (one login per fetcher).
        refetch: Allow re-fetching posts; when ``False`` a missing/stale URL
            raises :class:`RefetchDisabled`.
        http_client: ``httpx.Client`` for downloads (tests pass a mock transport).
        sleep: Sleep function for the re-fetch throttle.
        clock: Returns the current UTC time.
    """

    def __init__(
        self,
        db: Database,
        options: TranscriptionOptions | None = None,
        *,
        collector_factory: CollectorFactory | None = None,
        refetch: bool = True,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], Any] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db = db
        self.options = options or TranscriptionOptions()
        self.collector_factory = collector_factory
        self.refetch = refetch
        self._http = http_client
        self._owns_http = http_client is None
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(UTC))
        self._collector: Any = None
        self._refetch_attempts = 0
        #: Successful re-fetches.
        self.refetches = 0
        #: Bytes downloaded.
        self.bytes_downloaded = 0

    # -- lifecycle -----------------------------------------------------------

    def __enter__(self) -> InstagramVideoFetcher:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Save the Instagram session (if logged in) and close the HTTP client."""
        if self._collector is not None:
            try:
                self._collector.__exit__(None, None, None)
            except Exception:
                logger.warning("Could not close the Instagram session", exc_info=True)
            self._collector = None
        if self._http is not None and self._owns_http:
            self._http.close()
            self._http = None

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                timeout=self.options.download_timeout,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            )
            self._owns_http = True
        return self._http

    # -- fetching --------------------------------------------------------------

    def is_fresh(self, media: Media) -> bool:
        """True if the stored URL is recent enough to download without re-fetch."""
        if not media.remote_url or media.remote_url_seen_at is None:
            return False
        return self._clock() - media.remote_url_seen_at < self.options.remote_url_max_age

    def fetch(self, media: Media, shortcode: str, dest_dir: Path) -> FetchedMedia:
        """Download the video of ``media`` into ``dest_dir``.

        Args:
            media: Pending media row (Instagram video).
            shortcode: Shortcode of the owning post.
            dest_dir: Existing scratch directory.

        Returns:
            Downloaded file.

        Raises:
            RefetchDisabled: Re-fetch needed but disabled.
            MediaUnavailable: Post deleted / inaccessible / no video at the position.
            FetchError: Download or re-fetch failed (retry later).
            InstagramRateLimited: Instagram rate-limited the re-fetch (stop the run).
            InstagramAuthRequired: No valid Instagram session (stop the run).
        """
        target = Path(dest_dir) / f"{shortcode}_{media.position}.mp4"
        if self.is_fresh(media):
            assert media.remote_url is not None
            try:
                size = self._download(media.remote_url, target)
                return FetchedMedia(target, refetched=False, size_bytes=size)
            except _UrlExpired as exc:
                if not self.refetch:
                    raise FetchError(f"Stored video URL was refused: {exc}") from exc
                logger.info("Stored URL of %s refused (%s); re-fetching the post", shortcode, exc)
        elif not self.refetch:
            raise RefetchDisabled(
                f"{shortcode}: video URL missing or older than "
                f"{self.options.remote_url_max_age_hours:g} h"
            )
        url = self._refetch_url(media, shortcode)
        try:
            size = self._download(url, target)
        except _UrlExpired as exc:
            raise FetchError(f"Fresh video URL was refused: {exc}") from exc
        return FetchedMedia(target, refetched=True, size_bytes=size)

    def _collector_instance(self) -> Any:
        if self._collector is None:
            if self.collector_factory is None:
                raise FetchError("Re-fetch needed but no Instagram login is configured")
            collector = self.collector_factory()
            collector.__enter__()
            self._collector = collector
        return self._collector

    def _refetch_url(self, media: Media, shortcode: str) -> str:
        """Re-fetch the post and store the fresh video URL."""
        collector = self._collector_instance()
        if self._refetch_attempts:
            delay = jitter(self.options.refetch_min_delay, self.options.refetch_max_delay)
            logger.debug("Waiting %.1fs before the next Instagram re-fetch", delay)
            self._sleep(delay)
        self._refetch_attempts += 1
        try:
            post = collector.fetch_post(shortcode)
            url = video_url_for(post, media.position)
        except Exception as exc:
            name = type(exc).__name__
            if isinstance(exc, CollectorError):
                raise
            if name in _UNAVAILABLE_ERRORS:
                raise MediaUnavailable(f"post not available ({name})") from exc
            # Includes BadResponseException("... metadata failed"): Instagram sends it
            # for deleted posts *and* for soft-blocked sessions, so it is retried.
            raise RefetchError(f"Re-fetch of {shortcode} failed: {name}: {exc}") from exc
        if not url:
            raise MediaUnavailable(f"post has no video at position {media.position}")
        with self.db.transaction() as conn:
            MediaRepo(conn).set_remote_url(media.id, url, self._clock())
        self.refetches += 1
        logger.info("Re-fetched %s for a fresh video URL", shortcode)
        return url

    def _download(self, url: str, target: Path) -> int:
        """Stream ``url`` to ``target`` with the size cap; return the byte count."""
        cap = self.options.max_download_bytes
        written = 0
        try:
            with self._client().stream("GET", url) as response:
                if response.status_code in _EXPIRED_STATUS:
                    raise _UrlExpired(f"HTTP {response.status_code}")
                if response.status_code >= 400:
                    raise FetchError(f"Video download failed: HTTP {response.status_code}")
                length = response.headers.get("content-length")
                if length and length.isdigit() and int(length) > cap:
                    raise FetchError(
                        f"Video is too large ({int(length) / 1e6:.0f} MB > "
                        f"{self.options.max_download_mb:g} MB)"
                    )
                with target.open("wb") as handle:
                    for chunk in response.iter_bytes(_CHUNK):
                        written += len(chunk)
                        if written > cap:
                            raise FetchError(
                                f"Video exceeds the size cap of {self.options.max_download_mb:g} MB"
                            )
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            target.unlink(missing_ok=True)
            raise FetchError(f"Video download failed: {type(exc).__name__}: {exc}") from exc
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        if written == 0:
            target.unlink(missing_ok=True)
            raise FetchError("Video download returned no data")
        self.bytes_downloaded += written
        return written
