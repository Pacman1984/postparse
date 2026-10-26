"""Tests of the Instagram collector against fake instaloader objects."""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import instaloader
import pytest
import requests
from instaloader.exceptions import (
    AbortDownloadException,
    BadCredentialsException,
    LoginException,
    LoginRequiredException,
    QueryReturnedNotFoundException,
    TooManyRequestsException,
    TwoFactorAuthRequiredException,
)

from postparse.collectors.base import (
    InstagramAuthRequired,
    InstagramFeedUnavailable,
    InstagramRateLimited,
    InstagramSessionCheckFailed,
)
from postparse.collectors.credentials import InstagramCredentials
from postparse.collectors.instagram.collector import (
    InstagramCollector,
    InstagramOptions,
    iter_saved_feed,
    map_post,
    post_from_iphone_media,
    resolve_session_path,
)
from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.models import InstagramDetail, ItemUpsert
from postparse.core.db.repos import ItemsRepo, MediaRepo, TagsRepo

from .fakes import (
    IG_SAVED_FEED,
    IG_USER_ID,
    IG_USER_INFO,
    LEGACY_LOGIN_HASH,
    LOGGED_OUT_403,
    SESSION_COOKIES,
    THROTTLED_401,
    FakeIgContext,
    FakeLoader,
    Feed,
    NetworkUsed,
    SleepRecorder,
    ig_error,
    ig_iphone_child,
    ig_iphone_media,
    ig_node,
    ig_post,
    loader_factory,
    saved_feed_pages,
    saved_page,
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
    allow_password_login: bool = True,
    sleep: SleepRecorder | None = None,
    **kwargs,
) -> InstagramCollector:
    """A collector on fakes; by default as `check instagram --login` builds it.

    Extract runs (``allow_password_login=False``, the collector default) are
    tested explicitly below.
    """
    return InstagramCollector(
        db,
        settings,
        creds,
        interactive=interactive,
        allow_password_login=allow_password_login,
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


# ---------------------------------------------------------------------------
# Session check (no legacy query_hash, no password fallback on throttles)
# ---------------------------------------------------------------------------


def _existing_session(settings: Settings) -> Path:
    path = _session(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("original-session")
    return path


@pytest.mark.parametrize(
    "error",
    [
        ig_error(THROTTLED_401),
        ig_error("429 Too Many Requests"),
        TooManyRequestsException("429 Too Many Requests"),
        ig_error("HTTPSConnectionPool(host='i.instagram.com', port=443): Read timed out."),
        ig_error("500 Internal Server Error"),
    ],
    ids=["401-please-wait", "429", "429-raw", "timeout", "500"],
)
def test_throttled_session_check_never_logs_in_with_password(
    db: Database, settings: Settings, error: Exception
) -> None:
    path = _existing_session(settings)
    loader = FakeLoader(check_error=error)
    collector = make(db, settings, loader=loader)

    with pytest.raises(InstagramSessionCheckFailed) as info, collector:
        pytest.fail("must not enter")

    assert isinstance(info.value, InstagramRateLimited)  # exit code 3, job "rate_limited"
    assert "No password login was attempted" in str(info.value)
    assert "nothing was lost" in str(info.value)
    assert loader.logins == [] and loader.saved == []
    assert path.read_text() == "original-session"  # session file not rewritten
    assert not collector.logged_in
    assert [r[:2] for r in loader.context.requests] == [("iphone", IG_USER_INFO)]


@pytest.mark.parametrize(
    ("loader", "requests"),
    [
        (FakeLoader(session_user=None), 1),  # 403 login_required
        (
            FakeLoader(
                check_error=AbortDownloadException(
                    "Redirected to login page. You've been logged out, please wait some time, "
                    "recreate the session and try again"
                )
            ),
            1,
        ),
        (FakeLoader(check_error=LoginRequiredException("Redirected to login page.")), 1),
        (FakeLoader(session_user="someone_else"), 1),  # session of another account
        (FakeLoader(session_cookies={"csrftoken": "x"}), 0),  # no sessionid: no request
        (FakeLoader(session_cookies={"sessionid": "", "ds_user_id": IG_USER_ID}), 0),
    ],
    ids=[
        "login-required",
        "login-redirect",
        "login-required-exc",
        "other-user",
        "no-cookies",
        "empty-sessionid",
    ],
)
def test_logged_out_session_falls_back_to_password(
    db: Database, settings: Settings, loader: FakeLoader, requests: int
) -> None:
    path = _existing_session(settings)
    with make(db, settings, loader=loader) as collector:
        assert collector.logged_in
    assert loader.logins == ["me"]
    assert loader.saved[0] == str(path)
    assert len(loader.context.requests) == requests


def test_logged_out_session_without_password_is_auth_required(
    db: Database, settings: Settings
) -> None:
    _existing_session(settings)
    loader = FakeLoader(session_user=None)
    collector = make(db, settings, loader=loader, creds=InstagramCredentials("me", None))
    with pytest.raises(InstagramAuthRequired, match="INSTAGRAM_PASSWORD"):
        collector.login()
    assert loader.logins == [] and loader.saved == []


def test_checkpoint_on_session_check_needs_the_user(db: Database, settings: Settings) -> None:
    path = _existing_session(settings)
    loader = FakeLoader(
        check_error=AbortDownloadException(
            'Query to https://i.instagram.com/api/v1/users/4242/info/ responded with "400 Bad '
            'Request": {"message": "challenge_required", "status": "fail"}'
        )
    )
    collector = make(db, settings, loader=loader)
    with pytest.raises(InstagramAuthRequired, match="confirmation"):
        collector.login()
    assert loader.logins == [] and loader.saved == []
    assert path.read_text() == "original-session"


def test_valid_session_check_uses_one_attempt_and_no_legacy_hash(
    db: Database, settings: Settings
) -> None:
    _existing_session(settings)
    loader = FakeLoader(session_user="Me")  # usernames compare case-insensitively
    loader.context.web_responses[IG_SAVED_FEED] = saved_feed_pages(
        saved_page([ig_iphone_media("a")])
    )
    collector = InstagramCollector(
        db, settings, CREDS, loader_factory=loader_factory(loader), sleep=SleepRecorder()
    )
    with collector:
        collector.collect_saved()

    assert loader.logins == []
    assert loader.legacy_hash_requests() == []
    assert [r[0] for r in loader.context.requests] == ["iphone", "web"]
    (check, feed) = loader.context.requests
    assert check[1] == IG_USER_INFO and check[3] == 1  # single connection attempt
    assert feed[1] == IG_SAVED_FEED and feed[3] == 1  # feed pages: one attempt as well
    assert loader.context.max_connection_attempts == 3  # restored
    assert loader.context.user_id == int(IG_USER_ID)


def test_failed_session_check_restores_connection_attempts(
    db: Database, settings: Settings
) -> None:
    _existing_session(settings)
    loader = FakeLoader(check_error=ig_error(THROTTLED_401))
    with pytest.raises(InstagramSessionCheckFailed):
        make(db, settings, loader=loader).login()
    assert loader.context.requests[0][3] == 1
    assert loader.context.max_connection_attempts == 3


def test_unexpected_check_response_keeps_the_session(db: Database, settings: Settings) -> None:
    _existing_session(settings)
    loader = FakeLoader(session_user="me")
    loader.context.iphone_responses[IG_USER_INFO] = {"status": "ok"}
    with make(db, settings, loader=loader) as collector:
        assert collector.logged_in
    assert loader.logins == []


def test_unreadable_session_file_falls_back_to_password(db: Database, settings: Settings) -> None:
    _existing_session(settings)
    loader = FakeLoader(session_user="me")

    def broken(username: str, filename: str) -> None:
        raise EOFError("Ran out of input")

    loader.load_session_from_file = broken  # type: ignore[method-assign]
    with make(db, settings, loader=loader) as collector:
        assert collector.logged_in
    assert loader.logins == ["me"] and loader.context.requests == []


# ---------------------------------------------------------------------------
# Saved feed (web REST API by default, private iPhone API as fallback)
# ---------------------------------------------------------------------------

FEED_APIS = pytest.mark.parametrize("feed_api", ["web", "iphone"])
#: First-page parameters per feed API.
BASE_PARAMS = {"web": {"count": "50"}, "iphone": {"include_igtv_preview": "false"}}
#: ``FakeIgContext.requests`` kind per feed API.
KIND = {"web": "web", "iphone": "iphone"}

FEED_FAIL_200 = (
    '200 OK - "fail" status, message "We\'re sorry, but something went wrong. Please try again."'
)


def _feed_table(loader: FakeLoader | FakeIgContext, feed_api: str) -> dict:
    context = loader.context if isinstance(loader, FakeLoader) else loader
    return context.web_responses if feed_api == "web" else context.iphone_responses


def _feed_collector(
    db: Database, settings: Settings, *pages: dict, feed_api: str = "web", **kwargs
) -> tuple[InstagramCollector, FakeLoader]:
    _existing_session(settings)
    loader = FakeLoader(session_user="me")
    _feed_table(loader, feed_api)[IG_SAVED_FEED] = saved_feed_pages(*pages)
    collector = InstagramCollector(
        db,
        settings,
        CREDS,
        InstagramOptions(feed_api=feed_api),
        loader_factory=loader_factory(loader),
        sleep=SleepRecorder(),
        **kwargs,
    )
    return collector, loader


def _feed_requests(loader: FakeLoader) -> list[dict]:
    return [r[2] for r in loader.context.requests if r[1] == IG_SAVED_FEED]


@FEED_APIS
def test_saved_feed_paginates_with_max_id(db: Database, settings: Settings, feed_api: str) -> None:
    collector, loader = _feed_collector(
        db,
        settings,
        saved_page([ig_iphone_media("a"), ig_iphone_media("b")], next_max_id="cursor-1"),
        saved_page([ig_iphone_media("c")], next_max_id="cursor-2"),
        saved_page([ig_iphone_media("d")]),
        feed_api=feed_api,
    )
    with collector:
        stats = collector.collect_saved()

    assert (stats.new, stats.stopped_reason) == (4, "end_of_feed")
    base = BASE_PARAMS[feed_api]
    assert _feed_requests(loader) == [
        base,
        {**base, "max_id": "cursor-1"},
        {**base, "max_id": "cursor-2"},
    ]
    # Only the configured API is used for the feed (the session check is always iphone).
    feed_kinds = {r[0] for r in loader.context.requests if r[1] == IG_SAVED_FEED}
    assert feed_kinds == {KIND[feed_api]}
    assert [get(db, c)[1].saved_feed_rank for c in "abcd"] == [0, 1, 2, 3]


def test_default_feed_api_is_web_and_never_calls_the_iphone_feed(
    db: Database, settings: Settings
) -> None:
    _existing_session(settings)
    loader = FakeLoader(session_user="me")
    loader.context.web_responses[IG_SAVED_FEED] = saved_feed_pages(
        saved_page([ig_iphone_media("w1")])
    )
    # An iphone feed request would raise NetworkUsed (no scripted answer).
    collector = InstagramCollector(
        db, settings, CREDS, loader_factory=loader_factory(loader), sleep=SleepRecorder()
    )
    with collector:
        collector.collect_saved()
    assert ("iphone", IG_SAVED_FEED) not in [r[:2] for r in loader.context.requests]
    assert count(db) == 1


def test_web_feed_sends_the_web_app_headers(db: Database, settings: Settings) -> None:
    collector, loader = _feed_collector(
        db, settings, saved_page([ig_iphone_media("a")], next_max_id="c1"), saved_page([])
    )
    pages = saved_feed_pages(saved_page([ig_iphone_media("a")], next_max_id="c1"))
    claims: list[str] = []

    def answer(params: dict) -> dict:
        claims.append(loader.context.web_headers[-1]["X-IG-WWW-Claim"])
        return pages(params) if "max_id" not in params else saved_page([])

    loader.context.web_responses[IG_SAVED_FEED] = answer
    with collector:
        collector.collect_saved()

    headers = loader.context.web_headers[0]
    lower = {k.lower(): v for k, v in headers.items()}
    assert lower["x-ig-app-id"] == "936619743392459"
    assert lower["x-csrftoken"] == SESSION_COOKIES["csrftoken"]  # from the session cookie
    assert lower["x-requested-with"] == "XMLHttpRequest"
    assert lower["x-asbd-id"] == "129477"
    assert lower["referer"] == "https://www.instagram.com/me/saved/all-posts/"
    assert lower["origin"] == "https://www.instagram.com"
    assert lower["sec-fetch-site"] == "same-origin"
    assert "x-instagram-ajax" not in lower and "content-length" not in lower
    assert claims == ["0", "0"]
    # The main session is left unchanged (headers live on a temporary copy).
    main = {k.lower() for k in loader.context._session.headers}
    assert "x-asbd-id" not in main and "x-ig-www-claim" not in main


@FEED_APIS
def test_saved_feed_early_stop_skips_further_pages(
    db: Database, settings: Settings, feed_api: str
) -> None:
    store(db, "k1", "k2")
    collector, loader = _feed_collector(
        db,
        settings,
        saved_page([ig_iphone_media("n1"), ig_iphone_media("k1")], next_max_id="c1"),
        saved_page([ig_iphone_media("k2"), ig_iphone_media("n2")], next_max_id="c2"),
        saved_page([ig_iphone_media("n3")]),
        feed_api=feed_api,
    )
    with collector:
        stats = collector.collect_saved(stop_after_known=2)

    assert (stats.new, stats.known_skipped, stats.stopped_reason) == (1, 2, "early_stop")
    assert len(_feed_requests(loader)) == 2  # the third page is never requested


@FEED_APIS
def test_saved_feed_early_stop_on_page_one(db: Database, settings: Settings, feed_api: str) -> None:
    store(db, "k1")
    collector, loader = _feed_collector(
        db,
        settings,
        saved_page([ig_iphone_media("k1"), ig_iphone_media("n1")], next_max_id="c1"),
        saved_page([ig_iphone_media("n2")]),
        feed_api=feed_api,
    )
    with collector:
        stats = collector.collect_saved(stop_after_known=1)
    assert (stats.new, stats.stopped_reason) == (0, "early_stop")
    assert _feed_requests(loader) == [BASE_PARAMS[feed_api]]  # page 2 never requested


@FEED_APIS
def test_saved_feed_stops_on_empty_page_and_repeated_cursor(
    db: Database, settings: Settings, feed_api: str
) -> None:
    collector, loader = _feed_collector(
        db, settings, saved_page([ig_iphone_media("a")], next_max_id="same"), feed_api=feed_api
    )
    # The second request (max_id=same) answers the same cursor again.
    _feed_table(loader, feed_api)[IG_SAVED_FEED] = lambda params: saved_page(
        [ig_iphone_media("a" if "max_id" not in params else "b")], next_max_id="same"
    )
    with collector:
        stats = collector.collect_saved()
    assert stats.new == 2 and len(_feed_requests(loader)) == 2

    context = _context_with_feed(saved_page([], next_max_id="x"), feed_api=feed_api)
    assert list(iter_saved_feed(context, feed_api)) == []
    assert len(context.requests) == 1


def test_saved_feed_accepts_bare_media_items() -> None:
    """Items may be ``{"media": {...}}`` or the media struct itself; others are skipped."""
    page = saved_page([ig_iphone_media("wrapped")])
    page["items"] += [ig_iphone_media("bare"), {"media": {"no": "code"}}, "junk"]
    context = _context_with_feed(page)
    assert [p.shortcode for p in iter_saved_feed(context, "web", "me")] == ["wrapped", "bare"]


def test_unknown_feed_api_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown feed_api"):
        list(iter_saved_feed(FakeIgContext("me"), "graphql"))  # type: ignore[arg-type]


def _context_with_feed(*pages: dict, feed_api: str = "web") -> FakeIgContext:
    context = FakeIgContext("me")
    _feed_table(context, feed_api)[IG_SAVED_FEED] = saved_feed_pages(*pages)
    return context


@FEED_APIS
def test_saved_feed_rate_limit_keeps_progress(
    db: Database, settings: Settings, feed_api: str
) -> None:
    collector, loader = _feed_collector(db, settings, feed_api=feed_api)
    pages = saved_feed_pages(
        saved_page([ig_iphone_media("a"), ig_iphone_media("b")], next_max_id="c1")
    )
    _feed_table(loader, feed_api)[IG_SAVED_FEED] = lambda params: (
        ig_error(THROTTLED_401, IG_SAVED_FEED) if params.get("max_id") else pages(params)
    )
    with pytest.raises(InstagramRateLimited), collector:
        collector.collect_saved()
    assert count(db) == 2 and collector.stats.stopped_reason == "rate_limited"


@FEED_APIS
def test_feed_fail_status_is_one_request_and_keeps_progress(
    db: Database, settings: Settings, feed_api: str
) -> None:
    collector, loader = _feed_collector(db, settings, feed_api=feed_api)
    pages = saved_feed_pages(
        saved_page([ig_iphone_media("a"), ig_iphone_media("b")], next_max_id="c1")
    )
    _feed_table(loader, feed_api)[IG_SAVED_FEED] = lambda params: (
        ig_error(FEED_FAIL_200, IG_SAVED_FEED) if params.get("max_id") else pages(params)
    )
    with pytest.raises(InstagramFeedUnavailable) as info, collector:
        collector.collect_saved()

    other = "iphone" if feed_api == "web" else "web"
    message = str(info.value)
    assert info.value.feed_api == feed_api
    assert "something went wrong" in message and "session is fine" in message
    assert "nothing stored was lost" in message and f'feed_api = "{other}"' in message
    assert "https://" not in message  # no URL / query string in the message
    assert len(_feed_requests(loader)) == 2  # page 2 asked once, no retries
    assert all(r[3] == 1 for r in loader.context.requests if r[1] == IG_SAVED_FEED)
    assert loader.context.max_connection_attempts == 3  # restored
    assert count(db) == 2 and collector.stats.stopped_reason == "feed_unavailable"
    assert loader.logins == []


def test_feed_fail_status_on_first_page_is_one_request(db: Database, settings: Settings) -> None:
    collector, loader = _feed_collector(db, settings)
    loader.context.web_responses[IG_SAVED_FEED] = ig_error(FEED_FAIL_200, IG_SAVED_FEED)
    with pytest.raises(InstagramFeedUnavailable), collector:
        collector.collect_saved()
    assert len(_feed_requests(loader)) == 1
    assert collector.stats.stopped_reason == "feed_unavailable" and count(db) == 0


def _network_error() -> Exception:
    from instaloader.exceptions import ConnectionException

    cause = requests.exceptions.ReadTimeout("Read timed out.")
    try:
        raise ConnectionException(f"JSON Query to {IG_SAVED_FEED}: {cause}") from cause
    except ConnectionException as exc:
        return exc


def test_feed_network_errors_are_retried_up_to_the_configured_attempts(
    db: Database, settings: Settings
) -> None:
    collector, loader = _feed_collector(db, settings)
    answers = [_network_error(), saved_page([ig_iphone_media("a")])]
    loader.context.web_responses[IG_SAVED_FEED] = lambda params: answers.pop(0)
    with collector:
        stats = collector.collect_saved()
    assert stats.new == 1 and len(_feed_requests(loader)) == 2

    collector, loader = _feed_collector(db, settings)
    loader.context.web_responses[IG_SAVED_FEED] = lambda params: _network_error()
    with pytest.raises(Exception, match="Read timed out"), collector:
        collector.collect_saved()
    assert len(_feed_requests(loader)) == 3  # max_connection_attempts
    assert loader.context.max_connection_attempts == 3


def test_feed_api_option_parsing() -> None:
    class Cfg:
        def __init__(self, **values: object) -> None:
            self.values = {f"instagram.{k}": v for k, v in values.items()}

        def get(self, key: str, default: object = None) -> object:
            return self.values.get(key, default)

    assert InstagramOptions.from_config(None).feed_api == "web"
    assert InstagramOptions.from_config(Cfg()).feed_api == "web"
    assert InstagramOptions.from_config(Cfg(feed_api="iphone")).feed_api == "iphone"
    assert InstagramOptions.from_config(Cfg(feed_api=" Web ")).feed_api == "web"
    with pytest.raises(ValueError, match=r"instagram\.feed_api must be one of 'web', 'iphone'"):
        InstagramOptions.from_config(Cfg(feed_api="graphql"))
    with pytest.raises(ValueError, match="feed_api"):
        InstagramOptions(feed_api="mobile")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Session outcome on the progress callback
# ---------------------------------------------------------------------------


def test_verified_session_is_reported(db: Database, settings: Settings) -> None:
    events: list = []
    collector, _ = _feed_collector(db, settings, saved_page([]), progress=events.append)
    collector.login()
    assert [(e.phase, e.message) for e in events] == [
        ("session", "Instagram session verified (no password login)")
    ]


@pytest.mark.parametrize(
    ("setup", "why"),
    [
        ("logged_out", "session logged out: login_required"),
        ("no_file", "no session file"),
    ],
)
def test_password_login_is_reported(db: Database, settings: Settings, setup: str, why: str) -> None:
    if setup == "logged_out":
        _existing_session(settings)
    events: list = []
    loader = FakeLoader(session_user=None)
    collector = make(db, settings, loader=loader, progress=events.append)
    collector.login()
    assert loader.logins == ["me"]
    assert [(e.phase, e.message) for e in events] == [
        ("login", f"No usable Instagram session ({why}); logging in with the password now")
    ]
    assert all("pw-secret" not in (e.message or "") for e in events)


def test_map_iphone_image_post() -> None:
    post = post_from_iphone_media(FakeIgContext("me"), ig_iphone_media("Img1"))
    item = map_post(post, rank=3)

    assert (item.external_id, item.kind, item.author) == ("Img1", "image", "chef")
    assert item.text == "Pasta #Rezept @Chef"
    assert item.created_at.isoformat() == "2023-11-14T22:13:20+00:00"
    assert item.media is None
    assert item.detail == InstagramDetail(
        shortcode="Img1",
        owner_id=123,
        typename="GraphImage",
        likes=10,
        comments=2,
        saved_feed_rank=3,
        date_status="verified",
    )


def test_map_iphone_video_and_reel() -> None:
    post = post_from_iphone_media(
        FakeIgContext("me"), ig_iphone_media("Vid1", 2, video_url="https://cdn/reel.mp4")
    )
    item = map_post(post, 0)
    assert item.kind == "video" and item.detail.typename == "GraphVideo"
    (media,) = item.media
    assert (media.position, media.remote_url, media.duration_s, media.transcript_status) == (
        0,
        "https://cdn/reel.mp4",
        31.5,
        "pending",
    )


def test_map_iphone_sidecar_records_video_children() -> None:
    struct = ig_iphone_media(
        "Car1",
        8,
        children=[
            ig_iphone_child(1),
            ig_iphone_child(2, "https://cdn/child1.mp4"),
            ig_iphone_child(2, "https://cdn/child2.mp4"),
        ],
    )
    struct["carousel_media"][0].pop("image_versions2")  # instaloader would drop all children
    item = map_post(post_from_iphone_media(FakeIgContext("me"), struct), 0)

    assert item.kind == "carousel"
    assert [(m.position, m.remote_url, m.duration_s) for m in item.media] == [
        (1, "https://cdn/child1.mp4", 12.25),
        (2, "https://cdn/child2.mp4", 12.25),
    ]


def test_iphone_struct_missing_required_keys_uses_minimal_node() -> None:
    struct = ig_iphone_media("Odd1", 2, video_url="https://cdn/v.mp4", caption=None)
    del struct["like_count"], struct["has_liked"]  # e.g. like counts hidden
    item = map_post(post_from_iphone_media(FakeIgContext("me"), struct), 0)
    assert (item.kind, item.author, item.text, item.detail.likes) == ("video", "chef", None, None)
    assert item.media[0].remote_url == "https://cdn/v.mp4"

    unknown = ig_iphone_media("Odd2", 99)
    item = map_post(post_from_iphone_media(FakeIgContext("me"), unknown), 0)
    assert (item.kind, item.detail.typename) == ("other", None)


def test_iphone_mapping_never_triggers_requests() -> None:
    context = FakeIgContext("me")
    struct = ig_iphone_media("Q1", 8, children=[ig_iphone_child(2, "https://cdn/c.mp4")])
    map_post(post_from_iphone_media(context, struct), 0)
    assert context.requests == []


# ---------------------------------------------------------------------------
# Real instaloader context, HTTP layer faked (no socket is opened)
# ---------------------------------------------------------------------------


class _Http:
    """Records ``requests.Session.get/post`` calls and answers from a script."""

    def __init__(self, answers: list[tuple]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str, dict]] = []
        #: Request headers per call (lower-case names).
        self.headers: list[dict[str, str]] = []

    def response(
        self, method: str, url: str, params: dict | None, headers: Any = None
    ) -> requests.Response:
        self.calls.append((method, url, dict(params or {})))
        self.headers.append({k.lower(): v for k, v in dict(headers or {}).items()})
        if not self.answers:
            raise AssertionError(f"unexpected request {method} {url}")
        status, body, *extra = self.answers.pop(0)
        resp = requests.Response()
        resp.headers.update(extra[0] if extra else {})
        resp.status_code = status
        resp.reason = {200: "OK", 401: "Unauthorized", 403: "Forbidden"}.get(status, "")
        resp._content = json.dumps(body).encode()
        resp.headers["Content-Type"] = "application/json; charset=utf-8"
        resp.url = url
        return resp


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch):
    def install(*answers: tuple[int, dict]) -> _Http:
        fake = _Http(list(answers))
        monkeypatch.setattr(
            requests.Session,
            "get",
            lambda self, url, params=None, **kw: fake.response("GET", url, params, self.headers),
        )
        monkeypatch.setattr(
            requests.Session,
            "post",
            lambda self, url, data=None, **kw: fake.response("POST", url, data, self.headers),
        )
        return fake

    monkeypatch.setattr(instaloader.InstaloaderContext, "do_sleep", lambda self: None)
    return install


