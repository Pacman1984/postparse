"""Constraint tests for schema v2 (CHECKs, STRICT typing, FKs, cascades)."""

from __future__ import annotations

import sqlite3

import pytest

from postparse.core.db.models import InstagramDetail, ItemUpsert, MediaInput
from postparse.core.db.repos import (
    ClassificationRepo,
    ItemsRepo,
    LinksRepo,
    SummariesRepo,
    TranscriptsRepo,
)

TS = "2024-01-15T10:00:00.000Z"


def _insert_item(conn: sqlite3.Connection, **overrides: object) -> None:
    values = {"source": "telegram", "external_id": "1", "kind": "text", "created_at": TS}
    values.update(overrides)
    conn.execute(
        "INSERT INTO items (source, external_id, kind, created_at) VALUES (?, ?, ?, ?)",
        (values["source"], values["external_id"], values["kind"], values["created_at"]),
    )


@pytest.mark.parametrize(
    "bad_ts",
    ["2024-01-15 10:00:00", "2024-01-15T10:00:00Z", "2024-01-15T10:00:00+00:00", "yesterday"],
)
def test_non_canonical_timestamp_rejected(conn: sqlite3.Connection, bad_ts: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _insert_item(conn, created_at=bad_ts)


@pytest.mark.parametrize(("column", "value"), [("source", "twitter"), ("kind", "reel")])
def test_enum_checks(conn: sqlite3.Connection, column: str, value: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _insert_item(conn, **{column: value})


def test_default_timestamps_are_canonical(conn: sqlite3.Connection) -> None:
    _insert_item(conn, created_at=None)
    row = conn.execute("SELECT collected_at, updated_at, sort_at FROM items").fetchone()
    assert row["sort_at"] == row["collected_at"]
    assert len(row["collected_at"]) == 24 and row["collected_at"].endswith("Z")


def test_strict_typing(conn: sqlite3.Connection) -> None:
    _insert_item(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO telegram_messages (item_id, chat_id, message_id) VALUES (1, 'abc', 1)"
        )


def test_foreign_keys_enforced(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("INSERT INTO media (item_id, media_type) VALUES (999, 'image')")


def test_json_checks(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO taxonomies (name, mode, labels, label_set_sha256) "
            "VALUES ('x', 'multi', 'not json', 'h')"
        )


def test_confidence_range(conn: sqlite3.Connection) -> None:
    repo = ClassificationRepo(conn)
    tax = repo.ensure_taxonomy("topics", "multi", ["a"])
    item_id, _ = ItemsRepo(conn).upsert(ItemUpsert("telegram", "1", "text", text="x"))
    run = repo.create_run(tax.id)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        repo.add_result(run, item_id, "ok", [("a", 0.5)], confidence=1.5)


def test_cascade_delete_removes_everything(conn: sqlite3.Connection) -> None:
    items = ItemsRepo(conn)
    item_id, _ = items.upsert(
        ItemUpsert(
            "instagram",
            "abc",
            "video",
            text="see https://example.com/x",
            detail=InstagramDetail("abc"),
            hashtags=("food",),
            media=(MediaInput(0, "video", local_path="ig/abc.mp4"),),
        )
    )
    media_id = conn.execute("SELECT id FROM media").fetchone()[0]
    TranscriptsRepo(conn).add(media_id, backend="whisper", model="small", text="hello")
    SummariesRepo(conn).add(item_id, "summary")
    links = LinksRepo(conn)
    links.add_fetch(links.ensure("https://example.com/x"), fetcher="http", status="ok", text="t")
    repo = ClassificationRepo(conn)
    tax = repo.ensure_taxonomy("topics", "multi", ["a"])
    repo.add_result(repo.create_run(tax.id), item_id, "ok", ["a"])
    items.set_legacy_expanded_text(item_id, "legacy")

    assert items.delete(item_id)
    for table in (
        "instagram_posts",
        "item_tags",
        "media",
        "transcripts",
        "summaries",
        "item_links",
        "classification_results",
        "result_labels",
        "legacy_expanded_text",
        "search_docs",
        "items_fts_docsize",
    ):
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    # Shared rows survive: tags, links and their fetches.
    assert conn.execute("SELECT count(*) FROM tags").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM link_fetches").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
