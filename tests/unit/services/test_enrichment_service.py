"""EnrichmentService: selection, legacy refresh, retries/backoff, FTS refresh (no network)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.repos import ItemsRepo, LinksRepo
from postparse.enrichment.fetchers.base import FetchResult
from postparse.enrichment.options import EnrichmentOptions
from postparse.services.enrichment import EnrichmentService, normalize_domain
from tests.unit.enrichment.helpers import (
    NOW,
    ScriptedFetcher,
    add_fetch,
    add_item,
    add_legacy_fetch,
    fts_ids,
    link_id,
    router_factory,
)


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.chdir(tmp_path)
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def db(settings: Settings) -> Database:
    assert settings.db_path is not None
    return Database.open(settings.db_path)


def service(
    db: Database, settings: Settings, fetcher: Any = None, **options: Any
) -> tuple[EnrichmentService, ScriptedFetcher]:
    fetcher = fetcher or ScriptedFetcher()
    opts = EnrichmentOptions(
        **{
            "min_domain_interval": 0,
            "backoff_minutes": 60,
            "max_backoff_hours": 24,
            "max_attempts": 3,
            **options,
        }
    )
    svc = EnrichmentService(
        db, settings, options=opts, router_factory=router_factory(fetcher), clock=lambda: NOW
    )
    return svc, fetcher


def fetches(db: Database, url: str) -> list[tuple[str, str]]:
    with db.read() as conn:
        rows = conn.execute(
            "SELECT lf.fetcher, lf.status FROM link_fetches AS lf JOIN links AS l "
            "ON l.id = lf.link_id WHERE l.url = ? ORDER BY lf.id",
            (url,),
        ).fetchall()
    return [(row[0], row[1]) for row in rows]


def test_new_links_are_fetched_and_stored(db: Database, settings: Settings) -> None:
    item = add_item(db, "1:1", ["https://blog.example/a", "https://news.example/b"])
    svc, fetcher = service(db, settings)
    updates: list[Any] = []
    report = svc.run(progress=updates.append)
    assert report.stopped_reason == "done" and report.candidates == 2 and report.ok == 2
    assert report.by_fetcher == {"fake": {"ok": 2}}
    assert sorted(fetcher.calls) == ["https://blog.example/a", "https://news.example/b"]
    assert [u.index for u in updates] == [1, 2] and updates[-1].total == 2
    with db.read() as conn:
        fetch = LinksRepo(conn).latest_ok_fetch(link_id(db, "https://blog.example/a"))
    assert fetch is not None and fetch.fetcher == "fake" and fetch.fetched_at == NOW
    assert fts_ids(db, '"Fresh text from blog"') == [item]  # search document refreshed
    assert report.items_refreshed == 1
    # A second run has nothing to do.
    assert svc.run().candidates == 0


def test_legacy_links_are_refreshed_and_legacy_fetch_kept(db: Database, settings: Settings) -> None:
    item = add_item(db, "1:2", ["https://blog.example/old"])
    add_legacy_fetch(db, "https://blog.example/old", "Alter gescrapter Text")
    assert fts_ids(db, "gescrapter") == [item]
    svc, _ = service(db, settings)
    report = svc.run()
    assert report.ok == 1 and report.legacy_refreshed == 1
    assert fetches(db, "https://blog.example/old") == [("legacy_v1", "ok"), ("fake", "ok")]
    # The newest ok fetch wins in search; the legacy one stays as fallback.
    assert fts_ids(db, "gescrapter") == []
    assert fts_ids(db, '"Fresh text from blog"') == [item]


def test_failed_refresh_keeps_legacy_text_searchable(db: Database, settings: Settings) -> None:
    item = add_item(db, "1:3", ["https://blog.example/gone"])
    add_legacy_fetch(db, "https://blog.example/gone", "Alter gescrapter Text")
    fetcher = ScriptedFetcher(
        {"https://blog.example/gone": FetchResult.failed("HTTP 404", http_status=404)}
    )
    report = service(db, settings, fetcher)[0].run()
    assert report.errors_count == 1 and "HTTP 404" in report.errors[0]
    assert fts_ids(db, "gescrapter") == [item]


def test_no_legacy_flag_leaves_legacy_links_alone(db: Database, settings: Settings) -> None:
    add_item(db, "1:4", ["https://blog.example/old", "https://blog.example/new"])
    add_legacy_fetch(db, "https://blog.example/old", "Alt")
    svc, fetcher = service(db, settings)
    report = svc.run(refresh_legacy=False)
    assert fetcher.calls == ["https://blog.example/new"] and report.legacy_refreshed == 0


def test_new_links_come_before_legacy_links(db: Database, settings: Settings) -> None:
    add_item(db, "1:5", ["https://a.example/legacy", "https://a.example/new"])
    add_legacy_fetch(db, "https://a.example/legacy", "Alt")
    svc, fetcher = service(db, settings)
    svc.run(limit=1)
    assert fetcher.calls == ["https://a.example/new"]


def test_legacy_expanded_text_removed_once_all_links_are_fresh(
    db: Database, settings: Settings
) -> None:
    item = add_item(
        db,
        "1:6",
        ["https://a.example/1", "https://b.example/2", "https://www.instagram.com/p/XYZ/"],
    )
    other = add_item(db, "1:7", ["https://a.example/1", "https://c.example/3"])
    with db.transaction() as conn:
        ItemsRepo(conn).set_legacy_expanded_text(item, "Erweiterter Alttext")
        ItemsRepo(conn).set_legacy_expanded_text(other, "Noch ein Alttext")
    fetcher = ScriptedFetcher(
        {
            "https://www.instagram.com/p/XYZ/": FetchResult(
                "skipped", fetcher="instagram", error="Instagram"
            ),
            "https://c.example/3": FetchResult.failed("timeout"),
        }
    )
    report = service(db, settings, fetcher)[0].run()
    assert report.ok == 2 and report.skipped == 1 and report.errors_count == 1
    assert report.legacy_texts_removed == 1
    with db.read() as conn:
        legacy = ItemsRepo(conn).legacy_expanded_texts([item, other])
    # item: both web links ok + Instagram skipped -> removed; other: c.example failed -> kept.
    assert legacy == {other: "Noch ein Alttext"}
    assert fts_ids(db, "Erweiterter") == [] and fts_ids(db, "Alttext") == [other]


def test_errors_are_retried_with_backoff_until_max_attempts(
    db: Database, settings: Settings
) -> None:
    add_item(
        db,
        "1:8",
        [
            "https://a.example/recent",
            "https://a.example/old",
            "https://a.example/dead",
            "https://a.example/skip",
        ],
    )
    # One failure 30 min ago (backoff 60 min -> not due), one 2 h ago (due),
    # three failures (max_attempts=3 -> gave up), one skipped (final).
    add_fetch(db, "https://a.example/recent", "error", at=NOW - timedelta(minutes=30))
    add_fetch(db, "https://a.example/old", "error", at=NOW - timedelta(hours=2))
    for hours in (30, 20, 10):
        add_fetch(db, "https://a.example/dead", "error", at=NOW - timedelta(hours=hours))
    add_fetch(db, "https://a.example/skip", "skipped", at=NOW - timedelta(days=30))
    svc, fetcher = service(db, settings)
    stats = svc.status()
    assert stats["retry_due"] == 1 and stats["gave_up"] == 1 and stats["due"] == 1
    assert stats["next_retry_at"] == (NOW + timedelta(minutes=30)).isoformat(timespec="minutes")
    report = svc.run()
    assert fetcher.calls == ["https://a.example/old"] and report.ok == 1
    # force refetches everything in scope.
    forced = svc.run(force=True)
    assert forced.candidates == 4


def test_failure_count_resets_after_success(db: Database, settings: Settings) -> None:
    add_item(db, "1:9", ["https://a.example/x"])
    for hours in (50, 40):
        add_fetch(db, "https://a.example/x", "error", at=NOW - timedelta(hours=hours))
    add_fetch(db, "https://a.example/x", "ok", at=NOW - timedelta(hours=30), text="ok")
    add_fetch(db, "https://a.example/x", "error", at=NOW - timedelta(hours=20))
    svc, _ = service(db, settings)
    (state,) = svc._states("all", None)
    assert state.failures == 1 and state.has_ok and state.last_status == "error"
    assert svc.is_due(state, NOW)


def test_source_and_domain_filters(db: Database, settings: Settings) -> None:
    add_item(db, "1:10", ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://a.example/t"])
    add_item(db, "SHORT", ["https://b.example/i"], source="instagram")
    svc, fetcher = service(db, settings)
    assert {s.link.url for s in svc.select("instagram")} == {"https://b.example/i"}
    svc.run(domains=["https://WWW.YouTube.com/"])
    assert fetcher.calls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
    assert normalize_domain("www.Example.org/path") == "example.org"


def test_text_is_capped_and_metadata_records_it(db: Database, settings: Settings) -> None:
    add_item(db, "1:11", ["https://a.example/long"])
    fetcher = ScriptedFetcher(
        {
            "https://a.example/long": FetchResult(
                "ok", fetcher="generic", title="T" * 2000, text="x" * 500, metadata={"k": 1}
            )
        }
    )
    service(db, settings, fetcher, max_text_chars=100)[0].run()
    with db.read() as conn:
        fetch = LinksRepo(conn).latest_ok_fetch(link_id(db, "https://a.example/long"))
    assert fetch is not None and len(fetch.text or "") == 100 and len(fetch.title or "") == 1000
    assert fetch.metadata == {"k": 1, "text_truncated_from": 500}


def test_results_are_persisted_per_link(db: Database, settings: Settings) -> None:
    """A crash after some links keeps the stored ones (each link commits on its own)."""
    add_item(db, "1:12", ["https://a.example/1", "https://b.example/2"])

    def explode() -> FetchResult:
        raise KeyboardInterrupt

    fetcher = ScriptedFetcher({"https://b.example/2": explode})
    svc, _ = service(db, settings, fetcher, concurrency=1)
    with pytest.raises(KeyboardInterrupt):
        svc.run()
    assert fetches(db, "https://a.example/1") == [("fake", "ok")]
    assert fetches(db, "https://b.example/2") == []


def test_status_counts(db: Database, settings: Settings) -> None:
    add_item(db, "1:13", ["https://a.example/1", "https://a.example/2", "https://b.example/3"])
    add_legacy_fetch(db, "https://a.example/2", "Alt")
    add_fetch(db, "https://b.example/3", "ok", at=NOW, text="neu")
    stats = service(db, settings)[0].status()
    assert stats["links"] == 3
    assert stats["by_state"] == {
        ("-", "never"): 1,
        ("legacy_v1", "legacy"): 1,
        ("generic", "ok"): 1,
    }
    assert stats["domains"][0] == ("a.example", {"never": 1, "legacy": 1})
    assert stats["due"] == 2