def _real_session_file(settings: Settings) -> Path:
    path = _session(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        pickle.dump(dict(SESSION_COOKIES), fh)
    return path


def _real_collector(db: Database, settings: Settings, **kwargs) -> InstagramCollector:
    return InstagramCollector(db, settings, CREDS, sleep=SleepRecorder(), **kwargs)


def test_real_context_throttled_check_is_one_request(
    db: Database, settings: Settings, http
) -> None:
    path = _real_session_file(settings)
    before = path.read_bytes()
    fake = http(
        (401, {"message": "Please wait a few minutes before you try again.", "status": "fail"})
    )
    with pytest.raises(InstagramSessionCheckFailed, match="Please wait a few minutes"):
        _real_collector(db, settings).login()

    assert [(m, u) for m, u, _ in fake.calls] == [
        ("GET", f"https://i.instagram.com/{IG_USER_INFO}")
    ]
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("feed_api", "feed_url"),
    [
        ("web", f"https://www.instagram.com/{IG_SAVED_FEED}"),
        ("iphone", f"https://i.instagram.com/{IG_SAVED_FEED}"),
    ],
)
def test_real_context_valid_session_and_saved_feed(
    db: Database, settings: Settings, http, feed_api: str, feed_url: str
) -> None:
    _real_session_file(settings)
    fake = http(
        (200, {"user": {"pk": 4242, "username": "me"}, "status": "ok"}),
        (
            200,
            saved_page([ig_iphone_media("r1", 2, video_url="https://cdn/r1.mp4")], "c1"),
            {"x-ig-set-www-claim": "hmac.claim-1"},
        ),
        (
            200,
            saved_page(
                [ig_iphone_media("r2", 8, children=[ig_iphone_child(2, "https://cdn/r2.mp4")])]
            ),
        ),
    )
    collector = _real_collector(db, settings, options=InstagramOptions(feed_api=feed_api))
    with collector:
        stats = collector.collect_saved()

    assert stats.new == 2
    urls = [u for _, u, _ in fake.calls]
    assert urls == [f"https://i.instagram.com/{IG_USER_INFO}"] + [feed_url] * 2
    assert fake.calls[2][2]["max_id"] == "c1"
    first, second = fake.headers[1], fake.headers[2]
    if feed_api == "web":
        assert fake.calls[1][2] == {"count": "50"}
        assert first["x-ig-app-id"] == "936619743392459"
        assert first["x-csrftoken"] == SESSION_COOKIES["csrftoken"]
        assert first["x-requested-with"] == "XMLHttpRequest"
        assert first["referer"] == "https://www.instagram.com/me/saved/all-posts/"
        assert first["host"] == "www.instagram.com"
        assert (first["x-ig-www-claim"], second["x-ig-www-claim"]) == ("0", "hmac.claim-1")
        assert "x-instagram-ajax" not in first and "x-pigeon-session-id" not in first
    else:
        assert fake.calls[1][2] == {"include_igtv_preview": "false"}
        assert first["x-ig-app-id"] == "124024574287414"  # instaloader's iPad headers
        assert "x-requested-with" not in first
    assert all(LEGACY_LOGIN_HASH not in repr(call) for call in fake.calls)
    assert all("query_hash" not in call[2] for call in fake.calls)
    assert get(db, "r1")[2][0].remote_url == "https://cdn/r1.mp4"
    assert get(db, "r2")[2][0].remote_url == "https://cdn/r2.mp4"
    assert collector.loader.context.max_connection_attempts == 3


