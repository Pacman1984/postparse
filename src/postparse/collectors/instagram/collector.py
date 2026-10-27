"""Incremental collector for the Instagram saved feed (instaloader).

The saved feed (``api/v1/feed/saved/posts/``) is newest-first, paginated
with ``max_id``. It is requested the way the Instagram web app does it
(``www.instagram.com`` with web headers, ``instagram.feed_api = "web"``,
default) or through the private iPhone API (``i.instagram.com``,
``"iphone"``). The collector walks it and stops after
``stop_after_known`` consecutive posts that are already stored, so a routine
run costs only a page or two of feed requests. New posts are mapped from the
feed node itself (no per-post request), throttled with a jittered pause and
written in batches of ``batch_size`` (one transaction each).

Nothing is downloaded and no expiring image CDN URL is stored; for videos a
pending-transcription media row is created (with the video URL only when the
feed item already carries it).

The saved session is verified with a single request to the user-info
endpoint (no legacy GraphQL ``query_hash``), over the same API as the feed.
There is no automatic password login: without a usable session
:class:`InstagramAuthRequired` names the reason and points to the interactive
``postparse check instagram --import-session`` (the session of the user's
logged-in browser, :meth:`InstagramCollector.import_session`) or
``postparse check instagram --login`` (the only caller that sets
``allow_password_login``). A session is only saved after the check confirmed
it, also after a password login (instaloader may report a login without a
session cookie, instaloader issue #2487). A throttled or failed check raises
:class:`InstagramSessionCheckFailed` and leaves the session file alone. A feed
page that Instagram answers with a ``"fail"`` status is not retried: it raises
:class:`InstagramFeedUnavailable` (only network errors are retried).

Example:
    >>> with InstagramCollector(db, settings, creds) as collector:
    ...     stats = collector.collect_saved(stop_after_known=20)
"""

from __future__ import annotations

import logging
import re
import secrets
import string
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from postparse.collectors.base import (
    AuthRequired,
    BatchWriter,
    CollectorError,
    CollectStats,
    InstagramAuthRequired,
    InstagramFeedUnavailable,
    InstagramRateLimited,
    InstagramSessionCheckFailed,
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
    "FEED_APIS",
    "LEGACY_SESSION_FILE",
    "FeedApi",
    "InstagramCollector",
    "InstagramOptions",
    "InvalidSessionCookie",
    "iter_saved_feed",
    "map_post",
    "parse_sessionid",
    "post_from_iphone_media",
    "resolve_session_path",
]

logger = logging.getLogger(__name__)

#: Session file written by the old CLI (relative to the working directory).
LEGACY_SESSION_FILE = "instagram_session"

LoaderFactory = Callable[["InstagramOptions"], Any]
SavedPostsFn = Callable[[Any], Iterable[Any]]
PostFromShortcode = Callable[[Any, str], Any]
PromptFn = Callable[[str], str]

#: User info (session check); same path on ``i.instagram.com`` and ``www.instagram.com``.
USER_INFO_PATH = "api/v1/users/{user_id}/info/"
#: Saved feed (all saved posts, newest saved first); same path on both hosts.
SAVED_FEED_PATH = "api/v1/feed/saved/posts/"

#: How the saved feed is requested: web REST API or private iPhone API.
FeedApi = Literal["web", "iphone"]
FEED_APIS: tuple[FeedApi, ...] = ("web", "iphone")

WEB_HOST = "www.instagram.com"
#: ``Referer`` of web requests outside the saved page (the session check).
WEB_REFERER = f"https://{WEB_HOST}/"
#: App id of the Instagram web app (``X-IG-App-ID``; instaloader sends the same).
WEB_APP_ID = "936619743392459"
#: ``X-ASBD-ID`` the web app sends (value as used by gallery-dl's REST client).
WEB_ASBD_ID = "129477"
#: Posts per web feed page (as gallery-dl requests the saved feed).
WEB_PAGE_SIZE = "50"
#: instaloader www default headers that the web app's REST calls do not send.
_WEB_DROP_HEADERS = ("X-Instagram-AJAX", "Content-Length")

