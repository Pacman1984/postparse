"""Fakes for Telethon and instaloader used by the collector tests.

Telegram messages are real Telethon TL objects (so entity offsets, media and
attribute classes behave like production); only the client is fake. Instagram
posts are real ``instaloader.Post`` objects built from feed nodes on a fake
context that fails the test on any network request.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import instaloader
from telethon.tl.types import (
    Document,
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    Message,
    MessageEntityTextUrl,
    MessageEntityUrl,
    MessageFwdHeader,
    MessageMediaDocument,
    MessageMediaPhoto,
    PeerChannel,
    PeerUser,
    Photo,
    PhotoSize,
)

ME = 4242
BASE_DATE = datetime(2024, 3, 5, 10, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


def tg_text(msg_id: int, text: str = "", **kwargs: Any) -> Message:
    """A text message in Saved Messages."""
    return Message(
        id=msg_id,
        peer_id=PeerUser(ME),
        date=kwargs.pop("date", BASE_DATE),
        message=text,
        **kwargs,
    )


def tg_photo(msg_id: int, size: int = 2048, text: str = "") -> Message:
    photo = Photo(
        id=msg_id,
        access_hash=1,
        file_reference=b"",
        date=BASE_DATE,
        sizes=[
            PhotoSize(type="m", w=10, h=10, size=size // 2),
            PhotoSize(type="y", w=100, h=100, size=size),
        ],
        dc_id=1,
    )
    return tg_text(msg_id, text, media=MessageMediaPhoto(photo=photo))


def _document(mime: str, size: int, attributes: list[Any]) -> Document:
    return Document(
        id=1,
        access_hash=1,
        file_reference=b"",
        date=BASE_DATE,
        mime_type=mime,
        size=size,
        dc_id=1,
        attributes=attributes,
    )


def tg_document(
    msg_id: int,
    filename: str | None = "report.pdf",
    mime: str = "application/pdf",
    size: int = 4096,
) -> Message:
    attrs: list[Any] = [DocumentAttributeFilename(file_name=filename)] if filename else []
    return tg_text(msg_id, "", media=MessageMediaDocument(document=_document(mime, size, attrs)))


def tg_voice(msg_id: int, duration: int = 7) -> Message:
    doc = _document("audio/ogg", 9000, [DocumentAttributeAudio(duration=duration, voice=True)])
    return tg_text(msg_id, "", media=MessageMediaDocument(document=doc))


def tg_video(msg_id: int, duration: float = 12.0, size: int = 10_000_000) -> Message:
    doc = _document(
        "video/mp4",
        size,
        [
            DocumentAttributeVideo(duration=duration, w=640, h=360),
            DocumentAttributeFilename(file_name="clip.mp4"),
        ],
    )
    return tg_text(msg_id, "watch", media=MessageMediaDocument(document=doc))


def tg_links(msg_id: int) -> Message:
    text = "Try 😀 example.com/a and this link plus https://plain.org/x #Rezept @Koch"
    url_offset = len("Try 😀 ".encode("utf-16-le")) // 2
    link_offset = len("Try 😀 example.com/a and this ".encode("utf-16-le")) // 2
    return tg_text(
        msg_id,
        text,
        entities=[
            MessageEntityUrl(offset=url_offset, length=len("example.com/a")),
            MessageEntityTextUrl(offset=link_offset, length=4, url="https://hidden.example/page"),
        ],
    )


def tg_forward(msg_id: int) -> Message:
    return tg_text(
        msg_id,
        "forwarded post",
        fwd_from=MessageFwdHeader(
            date=BASE_DATE,
            from_id=PeerChannel(777),
            from_name="Chef Channel",
            channel_post=99,
        ),
        views=150,
        forwards=3,
    )


class FakeTelegramClient:
    """Minimal async stand-in for ``telethon.TelegramClient``."""

    def __init__(
        self,
        messages: Iterable[Message] = (),
        *,
        authorized: bool = True,
        start_error: BaseException | None = None,
        fail_after: int | None = None,
        fail_with: BaseException | None = None,
        download_error: BaseException | None = None,
    ) -> None:
        self.messages = list(messages)
        self.authorized = authorized
        self.start_error = start_error
        self.fail_after = fail_after
        self.fail_with = fail_with or RuntimeError("connection lost")
        self.download_error = download_error
        self.started_with: list[Any] = []
        self.iter_calls: list[dict[str, Any]] = []
        self.downloads: list[str] = []
        self.connected = False
        self.disconnected = False

    async def connect(self) -> None:
        self.connected = True

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def start(self, phone: Any = None) -> FakeTelegramClient:
        self.started_with.append(phone)
        if self.start_error is not None:
            raise self.start_error
        self.authorized = True
        return self

    async def get_me(self) -> Any:
        return SimpleNamespace(id=ME) if self.authorized else None

    async def iter_messages(
        self, entity: Any, limit: int | None = None, *, min_id: int = 0, reverse: bool = False
    ):
        self.iter_calls.append(
            {"entity": entity, "limit": limit, "min_id": min_id, "reverse": reverse}
        )
        selected = sorted(
            (m for m in self.messages if m.id > min_id), key=lambda m: m.id, reverse=not reverse
        )
        if limit is not None:
            selected = selected[:limit]
        for index, message in enumerate(selected):
            if self.fail_after is not None and index >= self.fail_after:
                raise self.fail_with
            yield message

    async def download_media(self, message: Message, file: str) -> str:
        if self.download_error is not None:
            raise self.download_error
        self.downloads.append(file)
        Path(file).write_bytes(b"x" * 64 + str(message.id).encode())
        return file

    async def disconnect(self) -> None:
        self.disconnected = True


def client_factory(client: FakeTelegramClient, sessions: list[Path] | None = None):
    """Return a ``client_factory`` handing out ``client`` (recording session paths)."""

    def factory(session: Path, api_id: int, api_hash: str, options: Any) -> FakeTelegramClient:
        if sessions is not None:
            sessions.append(session)
        return client

    return factory


async def no_sleep(_seconds: float) -> None:
    return None


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------


class NetworkUsed(AssertionError):
    """Raised by the fake context when code tries to make a request."""


#: Legacy GraphQL query_hash of ``test_login()`` / ``Profile.own_profile()``.
LEGACY_LOGIN_HASH = "d6f4427fbe92d846298cf93df0b937d3"
#: ``ds_user_id`` of the fake session.
IG_USER_ID = "4242"
IG_USER_INFO = f"api/v1/users/{IG_USER_ID}/info/"
IG_SAVED_FEED = "api/v1/feed/saved/posts/"

#: Cookies of a logged-in fake session (no real values).
SESSION_COOKIES = {"sessionid": "fake-sid", "ds_user_id": IG_USER_ID, "csrftoken": "fake-csrf"}


def ig_error(status: str, path: str = IG_USER_INFO) -> Exception:
    """The ConnectionException instaloader raises after its last attempt.

    ``status`` is the part after the URL path, e.g. ``401 Unauthorized - ...``.
    """
    from instaloader.exceptions import ConnectionException

    return ConnectionException(
        f"JSON Query to {path}: {status} when accessing https://i.instagram.com/{path}"
    )


THROTTLED_401 = (
    '401 Unauthorized - "fail" status, message "Please wait a few minutes before you try again."'
)
LOGGED_OUT_403 = '403 Forbidden - "fail" status, message "login_required"'


class FakeIgContext:
    """instaloader context that records requests and answers only scripted ones.

    ``iphone_responses`` maps a private API path to a response dict, an
    exception to raise, or a callable ``params -> dict | exception``. Any other
    request raises :class:`NetworkUsed`.
    """

    def __init__(self, username: str | None = None) -> None:
        self.username = username
        self.is_logged_in = username is not None
        self.iphone_support = False
        self.user_id: int | None = None
        self.max_connection_attempts = 3
        self.iphone_responses: dict[str, Any] = {}
        #: ``(kind, path or query id, params, max_connection_attempts)`` per request.
        self.requests: list[tuple[str, str, dict[str, Any], int]] = []

    def get_iphone_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(("iphone", path, dict(params), self.max_connection_attempts))
        answer = self.iphone_responses.get(path)
        if answer is None:
            raise NetworkUsed(f"unexpected Instagram request: {path}")
        if callable(answer):
            answer = answer(params)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def graphql_query(self, query_hash: str, variables: Any, referer: Any = None) -> Any:
        self.requests.append(("graphql", query_hash, dict(variables), self.max_connection_attempts))
        raise NetworkUsed(f"unexpected GraphQL query {query_hash}")

    def doc_id_graphql_query(self, doc_id: str, variables: Any, referer: Any = None) -> Any:
        self.requests.append(("doc_id", doc_id, dict(variables), self.max_connection_attempts))
        raise NetworkUsed(f"unexpected GraphQL doc_id query {doc_id}")

    def _refuse(self, *args: Any, **kwargs: Any) -> Any:
        raise NetworkUsed("unexpected Instagram request")

    get_json = head = _refuse

    def error(self, *args: Any, **kwargs: Any) -> None:
        return None

    def log(self, *args: Any, **kwargs: Any) -> None:
        return None


class FakeLoader:
    """Stand-in for ``instaloader.Instaloader`` (login/session methods only).

    Args:
        session_user: Username the session check (user-info endpoint) returns;
            ``None`` answers like a logged-out session (403 ``login_required``).
        check_error: Raised by the session check instead (e.g. a throttle).
        session_cookies: Cookies the loaded session file contains.
        login_error / two_factor_error: Raised by the password / 2FA login.
    """

    def __init__(
        self,
        *,
        session_user: str | None = None,
        check_error: BaseException | None = None,
        session_cookies: dict[str, str] | None = None,
        login_error: BaseException | None = None,
        two_factor_error: BaseException | None = None,
    ) -> None:
        self.context = FakeIgContext()
        self.session_user = session_user
        self.login_error = login_error
        self.two_factor_error = two_factor_error
        self.session_cookies = dict(SESSION_COOKIES if session_cookies is None else session_cookies)
        self.cookies: dict[str, str] = {}
        self.loaded: list[tuple[str, str]] = []
        self.logins: list[str] = []
        self.two_factor_codes: list[str] = []
        self.saved: list[str] = []
        if check_error is not None:
            self.context.iphone_responses[IG_USER_INFO] = check_error
        elif session_user is None:
            self.context.iphone_responses[IG_USER_INFO] = lambda _params: ig_error(LOGGED_OUT_403)
        else:
            self.context.iphone_responses[IG_USER_INFO] = {
                "user": {"pk": int(IG_USER_ID), "username": session_user},
                "status": "ok",
            }

    def load_session_from_file(self, username: str, filename: str) -> None:
        self.loaded.append((username, filename))
        self.context.username = username
        self.context.is_logged_in = True
        self.cookies = dict(self.session_cookies)

    def save_session(self) -> dict[str, str]:
        return dict(self.cookies)

    def test_login(self) -> str | None:
        raise AssertionError("test_login() uses a legacy query_hash and must not be called")

    def login(self, user: str, passwd: str) -> None:
        self.logins.append(user)
        if self.login_error is not None:
            raise self.login_error
        self.context.username = user
        self.context.is_logged_in = True
        self.cookies = dict(SESSION_COOKIES)

    def two_factor_login(self, code: str) -> None:
        self.two_factor_codes.append(code)
        if self.two_factor_error is not None:
            raise self.two_factor_error
        self.context.is_logged_in = True
        self.cookies = dict(SESSION_COOKIES)

    def save_session_to_file(self, filename: str) -> None:
        self.saved.append(filename)
        Path(filename).write_text("fake-session", encoding="utf-8")

    def legacy_hash_requests(self) -> list[tuple[str, str, dict[str, Any], int]]:
        """Requests that used the legacy ``test_login`` query_hash."""
        return [r for r in self.context.requests if LEGACY_LOGIN_HASH in repr(r)]


def ig_iphone_media(
    code: str,
    media_type: int = 1,
    *,
    caption: str | None = "Pasta #Rezept @Chef",
    taken_at: int = 1_700_000_000,
    video_url: str | None = None,
    children: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A private API media struct as in ``api/v1/feed/saved/posts/`` items.

    The keys follow what instaloader's ``Post.from_iphone_struct`` reads.
    """
    pk = int.from_bytes(code.encode(), "big") % 10**18
    media: dict[str, Any] = {
        "pk": pk,
        "id": f"{pk}_123",
        "code": code,
        "media_type": media_type,
        "product_type": {1: "feed", 2: "clips", 8: "carousel_container"}.get(media_type, "feed"),
        "taken_at": taken_at,
        "caption": {"pk": 1, "text": caption} if caption is not None else None,
        "has_liked": False,
        "like_count": 10,
        "comment_count": 2,
        "user": {
            "pk": 123,
            "username": "chef",
            "full_name": "Chef",
            "is_private": False,
            "profile_pic_url": "https://scontent.cdninstagram.com/pic.jpg?oe=EXPIRES",
        },
        "image_versions2": {
            "candidates": [
                {
                    "width": 1080,
                    "height": 1350,
                    "url": f"https://scontent.cdninstagram.com/{code}.jpg?oe=EXPIRES",
                }
            ]
        },
    }
    if video_url is not None:
        media["video_versions"] = [{"type": 101, "width": 720, "height": 1280, "url": video_url}]
        media["video_duration"] = 31.5
        media["view_count"] = 1000
    if children is not None:
        media["carousel_media"] = children
        media.pop("image_versions2")
    media.update(extra)
    return media


