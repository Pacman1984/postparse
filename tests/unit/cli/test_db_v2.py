"""Tests for `postparse db migrate | check | reindex` against a tmp database."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from postparse.cli.main import cli
from postparse.core.db import Database, connect
from postparse.core.db.models import ItemUpsert


def test_migrate_creates_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "v2.db"
    runner = CliRunner()
    first = runner.invoke(cli, ["db", "migrate", "--db", str(path)])
    assert first.exit_code == 0, first.output
    assert "Applied 1 migration" in first.output
    assert path.exists()
    second = runner.invoke(cli, ["db", "migrate", "--db", str(path)])
    assert second.exit_code == 0
    assert "up to date" in second.output


def test_migrate_uses_settings_path_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "from_settings.db"
    monkeypatch.setenv("POSTPARSE_DB_PATH", str(target))
    result = CliRunner().invoke(cli, ["db", "migrate"])
    assert result.exit_code == 0, result.output
    assert target.exists()


def test_check_passes_on_healthy_db(tmp_path: Path) -> None:
    path = tmp_path / "v2.db"
    db = Database.open(path)
    from postparse.core.db.repos import ItemsRepo

    with db.transaction() as conn:
        ItemsRepo(conn).upsert(ItemUpsert("telegram", "1", "text", text="hello"))
    result = CliRunner().invoke(cli, ["db", "check", "--db", str(path)])
    assert result.exit_code == 0, result.output
    assert "check passed" in result.output


def test_check_fails_when_index_out_of_sync_then_reindex_fixes(tmp_path: Path) -> None:
    path = tmp_path / "v2.db"
    Database.open(path)
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO items (source, external_id, kind, text) "
            "VALUES ('telegram', 'raw', 'text', 'bypassed repo')"
        )
    finally:
        conn.close()
    runner = CliRunner()
    bad = runner.invoke(cli, ["db", "check", "--db", str(path)])
    assert bad.exit_code == 1
    assert "out of sync" in bad.output

    fixed = runner.invoke(cli, ["db", "reindex", "--db", str(path)])
    assert fixed.exit_code == 0, fixed.output
    assert "Reindexed 1" in fixed.output
    assert runner.invoke(cli, ["db", "check", "--db", str(path)]).exit_code == 0


def test_check_reports_pending_migrations_and_missing_db(tmp_path: Path) -> None:
    runner = CliRunner()
    missing = runner.invoke(cli, ["db", "check", "--db", str(tmp_path / "nope.db")])
    assert missing.exit_code == 1
    assert "not found" in missing.output

    empty = tmp_path / "empty.db"
    connect(empty).close()
    pending = runner.invoke(cli, ["db", "check", "--db", str(empty)])
    assert pending.exit_code == 1
    assert "pending migration" in pending.output


def test_check_detects_tampered_migration(tmp_path: Path) -> None:
    path = tmp_path / "v2.db"
    Database.open(path)
    conn = connect(path)
    try:
        conn.execute("UPDATE schema_migrations SET sha256 = 'x'")
    finally:
        conn.close()
    runner = CliRunner()
    result = runner.invoke(cli, ["db", "check", "--db", str(path)])
    assert result.exit_code == 1
    assert "Checksum mismatch" in result.output
    assert runner.invoke(cli, ["db", "migrate", "--db", str(path)]).exit_code == 1