def test_real_context_login_required_falls_back_to_password(
    db: Database, settings: Settings, http, monkeypatch: pytest.MonkeyPatch
) -> None:
    _real_session_file(settings)
    http((403, {"message": "login_required", "status": "fail"}))
    logins: list[str] = []
    monkeypatch.setattr(
        instaloader.Instaloader, "login", lambda self, user, passwd: logins.append(user)
    )
    collector = _real_collector(db, settings, allow_password_login=True)
    collector.login()
    assert logins == ["me"] and collector.logged_in


def test_real_context_login_required_never_logs_in_by_default(
    db: Database, settings: Settings, http, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _real_session_file(settings)
    before = path.read_bytes()
    http(
        (
            403,
            {"message": "login_required", "status": "fail"},
            {"Set-Cookie": "sessionid=leaked-sid; Path=/"},
        )
    )
    monkeypatch.setattr(
        instaloader.Instaloader,
        "login",
        lambda self, user, passwd: pytest.fail("no password login"),
    )
    collector = _real_collector(db, settings)
    with pytest.raises(InstagramAuthRequired) as info:
        collector.login()
    message = str(info.value)
    assert "No password login was attempted (session logged out: login_required)" in message
    assert "`postparse check instagram --login`" in message
    assert "https://" not in message and "leaked-sid" not in message
    assert path.read_bytes() == before and not collector.logged_in


@pytest.mark.parametrize("feed_api", ["web", "iphone"])
def test_real_context_feed_fail_status_is_exactly_one_request(
    db: Database, settings: Settings, http, feed_api: str
) -> None:
    _real_session_file(settings)
    fail = {"message": "We're sorry, but something went wrong. Please try again.", "status": "fail"}
    fake = http((200, {"user": {"pk": 4242, "username": "me"}, "status": "ok"}), (200, fail))
    collector = _real_collector(db, settings, options=InstagramOptions(feed_api=feed_api))
    with pytest.raises(InstagramFeedUnavailable, match="something went wrong"), collector:
        collector.collect_saved()
    assert len(fake.calls) == 2  # session check + one feed request, no retries
    assert collector.stats.stopped_reason == "feed_unavailable"
    assert collector.loader.context.max_connection_attempts == 3


# ---------------------------------------------------------------------------
# No automatic password login (extract runs, re-fetches, API jobs)
# ---------------------------------------------------------------------------


def _broken_session_file(loader: FakeLoader) -> FakeLoader:
    def broken(username: str, filename: str) -> None:
        raise EOFError("Ran out of input")

    loader.load_session_from_file = broken  # type: ignore[method-assign]
    return loader


#: ``(setup, loader factory, reason in the message)`` of sessions that cannot be used.
UNUSABLE_SESSIONS = [
    ("no_file", lambda: FakeLoader(session_user="me"), "no session file"),
    (
        "file",
        lambda: _broken_session_file(FakeLoader(session_user="me")),
        "session file unreadable",
    ),
    ("file", lambda: FakeLoader(session_user=None), "session logged out: login_required"),
    (
        "file",
        lambda: FakeLoader(check_error=LoginRequiredException("Redirected to login page.")),
        "session logged out: redirected to login page",
    ),
    (
        "file",
        lambda: FakeLoader(session_cookies={"csrftoken": "x"}),
        "session logged out: the session file has no login cookies",
    ),
    (
        "file",
        lambda: FakeLoader(session_user="someone_else"),
        "session logged out: the session belongs to another account",
    ),
]


@pytest.mark.parametrize(
    "creds", [CREDS, InstagramCredentials("me", None)], ids=["password", "no-password"]
)
@pytest.mark.parametrize(
    ("setup", "make_loader", "why"),
    UNUSABLE_SESSIONS,
    ids=["no-file", "unreadable", "login-required", "login-redirect", "no-cookies", "other-user"],
)
def test_extract_never_logs_in_with_the_password(
    db: Database,
    settings: Settings,
    setup: str,
    make_loader: Any,
    why: str,
    creds: InstagramCredentials,
) -> None:
    path = _existing_session(settings) if setup == "file" else _session(settings)
    loader = make_loader()
    events: list = []
    collector = InstagramCollector(
        db,
        settings,
        creds,
        loader_factory=loader_factory(loader),
        saved_posts=Feed([]),
        sleep=SleepRecorder(),
        prompt=lambda _: pytest.fail("must not prompt"),
        progress=events.append,
    )
    assert collector.allow_password_login is False  # the default

    with pytest.raises(InstagramAuthRequired) as info, collector:
        pytest.fail("must not enter")

    message = str(info.value)
    assert message.startswith(f"No password login was attempted ({why}); automatic password ")
    assert "trigger Instagram checkpoints" in message
    assert "run `postparse check instagram --login` in a terminal" in message
    assert "2FA code" in message and "then retry" in message
    assert loader.logins == [] and loader.two_factor_codes == [] and loader.saved == []
    assert events == []  # no "logging in with the password" line
    assert not collector.logged_in
    if setup == "file":
        assert path.read_text() == "original-session"
    else:
        assert not path.exists()
    assert "pw-secret" not in message


# ---------------------------------------------------------------------------
# Instagram's reason in messages (sanitized)
# ---------------------------------------------------------------------------

#: A login redirect whose location carries a query string with cookie-like values.
REDIRECT_WITH_QUERY = (
    'Query to https://i.instagram.com/api/v1/users/4242/info/ responded with "302 Found" '
    "redirect to https://www.instagram.com/accounts/login/?next=%2Fapi%2F&sessionid=leaked-sid"
    "&csrftoken=leaked-csrf#frag"
)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ('403 Forbidden - "fail" status, message "login_required"', "login_required"),
        ('400 Bad Request - "fail" status, message "checkpoint_required"', "checkpoint_required"),
        ('400 Bad Request - "fail" status, message "challenge_required"', "challenge_required"),
        ('400 Bad Request - "fail" status, message "feedback_required"', "feedback_required"),
        (
            'Query to https://i.instagram.com/x/ responded with "400 Bad Request": '
            '{"message": "challenge_required", "status": "fail", "checkpoint_url": '
            '"https://i.instagram.com/challenge/?token=leaked-token"}',
            "challenge_required",
        ),
        (REDIRECT_WITH_QUERY, "redirect to https://www.instagram.com/accounts/login/"),
        ("Redirected to login page. Use --login or --load-cookies.", "redirected to login page"),
    ],
    ids=[
        "login_required",
        "checkpoint_required",
        "challenge_required",
        "feedback_required",
        "json-body",
        "redirect",
        "login-redirect",
    ],
)
def test_instagram_reason_is_short_and_sanitized(text: str, reason: str) -> None:
    from postparse.collectors.instagram.collector import _instagram_message

    full = (
        f"JSON Query to {IG_USER_INFO}: {text} when accessing "
        "https://i.instagram.com/x?sessionid=leaked-sid"
    )
    result = _instagram_message(full)
    assert result == reason
    for leak in ("leaked", "sessionid", "csrftoken", "token=", "?", "#"):
        assert leak not in result