#: ``media_type`` of private API media -> GraphQL ``__typename`` (as instaloader maps it).
_IPHONE_MEDIA_TYPES: dict[int, str] = {1: "GraphImage", 2: "GraphVideo", 8: "GraphSidecar"}

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
        max_connection_attempts: instaloader connection attempts (the session
            check and feed pages use one attempt; feed pages retry only
            network errors, up to this many attempts).
        user_agent: Custom user agent (``None``: instaloader default).
        feed_api: ``"web"`` (``www.instagram.com`` REST API, like the web
            app) or ``"iphone"`` (private API on ``i.instagram.com``).

    Raises:
        ValueError: ``feed_api`` is not one of :data:`FEED_APIS`.
    """

    min_delay: float = 5.0
    max_delay: float = 15.0
    refresh_min_delay: float = 5.0
    refresh_max_delay: float = 15.0
    request_timeout: float = 30.0
    max_connection_attempts: int = 3
    user_agent: str | None = None
    feed_api: FeedApi = "web"

    def __post_init__(self) -> None:
        if self.feed_api not in FEED_APIS:
            raise ValueError(
                f"instagram.feed_api must be one of {', '.join(map(repr, FEED_APIS))} "
                f"(got {self.feed_api!r})"
            )

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
            feed_api=cast(
                FeedApi, str(_cfg(config, "instagram.feed_api", d.feed_api)).strip().lower()
            ),
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


def iter_saved_feed(
    context: Any,
    feed_api: FeedApi = "web",
    username: str | None = None,
    web: _WebClient | None = None,
) -> Iterator[Any]:
    """Iterate the saved feed (newest saved first).

    Pages of ``api/v1/feed/saved/posts/`` are requested lazily (``max_id`` =
    previous ``next_max_id``), so a consumer that stops early costs no further
    page request. instaloader's ``Profile.get_saved_posts()`` (4.15.5) still
    uses a legacy GraphQL ``query_hash`` and needs ``Profile.own_profile()``,
    which uses another one; Instagram answers that endpoint family with 401
    "Please wait a few minutes".

    Each page gets one attempt (see :func:`_feed_page`).

    Args:
        context: Logged-in ``InstaloaderContext`` (``user_id`` set for ``iphone``).
        feed_api: ``"web"``: ``www.instagram.com`` with the web app's REST
            headers (see :class:`_WebClient`), with a web session the endpoint
            Instagram's own web app uses; ``"iphone"``: ``i.instagram.com``
            through ``context.get_iphone_json`` (iPad headers).
        username: Logged-in username (``Referer`` of web requests).
        web: Web client to use (the collector's, shared with the session
            check); ``None`` creates one for this walk.

    Yields:
        instaloader ``Post`` objects built from the media structs (both APIs
        answer ``items[].media`` with the same private-API media struct).

    Raises:
        InstagramFeedUnavailable: Instagram answered a page with a ``"fail"``
            status (e.g. "something went wrong").
        InstagramRateLimited: Instagram throttled a page.
        InstagramAuthRequired: The session was logged out or needs a confirmation.
        ValueError: Unknown ``feed_api``.
    """
    if feed_api not in FEED_APIS:
        raise ValueError(f"unknown feed_api {feed_api!r}")
    if feed_api == "iphone":
        yield from _iter_feed_posts(
            context, feed_api, lambda params: context.get_iphone_json(SAVED_FEED_PATH, params)
        )
        return
    client = web if web is not None else _WebClient(context)
    referer = f"https://{WEB_HOST}/{username}/saved/all-posts/" if username else WEB_REFERER
    try:
        yield from _iter_feed_posts(
            context, feed_api, lambda params: client.get(SAVED_FEED_PATH, params, referer=referer)
        )
    finally:
        if web is None:
            client.close()


def _iter_feed_posts(
    context: Any, feed_api: FeedApi, fetch: Callable[[dict[str, Any]], Any]
) -> Iterator[Any]:
    """Walk the feed pages (``fetch(params) -> page``) and yield posts."""
    max_id: str | None = None
    while True:
        params: dict[str, Any] = (
            {"count": WEB_PAGE_SIZE} if feed_api == "web" else {"include_igtv_preview": "false"}
        )
        if max_id:
            params["max_id"] = max_id
        data = _feed_page(context, feed_api, partial(fetch, params))
        if not isinstance(data, dict):
            return
        items = data.get("items") or []
        for item in items:
            media = item.get("media", item) if isinstance(item, dict) else None
            if isinstance(media, dict) and media.get("code"):
                yield post_from_iphone_media(context, media)
        next_max_id = data.get("next_max_id") or data.get("max_id")
        if not items or not data.get("more_available") or not next_max_id:
            return
        if str(next_max_id) == max_id:
            logger.warning("Instagram saved feed returned the same cursor twice; stopping")
            return
        max_id = str(next_max_id)


def _feed_page(context: Any, feed_api: FeedApi, call: Callable[[], Any]) -> Any:
    """Request one feed page with instaloader's own retries disabled.

    instaloader retries every failed JSON query ``max_connection_attempts``
    times, including a 200 answer with ``"status": "fail"`` that will not
    change on a retry. Here a page gets one attempt; only network errors
    (timeouts, connection resets) are retried, up to the configured attempts.
    Instagram's answers are translated: throttle -> :class:`InstagramRateLimited`,
    logout/checkpoint -> :class:`InstagramAuthRequired`, any other ``"fail"``
    status -> :class:`InstagramFeedUnavailable`; other errors are re-raised.
    """
    configured = context.max_connection_attempts
    attempts = max(1, int(configured or 1))
    context.max_connection_attempts = 1
    try:
        attempt = 1
        while True:
            try:
                return call()
            except Exception as exc:
                if attempt < attempts and _is_network_error(exc):
                    attempt += 1
                    logger.warning(
                        "Instagram saved feed: network error (%s); attempt %d/%d",
                        type(exc).__name__,
                        attempt,
                        attempts,
                    )
                    continue
                translated = _feed_error(exc, feed_api)
                if translated is exc:
                    raise
                raise translated from exc
    finally:
        context.max_connection_attempts = configured


def _is_network_error(exc: BaseException) -> bool:
    """True if ``exc`` is (or wraps) a ``requests`` transport error."""
    import requests

    seen: BaseException | None = exc
    for _ in range(5):
        if seen is None:
            return False
        if isinstance(seen, requests.exceptions.RequestException):
            return True
        seen = seen.__cause__
    return False


#: Feed answers that are a refusal (checked after throttle/logout markers).
_FEED_FAIL_MARKERS = ('"fail" status', "something went wrong")


def _feed_error(exc: BaseException, feed_api: FeedApi) -> BaseException:
    """Translate a failed feed page request (see :func:`_feed_page`)."""
    translated = translate_error(exc)
    if translated is not exc:
        return translated
    text = _marker_text(str(exc))
    if type(exc).__name__ == "ConnectionException" and any(m in text for m in _FEED_FAIL_MARKERS):
        return InstagramFeedUnavailable(feed_api, _instagram_message(str(exc)))
    return exc


#: Longest Instagram reason quoted in messages (characters).
MAX_REASON_LENGTH = 200
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
#: instaloader's request prefix (``JSON Query to <path>: ``); the path carries ids.
_QUERY_PREFIX_RE = re.compile(r"^\s*JSON Query to \S+:\s*", re.IGNORECASE)
#: ``message "..."`` (instaloader) or ``"message": "..."`` (JSON body of a fatal status).
_MESSAGE_RES = (
    re.compile(r'message "([^"]*)"'),
    re.compile(r'"message"\s*:\s*"([^"]*)"'),
)
_REDIRECT_RE = re.compile(r"redirect(?:ed)? to (https?://[^\s\"'<>]+)", re.IGNORECASE)
#: ``name=value`` / ``"name": "value"`` pairs that must never be shown (cookies,
#: tokens, passwords).
_SECRET_RE = re.compile(
    r"(?i)\b(sessionid|csrftoken|ds_user_id|mid|ig_did|rur|shbid|shbts|"
    r"[\w-]*token[\w-]*|[\w-]*passw\w*|enc_password|cookie|authorization)[\"']?\s*[=:]\s*"
    r"[\"']?[^\s;,&\"']+"
)
#: A bare ``sessionid`` value (``<user id>%3A...``, also URL-decoded with ``:``).
_SESSIONID_VALUE_RE = re.compile(r"(?i)\b\d+(?:%3A|:)[A-Za-z0-9%:_-]{8,}")
#: HTTP status 429 as a word (applied to the text without URLs and request paths).
_HTTP_429_RE = re.compile(r"(?<![\w./=&?-])429(?![\w./=&?-])")


def _strip_url(url: str) -> str:
    """``scheme://host/path`` of ``url`` (query string and fragment removed)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _error_head(text: str) -> str:
    """The error text before instaloader's `` when accessing <url>`` tail."""
    return text.split(" when accessing ", 1)[0]


