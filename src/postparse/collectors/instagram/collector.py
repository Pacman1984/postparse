"""Incremental collector for the Instagram saved feed (instaloader).

The saved feed is newest-first. The collector walks it and stops after
``stop_after_known`` consecutive posts that are already stored, so a routine
run costs only a page or two of feed requests. New posts are mapped from the
feed node itself (no per-post request), throttled with a jittered pause and
written in batches of ``batch_size`` (one transaction each).

Nothing is downloaded and no expiring image CDN URL is stored; for videos a
pending-transcription media row is created (with the video URL only when the
feed node already carries it).

Example:
    >>> with InstagramCollector(db, settings, creds) as collector:
    ...     stats = collector.collect_saved(stop_after_known=20)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from postparse.collectors.base import (
    AuthRequired,
    BatchWriter,
    CollectorError,
    CollectStats,
    InstagramAuthRequired,
    InstagramRateLimited,
    ProgressCallback,
    emit,
    jitter,
)
from postparse.collectors.credentials import InstagramCredentials
from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.models import InstagramDetail, ItemKind, ItemUpsert, MediaInput
from postparse.core.db.repos import ItemsRepo
from postparse.core.text import extract_hashtags, extract_mentions

__all__ = [
    "LEGACY_SESSION_FILE",
    "InstagramCollector",
    "InstagramOptions",
    "map_post",
    "resolve_session_path",
]

logger = logging.getLogger(__name__)

#: Session file written by the old CLI (relative to the working directory).
LEGACY_SESSION_FILE = "instagram_session"

LoaderFactory = Callable[["InstagramOptions"], Any]
SavedPostsFn = Callable[[Any], Iterable[Any]]
PostFromShortcode = Callable[[Any, str], Any]
PromptFn = Callable[[str], str]

_TYPENAME_KIND: dict[str, ItemKind] = {
    "GraphImage": "image",
    "GraphVideo": "video",
    "GraphSidecar": "carousel",
}


def _cfg(config: Any, key: str, default: Any) -> Any:
    """Read ``key`` from a ConfigManager-like object (``None`` -> default)."""
    if config is None:
        return default
    value = config.get(key, default=default)
    return default if value is None else value


@dataclass(frozen=True, slots=True)
class InstagramOptions:
    """Tunables of the Instagram collector (``[instagram]`` config section).

    Attributes:
        min_delay: Lower bound of the pause between new posts (seconds).
        max_delay: Upper bound of the pause between new posts (seconds).
        refresh_min_delay: Lower bound of the pause between date refreshes.
        refresh_max_delay: Upper bound of the pause between date refreshes.
        request_timeout: instaloader request timeout (seconds).
        max_connection_attempts: instaloader connection attempts.
        user_agent: Custom user agent (``None``: instaloader default).
    """

    min_delay: float = 5.0
    max_delay: float = 15.0
    refresh_min_delay: float = 5.0
    refresh_max_delay: float = 15.0
    request_timeout: float = 30.0
    max_connection_attempts: int = 3
    user_agent: str | None = None

    @classmethod
    def from_config(cls, config: Any) -> InstagramOptions:
        """Build options from a ConfigManager (``None``: defaults)."""
        d = cls()
        min_delay = float(_cfg(config, "instagram.default_min_delay", d.min_delay))
        max_delay = float(_cfg(config, "instagram.default_max_delay", d.max_delay))
        return cls(
            min_delay=min_delay,
            max_delay=max_delay,
            refresh_min_delay=float(_cfg(config, "instagram.refresh_min_delay", min_delay)),
            refresh_max_delay=float(_cfg(config, "instagram.refresh_max_delay", max_delay)),
            request_timeout=float(_cfg(config, "instagram.request_timeout", d.request_timeout)),
            max_connection_attempts=int(
                _cfg(config, "instagram.max_connection_attempts", d.max_connection_attempts)
            ),
            user_agent=_cfg(config, "instagram.user_agent", None),
        )


def resolve_session_path(
    settings: Settings, username: str, override: str | Path | None = None
) -> tuple[Path, Path]:
    """Return ``(session file to load, session file to save)``.

    Order: an explicit ``override`` (used for both); otherwise
    ``<sessions_dir>/instagram_<username>`` if it exists, else the legacy
    ``./instagram_session`` if it exists. Sessions are always saved to the
    new location (the legacy file is left untouched).

    Args:
        settings: Application settings.
        username: Instagram username.
        override: ``--session`` value (file path).

    Returns:
        ``(load_path, save_path)``.
    """
    assert settings.sessions_dir is not None
    if override is not None:
        path = Path(override).expanduser().resolve()
        return path, path
    primary = settings.sessions_dir / f"instagram_{username}"
    legacy = Path.cwd() / LEGACY_SESSION_FILE
    if not primary.exists() and legacy.exists():
        return legacy, primary
    return primary, primary


def _default_loader_factory(options: InstagramOptions) -> Any:
    """Create a real :class:`instaloader.Instaloader` with all downloads disabled."""
    import instaloader

    kwargs: dict[str, Any] = {
        "quiet": True,
        "download_pictures": False,
        "download_videos": False,
        "download_video_thumbnails": False,
        "download_geotags": False,
        "download_comments": False,
        "save_metadata": False,
        "compress_json": False,
        "max_connection_attempts": options.max_connection_attempts,
        "request_timeout": options.request_timeout,
        # The iPhone endpoint costs one extra request per post.
        "iphone_support": False,
    }
    if options.user_agent:
        kwargs["user_agent"] = options.user_agent
    return instaloader.Instaloader(**kwargs)


def _default_saved_posts(loader: Any) -> Iterable[Any]:
    """Iterate the logged-in user's saved posts (newest saved first)."""
    import instaloader

    return instaloader.Profile.own_profile(loader.context).get_saved_posts()