def test_instagram_reason_redacts_secrets_and_is_truncated() -> None:
    from postparse.collectors.instagram.collector import MAX_REASON_LENGTH, _instagram_message

    reason = _instagram_message("odd answer sessionid=leaked-sid; csrftoken=leaked " + "x" * 500)
    assert "leaked" not in reason and "sessionid=<redacted>" in reason
    assert len(reason) <= MAX_REASON_LENGTH


def test_checkpoint_on_session_check_shows_the_reason(db: Database, settings: Settings) -> None:
    from instaloader.exceptions import ConnectionException

    _existing_session(settings)
    loader = FakeLoader(
        check_error=ConnectionException(
            f'JSON Query to {IG_USER_INFO}: 400 Bad Request - "fail" status, message '
            f'"checkpoint_required" when accessing https://i.instagram.com/{IG_USER_INFO}'
            "?sessionid=leaked-sid"
        )
    )
    with pytest.raises(InstagramAuthRequired) as info:
        make(db, settings, loader=loader, allow_password_login=False).login()
    message = str(info.value)
    assert "(Instagram: checkpoint_required)" in message
    assert "leaked-sid" not in message and "https://" not in message
    assert loader.logins == []


def test_login_redirect_during_feed_shows_the_redirect_without_query(
    db: Database, settings: Settings
) -> None:
    collector, loader = _feed_collector(db, settings)
    loader.context.web_responses[IG_SAVED_FEED] = AbortDownloadException(REDIRECT_WITH_QUERY)
    with pytest.raises(InstagramAuthRequired) as info, collector:
        collector.collect_saved()
    message = str(info.value)
    assert "(Instagram: redirect to https://www.instagram.com/accounts/login/)" in message
    assert "`postparse check instagram --login`" in message
    for leak in ("leaked", "next=", "?", "#frag"):
        assert leak not in message
    assert collector.stats.stopped_reason == "auth_required"
    assert loader.logins == []


