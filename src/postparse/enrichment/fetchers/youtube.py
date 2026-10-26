"""YouTube videos: oEmbed + yt-dlp metadata + best-effort transcript.

For a video link (``watch?v=``, ``youtu.be/``, ``/shorts/``, ``/embed/``,
``/live/``) the fetcher combines

1. **oEmbed** (``https://www.youtube.com/oembed``): title and channel, one
   cheap request;
2. **yt-dlp** (optional extra ``youtube``; ``skip_download``): description,
   upload date, duration, tags, categories, chapters. Missing yt-dlp or a
   yt-dlp failure only reduces the metadata;
3. **youtube-transcript-api**: a transcript, preferring
   ``transcript_languages`` (default ``de``, ``en``) and falling back to any
   available language. No transcript is not an error.

The stored text is the description, the chapter list and the transcript. The
result is ``ok`` when at least a title was found. Non-video YouTube URLs
(channels, playlists) are handled by the generic fetcher.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from postparse.core.db.models import Link
from postparse.enrichment.fetchers.base import FetchResult
from postparse.enrichment.options import EnrichmentOptions

__all__ = [
    "TranscriptResult",
    "YouTubeFetcher",
    "default_transcript_fetcher",
    "default_ytdlp_extract",
    "youtube_video_id",
    "ytdlp_available",
]

logger = logging.getLogger(__name__)

OEMBED_URL = "https://www.youtube.com/oembed"
_YOUTUBE_DOMAINS = frozenset({"youtube.com", "youtu.be", "youtube-nocookie.com"})
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PATH_PREFIXES = ("shorts", "embed", "live", "v", "e")

#: ``(language_code, text, is_generated)`` of a transcript.
TranscriptResult = tuple[str, str, bool]
YtDlpExtract = Callable[[str], dict[str, Any] | None]
TranscriptFetcher = Callable[[str, Sequence[str]], TranscriptResult | None]

_YTDLP_FIELDS = (
    "title",
    "channel",
    "channel_id",
    "uploader",
    "upload_date",
    "duration",
    "view_count",
    "like_count",
    "categories",
    "tags",
    "language",
    "is_live",
    "availability",
)


def youtube_video_id(url: str) -> str | None:
    """Return the 11-character video id of a YouTube URL, or ``None``."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    segments = [s for s in parts.path.split("/") if s]
    candidate: str | None = None
    if host.endswith("youtu.be"):
        candidate = segments[0] if segments else None
    elif segments and segments[0] == "watch":
        candidate = (parse_qs(parts.query).get("v") or [None])[0]
    elif len(segments) >= 2 and segments[0] in _PATH_PREFIXES:
        candidate = segments[1]
    return candidate if candidate and _ID_RE.match(candidate) else None


