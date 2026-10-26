"""Tests for the schema v2 migration runner and connection setup."""

from __future__ import annotations

from pathlib import Path

import pytest

from postparse.core.db import Database, MigrationError, connect, latest_version, migrate
from postparse.core.db.migrate import (
    Migration,
    _statements,
    applied_migrations,
    discover_migrations,
    pending_migrations,
)


def test_fresh_apply_creates_schema_and_records_versions(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "v2.db"
    db = Database.open(path)
    assert path.exists()
    with db.read() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == latest_version() >= 1
        assert set(applied_migrations(conn)) == {m.version for m in discover_migrations()}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        assert {"items", "media", "search_docs", "items_fts", "taxonomies"} <= tables
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        strict = conn.execute(
            "SELECT count(*) FROM pragma_table_list WHERE schema='main' AND type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'items_fts%' AND strict = 0"
        ).fetchone()[0]
        assert strict == 0, "all regular tables must be STRICT"


def test_rerun_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "v2.db"
    Database.open(path)
    conn = connect(path)
    try:
        before = applied_migrations(conn)
        assert migrate(conn) == []
        assert applied_migrations(conn) == before
    finally:
        conn.close()


def test_changed_checksum_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "v2.db"
    Database.open(path)
    conn = connect(path)
    try:
        conn.execute("UPDATE schema_migrations SET sha256 = 'tampered' WHERE version = 1")
        with pytest.raises(MigrationError, match="Checksum mismatch"):
            migrate(conn)
        with pytest.raises(MigrationError):
            pending_migrations(conn)
    finally:
        conn.close()


def test_unknown_newer_migration_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "v2.db"
    Database.open(path)
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO schema_migrations VALUES (99, 'future', 'x', '2026-01-01T00:00:00.000Z')"
        )
        with pytest.raises(MigrationError, match="does not know"):
            migrate(conn)
    finally:
        conn.close()


def test_foreign_non_empty_database_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    conn = connect(path)
    try:
        conn.execute("CREATE TABLE instagram_posts (id INTEGER PRIMARY KEY)")
        with pytest.raises(MigrationError, match="legacy"):
            migrate(conn)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_schema")}
        assert names == {"instagram_posts"}
    finally:
        conn.close()


def test_crlf_checkout_has_same_checksum() -> None:
    lf = Migration.from_text("0001_x.sql", "CREATE TABLE a (x INTEGER) STRICT;\n")
    crlf = Migration.from_text("0001_x.sql", "CREATE TABLE a (x INTEGER) STRICT;\r\n")
    assert lf.sha256 == crlf.sha256


def test_failed_migration_rolls_back(tmp_path: Path) -> None:
    conn = connect(tmp_path / "custom.db")
    try:
        good = Migration.from_text("0001_one.sql", "CREATE TABLE a (x INTEGER) STRICT;\n")
        bad = Migration.from_text(
            "0002_two.sql", "CREATE TABLE b (x INTEGER) STRICT;\nTHIS IS NOT SQL;\n"
        )
        with pytest.raises(MigrationError, match="0002_two failed"):
            migrate(conn, [good, bad])
        assert set(applied_migrations(conn)) == {1}
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_schema")}
        assert "a" in names and "b" not in names
    finally:
        conn.close()


def test_invalid_file_name_rejected() -> None:
    with pytest.raises(MigrationError):
        Migration.from_text("1_bad.sql", "")


def test_statement_splitter_keeps_trigger_bodies() -> None:
    sql = (
        "-- comment\nCREATE TABLE t (x INTEGER);\n"
        "CREATE TRIGGER tr AFTER INSERT ON t BEGIN\n  SELECT 1;\n  SELECT 2;\nEND;\n-- end\n"
    )
    statements = _statements(sql)
    assert len(statements) == 2
    assert statements[1].endswith("END;")


def test_migration_files_are_packaged_and_contiguous() -> None:
    migrations = discover_migrations()
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "initial"


def test_memory_database_rejected() -> None:
    with pytest.raises(ValueError):
        Database(":memory:")


def test_transaction_rolls_back_on_error(db: Database) -> None:
    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute(
            "INSERT INTO items (source, external_id, kind) VALUES ('telegram', '1', 'text')"
        )
        raise RuntimeError("boom")
    with db.read() as conn:
        assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 0