def test_throttled_session_check_message_has_no_url(db: Database, settings: Settings) -> None:
    _existing_session(settings)
    loader = FakeLoader(check_error=ig_error(THROTTLED_401))
    with pytest.raises(InstagramSessionCheckFailed) as info:
        make(db, settings, loader=loader).login()
    message = str(info.value)
    assert "(Please wait a few minutes before you try again.)" in message
    assert "https://" not in message and IG_USER_INFO not in message
    assert loader.logins == []


# ---------------------------------------------------------------------------
# "429" only as an HTTP status, never inside URLs
# ---------------------------------------------------------------------------


def _feed_fail_with_cursor(cursor: str) -> Exception:
    from instaloader.exceptions import ConnectionException

    return ConnectionException(
        f'JSON Query to {IG_SAVED_FEED}: 200 OK - "fail" status, message "We\'re sorry, but '
        f'something went wrong." when accessing https://www.instagram.com/{IG_SAVED_FEED}'
        f"?count=50&max_id={cursor}"
    )


@pytest.mark.parametrize("cursor", ["3429876543210", "429", "QVFD429-x_429"])
def test_429_inside_the_url_is_not_a_rate_limit(
    db: Database, settings: Settings, cursor: str
) -> None:
    collector, loader = _feed_collector(db, settings)
    pages = saved_feed_pages(saved_page([ig_iphone_media("a")], next_max_id=cursor))
    loader.context.web_responses[IG_SAVED_FEED] = lambda params: (
        _feed_fail_with_cursor(cursor) if params.get("max_id") else pages(params)
    )
    with pytest.raises(InstagramFeedUnavailable) as info, collector:
        collector.collect_saved()
    assert "something went wrong" in str(info.value) and "max_id" not in str(info.value)
    assert collector.stats.stopped_reason == "feed_unavailable"
    assert count(db) == 1


