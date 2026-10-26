"""Unit tests for the database check of the health router."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from postparse.api.routers.health import database_check
from postparse.core.db import Database
from postparse.core.db.migrate import latest_version
from postparse.core.db.models import ItemUpsert
from postparse.core.db.repos import ItemsRepo


def _services(db: Database) -> SimpleNamespace:
    return SimpleNamespace(db=db)


def test_empty_database_is_ok(tmp_path: Path) -> None:
    result = database_check(_services(Database.open(tmp_path / "h.db")))
    assert result["status"] == "ok"
    assert result["items"] == 0 and result["fts_in_sync"] is True
    assert result["schema_version"] == latest_version()


def test_counts_items_and_index(tmp_path: Path) -> None:
    db = Database.open(tmp_path / "h.db")
    with db.transaction() as conn:
        for n in range(3):
            ItemsRepo(conn).upsert(ItemUpsert(source="telegram", external_id=f"1:{n}",
                                              kind="text", text=f"message {n}"))
    result = database_check(_services(db))
    assert (result["items"], result["fts_indexed"]) == (3, 3)


def test_outdated_schema_is_degraded(tmp_path: Path) -> None:
    db = Database.open(tmp_path / "h.db")
    with db.transaction() as conn:
        conn.execute("PRAGMA user_version = 1")
    result = database_check(_services(db))
    assert result["status"] == "degraded" and result["schema_version"] == 1


def test_unreadable_database_is_error(tmp_path: Path) -> None:
    folder = tmp_path / "not-a-db"
    folder.mkdir()
    result = database_check(_services(Database(folder, migrate=False)))
    assert result["status"] == "error" and "error" in result
