"""Tests of the Instagram collector against fake instaloader objects."""

from __future__ import annotations

from pathlib import Path

import pytest
from instaloader.exceptions import (
    BadCredentialsException,
    LoginException,
    QueryReturnedNotFoundException,
    TooManyRequestsException,
    TwoFactorAuthRequiredException,
)

from postparse.collectors.base import InstagramAuthRequired, InstagramRateLimited
from postparse.collectors.credentials import InstagramCredentials
from postparse.collectors.instagram.collector import (
    InstagramCollector,
    map_post,
    resolve_session_path,
)
from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.models import InstagramDetail, ItemUpsert
from postparse.core.db.repos import ItemsRepo, MediaRepo, TagsRepo

from .fakes import (
    FakeLoader,
    Feed,
    NetworkUsed,
    SleepRecorder,
    ig_node,
    ig_post,
    loader_factory,
)

CREDS = InstagramCredentials("me", "pw-secret")


def make(
    db: Database,
    settings: Settings,
    feed: Feed | None = None,
    *,
    loader: FakeLoader | None = None,
    creds: InstagramCredentials = CREDS,
    interactive: bool = True,
    sleep: SleepRecorder | None = None,
    **kwargs,
) -> InstagramCollector:
    return InstagramCollector(
        db,
        settings,
        creds,
        interactive=interactive,
        loader_factory=loader_factory(loader or FakeLoader()),
        saved_posts=feed or Feed([]),
        sleep=sleep or SleepRecorder(),
        **kwargs,
    )


def store(db: Database, *shortcodes: str) -> None:
    """Pretend these posts were collected before."""
    with db.transaction() as conn:
        for code in shortcodes:
            ItemsRepo(conn).upsert(
                ItemUpsert(
                    source="instagram",
                    external_id=code,
                    kind="image",
                    text="old caption",
                    created_at="2020-01-01T00:00:00+00:00",
                    detail=InstagramDetail(shortcode=code),
                )
            )


def posts(*codes: str, typename: str = "GraphImage"):
    return [ig_post(ig_node(code, typename)) for code in codes]


def get(db: Database, code: str):
    with db.read() as conn:
        repo = ItemsRepo(conn)
        item = repo.get_by_external("instagram", code)
        assert item is not None
        return item, repo.instagram_detail(item.id), MediaRepo(conn).for_item(item.id)


def count(db: Database) -> int:
    with db.read() as conn:
        return conn.execute("SELECT count(*) FROM items WHERE source='instagram'").fetchone()[0]


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def test_map_image_post_uses_node_only() -> None:
    item = map_post(ig_post(ig_node("AbC1")), rank=4)

    assert item.external_id == "AbC1"
    assert item.url == "https://www.instagram.com/p/AbC1/"
    assert item.kind == "image"
    assert item.text == "Pasta #Rezept @Chef"
    assert item.author == "chef"
    assert item.created_at.isoformat() == "2023-11-14T22:13:20+00:00"
    assert item.hashtags == ("rezept",) and item.mentions == ("chef",)
    assert item.media is None  # no image CDN URL is kept
    assert item.detail == InstagramDetail(
        shortcode="AbC1",
        owner_id=123,
        typename="GraphImage",
        likes=10,
        comments=2,
        saved_feed_rank=4,
        date_status="verified",
    )


def test_map_video_with_and_without_url() -> None:
    with_url = map_post(
        ig_post(ig_node("V1", "GraphVideo", video_url="https://cdn.example/v.mp4")), 0
    )
    (media,) = with_url.media
    assert (media.position, media.media_type, media.transcript_status) == (0, "video", "pending")
    assert media.remote_url == "https://cdn.example/v.mp4" and media.duration_s == 31.5

    # The feed node lacks video_url: no extra request (the fake context would raise).
    without = map_post(ig_post(ig_node("V2", "GraphVideo")), 1)
    assert without.kind == "video"
    assert without.media[0].remote_url is None


