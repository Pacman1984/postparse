"""Tests for ItemsRepo, TagsRepo, MediaRepo and LinksRepo."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from postparse.core.db.models import (
    InstagramDetail,
    ItemUpsert,
    MediaInput,
    TelegramDetail,
)
from postparse.core.db.repos import ItemsRepo, LinksRepo, MediaRepo, TagsRepo, TranscriptsRepo
from postparse.core.db.repos.media import normalize_local_path


def _ig(shortcode: str = "abc", **kwargs: object) -> ItemUpsert:
    base: dict[str, object] = {
        "source": "instagram",
        "external_id": shortcode,
        "kind": "image",
        "text": "Hello",
        "detail": InstagramDetail(shortcode, likes=1),
        "collected_at": "2024-02-01T00:00:00Z",
    }
    base.update(kwargs)
    return ItemUpsert(**base)  # type: ignore[arg-type]


def test_upsert_update_preserves_collected_at(conn: sqlite3.Connection) -> None:
    repo = ItemsRepo(conn)
    item_id, created = repo.upsert(_ig())
    assert created
    first = repo.get(item_id)
    assert first is not None

    again_id, created_again = repo.upsert(
        _ig(
            text="Edited",
            collected_at="2025-05-05T00:00:00Z",
            detail=InstagramDetail("abc", likes=5),
        )
    )
    assert (again_id, created_again) == (item_id, False)
    item = repo.get(item_id)
    assert item is not None
    assert item.text == "Edited"
    assert item.collected_at == first.collected_at
    assert item.updated_at >= first.updated_at
    detail = repo.instagram_detail(item_id)
    assert detail is not None and detail.likes == 5


def test_upsert_none_keeps_values(conn: sqlite3.Connection) -> None:
    repo = ItemsRepo(conn)
    item_id, _ = repo.upsert(_ig(author="alice", created_at="2024-01-01T00:00:00Z"))
    repo.upsert(_ig(text=None, author=None, detail=InstagramDetail("abc")))
    item = repo.get(item_id)
    assert item is not None
    assert (item.text, item.author) == ("Hello", "alice")
    assert item.created_at == datetime(2024, 1, 1, tzinfo=UTC)
    detail = repo.instagram_detail(item_id)
    assert detail is not None and detail.likes == 1


def test_detail_must_match_source(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        ItemsRepo(conn).upsert(ItemUpsert("instagram", "1", "text", detail=TelegramDetail(1, 1)))


def test_naive_timestamp_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="assume_tz"):
        ItemsRepo(conn).upsert(_ig(created_at=datetime(2024, 1, 1)))


def test_tags_replaced_per_kind(conn: sqlite3.Connection) -> None:
    repo = ItemsRepo(conn)
    item_id, _ = repo.upsert(_ig(hashtags=("#Food", "pasta", "food"), mentions=("@Chef",)))
    tags = TagsRepo(conn).for_item(item_id)
    assert [t.display for t in tags] == ["#food", "#pasta", "@chef"]

    repo.upsert(_ig(hashtags=("dinner",)))  # mentions=None keeps mentions
    assert [t.display for t in TagsRepo(conn).for_item(item_id)] == ["#dinner", "@chef"]

    repo.upsert(_ig(hashtags=(), mentions=()))
    assert TagsRepo(conn).for_item(item_id) == []


def test_media_upsert_preserves_transcript_state(conn: sqlite3.Connection) -> None:
    repo = ItemsRepo(conn)
    item_id, _ = repo.upsert(
        _ig(kind="video", media=(MediaInput(0, "video", local_path="ig\\abc.mp4"),))
    )
    media_repo = MediaRepo(conn)
    (media,) = media_repo.for_item(item_id)
    assert media.local_path == "ig/abc.mp4"
    assert media.transcript_status == "pending"
    TranscriptsRepo(conn).add(media.id, backend="whisper", model="base", text="spoken")
    media_repo.mark_transcribed(media.id)

    repo.upsert(
        _ig(
            kind="video",
            media=(
                MediaInput(0, "video", remote_url="https://cdn/x.mp4", duration_s=3.5),
                MediaInput(1, "image"),
            ),
        )
    )
    first, second = media_repo.for_item(item_id)
    assert first.id == media.id
    assert first.transcript_status == "transcribed"
    assert first.local_path == "ig/abc.mp4"  # not clobbered by NULL
    assert first.remote_url == "https://cdn/x.mp4" and first.remote_url_seen_at is not None
    assert first.duration_s == 3.5
    assert second.transcript_status == "none"


def test_local_path_must_be_relative() -> None:
    for bad in ("/abs/x.mp4", "C:\\x.mp4", "../x.mp4", ""):
        with pytest.raises(ValueError):
            normalize_local_path(bad)
    assert normalize_local_path("a\\b\\c.jpg") == "a/b/c.jpg"


def test_pending_transcriptions_and_backoff(conn: sqlite3.Connection) -> None:
    repo = ItemsRepo(conn)
    repo.upsert(_ig("a", kind="video", media=(MediaInput(0, "video"),)))
    repo.upsert(
        ItemUpsert(
            "telegram", "1:1", "audio", media=(MediaInput(0, "audio"),), detail=TelegramDetail(1, 1)
        )
    )
    media_repo = MediaRepo(conn)
    now = datetime(2025, 1, 1, tzinfo=UTC)
    due = media_repo.pending_transcriptions(now=now)
    assert len(due) == 2
    assert len(media_repo.pending_transcriptions(source="telegram", now=now)) == 1

    target = due[0].id
    next_at = media_repo.mark_failed(target, "boom", backoff=timedelta(minutes=10), now=now)
    assert next_at == now + timedelta(minutes=10)
    assert target not in {m.id for m in media_repo.pending_transcriptions(now=now)}
    assert target in {
        m.id for m in media_repo.pending_transcriptions(now=now + timedelta(minutes=10))
    }
    second = media_repo.mark_failed(target, "boom", backoff=timedelta(minutes=10), now=now)
    assert second == now + timedelta(minutes=20)
    failed = media_repo.get(target)
    assert failed is not None
    assert (failed.transcript_status, failed.attempts, failed.last_error) == ("failed", 2, "boom")
    later = now + timedelta(days=2)
    assert target not in {
        m.id for m in media_repo.pending_transcriptions(now=later, max_attempts=2)
    }


def test_lookup_helpers(conn: sqlite3.Connection) -> None:
    repo = ItemsRepo(conn)
    repo.upsert(_ig("a"))
    repo.upsert(_ig("b"))
    for chat, msg in ((1, 5), (1, 9), (2, 3)):
        repo.upsert(
            ItemUpsert("telegram", f"{chat}:{msg}", "text", detail=TelegramDetail(chat, msg))
        )
    assert repo.exists("instagram", "a") and not repo.exists("instagram", "zzz")
    found = repo.get_by_external("telegram", "1:9")
    assert found is not None and found.source == "telegram"
    assert repo.max_telegram_message_id() == 9
    assert repo.max_telegram_message_id(2) == 3
    assert repo.max_telegram_message_id(42) is None
    assert repo.known_instagram_shortcodes(["a", "c", "b", "a"]) == {"a", "b"}
    assert repo.known_instagram_shortcodes([]) == set()


def test_links_extracted_normalized_and_deduplicated(conn: sqlite3.Connection) -> None:
    repo = ItemsRepo(conn)
    item_id, _ = repo.upsert(
        _ig(
            text="a https://Example.com/p?utm_source=x&b=1 and "
            "https://example.com/p?b=1#frag, then (https://other.org/x)."
        )
    )
    links = LinksRepo(conn).for_items([item_id])[item_id]
    assert [link.url for link in links] == ["https://example.com/p?b=1", "https://other.org/x"]
    assert links[0].domain == "example.com"

    repo.upsert(_ig(links=("https://third.net/",)))
    assert [link.url for link in LinksRepo(conn).for_items([item_id])[item_id]] == [
        "https://third.net/"
    ]


def test_links_needing_fetch(conn: sqlite3.Connection) -> None:
    repo = ItemsRepo(conn)
    repo.upsert(_ig(text="https://a.com https://b.com https://c.com"))
    links = LinksRepo(conn)
    a, b, c = (links.ensure(u) for u in ("https://a.com", "https://b.com", "https://c.com"))
    links.ensure("https://orphan.com")  # not linked by any item
    links.add_fetch(a, fetcher="http", status="ok", title="A")
    links.add_fetch(b, fetcher="http", status="error", error="timeout")
    assert [link.id for link in links.links_needing_fetch()] == [c]
    assert [link.id for link in links.links_needing_fetch(include_failed=True)] == [b, c]
    assert [link.id for link in links.links_needing_fetch(fetcher="other")] == [a, b, c]
    fetch = links.latest_ok_fetch(a)
    assert fetch is not None and fetch.title == "A"
    assert links.latest_ok_fetch(b) is None