def ytdlp_available() -> bool:
    """True if the optional yt-dlp dependency is installed."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


class _YtDlpLogger:
    """Route yt-dlp output to :mod:`logging` at debug level."""

    def debug(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        logger.debug("yt-dlp warning: %s", msg)

    def error(self, msg: str) -> None:
        logger.debug("yt-dlp error: %s", msg)


def default_ytdlp_extract(url: str, *, timeout: float = 15.0) -> dict[str, Any] | None:
    """Extract video metadata with yt-dlp (no download); ``None`` if yt-dlp is missing."""
    try:
        import yt_dlp
    except ImportError:
        return None
    params = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": timeout,
        "logger": _YtDlpLogger(),
        "extract_flat": False,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(params) as ydl:
        info = ydl.extract_info(url, download=False)
        return ydl.sanitize_info(info) if info else None


def default_transcript_fetcher(video_id: str, languages: Sequence[str]) -> TranscriptResult | None:
    """Fetch a transcript with youtube-transcript-api (preferred languages, then any)."""
    from youtube_transcript_api import NoTranscriptFound, YouTubeTranscriptApi

    transcripts = YouTubeTranscriptApi().list(video_id)
    try:
        transcript = transcripts.find_transcript(list(languages))
    except NoTranscriptFound:
        available = list(transcripts)
        if not available:
            return None
        manual = [t for t in available if not t.is_generated]
        transcript = (manual or available)[0]
    fetched = transcript.fetch()
    text = " ".join(snippet.text.strip() for snippet in fetched if snippet.text.strip())
    return (transcript.language_code, text, bool(transcript.is_generated)) if text else None


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _format_upload_date(value: str | None) -> str | None:
    if value and len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value or None


class YouTubeFetcher:
    """oEmbed + yt-dlp + transcript fetcher for YouTube videos.

    Args:
        options: Timeouts and transcript languages.
        ytdlp_extract: ``url -> info dict`` (default: yt-dlp, ``None`` result if
            not installed; tests pass fakes).
        transcript_fetcher: ``(video_id, languages) -> (lang, text, generated)``.
    """

    name = "youtube"
    uses_network = True

    def __init__(
        self,
        options: EnrichmentOptions | None = None,
        *,
        ytdlp_extract: YtDlpExtract | None = None,
        transcript_fetcher: TranscriptFetcher | None = None,
    ) -> None:
        self.options = options or EnrichmentOptions()
        self._ytdlp = ytdlp_extract or (
            lambda url: default_ytdlp_extract(url, timeout=self.options.timeout)
        )
        self._transcripts = transcript_fetcher or default_transcript_fetcher

    def matches(self, link: Link) -> bool:
        """YouTube video links (channels/playlists go to the generic fetcher)."""
        return link.domain in _YOUTUBE_DOMAINS and youtube_video_id(link.url) is not None

    async def _oembed(
        self, client: httpx.AsyncClient, watch_url: str
    ) -> tuple[dict[str, Any] | None, int | None]:
        try:
            response = await client.get(OEMBED_URL, params={"url": watch_url, "format": "json"})
        except httpx.HTTPError as exc:
            logger.debug("YouTube oEmbed failed for %s: %s", watch_url, exc)
            return None, None
        if response.status_code != 200:
            return None, response.status_code
        try:
            data = response.json()
        except ValueError:
            return None, response.status_code
        return (data if isinstance(data, dict) else None), response.status_code

    async def fetch(self, link: Link, client: httpx.AsyncClient) -> FetchResult:
        """Fetch title, channel, description, chapters and transcript of a video."""
        video_id = youtube_video_id(link.url)
        assert video_id is not None
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        metadata: dict[str, Any] = {"video_id": video_id, "url": watch_url}

        oembed, oembed_status = await self._oembed(client, watch_url)
        metadata["oembed_status"] = oembed_status
        title: str | None = None
        if oembed:
            title = oembed.get("title") or None
            for key, target in (
                ("author_name", "channel"),
                ("author_url", "channel_url"),
                ("thumbnail_url", "thumbnail"),
            ):
                if oembed.get(key):
                    metadata[target] = oembed[key]

        description, chapters = None, []
        try:
            info = await asyncio.to_thread(self._ytdlp, watch_url)
        except Exception as exc:  # yt-dlp raises DownloadError & friends
            info = None
            metadata["ytdlp_error"] = f"{type(exc).__name__}: {exc}"[:300]
            logger.debug("yt-dlp failed for %s: %s", watch_url, exc)
        if info is None and "ytdlp_error" not in metadata and not ytdlp_available():
            metadata["ytdlp"] = "not installed (install the 'youtube' extra)"
        if info:
            for key in _YTDLP_FIELDS:
                value = info.get(key)
                if value not in (None, "", []):
                    metadata[key] = value
            metadata["upload_date"] = _format_upload_date(info.get("upload_date"))
            title = title or info.get("title") or None
            description = (info.get("description") or "").strip() or None
            chapters = [
                {"start": c.get("start_time"), "end": c.get("end_time"), "title": c.get("title")}
                for c in info.get("chapters") or []
                if isinstance(c, dict)
            ]
            if chapters:
                metadata["chapters"] = chapters

        transcript: TranscriptResult | None = None
        if self.options.youtube_transcripts:
            try:
                transcript = await asyncio.to_thread(
                    self._transcripts, video_id, self.options.transcript_languages
                )
            except Exception as exc:  # no transcript / blocked: not an error
                metadata["transcript_error"] = type(exc).__name__
                logger.debug("No transcript for %s: %s", video_id, exc)
        if transcript is not None:
            metadata["transcript_language"] = transcript[0]
            metadata["transcript_generated"] = transcript[2]

        if not title:
            reason = (
                f"video unavailable (oEmbed HTTP {oembed_status})"
                if oembed_status
                else "video metadata unavailable"
            )
            result = FetchResult.failed(reason, http_status=oembed_status, **metadata)
            result.fetcher = self.name
            return result

        parts: list[str] = []
        if description:
            parts.append(description)
        if chapters:
            parts.append(
                "Chapters:\n"
                + "\n".join(f"{_format_duration(c['start'] or 0)} {c['title']}" for c in chapters)
            )
        if transcript is not None:
            parts.append(f"Transcript ({transcript[0]}):\n{transcript[1]}")
        result = FetchResult(
            "ok",
            fetcher=self.name,
            http_status=oembed_status,
            title=title,
            text="\n\n".join(parts) or None,
            metadata=metadata,
        )
        return result