def _marker_text(text: str) -> str:
    """Lower-case error text for marker checks.

    The request URL (`` when accessing ...``) is dropped and other URLs are
    reduced to ``scheme://host/path``, so cursor ids, user ids and query
    parameters cannot match a marker.
    """
    return _URL_RE.sub(lambda m: _strip_url(m.group(0)), _error_head(text)).lower()


def _is_http_429(text: str) -> bool:
    """True if the error text reports HTTP 429 (never matched inside URLs or paths)."""
    head = _QUERY_PREFIX_RE.sub("", _URL_RE.sub(" ", _error_head(text)))
    return bool(_HTTP_429_RE.search(head))


def _instagram_message(text: str) -> str:
    """Instagram's short reason from an instaloader error text (sanitized).

    Returns the ``message "..."`` part (e.g. ``checkpoint_required``,
    ``login_required``), for a login redirect the redirect target as
    ``scheme://host/path``, otherwise the error text without the request URL.
    Query strings, fragments and ``name=value`` secrets (cookies, tokens,
    passwords) are removed; the result is at most :data:`MAX_REASON_LENGTH`
    characters.
    """
    reason: str | None = None
    for pattern in _MESSAGE_RES:
        match = pattern.search(text)
        if match and match.group(1).strip():
            reason = match.group(1).strip()
            break
    if reason is None:
        redirect = _REDIRECT_RE.search(text)
        if redirect:
            reason = f"redirect to {_strip_url(redirect.group(1))}"
        elif "redirected to login page" in text.lower():
            reason = "redirected to login page"
        else:
            head = _error_head(text)
            head = head.split(": {", 1)[0]  # no JSON response body
            reason = _QUERY_PREFIX_RE.sub("", head).strip()
    reason = _URL_RE.sub(lambda m: _strip_url(m.group(0)), reason)
    reason = _SECRET_RE.sub(lambda m: f"{m.group(1)}=<redacted>", reason)
    reason = _SESSIONID_VALUE_RE.sub("<redacted>", reason)
    reason = " ".join(reason.split())
    if len(reason) > MAX_REASON_LENGTH:
        reason = reason[: MAX_REASON_LENGTH - 1].rstrip() + "…"
    return reason