def ig_iphone_child(media_type: int = 1, video_url: str | None = None) -> dict[str, Any]:
    """A ``carousel_media`` entry of a private API sidecar struct."""
    child: dict[str, Any] = {
        "id": f"child_{media_type}_{video_url}",
        "media_type": media_type,
        "image_versions2": {"candidates": [{"url": "https://scontent.cdninstagram.com/c.jpg"}]},
    }
    if video_url is not None:
        child["video_versions"] = [{"type": 101, "url": video_url}]
        child["video_duration"] = 12.25
    return child


def saved_page(medias: list[dict[str, Any]], next_max_id: str | None = None) -> dict[str, Any]:
    """One page of ``api/v1/feed/saved/posts/``."""
    page: dict[str, Any] = {
        "items": [{"media": m} for m in medias],
        "num_results": len(medias),
        "more_available": next_max_id is not None,
        "auto_load_more_enabled": True,
        "status": "ok",
    }
    if next_max_id is not None:
        page["next_max_id"] = next_max_id
    return page


def saved_feed_pages(*pages: dict[str, Any]):
    """Answer the saved feed by ``max_id``: the first page, then the ``next_max_id`` chain."""
    by_cursor: dict[str | None, dict[str, Any]] = {}
    cursor: str | None = None
    for page in pages:
        by_cursor[cursor] = page
        cursor = page.get("next_max_id")

    def answer(params: dict[str, Any]) -> dict[str, Any]:
        return by_cursor[params.get("max_id")]

    return answer


