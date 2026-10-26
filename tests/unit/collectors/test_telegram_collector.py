"""Tests of the Telegram collector against a fake Telethon client."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from telethon.errors import FloodWaitError, PhoneCodeInvalidError

from postparse.collectors.base import TelegramAuthRequired, TelegramRateLimited, safe_filename
from postparse.collectors.credentials import TelegramCredentials
from postparse.collectors.telegram.collector import (
    TelegramCollector,
    TelegramOptions,
    resolve_session_path,
)
from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.repos import ItemsRepo, LinksRepo, MediaRepo, TagsRepo

from .fakes import (
    ME,
    FakeTelegramClient,
    client_factory,
    no_sleep,
    tg_document,
    tg_forward,
    tg_links,
    tg_photo,
    tg_text,
    tg_video,
    tg_voice,
)

CREDS = TelegramCredentials(api_id=1, api_hash="hash-secret", phone="+490000")


async def collect(
    db: Database,
    settings: Settings,
    client: FakeTelegramClient,
    *,
    interactive: bool = True,
    options: TelegramOptions | None = None,
    sleep=no_sleep,
    **kwargs,
):
    collector = TelegramCollector(
        db,
        settings,
        CREDS,
        options or TelegramOptions(batch_size=2),
        interactive=interactive,
        client_factory=client_factory(client),
        sleep=sleep,
    )
    async with collector:
        return await collector.collect(**kwargs)


def _item(db: Database, message_id: int):
    with db.read() as conn:
        repo = ItemsRepo(conn)
        item = repo.get_by_external("telegram", f"{ME}:{message_id}")
        assert item is not None
        return (
            item,
            repo.telegram_detail(item.id),
            MediaRepo(conn).for_item(item.id),
            [link.url for link in LinksRepo(conn).for_items([item.id]).get(item.id, [])],
            [tag.display for tag in TagsRepo(conn).for_item(item.id)],
        )


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


async def test_text_with_url_entities_and_tags(db: Database, settings: Settings) -> None:
    stats = await collect(db, settings, FakeTelegramClient([tg_links(1)]))

    assert (stats.new, stats.updated, stats.stopped_reason) == (1, 0, "end_of_feed")
    item, detail, media, links, tags = _item(db, 1)
    assert item.kind == "text"
    assert item.created_at is not None and item.created_at.utcoffset().total_seconds() == 0
    assert detail.chat_id == ME and detail.message_id == 1
    assert media == []
    assert links == [
        "https://example.com/a",
        "https://hidden.example/page",
        "https://plain.org/x",
    ]
    assert set(tags) == {"#rezept", "@koch"}


async def test_forward_origin_and_counters(db: Database, settings: Settings) -> None:
    await collect(db, settings, FakeTelegramClient([tg_forward(5)]))

    item, detail, *_ = _item(db, 5)
    assert item.author == "Chef Channel"
    assert detail.fwd_from_name == "Chef Channel"
    assert detail.fwd_from_id == -1000000000777
    assert detail.fwd_from_post_id == 99
    assert (detail.views, detail.forwards) == (150, 3)


async def test_photo_is_downloaded_with_hash(db: Database, settings: Settings) -> None:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = FakeTelegramClient([tg_photo(7, size=100)])
    stats = await collect(db, settings, client, sleep=sleep)

    item, _, media, *_ = _item(db, 7)
    assert item.kind == "image"
    assert stats.media_downloaded == 1
    assert len(sleeps) == 1
    row = media[0]
    assert row.local_path == "telegram/2024/03/05/7_photo.jpg"
    target = settings.downloads_dir / row.local_path
    assert target.read_bytes() == b"x" * 64 + b"7"
    assert row.sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    assert row.size_bytes == target.stat().st_size
    assert (row.media_type, row.mime, row.transcript_status) == ("image", "image/jpeg", "none")


async def test_document_name_from_attribute_is_sanitized(db: Database, settings: Settings) -> None:
    client = FakeTelegramClient([tg_document(8, filename="../Mein Rezept (fïnal).pdf")])
    await collect(db, settings, client)

    item, _, media, *_ = _item(db, 8)
    assert item.kind == "document"
    assert media[0].local_path == "telegram/2024/03/05/8_Mein_Rezept_final_.pdf"
    assert media[0].mime == "application/pdf"


async def test_document_without_filename_uses_mime_extension(
    db: Database, settings: Settings
) -> None:
    await collect(db, settings, FakeTelegramClient([tg_document(9, filename=None)]))

    _, _, media, *_ = _item(db, 9)
    assert media[0].local_path == "telegram/2024/03/05/9_document.pdf"


async def test_voice_and_video_are_recorded_without_download(
    db: Database, settings: Settings
) -> None:
    client = FakeTelegramClient([tg_voice(10, duration=7), tg_video(11, duration=12.5)])
    stats = await collect(db, settings, client)

    assert client.downloads == [] and stats.media_downloaded == 0
    voice, _, voice_media, *_ = _item(db, 10)
    video, _, video_media, *_ = _item(db, 11)
    assert (voice.kind, video.kind) == ("audio", "video")
    assert voice_media[0].media_type == "audio" and voice_media[0].local_path is None
    assert voice_media[0].transcript_status == "none"
    assert voice_media[0].duration_s == 7.0 and voice_media[0].mime == "audio/ogg"
    assert video_media[0].media_type == "video" and video_media[0].local_path is None
    assert video_media[0].transcript_status == "none"
    assert video_media[0].size_bytes == 10_000_000


async def test_files_over_max_size_are_not_downloaded(db: Database, settings: Settings) -> None:
    client = FakeTelegramClient([tg_document(12, size=3 * 1024 * 1024)])
    stats = await collect(
        db, settings, client, options=TelegramOptions(batch_size=5, max_download_mb=2)
    )

    _, _, media, *_ = _item(db, 12)
    assert client.downloads == [] and stats.media_downloaded == 0
    assert media[0].local_path is None
    assert media[0].size_bytes == 3 * 1024 * 1024


async def test_download_failure_keeps_row_and_reports_error(
    db: Database, settings: Settings
) -> None:
    client = FakeTelegramClient([tg_photo(13)], download_error=OSError("disk full"))
    stats = await collect(db, settings, client)

    _, _, media, *_ = _item(db, 13)
    assert media[0].local_path is None
    assert stats.errors and "13" in stats.errors[0]


def test_safe_filename() -> None:
    assert safe_filename("Café menu.PDF") == "Cafe_menu.PDF"
    assert safe_filename("..\\..\\evil.exe") == "evil.exe"
    assert safe_filename("😀😀", fallback="document.bin") == "document.bin"
    long = safe_filename("a" * 300 + ".jpeg")
    assert len(long) == 100 and long.endswith(".jpeg")


# ---------------------------------------------------------------------------
# Incremental / full / limit / batches
# ---------------------------------------------------------------------------


async def test_incremental_run_uses_min_id(db: Database, settings: Settings) -> None:
    first = FakeTelegramClient([tg_text(i, f"m{i}") for i in (1, 2, 3)])
    await collect(db, settings, first)
    assert first.iter_calls[0] == {"entity": "me", "limit": None, "min_id": 0, "reverse": True}

    second = FakeTelegramClient([tg_text(i, f"m{i}") for i in (1, 2, 3, 4, 5)])
    stats = await collect(db, settings, second)

    assert second.iter_calls[0]["min_id"] == 3
    assert (stats.new, stats.updated, stats.processed) == (2, 0, 2)


async def test_full_reread_updates_stored_messages(db: Database, settings: Settings) -> None:
    await collect(db, settings, FakeTelegramClient([tg_text(1, "old"), tg_text(2, "two")]))

    stats = await collect(
        db,
        settings,
        FakeTelegramClient([tg_text(1, "edited"), tg_text(2, "two"), tg_text(3, "three")]),
        full=True,
    )

    assert (stats.new, stats.updated) == (1, 2)
    item, *_ = _item(db, 1)
    assert item.text == "edited"


async def test_limit(db: Database, settings: Settings) -> None:
    client = FakeTelegramClient([tg_text(i, "x") for i in range(1, 11)])
    stats = await collect(db, settings, client, limit=4)

    assert client.iter_calls[0]["limit"] == 4
    assert (stats.new, stats.stopped_reason) == (4, "limit")
    with db.read() as conn:
        assert ItemsRepo(conn).max_telegram_message_id(ME) == 4  # oldest first


async def test_batches_survive_a_failed_batch(
    db: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ItemsRepo.upsert

    def upsert(self, item):
        if item.external_id == f"{ME}:3":
            raise RuntimeError("disk I/O error")
        return original(self, item)

    monkeypatch.setattr(ItemsRepo, "upsert", upsert)
    client = FakeTelegramClient([tg_text(i, "x") for i in range(1, 6)])
    collector = TelegramCollector(
        db,
        settings,
        CREDS,
        TelegramOptions(batch_size=2),
        client_factory=client_factory(client),
        sleep=no_sleep,
    )
    with pytest.raises(RuntimeError, match="disk I/O"):
        async with collector:
            await collector.collect()

    with db.read() as conn:
        assert ItemsRepo(conn).max_telegram_message_id(ME) == 2
    assert collector.stats.batches_committed == 1
    assert collector.stats.new == 2


async def test_connection_loss_keeps_messages_read_so_far(db: Database, settings: Settings) -> None:
    client = FakeTelegramClient([tg_text(i, "x") for i in range(1, 8)], fail_after=5)
    collector = TelegramCollector(
        db,
        settings,
        CREDS,
        TelegramOptions(batch_size=2),
        client_factory=client_factory(client),
        sleep=no_sleep,
    )
    with pytest.raises(RuntimeError, match="connection lost"):
        async with collector:
            await collector.collect()

    with db.read() as conn:
        assert ItemsRepo(conn).max_telegram_message_id(ME) == 5
    assert client.disconnected


async def test_flood_wait_stops_with_rate_limited(db: Database, settings: Settings) -> None:
    client = FakeTelegramClient(
        [tg_text(i, "x") for i in range(1, 6)],
        fail_after=3,
        fail_with=FloodWaitError(request=None, capture=600),
    )
    collector = TelegramCollector(
        db,
        settings,
        CREDS,
        TelegramOptions(batch_size=2),
        client_factory=client_factory(client),
        sleep=no_sleep,
    )
    with pytest.raises(TelegramRateLimited) as info:
        async with collector:
            await collector.collect()

    assert info.value.retry_after == 600
    assert collector.stats.stopped_reason == "rate_limited"
    assert collector.stats.new == 3


# ---------------------------------------------------------------------------
# Auth and sessions
# ---------------------------------------------------------------------------


async def test_unauthorized_non_interactive_raises(db: Database, settings: Settings) -> None:
    client = FakeTelegramClient([tg_text(1)], authorized=False)
    with pytest.raises(TelegramAuthRequired, match="extract telegram"):
        await collect(db, settings, client, interactive=False)
    assert client.started_with == []
    assert client.disconnected


async def test_unauthorized_interactive_starts_login(db: Database, settings: Settings) -> None:
    client = FakeTelegramClient([tg_text(1, "hi")], authorized=False)
    stats = await collect(db, settings, client, interactive=True)

    assert client.started_with == ["+490000"]
    assert stats.new == 1


async def test_failed_interactive_login_is_auth_required(db: Database, settings: Settings) -> None:
    client = FakeTelegramClient(authorized=False, start_error=PhoneCodeInvalidError(request=None))
    with pytest.raises(TelegramAuthRequired, match="PhoneCodeInvalidError"):
        await collect(db, settings, client)


def test_session_path_fallback_order(settings: Settings) -> None:
    new = settings.sessions_dir / "telegram.session"
    legacy = settings.data_dir / "cache" / "telegram_session.session"

    assert resolve_session_path(settings) == new  # nothing exists: new location

    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"")
    assert resolve_session_path(settings) == legacy

    new.parent.mkdir(parents=True)
    new.write_bytes(b"")
    assert resolve_session_path(settings) == new

    assert resolve_session_path(settings, "telegram_session") == legacy
    assert resolve_session_path(settings, "other") == settings.sessions_dir / "other.session"
    explicit = Path("custom/dir/my.session")
    assert resolve_session_path(settings, explicit) == explicit.resolve()


async def test_collector_uses_resolved_session(db: Database, settings: Settings) -> None:
    legacy = settings.data_dir / "cache" / "telegram_session.session"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"")
    sessions: list[Path] = []
    collector = TelegramCollector(
        db,
        settings,
        CREDS,
        client_factory=client_factory(FakeTelegramClient(), sessions),
        sleep=no_sleep,
    )
    async with collector:
        await collector.collect()
    assert sessions == [legacy]
    assert legacy.exists()  # never moved