class _WebClient:
    """Requests to ``www.instagram.com`` as the Instagram web app makes them.

    Used for the saved feed and for the session check (``feed_api = "web"``),
    so a run talks to Instagram with one client identity, and a browser
    session is never sent with iPad headers to ``i.instagram.com``.

    Uses a temporary copy of instaloader's session (``copy_session``, as
    ``get_iphone_json`` does), so the loaded cookies, instaloader's www
    defaults (``User-Agent``, ``Origin``, ``Accept-Language``) and its rate
    controller and error handling (``context.get_json``) stay in use; the main
    session is not changed. The copy follows the context: when instaloader
    replaces its session (password login, imported session), a new copy is
    made. On top, the web app's REST headers are sent (``X-IG-App-ID``,
    ``X-ASBD-ID``, ``X-Requested-With``, ``Sec-Fetch-*``, a ``Referer``). Each
    request takes ``X-CSRFToken`` from the current ``csrftoken`` cookie and
    sends the last ``x-ig-set-www-claim`` the server handed out as
    ``X-IG-WWW-Claim`` (``"0"`` before), like the web app and gallery-dl's REST
    client do.

    Args:
        context: instaloader context (its ``_session`` holds the cookies).
        referer: Default ``Referer`` (the web app's start page).
    """

    def __init__(self, context: Any, referer: str = WEB_REFERER) -> None:
        self.context = context
        self.referer = referer
        self.www_claim = "0"
        self.session: Any = None
        self._source: Any = None

    def _session(self) -> Any:
        source = self.context._session
        if self.session is None or self._source is not source:
            from instaloader.instaloadercontext import copy_session

            self.close()
            session = copy_session(source, self.context.request_timeout)
            for header in _WEB_DROP_HEADERS:
                session.headers.pop(header, None)
            session.headers.update(
                {
                    "Accept": "*/*",
                    "Origin": f"https://{WEB_HOST}",
                    "X-ASBD-ID": WEB_ASBD_ID,
                    "X-IG-App-ID": WEB_APP_ID,
                    "X-Requested-With": "XMLHttpRequest",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                }
            )
            self.session = session
            self._source = source
            self.www_claim = "0"  # the claim belongs to the session
        return self.session

    def get(self, path: str, params: dict[str, Any], *, referer: str | None = None) -> Any:
        """GET ``https://www.instagram.com/<path>`` (JSON) with the web headers."""
        session = self._session()
        session.headers["Referer"] = referer or self.referer
        session.headers["X-CSRFToken"] = str(session.cookies.get_dict().get("csrftoken") or "")
        session.headers["X-IG-WWW-Claim"] = self.www_claim
        response_headers: dict[str, Any] = {}
        data = self.context.get_json(
            path,
            params,
            host=WEB_HOST,
            session=session,
            response_headers=response_headers,
        )
        for key, value in response_headers.items():
            if key.lower() == "x-ig-set-www-claim" and value:
                self.www_claim = str(value)
        return data

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None
            self._source = None


def post_from_iphone_media(context: Any, media: dict[str, Any]) -> Any:
    """Build an instaloader ``Post`` from a private API media struct.

    Uses ``Post.from_iphone_struct``; if the struct lacks a key that instaloader
    requires (e.g. ``like_count`` hidden, unknown ``media_type``), a minimal
    node with the same keys is built instead so the post is not lost.
    """
    import instaloader

    try:
        return instaloader.Post.from_iphone_struct(context, media)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        logger.debug("Building a minimal node for saved post %s", media.get("code"))
        return instaloader.Post(context, _minimal_iphone_node(media))


def _minimal_iphone_node(media: dict[str, Any]) -> dict[str, Any]:
    """Tolerant version of the node ``Post.from_iphone_struct`` builds."""
    media_type = media.get("media_type")
    typename = _IPHONE_MEDIA_TYPES.get(media_type) if isinstance(media_type, int) else None
    caption = media.get("caption")
    node: dict[str, Any] = {
        "shortcode": media["code"],
        "id": media.get("pk"),
        "__typename": typename,
        "is_video": typename == "GraphVideo",
        "date": media.get("taken_at"),
        "caption": caption.get("text") if isinstance(caption, dict) else None,
        "comments": media.get("comment_count"),
        "iphone_struct": media,
    }
    if isinstance(media.get("like_count"), int):
        node["edge_media_preview_like"] = {"count": media["like_count"]}
    video_url = _first_url(media.get("video_versions"))
    if video_url is not None:
        node["video_url"] = video_url
        node["video_duration"] = media.get("video_duration")
    return node


def _first_url(versions: Any) -> str | None:
    """First ``url`` of an ``image_versions2.candidates`` / ``video_versions`` list."""
    if isinstance(versions, list) and versions and isinstance(versions[0], dict):
        url = versions[0].get("url")
        return url if isinstance(url, str) and url else None
    return None


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
    """First count among ``keys`` (GraphQL ``{"count": n}`` edges or plain ints)."""
    for key in keys:
        value = node.get(key)
        if isinstance(value, dict):
            value = value.get("count")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _iphone_struct(node: dict[str, Any]) -> dict[str, Any]:
    """The private API media struct a node was built from (empty for GraphQL nodes)."""
    struct = node.get("iphone_struct")
    return struct if isinstance(struct, dict) else {}


def _owner(node: dict[str, Any]) -> tuple[Any, str | None]:
    """``(owner id, username)`` from a GraphQL node or its private API struct."""
    owner = node.get("owner")
    if isinstance(owner, dict) and owner:
        return owner.get("id"), owner.get("username") or None
    user = _iphone_struct(node).get("user")
    if isinstance(user, dict):
        return user.get("pk", user.get("id")), user.get("username") or None
    return None, None