def ig_node(
    shortcode: str,
    typename: str = "GraphImage",
    *,
    caption: str | None = "Pasta #Rezept @Chef",
    date: int = 1_700_000_000,
    video_url: str | None = None,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A saved-feed node as delivered by the GraphQL saved-media query."""
    node: dict[str, Any] = {
        "shortcode": shortcode,
        "__typename": typename,
        "is_video": typename == "GraphVideo",
        "taken_at_timestamp": date,
        "display_url": f"https://scontent.cdninstagram.com/{shortcode}.jpg?oe=EXPIRES",
        "owner": {"id": "123", "username": "chef"},
        "edge_media_preview_like": {"count": 10},
        "edge_media_to_comment": {"count": 2},
        "edge_media_to_caption": {"edges": [{"node": {"text": caption}}] if caption else []},
    }
    if video_url is not None:
        node["video_url"] = video_url
        node["video_duration"] = 31.5
    if children is not None:
        node["edge_sidecar_to_children"] = {"edges": [{"node": c} for c in children]}
    return node


def ig_post(node: dict[str, Any], context: Any | None = None) -> instaloader.Post:
    return instaloader.Post(context or FakeIgContext("me"), node)


class Feed:
    """Saved feed that records how far it was consumed and can fail mid-way."""

    def __init__(
        self,
        posts: list[instaloader.Post],
        *,
        fail_at: int | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.posts = posts
        self.fail_at = fail_at
        self.error = error or RuntimeError("feed broke")
        self.consumed = 0

    def __call__(self, loader: Any) -> Iterator[instaloader.Post]:
        for index, post in enumerate(self.posts):
            if self.fail_at is not None and index >= self.fail_at:
                raise self.error
            self.consumed = index + 1
            yield post


def loader_factory(loader: FakeLoader):
    return lambda options: loader


class SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
