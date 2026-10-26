"""CLI ``enrich run/status`` (schema v2) and the v1 ``content_expanded`` DB methods."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from postparse.cli.main import cli
from postparse.config import Settings
from postparse.core.data.database import SocialMediaDatabase
from postparse.core.db import Database
from postparse.enrichment.fetchers.base import FetchResult
from postparse.enrichment.options import EnrichmentOptions
from postparse.services.enrichment import EnrichmentService
from tests.unit.enrichment.helpers import (
    NOW,
    ScriptedFetcher,
    add_fetch,
    add_item,
    add_legacy_fetch,
    router_factory,
)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.chdir(tmp_path)
    settings = Settings(data_dir=tmp_path / "data")
    assert settings.db_path is not None
    db = Database.open(settings.db_path)
    fetcher = ScriptedFetcher()
    state: dict[str, Any] = {"db": db, "fetcher": fetcher, "db_paths": []}

    def build(ctx: Any, db_path: str | None) -> EnrichmentService:
        state["db_paths"].append(db_path)
        return EnrichmentService(
            db, settings, options=EnrichmentOptions(min_domain_interval=0),
            router_factory=router_factory(fetcher), clock=lambda: NOW,
        )

    monkeypatch.setattr("postparse.cli.enrich._build_service", build)
    return state


def invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


def test_enrich_run(env: dict[str, Any]) -> None:
    add_item(env["db"], "1:1", ["https://a.example/1", "https://b.example/2",
                                "https://c.example/3"])
    add_legacy_fetch(env["db"], "https://c.example/3", "Alt")
    env["fetcher"].results["https://b.example/2"] = FetchResult.failed("HTTP 500")
    result = invoke("enrich", "run", "--limit", "5", "--db", "x.db")
    assert result.exit_code == 0, result.output
    assert "Enrichment" in result.output and "legacy texts replaced 1" in result.output
    assert "HTTP 500" in result.output
    assert env["db_paths"] == ["x.db"]
    assert sorted(env["fetcher"].calls) == ["https://a.example/1", "https://b.example/2",
                                            "https://c.example/3"]


def test_enrich_run_filters(env: dict[str, Any]) -> None:
    add_item(env["db"], "1:2", ["https://a.example/1", "https://c.example/old"])
    add_item(env["db"], "SC", ["https://b.example/2"], source="instagram")
    add_legacy_fetch(env["db"], "https://c.example/old", "Alt")
    result = invoke("enrich", "run", "--source", "telegram", "--no-legacy")
    assert result.exit_code == 0, result.output
    assert env["fetcher"].calls == ["https://a.example/1"]
    result = invoke("enrich", "run", "--domain", "b.example", "--force")
    assert result.exit_code == 0, result.output
    assert env["fetcher"].calls[-1] == "https://b.example/2"


def test_enrich_run_nothing_to_do(env: dict[str, Any]) -> None:
    result = invoke("enrich", "run")
    assert result.exit_code == 0 and "No links need a fetch" in result.output


def test_enrich_run_interrupted(env: dict[str, Any]) -> None:
    add_item(env["db"], "1:3", ["https://a.example/1"])

    def explode() -> FetchResult:
        raise KeyboardInterrupt

    env["fetcher"].results["https://a.example/1"] = explode
    result = invoke("enrich", "run")
    assert result.exit_code == 130


def test_enrich_status(env: dict[str, Any]) -> None:
    add_item(env["db"], "1:4", ["https://a.example/1", "https://a.example/2"])
    add_fetch(env["db"], "https://a.example/1", "error", at=NOW - timedelta(hours=3))
    result = invoke("enrich", "status")
    assert result.exit_code == 0, result.output
    assert "a.example" in result.output and "never" in result.output
    assert "retries due: 1" in result.output


def test_enrich_scrape_is_a_deprecated_alias(env: dict[str, Any]) -> None:
    add_item(env["db"], "1:5", ["https://a.example/1"])
    result = invoke("enrich", "scrape", "--source", "telegram", "--timeout", "3")
    assert result.exit_code == 0, result.output
    assert "deprecated" in result.output.lower()
    assert env["fetcher"].calls == ["https://a.example/1"]


def test_enrich_urls_is_a_noop(env: dict[str, Any]) -> None:
    result = invoke("enrich", "urls", "--source", "telegram", "--limit", "5")
    assert result.exit_code == 0, result.output
    assert "no longer needed" in result.output
    assert env["db_paths"] == []


def test_enrich_build_service_uses_db_option(tmp_path: Path) -> None:
    # Runs in the isolated session directory (test config), database via --db.
    result = invoke("enrich", "status", "--db", str(tmp_path / "fresh.db"))
    assert result.exit_code == 0, result.output
    assert (tmp_path / "fresh.db").exists() and "Links (0)" in result.output


# ============================================================================
# v1 database content_expanded methods
# ============================================================================


class TestContentExpandedDb:
    """Test content_expanded DB methods."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> SocialMediaDatabase:
        """Create a temporary database."""
        return SocialMediaDatabase(str(tmp_path / "test.db"))

    def _insert_telegram_message(self, db: SocialMediaDatabase, content: str) -> int:
        """Insert a telegram message with a deterministic unique ID."""
        with db as database_ctx:
            database_ctx._cursor.execute(
                "SELECT COALESCE(MAX(message_id), 0) FROM telegram_messages"
            )
            row = database_ctx._cursor.fetchone()
        next_message_id = int(row[0]) + 1 if row else 1
        inserted_id = db._insert_telegram_message(
            message_id=next_message_id,
            content=content,
            content_type="text",
        )
        assert inserted_id is not None
        return inserted_id

    def _insert_instagram_post(self, db: SocialMediaDatabase, caption: str) -> int:
        """Insert an Instagram post with a deterministic shortcode."""
        with db as database_ctx:
            database_ctx._cursor.execute(
                "SELECT COALESCE(MAX(id), 0) FROM instagram_posts"
            )
            row = database_ctx._cursor.fetchone()
        shortcode_suffix = int(row[0]) + 1 if row else 1
        inserted_id = db._insert_instagram_post(
            shortcode=f"test_{shortcode_suffix}",
            caption=caption,
        )
        assert inserted_id is not None
        return inserted_id

    def test_save_and_get_content_expanded_telegram(
        self, db: SocialMediaDatabase
    ) -> None:
        """save/get content_expanded roundtrip for telegram."""
        item_id = self._insert_telegram_message(db, "Watch https://youtube.com/abc")
        db.save_content_expanded(item_id, 'telegram', 'https://youtube.com/abc')
        result = db.get_content_expanded(item_id, 'telegram')
        assert result == 'https://youtube.com/abc'

    def test_save_and_get_content_expanded_instagram(
        self, db: SocialMediaDatabase
    ) -> None:
        """save/get content_expanded roundtrip for instagram."""
        item_id = self._insert_instagram_post(db, "https://x.com/post/1")
        db.save_content_expanded(item_id, 'instagram', 'https://x.com/post/1')
        result = db.get_content_expanded(item_id, 'instagram')
        assert result == 'https://x.com/post/1'

    def test_get_content_expanded_none(self, db: SocialMediaDatabase) -> None:
        """Returns None when content_expanded not set."""
        item_id = self._insert_telegram_message(db, "No URL here")
        result = db.get_content_expanded(item_id, 'telegram')
        assert result is None

    def test_get_items_without_content_expanded(
        self, db: SocialMediaDatabase
    ) -> None:
        """Returns items with content but no content_expanded."""
        id1 = self._insert_telegram_message(db, "https://youtube.com/abc")
        id2 = self._insert_telegram_message(db, "https://x.com/1")
        id3 = self._insert_telegram_message(db, "No URL here")

        items = db.get_items_without_content_expanded('telegram')
        ids = {item['id'] for item in items}
        assert id1 in ids
        assert id2 in ids
        assert id3 in ids

    def test_already_expanded_not_returned(self, db: SocialMediaDatabase) -> None:
        """Items with content_expanded already set are excluded."""
        id1 = self._insert_telegram_message(db, "https://youtube.com/abc")
        id2 = self._insert_telegram_message(db, "https://x.com/1")
        db.save_content_expanded(id1, 'telegram', 'https://youtube.com/abc')

        items = db.get_items_without_content_expanded('telegram')
        ids = {item['id'] for item in items}
        assert id1 not in ids
        assert id2 in ids

    def test_content_expanded_table_has_column(
        self, db: SocialMediaDatabase
    ) -> None:
        """content_expanded column exists on both tables."""
        with db as d:
            d._cursor.execute("PRAGMA table_info(telegram_messages)")
            cols = {row[1] for row in d._cursor.fetchall()}
            assert 'content_expanded' in cols

            d._cursor.execute("PRAGMA table_info(instagram_posts)")
            cols = {row[1] for row in d._cursor.fetchall()}
            assert 'content_expanded' in cols
