"""Tests of ExtractionService (collectors driven by fakes)."""

from __future__ import annotations

from pathlib import Path

import pytest
from instaloader.exceptions import TooManyRequestsException

from postparse.config import Settings
from postparse.core.db import Database
from postparse.services.extraction import ExtractionService
from tests.unit.collectors.fakes import (
    FakeLoader,
    FakeTelegramClient,
    Feed,
    SleepRecorder,
    client_factory,
    ig_node,
    ig_post,
    loader_factory,
    no_sleep,
    tg_text,
)

TG_ENV = {"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "h"}
IG_ENV = {"INSTAGRAM_USERNAME": "me", "INSTAGRAM_PASSWORD": "pw"}


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.chdir(tmp_path)
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def db(settings: Settings) -> Database:
    return Database.open(settings.db_path)


def service(db, settings, env, client=None, feed=None, loader=None, **ig) -> ExtractionService:
    return ExtractionService(
        db,
        settings,
        env=env,
        telegram_overrides={
            "client_factory": client_factory(client or FakeTelegramClient()),
            "sleep": no_sleep,
        },
        instagram_overrides={
            "loader_factory": loader_factory(loader or FakeLoader()),
            "saved_posts": feed or Feed([]),
            "sleep": SleepRecorder(),
            **ig,
        },
    )


def test_telegram_report(db: Database, settings: Settings) -> None:
    client = FakeTelegramClient([tg_text(i, "x") for i in (1, 2, 3)])
    events = []
    report = service(db, settings, TG_ENV, client=client).telegram(progress=events.append)

    assert (report.new, report.updated, report.stopped_reason, report.ok) == (
        3,
        0,
        "end_of_feed",
        True,
    )
    assert report.processed == 3 and report.duration_s >= 0
    assert events and events[-1].new == 3


def test_telegram_missing_credentials(db: Database, settings: Settings) -> None:
    report = service(db, settings, {"TELEGRAM_API_ID": "1"}).telegram()
    assert report.stopped_reason == "auth_required"
    assert "TELEGRAM_API_HASH" in report.error
    assert not report.ok


def test_telegram_not_authorized_non_interactive(db: Database, settings: Settings) -> None:
    report = service(db, settings, TG_ENV, client=FakeTelegramClient(authorized=False)).telegram(
        interactive=False
    )
    assert report.stopped_reason == "auth_required"


def test_instagram_rate_limit_gives_partial_report(db: Database, settings: Settings) -> None:
    feed = Feed(
        [ig_post(ig_node(c)) for c in "abcd"], fail_at=3, error=TooManyRequestsException("429")
    )
    report = service(db, settings, IG_ENV, feed=feed).instagram(batch_size=2)

    assert report.stopped_reason == "rate_limited"
    assert report.new == 3 and report.last_external_id == "c"
    assert "rate limit" in report.error


def test_instagram_refresh_dates_keeps_collect_reason(db: Database, settings: Settings) -> None:
    from postparse.core.db.models import InstagramDetail, ItemUpsert
    from postparse.core.db.repos import ItemsRepo

    with db.transaction() as conn:
        ItemsRepo(conn).upsert(
            ItemUpsert(
                source="instagram",
                external_id="old",
                kind="image",
                created_at="2020-01-01T00:00:00+00:00",
                detail=InstagramDetail(shortcode="old"),
            )
        )
    svc = service(
        db,
        settings,
        IG_ENV,
        feed=Feed([ig_post(ig_node("new"))]),
        post_from_shortcode=lambda loader, code: ig_post(ig_node(code)),
    )
    report = svc.instagram(refresh_dates=True)

    assert (report.new, report.dates_refreshed, report.stopped_reason) == (1, 1, "end_of_feed")


def test_instagram_missing_username(db: Database, settings: Settings) -> None:
    report = service(db, settings, {}).instagram()
    assert report.stopped_reason == "auth_required"
    assert "INSTAGRAM_USERNAME" in report.error
