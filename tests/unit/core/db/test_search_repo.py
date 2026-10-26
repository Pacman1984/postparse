"""Tests for the full-text search documents and FTS5 index."""

from __future__ import annotations

import sqlite3

from postparse.core.db.models import ItemUpsert, MediaInput
from postparse.core.db.repos import (
    ItemsRepo,
    LinksRepo,
    SearchRepo,
    SummariesRepo,
    TranscriptsRepo,
)


def _match(conn: sqlite3.Connection, query: str) -> list[int]:
    rows = conn.execute(
        "SELECT rowid FROM items_fts WHERE items_fts MATCH ? ORDER BY rowid", (query,)
    ).fetchall()
    return [row[0] for row in rows]


def test_insert_update_delete_reflected(conn: sqlite3.Connection) -> None:
    repo = ItemsRepo(conn)
    item_id, _ = repo.upsert(ItemUpsert("telegram", "1", "text", text="banana bread"))
    assert _match(conn, "banana") == [item_id]

    repo.upsert(ItemUpsert("telegram", "1", "text", text="apple pie"))
    assert _match(conn, "banana") == []
    assert _match(conn, "apple") == [item_id]

    repo.delete(item_id)
    assert _match(conn, "apple") == []
    assert SearchRepo(conn).integrity_check()


def test_diacritics_are_folded(conn: sqlite3.Connection) -> None:
    item_id, _ = ItemsRepo(conn).upsert(
        ItemUpsert("telegram", "1", "text", text="Crème brûlée im Café Müller")
    )
    for query in ("creme", "brulee", "cafe", "muller", "MÜLLER"):
        assert _match(conn, query) == [item_id], query


def test_derived_content_is_searchable(conn: sqlite3.Connection) -> None:
    items = ItemsRepo(conn)
    item_id, _ = items.upsert(
        ItemUpsert(
            "instagram", "abc", "video", text="watch https://blog.example/post",
            hashtags=("veggie",), media=(MediaInput(0, "video"),),
        )
    )
    media_id = conn.execute("SELECT id FROM media WHERE item_id = ?", (item_id,)).fetchone()[0]
    TranscriptsRepo(conn).add(media_id, backend="whisper", model="small", text="spoken words")
    SummariesRepo(conn).add(item_id, "old summary")
    SummariesRepo(conn).add(item_id, "fresh overview")
    links = LinksRepo(conn)
    link_id = links.ensure("https://blog.example/post")
    links.add_fetch(link_id, fetcher="http", status="error", text="ignored failure")
    links.add_fetch(link_id, fetcher="http", status="ok", title="Lentil Guide", text="body")
    items.set_legacy_expanded_text(item_id, "legacy expansion")

    for query in ("spoken", "overview", "lentil", "legacy", "veggie"):
        assert _match(conn, query) == [item_id], query
    assert _match(conn, "old") == []  # only the latest summary is indexed
    assert _match(conn, "ignored") == []  # failed fetches are not indexed
    assert _match(conn, "tags:veggie") == [item_id]

    TranscriptsRepo(conn).add(media_id, backend="whisper", model="small", text="replaced")
    assert _match(conn, "spoken") == []
    assert _match(conn, "replaced") == [item_id]


def test_rebuild_all_repairs_out_of_sync_index(conn: sqlite3.Connection) -> None:
    item_id, _ = ItemsRepo(conn).upsert(ItemUpsert("telegram", "1", "text", text="kiwi"))
    # Simulate a raw write that bypassed the repositories.
    conn.execute("UPDATE items SET text = 'mango' WHERE id = ?", (item_id,))
    conn.execute("DELETE FROM search_docs")
    assert _match(conn, "mango") == []
    assert SearchRepo(conn).rebuild_all() == 1
    assert _match(conn, "mango") == [item_id]
    assert SearchRepo(conn).indexed_count() == 1
    assert SearchRepo(conn).integrity_check()


def test_unchanged_refresh_does_not_rewrite(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TEMP TABLE doc_log (op TEXT)")
    conn.execute(
        "CREATE TEMP TRIGGER log_doc_update AFTER UPDATE ON main.search_docs "
        "BEGIN INSERT INTO doc_log VALUES ('update'); END"
    )
    item_id, _ = ItemsRepo(conn).upsert(ItemUpsert("telegram", "1", "text", text="same"))
    SearchRepo(conn).refresh([item_id])
    assert conn.execute("SELECT count(*) FROM doc_log").fetchone()[0] == 0
    ItemsRepo(conn).upsert(ItemUpsert("telegram", "1", "text", text="changed"))
    assert conn.execute("SELECT count(*) FROM doc_log").fetchone()[0] == 1