@pytest.mark.parametrize(
    "error",
    [
        TooManyRequestsException("429 Too Many Requests when accessing https://x/?max_id=1"),
        ig_error("429 Too Many Requests", IG_SAVED_FEED),
        ig_error('429 - "fail" status, message "slow down"', IG_SAVED_FEED),
        ig_error(THROTTLED_401, IG_SAVED_FEED),
    ],
    ids=["exception", "status-429", "status-429-bare", "401-please-wait"],
)
def test_real_rate_limits_are_still_detected(
    db: Database, settings: Settings, error: Exception
) -> None:
    collector, loader = _feed_collector(db, settings)
    loader.context.web_responses[IG_SAVED_FEED] = error
    with pytest.raises(InstagramRateLimited) as info, collector:
        collector.collect_saved()
    assert not isinstance(info.value, InstagramFeedUnavailable)
    assert collector.stats.stopped_reason == "rate_limited"
    assert "https://" not in str(info.value)


def test_session_check_ids_in_the_path_are_not_a_throttle() -> None:
    """A user id containing 429 does not turn "login_required" into a throttle."""
    from postparse.collectors.instagram.collector import _session_check_verdict

    exc = ig_error(LOGGED_OUT_403, "api/v1/users/14290/info/")
    assert "429" in str(exc)
    assert _session_check_verdict(exc) == "logged_out"
    assert _session_check_verdict(ig_error("429 Too Many Requests")) == "failed"