def _default_post_from_shortcode(loader: Any, shortcode: str) -> Any:
    import instaloader

    return instaloader.Post.from_shortcode(loader.context, shortcode)


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def _node(post: Any) -> dict[str, Any]:
    """Return the raw feed node of an instaloader post (empty if unavailable)."""
    node = getattr(post, "_node", None)
    return node if isinstance(node, dict) else {}


def _count(node: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = node.get(key)
        if isinstance(value, dict) and isinstance(value.get("count"), int):
            return value["count"]
    return None


def _caption(node: dict[str, Any]) -> str | None:
    edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
    if edges:
        text = (edges[0].get("node") or {}).get("text")
        return text if text else None
    caption = node.get("caption")
    if isinstance(caption, dict):  # iPhone-style struct
        caption = caption.get("text")
    return caption or None


def post_date_utc(post: Any) -> datetime | None:
    """Return the post's publication time as an aware UTC datetime.

    Reads the feed node (no request); falls back to ``post.date_utc``.
    """
    node = _node(post)
    ts = node.get("date", node.get("taken_at_timestamp"))
    if isinstance(ts, int | float):
        return datetime.fromtimestamp(ts, UTC)
    value = getattr(post, "date_utc", None)
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return None


def map_post(post: Any, rank: int | None) -> ItemUpsert:
    """Build the :class:`ItemUpsert` of a saved post from its feed node only.

    No property that could trigger an extra instaloader request is used.

    Args:
        post: instaloader ``Post`` (from the saved-posts iterator).
        rank: Position in the saved feed (0 = most recently saved).

    Returns:
        Item description (``external_id`` = shortcode). Video posts get a
        pending-transcription media row; carousel video children get one per
        child (position = child index). No image URLs are stored.
    """
    node = _node(post)
    shortcode = node.get("shortcode") or post.shortcode
    typename = node.get("__typename")
    kind = _TYPENAME_KIND.get(typename or "")
    if kind is None:
        kind = "video" if node.get("is_video") else "other"
    caption = _caption(node)
    owner = node.get("owner") or {}
    owner_id = owner.get("id")
    media: list[MediaInput] = []
    if kind == "video":
        media.append(_video_media(0, node))
    elif kind == "carousel":
        edges = (node.get("edge_sidecar_to_children") or {}).get("edges") or []
        for index, edge in enumerate(edges):
            child = edge.get("node") or {}
            if child.get("is_video"):
                media.append(_video_media(index, child))
    return ItemUpsert(
        source="instagram",
        external_id=shortcode,
        kind=kind,
        text=caption,
        author=owner.get("username") or None,
        url=f"https://www.instagram.com/p/{shortcode}/",
        created_at=post_date_utc(post),
        detail=InstagramDetail(
            shortcode=shortcode,
            owner_id=int(owner_id) if owner_id is not None else None,
            typename=typename,
            likes=_count(node, "edge_media_preview_like", "edge_liked_by"),
            comments=_count(node, "edge_media_to_comment", "edge_media_to_parent_comment"),
            saved_feed_rank=rank,
            date_status="verified" if post_date_utc(post) is not None else None,
        ),
        hashtags=tuple(extract_hashtags(caption)) if caption is not None else None,
        mentions=tuple(extract_mentions(caption)) if caption is not None else None,
        media=tuple(media) if media else None,
    )


def _video_media(position: int, node: dict[str, Any]) -> MediaInput:
    duration = node.get("video_duration")
    return MediaInput(
        position=position,
        media_type="video",
        remote_url=node.get("video_url") or None,
        duration_s=float(duration) if isinstance(duration, int | float) else None,
        transcript_status="pending",
    )


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------

_CHALLENGE_MARKERS = ("checkpoint", "challenge", "feedback_required", "login_required")
_RATE_MARKERS = ("429", "too many requests", "please wait a few minutes", "rate limit")


def translate_error(exc: BaseException) -> BaseException:
    """Map instaloader exceptions to collector errors (others are returned as-is)."""
    if isinstance(exc, CollectorError):
        return exc
    name = type(exc).__name__
    text = str(exc).lower()
    if name == "TooManyRequestsException" or (
        name in ("ConnectionException", "QueryReturnedBadRequestException")
        and any(marker in text for marker in _RATE_MARKERS)
    ):
        return InstagramRateLimited(str(exc) or None)
    if name == "TwoFactorAuthRequiredException":
        return InstagramAuthRequired("Two-factor code required.")
    if name == "BadCredentialsException":
        return InstagramAuthRequired("Instagram rejected the password or 2FA code.")
    if name in ("LoginRequiredException", "LoginException") or (
        name in ("ConnectionException", "QueryReturnedBadRequestException",
                 "QueryReturnedForbiddenException")
        and any(marker in text for marker in _CHALLENGE_MARKERS)
    ):
        return InstagramAuthRequired("Instagram requires a confirmation or a new login.")
    return exc


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class InstagramCollector:
    """Collect saved Instagram posts into the schema v2 database.

    Use as a context manager: entering loads/validates the session (logging in
    if needed), leaving saves the session.

    Args:
        db: Target database.
        settings: Paths (sessions).
        credentials: Username and optional password.
        options: Tunables (default: built-in defaults).
        interactive: Allow prompting for a two-factor code; otherwise a 2FA
            challenge raises :class:`InstagramAuthRequired`.
        session: ``--session`` override (file path).
        loader_factory: Creates the instaloader instance (tests pass a fake).
        saved_posts: Returns the saved-post iterator for a loader.
        post_from_shortcode: Fetches one post (``refresh_dates``).
        prompt: Reads the 2FA code in interactive mode (default ``input``).
        sleep: Sleep function (tests pass a no-op).
    """

    def __init__(
        self,
        db: Database,
        settings: Settings,
        credentials: InstagramCredentials,
        options: InstagramOptions | None = None,
        *,
        interactive: bool = True,
        session: str | Path | None = None,
        loader_factory: LoaderFactory | None = None,
        saved_posts: SavedPostsFn | None = None,
        post_from_shortcode: PostFromShortcode | None = None,
        prompt: PromptFn | None = None,
        sleep: Callable[[float], Any] = time.sleep,
    ) -> None:
        self.db = db
        self.settings = settings
        self.credentials = credentials
        self.options = options or InstagramOptions()
        self.interactive = interactive
        self.load_path, self.save_path = resolve_session_path(
            settings, credentials.username, session
        )
        self._loader_factory = loader_factory or _default_loader_factory
        self._saved_posts = saved_posts or _default_saved_posts
        self._post_from_shortcode = post_from_shortcode or _default_post_from_shortcode
        self._prompt = prompt or input
        self._sleep = sleep
        self.loader: Any = None
        self.logged_in = False
        self.stats = CollectStats(source="instagram")

    # -- session ---------------------------------------------------------

    def __enter__(self) -> InstagramCollector:
        self.login()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.save_session()

    def login(self) -> None:
        """Load the saved session or log in.

        Raises:
            InstagramAuthRequired: No valid session and the login failed or
                needs user interaction that is not allowed.
            InstagramRateLimited: Instagram rate-limited the login.
        """
        self.loader = self._loader_factory(self.options)
        username = self.credentials.username
        if self.load_path.exists():
            logger.info("Loading Instagram session from %s", self.load_path)
            try:
                self.loader.load_session_from_file(username, str(self.load_path))
                current = self.loader.test_login()
            except Exception as exc:
                translated = translate_error(exc)
                if isinstance(translated, InstagramRateLimited):
                    raise translated from exc
                logger.warning("Instagram session could not be used: %s", type(exc).__name__)
                current = None
            if current and current.lower() == username.lower():
                self.logged_in = True
                logger.info("Instagram session is valid")
                return
            logger.info("Instagram session is no longer valid")
        else:
            logger.info("No Instagram session file at %s", self.load_path)
        if not self.credentials.password:
            raise InstagramAuthRequired(
                "No valid session and INSTAGRAM_PASSWORD is not set."
            )
        self._password_login()

    def _password_login(self) -> None:
        """Log in with the password (and a 2FA code when interactive)."""
        assert self.credentials.password is not None
        logger.info("Logging in to Instagram as %s", self.credentials.username)
        try:
            self.loader.login(self.credentials.username, self.credentials.password)
        except Exception as exc:
            if type(exc).__name__ != "TwoFactorAuthRequiredException":
                raise translate_error(exc) from exc
            if not self.interactive:
                raise InstagramAuthRequired(
                    "Two-factor authentication required (non-interactive run)."
                ) from exc
            code = self._prompt("Instagram two-factor code: ").strip()
            try:
                self.loader.two_factor_login(code)
            except Exception as exc2:
                raise translate_error(exc2) from exc2
        self.logged_in = True
        self.save_session()

    def save_session(self) -> None:
        """Save the session file (only when logged in)."""
        if not self.logged_in or self.loader is None:
            return
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            self.loader.save_session_to_file(str(self.save_path))
            logger.info("Saved Instagram session to %s", self.save_path)
        except Exception:
            logger.warning("Could not save the Instagram session", exc_info=True)

    def _require_login(self) -> None:
        if not self.logged_in or self.loader is None:
            raise RuntimeError("InstagramCollector is not logged in; use 'with'")

    # -- collection ------------------------------------------------------

    def collect_saved(
        self,
        *,
        stop_after_known: int | None = 20,
        limit: int | None = None,
        batch_size: int = 25,
        progress: ProgressCallback | None = None,
    ) -> CollectStats:
        """Walk the saved feed and store new posts.

        Args:
            stop_after_known: Stop after this many consecutive known posts;
                ``None`` walks the whole feed and also updates known posts.
            limit: Maximum posts to write (new + updated).
            batch_size: Posts per write transaction.
            progress: Progress callback.

        Returns:
            Run statistics (also available as :attr:`stats` if an error occurs).

        Raises:
            InstagramRateLimited: Instagram rate-limited the feed (completed
                and pending batches are kept).
            InstagramAuthRequired: The session became invalid during the run.
        """
        self._require_login()
        stats = self.stats
        writer = BatchWriter(self.db, stats, batch_size)
        full = stop_after_known is None or stop_after_known <= 0
        streak = 0
        new_seen = 0
        seen = 0
        reason: Any = "end_of_feed"
        try:
            posts: Iterator[Any] = iter(self._saved_posts(self.loader))
            for rank, post in enumerate(posts):
                seen = rank + 1
                shortcode = _node(post).get("shortcode") or post.shortcode
                with self.db.read() as conn:
                    known = bool(ItemsRepo(conn).known_instagram_shortcodes([shortcode]))
                if known and not full:
                    streak += 1
                    stats.known_skipped += 1
                    emit(progress, stats, seen=seen)
                    if stop_after_known is not None and streak >= stop_after_known:
                        reason = "early_stop"
                        break
                    continue
                streak = 0
                if not known:
                    if new_seen:
                        self._sleep(jitter(self.options.min_delay, self.options.max_delay))
                    new_seen += 1
                writer.add(map_post(post, rank))
                emit(progress, stats, seen=seen)
                if limit is not None and stats.processed >= limit:
                    reason = "limit"
                    break
        except BaseException as exc:
            try:
                writer.flush()
            except Exception:
                logger.exception("Could not write the last Instagram batch")
            translated = translate_error(exc) if isinstance(exc, Exception) else exc
            if isinstance(translated, InstagramRateLimited):
                stats.stopped_reason = "rate_limited"
            elif isinstance(translated, AuthRequired):
                stats.stopped_reason = "auth_required"
            logger.warning(
                "Instagram collection stopped after %d feed posts (last stored: %s)",
                seen, stats.last_external_id,
            )
            if translated is exc:
                raise
            raise translated from exc
        writer.flush()
        stats.stopped_reason = reason
        emit(progress, stats, seen=seen, message="done")
        logger.info(
            "Instagram: %d new, %d updated, %d known skipped (%s)",
            stats.new, stats.updated, stats.known_skipped, reason,
        )
        return stats

    def refresh_dates(
        self, limit: int | None = None, progress: ProgressCallback | None = None
    ) -> int:
        """Re-fetch ``date_utc`` of stored posts whose date is unverified.

        Rows migrated from schema v1 carry a ``created_at`` derived from an
        assumed timezone (``instagram_posts.date_status IS NULL``). Each post is
        fetched with one request (throttled); the confirmed UTC time replaces
        ``created_at`` and the row is marked ``verified``. Posts that no longer
        exist are marked ``unavailable`` so they are not retried.

        Args:
            limit: Maximum posts to refresh (``None``: all unverified).
            progress: Progress callback (phase ``refresh_dates``).

        Returns:
            Number of posts whose date was refreshed.

        Raises:
            InstagramRateLimited: Instagram rate-limited the requests (dates
                refreshed so far are kept).
        """
        self._require_login()
        with self.db.read() as conn:
            todo = ItemsRepo(conn).instagram_unverified_dates(limit)
        logger.info("Refreshing dates of %d Instagram posts", len(todo))
        refreshed = 0
        for index, (item_id, shortcode) in enumerate(todo):
            if index:
                self._sleep(
                    jitter(self.options.refresh_min_delay, self.options.refresh_max_delay)
                )
            try:
                post = self._post_from_shortcode(self.loader, shortcode)
                created = post_date_utc(post)
            except Exception as exc:
                if type(exc).__name__ in (
                    "QueryReturnedNotFoundException", "ProfileNotExistsException",
                ):
                    with self.db.transaction() as conn:
                        ItemsRepo(conn).set_instagram_date(item_id, None, "unavailable")
                    self.stats.errors.append(f"{shortcode}: post not available")
                    continue
                translated = translate_error(exc)
                if translated is not exc:
                    raise translated from exc
                self.stats.errors.append(f"{shortcode}: date refresh failed: {exc}")
                logger.warning("Date refresh failed for %s: %s", shortcode, exc)
                continue
            if created is None:
                self.stats.errors.append(f"{shortcode}: no date in response")
                continue
            with self.db.transaction() as conn:
                ItemsRepo(conn).set_instagram_date(item_id, created, "verified")
            refreshed += 1
            self.stats.dates_refreshed = refreshed
            emit(
                progress, self.stats, phase="refresh_dates", seen=index + 1, total=len(todo)
            )
        return refreshed
