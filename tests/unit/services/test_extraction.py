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
    settings = Settings(data_dir=tmp_path / "data")
    assert settings.sessions_dir is not None
    session = settings.sessions_dir / "instagram_me"  # a verified saved session
    session.parent.mkdir(parents=True)
    session.write_text("original-session")
    return settings


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
            "loader_factory": loader_factory(loader or FakeLoader(session_user="me")),
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


def test_instagram_feed_unavailable_gives_partial_report(db: Database, settings: Settings) -> None:
    from postparse.collectors.base import InstagramFeedUnavailable

    feed = Feed(
        [ig_post(ig_node(c)) for c in "abcd"],
        fail_at=3,
        error=InstagramFeedUnavailable("web", "something went wrong"),
    )
    report = service(db, settings, IG_ENV, feed=feed).instagram(batch_size=2)

    assert report.stopped_reason == "feed_unavailable" and not report.ok
    assert report.new == 3 and report.last_external_id == "c"
    assert "session is fine" in report.error


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


# -- no automatic password login (CLI extract and API jobs) -------------------------


@pytest.mark.parametrize(
    "overrides", [{}, {"allow_password_login": True}], ids=["default", "forced"]
)
def test_instagram_never_logs_in_with_the_password(
    db: Database, settings: Settings, overrides: dict
) -> None:
    loader = FakeLoader(session_user=None)  # the saved session is logged out
    report = service(db, settings, IG_ENV, loader=loader, **overrides).instagram()

    assert report.stopped_reason == "auth_required" and not report.ok
    assert "No password login was attempted (session logged out: login_required)" in report.error
    assert "`postparse check instagram --login`" in report.error
    assert loader.logins == [] and loader.two_factor_codes == [] and loader.saved == []
    assert (settings.sessions_dir / "instagram_me").read_text() == "original-session"


def test_api_instagram_job_never_logs_in_with_the_password(
    db: Database, settings: Settings
) -> None:
    import asyncio

    from postparse.api.jobs.kinds import instagram_extract_job, with_credentials

    (settings.sessions_dir / "instagram_me").unlink()
    loader = FakeLoader(session_user="me")
    shared = service(db, settings, {}, loader=loader)
    job = instagram_extract_job(
        with_credentials(shared, {"INSTAGRAM_USERNAME": "me", "INSTAGRAM_PASSWORD": "pw"}),
        limit=None,
        stop_after_known=20,
        username="me",
    )
    report = asyncio.run(job(lambda *args: None))

    assert report.stopped_reason == "auth_required"
    assert "No password login was attempted (no session file)" in report.error
    assert loader.logins == [] and loader.saved == []
    assert not (settings.sessions_dir / "instagram_me").exists()
