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


class FakeIgContext:
    """instaloader context that refuses every request."""

    def __init__(self, username: str | None = None) -> None:
        self.username = username
        self.is_logged_in = username is not None
        self.iphone_support = False

    def _refuse(self, *args: Any, **kwargs: Any) -> Any:
        raise NetworkUsed("unexpected Instagram request")

    graphql_query = doc_id_graphql_query = get_json = get_iphone_json = head = _refuse

    def error(self, *args: Any, **kwargs: Any) -> None:
        return None

    def log(self, *args: Any, **kwargs: Any) -> None:
        return None


class FakeLoader:
    """Stand-in for ``instaloader.Instaloader`` (login/session methods only)."""

    def __init__(
        self,
        *,
        session_user: str | None = None,
        login_error: BaseException | None = None,
        two_factor_error: BaseException | None = None,
        test_login_error: BaseException | None = None,
    ) -> None:
        self.context = FakeIgContext()
        self.session_user = session_user
        self.login_error = login_error
        self.two_factor_error = two_factor_error
        self.test_login_error = test_login_error
        self.loaded: list[tuple[str, str]] = []
        self.logins: list[str] = []
        self.two_factor_codes: list[str] = []
        self.saved: list[str] = []

    def load_session_from_file(self, username: str, filename: str) -> None:
        self.loaded.append((username, filename))
        self.context.username = username

    def test_login(self) -> str | None:
        if self.test_login_error is not None:
            raise self.test_login_error
        return self.session_user

    def login(self, user: str, passwd: str) -> None:
        self.logins.append(user)
        if self.login_error is not None:
            raise self.login_error
        self.context.username = user
        self.context.is_logged_in = True

    def two_factor_login(self, code: str) -> None:
        self.two_factor_codes.append(code)
        if self.two_factor_error is not None:
            raise self.two_factor_error
        self.context.is_logged_in = True

    def save_session_to_file(self, filename: str) -> None:
        self.saved.append(filename)
        Path(filename).write_text("fake-session", encoding="utf-8")


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