def test_map_carousel_records_video_children_only() -> None:
    node = ig_node(
        "C1",
        "GraphSidecar",
        children=[
            {"is_video": False, "display_url": "https://cdn/img.jpg"},
            {"is_video": True, "video_url": "https://cdn/child.mp4"},
        ],
    )
    item = map_post(ig_post(node), 0)
    assert item.kind == "carousel"
    assert [(m.position, m.media_type, m.remote_url) for m in item.media] == [
        (1, "video", "https://cdn/child.mp4"),
    ]


def test_mapping_never_triggers_requests() -> None:
    post = ig_post(ig_node("N1", caption=None))
    item = map_post(post, 0)
    assert item.text is None and item.hashtags is None
    with pytest.raises(NetworkUsed):
        post._full_metadata  # noqa: B018 - proves the fake context refuses requests


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def test_collect_new_posts_and_store_no_cdn_urls(db: Database, settings: Settings) -> None:
    feed = Feed([*posts("a", "b"), ig_post(ig_node("v", "GraphVideo", video_url="https://cdn/v"))])
    with make(db, settings, feed) as collector:
        stats = collector.collect_saved()

    assert (stats.new, stats.updated, stats.stopped_reason) == (3, 0, "end_of_feed")
    _, _detail, media = get(db, "v")
    assert media[0].transcript_status == "pending" and media[0].remote_url == "https://cdn/v"
    assert media[0].remote_url_seen_at is not None
    _, detail_a, media_a = get(db, "a")
    assert media_a == [] and detail_a.saved_feed_rank == 0
    with db.read() as conn:
        dump = "\n".join(
            str(tuple(r))
            for t in ("items", "media", "links")
            for r in conn.execute(f"SELECT * FROM {t}")
        )
        tags = {t.display for t in TagsRepo(conn).for_item(get(db, "a")[0].id)}
    assert "cdninstagram" not in dump
    assert tags == {"#rezept", "@chef"}


@pytest.mark.parametrize(
    ("feed_codes", "known", "expected_new", "expected_known", "consumed", "reason"),
    [
        # three known in a row right at the top: nothing new
        (["k1", "k2", "k3", "n1"], {"k1", "k2", "k3"}, 0, 3, 3, "early_stop"),
        # new posts first, then the known streak
        (["n1", "n2", "k1", "k2", "k3", "n3"], {"k1", "k2", "k3"}, 2, 3, 5, "early_stop"),
        # an interrupted streak resets the counter
        (["k1", "k2", "n1", "k3", "k4", "n2"], {"k1", "k2", "k3", "k4"}, 2, 4, 6, "end_of_feed"),
        # fewer known than the threshold at the end of the feed
        (["n1", "k1", "k2"], {"k1", "k2"}, 1, 2, 3, "end_of_feed"),
    ],
)
def test_early_stop(
    db: Database,
    settings: Settings,
    feed_codes,
    known,
    expected_new,
    expected_known,
    consumed,
    reason,
) -> None:
    store(db, *known)
    feed = Feed(posts(*feed_codes))
    with make(db, settings, feed) as collector:
        stats = collector.collect_saved(stop_after_known=3)

    assert stats.new == expected_new
    assert stats.known_skipped == expected_known
    assert stats.updated == 0
    assert feed.consumed == consumed
    assert stats.stopped_reason == reason
    # known posts were not touched
    item, *_ = get(db, sorted(known)[0])
    assert item.text == "old caption"


def test_full_walk_updates_known_posts(db: Database, settings: Settings) -> None:
    store(db, "k1", "k2")
    feed = Feed(posts("n1", "k1", "k2", "n2"))
    with make(db, settings, feed) as collector:
        stats = collector.collect_saved(stop_after_known=None)

    assert (stats.new, stats.updated, stats.known_skipped) == (2, 2, 0)
    item, detail, _ = get(db, "k1")
    assert item.text == "Pasta #Rezept @Chef"
    assert detail.saved_feed_rank == 1 and detail.date_status == "verified"


def test_sleeps_only_between_new_posts(db: Database, settings: Settings) -> None:
    store(db, "k1", "k2")
    sleep = SleepRecorder()
    feed = Feed(posts("n1", "k1", "n2", "k2", "n3"))
    with make(db, settings, feed, sleep=sleep) as collector:
        collector.collect_saved(stop_after_known=5)

    assert len(sleep.calls) == 2  # before n2 and n3
    assert all(5.0 <= s <= 15.0 for s in sleep.calls)


