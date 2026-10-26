"""Incremental collector for Telegram "Saved Messages" (Telethon).

Only messages newer than the highest stored message id are read (``min_id``),
oldest first, and written in small transactions, so an interrupted run resumes
where it stopped. ``full=True`` re-reads everything and updates stored items.

Photos and documents are downloaded to
``<downloads_dir>/telegram/YYYY/MM/DD/<message_id>_<name>``; videos, voice
notes and audio are recorded as media rows without download.

Example:
    >>> async with TelegramCollector(db, settings, creds) as collector:
    ...     stats = await collector.collect()
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from postparse.collectors.base import (
    BatchWriter,
    CollectStats,
    ProgressCallback,
    TelegramAuthRequired,
    TelegramRateLimited,
    emit,
    jitter,
    safe_filename,
)
from postparse.collectors.credentials import TelegramCredentials
from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.models import ItemKind, ItemUpsert, MediaInput, MediaType, TelegramDetail
from postparse.core.db.repos import ItemsRepo
from postparse.core.text import extract_hashtags, extract_mentions
from postparse.core.urls import extract_urls

__all__ = [
    "LEGACY_SESSION_NAME",
    "TelegramCollector",
    "TelegramOptions",
    "map_message",
    "resolve_session_path",
]

logger = logging.getLogger(__name__)

#: Session file name used by the old CLI (inside ``<data_dir>/cache``).
LEGACY_SESSION_NAME = "telegram_session.session"
SESSION_NAME = "telegram.session"

ClientFactory = Callable[[Path, int, str, "TelegramOptions"], Any]


def _cfg(config: Any, key: str, default: Any) -> Any:
    """Read ``key`` from a ConfigManager-like object (``None`` -> default)."""
    if config is None:
        return default
    value = config.get(key, default=default)
    return default if value is None else value


@dataclass(frozen=True, slots=True)
class TelegramOptions:
    """Tunables of the Telegram collector (``[telegram]`` config section).

    Attributes:
        batch_size: Messages per write transaction.
        flood_sleep_threshold: FloodWaits up to this many seconds are slept
            through automatically by Telethon; longer ones stop the run.
        max_download_mb: Larger files are recorded without download.
        media_delay_min: Lower bound of the pause after a download (seconds).
        media_delay_max: Upper bound of the pause after a download (seconds).
        media_timeout_image: Download timeout for photos (seconds).
        media_timeout_document: Download timeout for documents (seconds).
        connection_retries: Telethon ``connection_retries``.
        retry_delay: Telethon ``retry_delay``.
        auto_reconnect: Telethon ``auto_reconnect``.
        request_retries: Telethon ``request_retries``.
    """

    batch_size: int = 50
    flood_sleep_threshold: int = 60
    max_download_mb: float = 50.0
    media_delay_min: float = 0.5
    media_delay_max: float = 1.5
    media_timeout_image: float = 30.0
    media_timeout_document: float = 120.0
    connection_retries: int = 5
    retry_delay: int = 1
    auto_reconnect: bool = True
    request_retries: int = 5

    @classmethod
    def from_config(cls, config: Any) -> TelegramOptions:
        """Build options from a ConfigManager (``None``: defaults)."""
        d = cls()
        return cls(
            batch_size=int(_cfg(config, "telegram.batch_size", d.batch_size)),
            flood_sleep_threshold=int(
                _cfg(config, "telegram.flood_sleep_threshold", d.flood_sleep_threshold)
            ),
            max_download_mb=float(_cfg(config, "telegram.max_download_mb", d.max_download_mb)),
            media_delay_min=float(_cfg(config, "telegram.media_delay_min", d.media_delay_min)),
            media_delay_max=float(_cfg(config, "telegram.media_delay_max", d.media_delay_max)),
            media_timeout_image=float(
                _cfg(config, "telegram.media_timeout_image", d.media_timeout_image)
            ),
            media_timeout_document=float(
                _cfg(config, "telegram.media_timeout_document", d.media_timeout_document)
            ),
            connection_retries=int(
                _cfg(config, "telegram.connection_retries", d.connection_retries)
            ),
            retry_delay=int(_cfg(config, "telegram.retry_delay", d.retry_delay)),
            auto_reconnect=bool(_cfg(config, "telegram.auto_reconnect", d.auto_reconnect)),
            request_retries=int(_cfg(config, "telegram.request_retries", d.request_retries)),
        )


def resolve_session_path(settings: Settings, override: str | Path | None = None) -> Path:
    """Return the Telethon session file to use.

    Order: an explicit ``override`` (a path, or a bare name looked up as
    ``<sessions_dir>/<name>.session`` then ``<data_dir>/cache/<name>.session``);
    otherwise ``<sessions_dir>/telegram.session`` if it exists, else the legacy
    CLI session ``<data_dir>/cache/telegram_session.session`` if it exists,
    else the new path (a login creates it). Files are never moved.

    Args:
        settings: Application settings.
        override: ``--session`` value.

    Returns:
        Absolute session file path.
    """
    assert settings.sessions_dir is not None
    legacy_dir = settings.data_dir / "cache"
    if override is not None:
        text = str(override)
        candidate = Path(text).expanduser()
        if candidate.suffix == ".session" or len(candidate.parts) > 1:
            return candidate.resolve()
        name = f"{text}.session"
        for path in (settings.sessions_dir / name, legacy_dir / name):
            if path.exists():
                return path
        return settings.sessions_dir / name
    primary = settings.sessions_dir / SESSION_NAME
    legacy = legacy_dir / LEGACY_SESSION_NAME
    if not primary.exists() and legacy.exists():
        return legacy
    return primary


def _default_client_factory(
    session: Path, api_id: int, api_hash: str, options: TelegramOptions
) -> Any:
    """Create a real :class:`telethon.TelegramClient`."""
    from telethon import TelegramClient

    return TelegramClient(
        str(session),
        api_id,
        api_hash,
        connection_retries=options.connection_retries,
        retry_delay=options.retry_delay,
        auto_reconnect=options.auto_reconnect,
        request_retries=options.request_retries,
        flood_sleep_threshold=options.flood_sleep_threshold,
    )


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MediaPlan:
    """What to do with a message's media.

    Attributes:
        media_type: Media type of the row.
        download: Whether the file should be downloaded.
        filename: Sanitized file name (without the message-id prefix).
        mime: MIME type, if known.
        size_bytes: Size reported by Telegram.
        duration_s: Duration of audio/video.
        timeout: Download timeout (seconds).
    """

    media_type: MediaType
    download: bool
    filename: str
    mime: str | None
    size_bytes: int | None
    duration_s: float | None
    timeout: float


def _attr_name(attr: Any) -> str:
    return type(attr).__name__


def _extension(mime: str | None, default: str = ".bin") -> str:
    if not mime:
        return default
    overrides = {"image/jpeg": ".jpg", "audio/ogg": ".ogg", "video/mp4": ".mp4"}
    return overrides.get(mime) or mimetypes.guess_extension(mime) or default


def plan_media(message: Any, options: TelegramOptions) -> tuple[ItemKind, MediaPlan | None]:
    """Classify a message's media and decide how to store it.

    Args:
        message: Telethon message.
        options: Collector options.

    Returns:
        ``(item kind, media plan or None)``.
    """
    media = getattr(message, "media", None)
    if media is None:
        return "text", None
    media_cls = type(media).__name__
    if media_cls == "MessageMediaPhoto" and getattr(media, "photo", None) is not None:
        size = _photo_size(media.photo)
        return "image", MediaPlan(
            "image", True, "photo.jpg", "image/jpeg", size, None, options.media_timeout_image
        )
    document = getattr(media, "document", None)
    if media_cls == "MessageMediaDocument" and document is not None:
        attrs = list(getattr(document, "attributes", None) or [])
        names = {_attr_name(a) for a in attrs}
        mime = getattr(document, "mime_type", None)
        size = getattr(document, "size", None)
        file_name = next(
            (
                a.file_name
                for a in attrs
                if _attr_name(a) == "DocumentAttributeFilename" and getattr(a, "file_name", None)
            ),
            None,
        )
        duration = next(
            (
                float(a.duration)
                for a in attrs
                if _attr_name(a) in ("DocumentAttributeVideo", "DocumentAttributeAudio")
                and getattr(a, "duration", None) is not None
            ),
            None,
        )
        if "DocumentAttributeAnimated" in names:
            kind: ItemKind = "image"
            media_type: MediaType = "image"
            download = True
            stem = "animation"
        elif "DocumentAttributeSticker" in names:
            kind, media_type, download, stem = "other", "image", True, "sticker"
        elif "DocumentAttributeVideo" in names:
            kind, media_type, download, stem = "video", "video", False, "video"
        elif "DocumentAttributeAudio" in names:
            voice = any(getattr(a, "voice", False) for a in attrs)
            kind, media_type, download = "audio", "audio", False
            stem = "voice" if voice else "audio"
        else:
            kind, media_type, download, stem = "document", "document", True, "document"
        filename = (
            safe_filename(file_name, fallback=stem + _extension(mime))
            if file_name
            else (stem + _extension(mime))
        )
        return kind, MediaPlan(
            media_type, download, filename, mime, size, duration, options.media_timeout_document
        )
    if media_cls in ("MessageMediaWebPage", "MessageMediaEmpty"):
        return "text", None
    return "other", None


def _photo_size(photo: Any) -> int | None:
    """Return the byte size of the largest photo size, if reported."""
    best: int | None = None
    for size in getattr(photo, "sizes", None) or []:
        value = getattr(size, "size", None)
        if value is None and hasattr(size, "sizes"):  # PhotoSizeProgressive
            value = max(size.sizes) if size.sizes else None
        if isinstance(value, int) and (best is None or value > best):
            best = value
    return best


def message_links(message: Any) -> tuple[str, ...]:
    """Return the URLs of a message: URL entities, text-URL entities and plain text URLs."""
    urls: list[str] = []
    entities = getattr(message, "entities", None) or []
    if entities:
        try:
            pairs = message.get_entities_text()
        except Exception:  # pragma: no cover - malformed entities
            pairs = [(e, None) for e in entities]
        for entity, text in pairs:
            name = type(entity).__name__
            if name == "MessageEntityTextUrl" and getattr(entity, "url", None):
                urls.append(entity.url)
            elif name == "MessageEntityUrl" and text:
                urls.append(text if "://" in text else f"https://{text}")
    urls.extend(extract_urls(getattr(message, "message", None) or ""))
    return tuple(dict.fromkeys(urls))


def _peer_id(peer: Any) -> int | None:
    if peer is None:
        return None
    try:
        from telethon import utils

        return int(utils.get_peer_id(peer))
    except Exception:  # pragma: no cover - unexpected peer type
        return None


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def map_message(
    message: Any, chat_id: int, media: tuple[MediaInput, ...] | None, kind: ItemKind
) -> ItemUpsert:
    """Build the :class:`ItemUpsert` for a Telethon message.

    Args:
        message: Telethon message.
        chat_id: Chat id of "Saved Messages" (own user id).
        media: Media rows (``None``: message without media).
        kind: Item kind from :func:`plan_media`.

    Returns:
        Item description (``external_id`` = ``"<chat_id>:<message_id>"``).
    """
    text = getattr(message, "message", None) or None
    fwd = getattr(message, "fwd_from", None)
    fwd_name = getattr(fwd, "from_name", None) if fwd else None
    fwd_id = _peer_id(getattr(fwd, "from_id", None)) if fwd else None
    fwd_post = getattr(fwd, "channel_post", None) if fwd else None
    reply_to = getattr(message, "reply_to", None)
    reply_id = getattr(reply_to, "reply_to_msg_id", None) if reply_to else None
    author = fwd_name or (getattr(fwd, "post_author", None) if fwd else None)
    return ItemUpsert(
        source="telegram",
        external_id=f"{chat_id}:{message.id}",
        kind=kind,
        text=text,
        author=author,
        created_at=_utc(getattr(message, "date", None)),
        detail=TelegramDetail(
            chat_id=chat_id,
            message_id=int(message.id),
            views=getattr(message, "views", None),
            forwards=getattr(message, "forwards", None),
            reply_to_msg_id=reply_id,
            fwd_from_name=fwd_name,
            fwd_from_id=fwd_id,
            fwd_from_post_id=fwd_post,
        ),
        hashtags=tuple(extract_hashtags(text)),
        mentions=tuple(extract_mentions(text)),
        media=media if media is not None else (),
        links=message_links(message),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class TelegramCollector:
    """Collect "Saved Messages" into the schema v2 database.

    Use as an async context manager: entering connects and checks the login.

    Args:
        db: Target database.
        settings: Paths (sessions, downloads).
        credentials: API id/hash and optional phone.
        options: Tunables (default: built-in defaults).
        interactive: Allow Telethon to prompt for phone/code/2FA password in
            the terminal; otherwise an unauthorized session raises
            :class:`TelegramAuthRequired`.
        session: ``--session`` override (see :func:`resolve_session_path`).
        client_factory: Creates the Telethon client (tests pass a fake).
        sleep: Async sleep function (tests pass a no-op).
    """

    def __init__(
        self,
        db: Database,
        settings: Settings,
        credentials: TelegramCredentials,
        options: TelegramOptions | None = None,
        *,
        interactive: bool = True,
        session: str | Path | None = None,
        client_factory: ClientFactory | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.db = db
        self.settings = settings
        self.credentials = credentials
        self.options = options or TelegramOptions()
        self.interactive = interactive
        self.session_path = resolve_session_path(settings, session)
        self._client_factory = client_factory or _default_client_factory
        self._sleep = sleep
        self.client: Any = None
        self.chat_id: int | None = None
        self.stats = CollectStats(source="telegram")

    async def __aenter__(self) -> TelegramCollector:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def connect(self) -> None:
        """Connect and make sure the session is authorized.

        Raises:
            TelegramAuthRequired: Not authorized and not interactive, or the
                interactive login failed.
        """
        assert self.settings.sessions_dir is not None
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Using Telegram session %s", self.session_path)
        self.client = self._client_factory(
            self.session_path, self.credentials.api_id, self.credentials.api_hash, self.options
        )
        try:
            await self.client.connect()
            authorized = await self.client.is_user_authorized()
            if not authorized:
                if not self.interactive:
                    raise TelegramAuthRequired("Session is not authorized.")
                logger.info("Telegram session not authorized; starting interactive login")
                phone = self.credentials.phone
                if phone:
                    await self.client.start(phone=phone)
                else:
                    await self.client.start()
            me = await self.client.get_me()
            if me is None:
                raise TelegramAuthRequired("Login did not complete.")
            self.chat_id = int(me.id)
        except TelegramAuthRequired:
            await self.close()
            raise
        except Exception as exc:
            await self.close()
            raise _translate(exc) from exc

    async def close(self) -> None:
        """Disconnect the client (idempotent)."""
        client, self.client = self.client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # pragma: no cover - best effort
                logger.debug("Telegram disconnect failed", exc_info=True)

    async def collect(
        self,
        *,
        limit: int | None = None,
        full: bool = False,
        progress: ProgressCallback | None = None,
    ) -> CollectStats:
        """Read Saved Messages and upsert them in batches.

        Args:
            limit: Maximum messages to process (``None``: all available).
            full: Re-read all messages (update stored ones) instead of only
                messages newer than the newest stored one.
            progress: Progress callback.

        Returns:
            Run statistics (also available as :attr:`stats` if an error occurs).

        Raises:
            TelegramRateLimited: FloodWait above ``flood_sleep_threshold``.
            TelegramAuthRequired: The session was revoked during the run.
        """
        if self.client is None or self.chat_id is None:
            raise RuntimeError("TelegramCollector is not connected; use 'async with'")
        chat_id = self.chat_id
        min_id = 0
        if not full:
            with self.db.read() as conn:
                min_id = ItemsRepo(conn).max_telegram_message_id(chat_id) or 0
        logger.info(
            "Collecting Telegram saved messages (%s, min_id=%d, limit=%s)",
            "full" if full else "incremental",
            min_id,
            limit,
        )
        writer = BatchWriter(self.db, self.stats, self.options.batch_size)
        kwargs: dict[str, Any] = {"reverse": True, "min_id": min_id}
        if limit is not None:
            kwargs["limit"] = limit
        try:
            async for message in self.client.iter_messages("me", **kwargs):
                if limit is not None and self.stats.processed >= limit:
                    break
                if type(message).__name__ == "MessageService":
                    continue
                item = await self._build_item(message, chat_id)
                writer.add(item)
                emit(progress, self.stats)
        except BaseException as exc:
            # Keep what was already read (the failing message is not included).
            try:
                writer.flush()
            except Exception:
                logger.exception("Could not write the last Telegram batch")
            translated = _translate(exc) if isinstance(exc, Exception) else exc
            if isinstance(translated, (TelegramRateLimited, TelegramAuthRequired)):
                self.stats.stopped_reason = _reason(translated)
            if translated is exc:
                raise
            raise translated from exc
        writer.flush()
        self.stats.stopped_reason = (
            "limit" if limit is not None and self.stats.processed >= limit else "end_of_feed"
        )
        emit(progress, self.stats, message="done")
        return self.stats

    async def _build_item(self, message: Any, chat_id: int) -> ItemUpsert:
        """Map a message, downloading its media if needed."""
        kind, plan = plan_media(message, self.options)
        media: tuple[MediaInput, ...] | None = None
        if plan is not None:
            media = (await self._media_input(message, plan),)
        return map_message(message, chat_id, media, kind)

    async def _media_input(self, message: Any, plan: MediaPlan) -> MediaInput:
        """Download (if planned and allowed) and describe the message's media."""
        base = MediaInput(
            position=0,
            media_type=plan.media_type,
            mime=plan.mime,
            size_bytes=plan.size_bytes,
            duration_s=plan.duration_s,
            transcript_status="none",
        )
        if not plan.download:
            return base
        max_bytes = int(self.options.max_download_mb * 1024 * 1024)
        if plan.size_bytes is not None and plan.size_bytes > max_bytes:
            logger.info(
                "Skipping download of message %s (%d bytes > %d)",
                message.id,
                plan.size_bytes,
                max_bytes,
            )
            return base
        date = _utc(message.date) or datetime.now(UTC)
        relative = Path(
            "telegram", f"{date:%Y}", f"{date:%m}", f"{date:%d}", f"{message.id}_{plan.filename}"
        )
        assert self.settings.downloads_dir is not None
        target = self.settings.downloads_dir / relative
        if not (
            target.exists()
            and target.stat().st_size > 0
            and (plan.size_bytes is None or target.stat().st_size == plan.size_bytes)
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                result = await asyncio.wait_for(
                    self.client.download_media(message, file=str(target)), timeout=plan.timeout
                )
            except TimeoutError:
                self.stats.errors.append(f"message {message.id}: download timed out")
                logger.warning("Download timed out for Telegram message %s", message.id)
                return base
            except Exception as exc:
                translated = _translate(exc)
                if translated is not exc:
                    raise translated from exc
                self.stats.errors.append(f"message {message.id}: download failed: {exc}")
                logger.warning("Download failed for Telegram message %s: %s", message.id, exc)
                return base
            if result is None or not target.exists():
                self.stats.errors.append(f"message {message.id}: nothing downloaded")
                return base
            self.stats.media_downloaded += 1
            await self._sleep(jitter(self.options.media_delay_min, self.options.media_delay_max))
        return MediaInput(
            position=0,
            media_type=plan.media_type,
            local_path=relative.as_posix(),
            mime=plan.mime,
            size_bytes=target.stat().st_size,
            duration_s=plan.duration_s,
            sha256=_sha256(target),
            transcript_status="none",
        )


def _reason(exc: BaseException) -> Any:
    return "rate_limited" if isinstance(exc, TelegramRateLimited) else "auth_required"


_AUTH_ERRORS = {
    "AuthKeyUnregisteredError",
    "AuthKeyDuplicatedError",
    "AuthKeyInvalidError",
    "SessionRevokedError",
    "SessionExpiredError",
    "UserDeactivatedError",
    "UserDeactivatedBanError",
    "PhoneCodeInvalidError",
    "PhoneCodeExpiredError",
    "PhoneNumberInvalidError",
    "PasswordHashInvalidError",
    "SessionPasswordNeededError",
    "ApiIdInvalidError",
}


def _translate(exc: BaseException) -> BaseException:
    """Map Telethon errors to collector errors (other exceptions are returned as-is)."""
    name = type(exc).__name__
    if name in ("FloodWaitError", "FloodPremiumWaitError", "SlowModeWaitError"):
        return TelegramRateLimited(getattr(exc, "seconds", None))
    if name in _AUTH_ERRORS:
        return TelegramAuthRequired(f"Telegram rejected the login ({name}).")
    return exc