def _children(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Carousel children as nodes with ``is_video`` / ``video_url`` / ``video_duration``.

    Private API structs are read directly (``carousel_media``): instaloader's
    conversion drops the child durations and, if one child lacks an image, all
    children.
    """
    carousel = _iphone_struct(node).get("carousel_media")
    if isinstance(carousel, list):
        children: list[dict[str, Any]] = []
        for media in carousel:
            media = media if isinstance(media, dict) else {}
            child: dict[str, Any] = {"is_video": media.get("media_type") == 2}
            video_url = _first_url(media.get("video_versions"))
            if video_url is not None:
                child["video_url"] = video_url
            if "video_duration" in media:
                child["video_duration"] = media["video_duration"]
            children.append(child)
        return children
    edges = (node.get("edge_sidecar_to_children") or {}).get("edges") or []
    return [edge.get("node") or {} for edge in edges]


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

    Works with GraphQL nodes and with nodes built from private API media
    structs (``Post.from_iphone_struct``; the struct is read for the owner and
    the carousel children).

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
    owner_id, owner_name = _owner(node)
    media: list[MediaInput] = []
    if kind == "video":
        media.append(_video_media(0, node))
    elif kind == "carousel":
        for index, child in enumerate(_children(node)):
            if child.get("is_video"):
                media.append(_video_media(index, child))
    return ItemUpsert(
        source="instagram",
        external_id=shortcode,
        kind=kind,
        text=caption,
        author=owner_name,
        url=f"https://www.instagram.com/p/{shortcode}/",
        created_at=post_date_utc(post),
        detail=InstagramDetail(
            shortcode=shortcode,
            owner_id=int(owner_id) if owner_id is not None else None,
            typename=typename,
            likes=_count(node, "edge_media_preview_like", "edge_liked_by"),
            comments=_count(
                node, "edge_media_to_comment", "edge_media_to_parent_comment", "comments"
            ),
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

_CHALLENGE_MARKERS = (
    "checkpoint",
    "challenge",
    "feedback_required",
    "login_required",
    "redirected to login page",
    "instagram.com/accounts/login",
)
#: Throttle answers (an HTTP 429 status is detected separately, see :func:`_is_http_429`).
_RATE_MARKERS = ("too many requests", "please wait a few minutes", "rate limit")
#: Session-check answers that are throttles (checked first; markers never match URL text).
_THROTTLE_MARKERS = ("too many requests", "please wait a few minutes", "rate limit", "401 ")
#: Session-check answers that positively mean "this session is not logged in".
_LOGGED_OUT_MARKERS = (
    "login_required",
    "redirected to login page",
    "require_login",
    "instagram.com/accounts/login",
)
#: Session-check answers that need the user (a password login would not help).
_USER_ACTION_MARKERS = ("checkpoint", "challenge", "feedback_required")


def translate_error(exc: BaseException) -> BaseException:
    """Map instaloader exceptions to collector errors (others are returned as-is).

    Markers are matched only against the error text without the request URL
    (see :func:`_marker_text`), so ids in URLs (``max_id=...3429...``) cannot
    turn a refusal into a rate limit. The collector errors carry Instagram's
    sanitized reason (:func:`_instagram_message`).
    """
    if isinstance(exc, CollectorError):
        return exc
    name = type(exc).__name__
    raw = str(exc)
    text = _marker_text(raw)
    reason = _instagram_message(raw) if raw else None
    if name == "TooManyRequestsException" or (
        name in ("ConnectionException", "QueryReturnedBadRequestException")
        and (_is_http_429(raw) or any(marker in text for marker in _RATE_MARKERS))
    ):
        return InstagramRateLimited(reason)
    if name == "TwoFactorAuthRequiredException":
        return InstagramAuthRequired("Two-factor code required.")
    if name == "BadCredentialsException":
        return InstagramAuthRequired("Instagram rejected the password or 2FA code.")
    if name in ("LoginRequiredException", "LoginException") or (
        name
        in (
            "AbortDownloadException",
            "ConnectionException",
            "QueryReturnedBadRequestException",
            "QueryReturnedForbiddenException",
        )
        and any(marker in text for marker in _CHALLENGE_MARKERS)
    ):
        return InstagramAuthRequired(
            "Instagram requires a confirmation or a new login"
            + (f" (Instagram: {reason})." if reason else ".")
        )
    return exc


def _session_check_verdict(exc: BaseException) -> str:
    """Classify a failed session check: ``logged_out``, ``user_action`` or ``failed``.

    Only ``logged_out`` (login redirect, ``login_required``) justifies a
    password login. Throttles (401 "please wait", 429), connection errors and
    anything unknown are ``failed``: they say nothing about the session.
    """
    name = type(exc).__name__
    if name == "LoginRequiredException":
        return "logged_out"
    text = _marker_text(str(exc))
    if (
        name == "TooManyRequestsException"
        or _is_http_429(str(exc))
        or any(m in text for m in _THROTTLE_MARKERS)
    ):
        return "failed"
    if any(marker in text for marker in _USER_ACTION_MARKERS):
        return "user_action"
    if any(marker in text for marker in _LOGGED_OUT_MARKERS):
        return "logged_out"
    return "failed"


def _session_cookies(loader: Any) -> dict[str, Any]:
    """Cookies of the loaded session (``Instaloader.save_session``; never logged)."""
    try:
        cookies = loader.save_session()
    except Exception:
        return {}
    return cookies if isinstance(cookies, dict) else {}


def _has_login_cookies(cookies: dict[str, Any]) -> bool:
    """True if ``cookies`` carry a ``sessionid`` and a numeric ``ds_user_id``."""
    return bool(cookies.get("sessionid")) and str(cookies.get("ds_user_id") or "").isdigit()


def _drop_placeholder_cookies(jar: Any) -> int:
    """Remove instaloader's empty placeholder cookies from ``jar``.

    ``InstaloaderContext.login`` puts ``sessionid``, ``mid``, ``csrftoken``,
    ``s_network`` and ``ds_user_id`` with empty values (and no domain) into a
    fresh jar before logging in. Cookies Instagram sets carry a domain, so a
    cookie with an empty value and no domain is such a placeholder; it would
    hide a missing (or shadow a real) login cookie. Everything else (also
    ``ig_pr="1"`` and the like) is kept.

    Returns:
        Number of removed cookies.
    """
    placeholders = [c for c in list(jar) if not c.value and not c.domain]
    for cookie in placeholders:
        jar.clear(cookie.domain, cookie.path, cookie.name)
    return len(placeholders)


class InvalidSessionCookie(ValueError):
    """A pasted cookie value does not have the expected shape (the value is never shown)."""


#: ``sessionid`` cookie as the browser stores it: ``<ds_user_id>%3A<rest>``.
_SESSIONID_RE = re.compile(r"^(\d+)%3A[^\s;,\"']+$", re.IGNORECASE)
_CSRFTOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")
#: Length of a generated ``csrftoken`` (as Instagram's).
CSRFTOKEN_LENGTH = 32


def _strip_cookie_value(value: str) -> str:
    """``value`` without surrounding whitespace and quotes."""
    return value.strip().strip("\"'").strip()


def parse_sessionid(value: str) -> tuple[str, str]:
    """Normalize a ``sessionid`` cookie copied from the browser.

    Whitespace and surrounding quotes are removed and ``:`` is encoded as
    ``%3A`` (the browser's developer tools show the URL-encoded value; a
    decoded copy is accepted as well).

    Args:
        value: Pasted cookie value.

    Returns:
        ``(sessionid, ds_user_id)``; the user id is the leading number.

    Raises:
        InvalidSessionCookie: Not shaped like ``<digits>%3A...`` (the message
            never contains the value).
    """
    sessionid = _strip_cookie_value(value).replace(":", "%3A")
    match = _SESSIONID_RE.match(sessionid)
    if match is None:
        raise InvalidSessionCookie(
            "The value does not look like an Instagram sessionid cookie (expected <digits>%3A…)."
        )
    return sessionid, match.group(1)


def _csrftoken(value: str | None) -> str:
    """The pasted ``csrftoken`` (normalized), or a newly generated one when empty."""
    token = _strip_cookie_value(value or "")
    if not token:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(CSRFTOKEN_LENGTH))
    if not _CSRFTOKEN_RE.match(token):
        raise InvalidSessionCookie(
            "The value does not look like an Instagram csrftoken cookie (letters and digits)."
        )
    return token


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class InstagramCollector:
    """Collect saved Instagram posts into the schema v2 database.

    Use as a context manager: entering loads/validates the session, leaving
    saves the session.

    A password login is never automatic: scripted password logins are what
    makes Instagram ask for checkpoints. Without a usable session the collector
    raises :class:`InstagramAuthRequired` unless ``allow_password_login`` is set,
    which only the interactive ``postparse check instagram --login`` does. The
    recommended way to create a session is :meth:`import_session` (the browser's
    ``sessionid`` cookie, ``postparse check instagram --import-session``). New
    sessions are saved only after the session check confirmed them.

    Args:
        db: Target database.
        settings: Paths (sessions).
        credentials: Username and optional password.
        options: Tunables (default: built-in defaults).
        interactive: Allow prompting for a two-factor code; otherwise a 2FA
            challenge raises :class:`InstagramAuthRequired`.
        session: ``--session`` override (file path).
        allow_password_login: Fall back to the password login when there is
            no usable session (only for the interactive
            ``postparse check instagram --login``; default ``False``).
        loader_factory: Creates the instaloader instance (tests pass a fake).
        saved_posts: Returns the saved-post iterator for a loader (default:
            :func:`iter_saved_feed` with ``options.feed_api``).
        post_from_shortcode: Fetches one post (``refresh_dates``).
        prompt: Reads the 2FA code in interactive mode (default ``input``).
        sleep: Sleep function (tests pass a no-op).
        progress: Receives the session outcome while logging in (phase
            ``session``: saved session verified; phase ``login``: password
            login about to start, only with ``allow_password_login``); no
            secrets in the messages.
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
        allow_password_login: bool = False,
        loader_factory: LoaderFactory | None = None,
        saved_posts: SavedPostsFn | None = None,
        post_from_shortcode: PostFromShortcode | None = None,
        prompt: PromptFn | None = None,
        sleep: Callable[[float], Any] = time.sleep,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.credentials = credentials
        self.options = options or InstagramOptions()
        self.interactive = interactive
        self.allow_password_login = allow_password_login
        self.load_path, self.save_path = resolve_session_path(
            settings, credentials.username, session
        )
        self._loader_factory = loader_factory or _default_loader_factory
        self._saved_posts = saved_posts or self._default_saved_posts
        self._post_from_shortcode = post_from_shortcode or _default_post_from_shortcode
        self._prompt = prompt or input
        self._sleep = sleep
        self._progress = progress
        self.loader: Any = None
        self.logged_in = False
        self.stats = CollectStats(source="instagram")
        self._web: _WebClient | None = None

    def _default_saved_posts(self, loader: Any) -> Iterable[Any]:
        """The saved feed through the configured ``feed_api``."""
        return iter_saved_feed(
            loader.context,
            self.options.feed_api,
            self.credentials.username,
            web=self._web_client() if loader is self.loader else None,
        )

    def _web_client(self) -> _WebClient:
        """The web client of this collector (session check and feed share it)."""
        context = self.loader.context
        if self._web is None or self._web.context is not context:
            self._close_web()
            self._web = _WebClient(context)
        return self._web

    def _close_web(self) -> None:
        if self._web is not None:
            self._web.close()
            self._web = None

    # -- session ---------------------------------------------------------

    def _session_event(self, phase: str, message: str) -> None:
        """Report the session outcome (``session`` / ``login``) to the progress callback."""
        emit(self._progress, self.stats, phase=phase, seen=0, message=message)

    def __enter__(self) -> InstagramCollector:
        self.login()
        return self

    def __exit__(self, *exc_info: object) -> None:
        try:
            self.save_session()
        finally:
            self._close_web()

    def login(self) -> None:
        """Load and verify the saved session.

        Without a usable session (no file, unreadable file, or the session
        check positively shows that it is not logged in) a password login is
        only tried when ``allow_password_login`` is set and
        ``INSTAGRAM_PASSWORD`` is configured; otherwise
        :class:`InstagramAuthRequired` names the reason and the way to log in.

        Raises:
            InstagramAuthRequired: No usable session and no password login
                allowed (or possible), the login failed or needs user
                interaction that is not allowed, or Instagram asks for a
                confirmation (checkpoint).
            InstagramSessionCheckFailed: The session check was throttled or
                failed; no password login was attempted.
            InstagramRateLimited: Instagram rate-limited the login.
        """
        self.loader = self._loader_factory(self.options)
        username = self.credentials.username
        if self.load_path.exists():
            logger.info("Loading Instagram session from %s", self.load_path)
            logged_out: str | None
            try:
                self.loader.load_session_from_file(username, str(self.load_path))
            except Exception as exc:
                logger.warning("Instagram session file could not be read: %s", type(exc).__name__)
                logged_out = "session file unreadable"
            else:
                logged_out = self._check_session()
            if logged_out is None:
                self.logged_in = True
                logger.info("Instagram session is valid")
                self._session_event("session", "Instagram session verified (no password login)")
                return
            why = logged_out
            logger.info("Instagram session is not usable (%s)", why)
        else:
            logger.info("No Instagram session file at %s", self.load_path)
            why = "no session file"
        if not self.allow_password_login:
            raise InstagramAuthRequired(
                f"No password login was attempted ({why}); automatic password logins "
                "are disabled because they trigger Instagram checkpoints."
            )
        if not self.credentials.password:
            raise InstagramAuthRequired(
                f"No valid session ({why}) and INSTAGRAM_PASSWORD is not set."
            )
        logger.info("Falling back to the Instagram password login (%s)", why)
        self._session_event(
            "login",
            f"No usable Instagram session ({why}); logging in with the password now",
        )
        self._password_login()

    def _check_session(self) -> str | None:
        """Verify the loaded session with at most one request.

        The ``sessionid`` / ``ds_user_id`` cookies are checked locally first
        (missing: not logged in, no request). Then the user-info endpoint
        (``api/v1/users/<ds_user_id>/info/``) is asked once, with
        ``max_connection_attempts`` temporarily set to 1, over the API the
        feed uses: with ``feed_api = "web"`` as the web app asks it
        (``www.instagram.com``, the web headers of :class:`_WebClient`), with
        ``"iphone"`` through ``get_iphone_json`` (``i.instagram.com``). So a run
        has one client identity, and a browser session is never sent with
        iPad headers to ``i.instagram.com``. instaloader's ``test_login()`` is
        not used: it queries a legacy GraphQL ``query_hash`` and turns every
        error (including throttles) into "not logged in".

        Returns:
            ``None`` if the session is usable, otherwise why it is positively
            not logged in (e.g. ``session logged out: login_required``,
            Instagram's sanitized reason).

        Raises:
            InstagramAuthRequired: Instagram asks for a confirmation.
            InstagramSessionCheckFailed: Throttled, unreachable or unknown error.
        """
        cookies = _session_cookies(self.loader)
        if not _has_login_cookies(cookies):
            logger.info("Instagram session file has no login cookies")
            return "session logged out: the session file has no login cookies"
        user_id = str(cookies["ds_user_id"])
        context = self.loader.context
        context.user_id = int(user_id)  # sent as ig-intended-user-id by get_iphone_json
        path = USER_INFO_PATH.format(user_id=user_id)
        attempts = context.max_connection_attempts
        context.max_connection_attempts = 1
        try:
            if self.options.feed_api == "web":
                data = self._web_client().get(path, {})
            else:
                data = context.get_iphone_json(path, {})
        except Exception as exc:
            verdict = _session_check_verdict(exc)
            reason = _instagram_message(str(exc)) or type(exc).__name__
            if verdict == "logged_out":
                logger.info("Instagram session check: not logged in (%s)", reason)
                return f"session logged out: {reason}"
            if verdict == "user_action":
                logger.warning("Instagram session check: confirmation required (%s)", reason)
                raise InstagramAuthRequired(
                    f"Instagram asks for a confirmation of the saved session (Instagram: {reason})."
                ) from exc
            logger.warning(
                "Instagram session check failed (%s); no password login attempted", reason
            )
            raise InstagramSessionCheckFailed(reason) from exc
        finally:
            context.max_connection_attempts = attempts
        user = data.get("user") if isinstance(data, dict) else None
        current = user.get("username") if isinstance(user, dict) else None
        if not isinstance(current, str) or not current:
            logger.warning("Instagram session check returned no username; using the session")
            return None
        if current.lower() != self.credentials.username.lower():
            logger.info("Instagram session belongs to another account")
            return "session logged out: the session belongs to another account"
        return None

    def _password_login(self) -> None:
        """Log in with the password (and a 2FA code when interactive).

        The new session is saved only after it was verified (see
        :meth:`_verify_new_session`): instaloader reports a login as soon as
        Instagram answers ``authenticated: true``, even when no ``sessionid``
        cookie came back (instaloader issue #2487).
        """
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
        self._verify_new_session("password login")
        self.logged_in = True
        self.save_session()

    def _verify_new_session(self, origin: str) -> None:
        """Verify a session that a password login just created (nothing is saved).

        instaloader's empty placeholder cookies are removed first (see
        :func:`_drop_placeholder_cookies`); without real login cookies no
        request is made. Then :meth:`_check_session` asks Instagram once.

        Args:
            origin: What created the session (``password login``), for messages.

        Raises:
            InstagramAuthRequired: No session cookie, or the check says the
                session is not usable (or asks for a confirmation).
            InstagramSessionCheckFailed: The check was throttled or failed.
        """
        session = getattr(self.loader.context, "_session", None)
        if session is not None:
            dropped = _drop_placeholder_cookies(session.cookies)
            logger.debug("Removed %d placeholder cookies after the %s", dropped, origin)
        if not _has_login_cookies(_session_cookies(self.loader)):
            logger.warning("Instagram %s returned no session cookie (instaloader #2487)", origin)
            raise InstagramAuthRequired(
                "Instagram accepted the password but returned no session cookie "
                "(instaloader issue #2487); nothing was saved."
            )
        reason = self._check_after(origin)
        if reason is not None:
            logger.warning("Instagram session check after the %s failed (%s)", origin, reason)
            raise InstagramAuthRequired(
                f"Instagram accepted the password, but the session check after the {origin} "
                f"failed ({reason}); nothing was saved."
            )

    def _check_after(self, origin: str) -> str | None:
        """:meth:`_check_session` for a new session (a failed check names ``origin``)."""
        try:
            return self._check_session()
        except InstagramSessionCheckFailed as exc:
            raise InstagramSessionCheckFailed(exc.detail, exc.retry_after, after=origin) from exc

    def import_session(self, sessionid: str, csrftoken: str | None = None) -> None:
        """Import the session of the user's logged-in browser and verify it.

        Never uses the password and never falls back to a password login. The
        ``sessionid`` cookie is normalized (:func:`parse_sessionid`; its
        leading number is the ``ds_user_id``), loaded into a fresh instaloader
        session (``Instaloader.load_session``) and verified with
        :meth:`_check_session` (exactly one request). Only a confirmed session
        of :attr:`credentials` ``.username`` is saved (the session file is
        overwritten only then).

        Args:
            sessionid: ``sessionid`` cookie value copied from the browser.
            csrftoken: ``csrftoken`` cookie value; empty or ``None`` generates
                a random one.

        Raises:
            InvalidSessionCookie: A value is not shaped like the cookie (no
                request was made).
            InstagramAuthRequired: The session is not usable (logged out,
                another account) or Instagram asks for a confirmation;
                nothing was saved.
            InstagramSessionCheckFailed: The check was throttled or failed;
                nothing was saved.
        """
        value, user_id = parse_sessionid(sessionid)
        token = _csrftoken(csrftoken)
        self.logged_in = False
        self.loader = self._loader_factory(self.options)
        username = self.credentials.username
        logger.info("Importing the browser session of Instagram user %s", username)
        self.loader.load_session(
            username, {"sessionid": value, "ds_user_id": user_id, "csrftoken": token}
        )
        reason = self._check_after("session import")
        if reason is not None:
            logger.warning("Imported Instagram session is not usable (%s)", reason)
            raise InstagramAuthRequired(
                f"The imported session is not usable ({reason}); nothing was saved."
            )
        self.logged_in = True
        self.save_session()
        self._session_event("session", "Browser session imported and verified (no password login)")

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

    # -- single posts ----------------------------------------------------

    def fetch_post(self, shortcode: str) -> Any:
        """Fetch one post with full metadata (one request).

        Args:
            shortcode: Post shortcode.

        Returns:
            instaloader ``Post``.

        Raises:
            InstagramRateLimited: Instagram rate-limited the request.
            InstagramAuthRequired: The session became invalid.
            Exception: Other instaloader errors unchanged (e.g.
                ``QueryReturnedNotFoundException`` / ``BadResponseException``
                for deleted or inaccessible posts).
        """
        self._require_login()
        try:
            return self._post_from_shortcode(self.loader, shortcode)
        except Exception as exc:
            translated = translate_error(exc)
            if translated is not exc:
                raise translated from exc
            raise

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
            InstagramFeedUnavailable: Instagram refused a feed page with a
                ``"fail"`` status (completed and pending batches are kept).
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
            if isinstance(translated, InstagramFeedUnavailable):
                stats.stopped_reason = "feed_unavailable"
            elif isinstance(translated, InstagramRateLimited):
                stats.stopped_reason = "rate_limited"
            elif isinstance(translated, AuthRequired):
                stats.stopped_reason = "auth_required"
            logger.warning(
                "Instagram collection stopped after %d feed posts (last stored: %s)",
                seen,
                stats.last_external_id,
            )
            if translated is exc:
                raise
            raise translated from exc
        writer.flush()
        stats.stopped_reason = reason
        emit(progress, stats, seen=seen, message="done")
        logger.info(
            "Instagram: %d new, %d updated, %d known skipped (%s)",
            stats.new,
            stats.updated,
            stats.known_skipped,
            reason,
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
                self._sleep(jitter(self.options.refresh_min_delay, self.options.refresh_max_delay))
            try:
                post = self._post_from_shortcode(self.loader, shortcode)
                created = post_date_utc(post)
            except Exception as exc:
                if type(exc).__name__ in (
                    "QueryReturnedNotFoundException",
                    "ProfileNotExistsException",
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
            emit(progress, self.stats, phase="refresh_dates", seen=index + 1, total=len(todo))
        return refreshed