def test_limit_counts_written_posts(db: Database, settings: Settings) -> None:
    store(db, "k1")
    feed = Feed(posts("n1", "k1", "n2", "n3", "n4"))
    with make(db, settings, feed) as collector:
        stats = collector.collect_saved(limit=2)

    assert (stats.new, stats.stopped_reason, feed.consumed) == (2, "limit", 3)
    assert count(db) == 3


def test_batches_are_committed_separately(
    db: Database, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ItemsRepo.upsert

    def upsert(self, item):
        if item.external_id == "p3":
            raise RuntimeError("database is locked")
        return original(self, item)

    monkeypatch.setattr(ItemsRepo, "upsert", upsert)
    collector = make(db, settings, Feed(posts("p1", "p2", "p3", "p4", "p5")))
    with pytest.raises(RuntimeError, match="locked"), collector:
        collector.collect_saved(batch_size=2)

    assert count(db) == 2
    assert collector.stats.batches_committed == 1
    assert collector.stats.last_external_id == "p2"


def test_rate_limit_keeps_progress(db: Database, settings: Settings) -> None:
    feed = Feed(
        posts("p1", "p2", "p3", "p4", "p5"),
        fail_at=3,
        error=TooManyRequestsException("429 Too Many Requests"),
    )
    collector = make(db, settings, feed)
    with pytest.raises(InstagramRateLimited), collector:
        collector.collect_saved(batch_size=2)

    assert count(db) == 3  # full batch + the pending one
    assert collector.stats.stopped_reason == "rate_limited"
    assert collector.stats.new == 3 and collector.stats.last_external_id == "p3"


def test_checkpoint_during_feed_is_auth_required(db: Database, settings: Settings) -> None:
    from instaloader.exceptions import ConnectionException

    feed = Feed(
        posts("p1"), fail_at=0, error=ConnectionException("checkpoint_required: confirm it's you")
    )
    collector = make(db, settings, feed)
    with pytest.raises(InstagramAuthRequired, match="Instagram app"), collector:
        collector.collect_saved()
    assert collector.stats.stopped_reason == "auth_required"


# ---------------------------------------------------------------------------
# Login and sessions
# ---------------------------------------------------------------------------


def _session(settings: Settings) -> Path:
    return settings.sessions_dir / "instagram_me"


def test_valid_session_skips_login(db: Database, settings: Settings) -> None:
    path = _session(settings)
    path.parent.mkdir(parents=True)
    path.write_text("s")
    loader = FakeLoader(session_user="me")
    with make(db, settings, loader=loader):
        pass
    assert loader.loaded == [("me", str(path))]
    assert loader.logins == []
    assert loader.saved == [str(path)]  # saved on exit


def test_invalid_session_logs_in_with_password(db: Database, settings: Settings) -> None:
    path = _session(settings)
    path.parent.mkdir(parents=True)
    path.write_text("s")
    loader = FakeLoader(session_user=None)
    with make(db, settings, loader=loader) as collector:
        assert collector.logged_in
    assert loader.logins == ["me"]
    assert loader.saved[0] == str(path)


def test_no_session_and_no_password(db: Database, settings: Settings) -> None:
    collector = make(db, settings, creds=InstagramCredentials("me", None))
    with pytest.raises(InstagramAuthRequired, match="INSTAGRAM_PASSWORD"):
        collector.login()


def test_two_factor_interactive_prompts(db: Database, settings: Settings) -> None:
    loader = FakeLoader(login_error=TwoFactorAuthRequiredException("2fa"))
    prompts: list[str] = []

    def prompt(text: str) -> str:
        prompts.append(text)
        return " 123456 "

    with make(db, settings, loader=loader, prompt=prompt) as collector:
        assert collector.logged_in
    assert loader.two_factor_codes == ["123456"]
    assert prompts and "two-factor" in prompts[0]


def test_two_factor_non_interactive_raises(db: Database, settings: Settings) -> None:
    loader = FakeLoader(login_error=TwoFactorAuthRequiredException("2fa"))
    collector = make(
        db,
        settings,
        loader=loader,
        interactive=False,
        prompt=lambda _: pytest.fail("must not prompt"),
    )
    with pytest.raises(InstagramAuthRequired, match="Two-factor"):
        collector.login()
    assert loader.saved == []


@pytest.mark.parametrize(
    "error",
    [
        LoginException("Checkpoint required. Point your browser to https://instagram.com/x"),
        BadCredentialsException("wrong password"),
    ],
)
def test_login_failures_are_auth_required(db: Database, settings: Settings, error) -> None:
    collector = make(db, settings, loader=FakeLoader(login_error=error))
    with pytest.raises(InstagramAuthRequired, match="retry"):
        collector.login()


def test_rate_limited_login(db: Database, settings: Settings) -> None:
    collector = make(db, settings, loader=FakeLoader(login_error=TooManyRequestsException("429")))
    with pytest.raises(InstagramRateLimited):
        collector.login()


def test_session_fallback_order(settings: Settings) -> None:
    new = _session(settings)
    legacy = Path.cwd() / "instagram_session"
    assert resolve_session_path(settings, "me") == (new, new)

    legacy.write_text("legacy")
    assert resolve_session_path(settings, "me") == (legacy, new)

    new.parent.mkdir(parents=True)
    new.write_text("new")
    assert resolve_session_path(settings, "me") == (new, new)

    custom = Path("x/custom_session")
    assert resolve_session_path(settings, "me", custom) == (custom.resolve(), custom.resolve())


def test_legacy_session_is_loaded_and_saved_to_new_path(db: Database, settings: Settings) -> None:
    legacy = Path.cwd() / "instagram_session"
    legacy.write_text("legacy")
    loader = FakeLoader(session_user="me")
    with make(db, settings, loader=loader):
        pass
    assert loader.loaded == [("me", str(legacy))]
    assert loader.saved == [str(_session(settings))]
    assert legacy.read_text() == "legacy"


# ---------------------------------------------------------------------------
# refresh_dates
# ---------------------------------------------------------------------------


def test_refresh_dates(db: Database, settings: Settings) -> None:
    store(db, "old1", "gone", "old2")
    with db.transaction() as conn:  # a post collected by the new collector is verified
        ItemsRepo(conn).upsert(map_post(ig_post(ig_node("fresh")), 0))

    fetched: list[str] = []

    def from_shortcode(loader, code):
        fetched.append(code)
        if code == "gone":
            raise QueryReturnedNotFoundException("404")
        return ig_post(ig_node(code, date=1_600_000_000))

    sleep = SleepRecorder()
    with make(db, settings, post_from_shortcode=from_shortcode, sleep=sleep) as collector:
        assert collector.refresh_dates() == 2
        assert collector.refresh_dates() == 0  # nothing left to refresh

    assert fetched == ["old1", "gone", "old2"]
    assert len(sleep.calls) == 2
    item, detail, _ = get(db, "old1")
    assert item.created_at.isoformat() == "2020-09-13T12:26:40+00:00"
    assert detail.date_status == "verified"
    item, detail, _ = get(db, "gone")
    assert item.created_at.isoformat() == "2020-01-01T00:00:00+00:00"
    assert detail.date_status == "unavailable"


def test_refresh_dates_respects_limit_and_rate_limit(db: Database, settings: Settings) -> None:
    store(db, "a", "b", "c")
    calls: list[str] = []

    def from_shortcode(loader, code):
        calls.append(code)
        if code == "b":
            raise TooManyRequestsException("429")
        return ig_post(ig_node(code))

    with make(db, settings, post_from_shortcode=from_shortcode) as collector:
        assert collector.refresh_dates(limit=1) == 1
        with pytest.raises(InstagramRateLimited):
            collector.refresh_dates()
    assert calls == ["a", "b"]
    assert get(db, "a")[1].date_status == "verified"
    assert get(db, "b")[1].date_status is None
