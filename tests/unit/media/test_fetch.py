"""InstagramVideoFetcher: fresh vs stale URLs, re-fetch throttling, errors (no network)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from instaloader.exceptions import (
    BadResponseException,
    ProfileNotExistsException,
    QueryReturnedNotFoundException,
)

from postparse.collectors.base import InstagramAuthRequired, InstagramRateLimited
from postparse.core.db import Database
from postparse.media.fetch import (
    FetchError,
    InstagramVideoFetcher,
    MediaUnavailable,
    RefetchDisabled,
    RefetchError,
    video_url_for,
)
from postparse.media.options import TranscriptionOptions
from tests.unit.collectors.fakes import ig_node, ig_post
from tests.unit.media.helpers import NOW, add_video_item, fresh, get_media

VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"v" * 4000


class FakeCollector:
    """Stand-in for an InstagramCollector (context manager + fetch_post)."""

    def __init__(
        self,
        posts: dict[str, Any] | None = None,
        errors: dict[str, BaseException] | None = None,
        enter_error: BaseException | None = None,
    ) -> None:
        self.posts = posts or {}
        self.errors = errors or {}
        self.enter_error = enter_error
        self.entered = 0
        self.exited = 0
        self.fetched: list[str] = []

    def __enter__(self) -> FakeCollector:
        self.entered += 1
        if self.enter_error is not None:
            raise self.enter_error
        return self

    def __exit__(self, *exc: object) -> None:
        self.exited += 1

    def fetch_post(self, shortcode: str) -> Any:
        self.fetched.append(shortcode)
        if shortcode in self.errors:
            raise self.errors[shortcode]
        return self.posts[shortcode]


def video_post(url: str) -> Any:
    return SimpleNamespace(typename="GraphVideo", is_video=True, video_url=url)


class Cdn:
    """httpx mock transport serving videos by URL."""

    def __init__(self, responses: dict[str, httpx.Response | bytes]) -> None:
        self.responses = responses
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        value = self.responses.get(url, httpx.Response(404))
        return httpx.Response(200, content=value) if isinstance(value, bytes) else value


def make_fetcher(
    db: Database,
    cdn: Cdn,
    collector: FakeCollector | None = None,
    *,
    refetch: bool = True,
    sleeps: list[float] | None = None,
    **options: Any,
) -> InstagramVideoFetcher:
    opts = TranscriptionOptions(refetch_min_delay=20, refetch_max_delay=60, **options)
    factory_calls: list[int] = []

    def factory() -> FakeCollector:
        factory_calls.append(1)
        assert collector is not None
        return collector

    fetcher = InstagramVideoFetcher(
        db,
        opts,
        collector_factory=factory if collector is not None else None,
        refetch=refetch,
        http_client=httpx.Client(transport=httpx.MockTransport(cdn)),
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        clock=lambda: NOW,
    )
    fetcher.factory_calls = factory_calls  # type: ignore[attr-defined]
    return fetcher


def test_fresh_url_is_downloaded_without_refetch(db: Database, tmp_path: Path) -> None:
    _, (mid,) = add_video_item(
        db, "FRESH", remote_url="https://cdn.test/fresh.mp4", seen_at=fresh(30)
    )
    cdn = Cdn({"https://cdn.test/fresh.mp4": VIDEO})
    collector = FakeCollector()
    with make_fetcher(db, cdn, collector) as fetcher:
        result = fetcher.fetch(get_media(db, mid), "FRESH", tmp_path)
    assert result.path.read_bytes() == VIDEO and result.refetched is False
    assert result.size_bytes == len(VIDEO)
    assert collector.entered == 0 and fetcher.refetches == 0  # no Instagram login at all


def test_stale_url_triggers_refetch_and_stores_fresh_url(db: Database, tmp_path: Path) -> None:
    _, (mid,) = add_video_item(
        db, "STALE", remote_url="https://cdn.test/old.mp4", seen_at=NOW - timedelta(hours=7)
    )
    cdn = Cdn({"https://cdn.test/new.mp4": VIDEO})
    collector = FakeCollector({"STALE": video_post("https://cdn.test/new.mp4")})
    with make_fetcher(db, cdn, collector) as fetcher:
        result = fetcher.fetch(get_media(db, mid), "STALE", tmp_path)
    assert result.refetched and fetcher.refetches == 1
    assert cdn.requests == ["https://cdn.test/new.mp4"]  # the stale URL is not even tried
    media = get_media(db, mid)
    assert media.remote_url == "https://cdn.test/new.mp4"
    assert media.remote_url_seen_at == NOW
    assert collector.exited == 1  # session saved on close


def test_missing_url_refetch_disabled(db: Database, tmp_path: Path) -> None:
    _, (mid,) = add_video_item(db, "NOURL")
    with (
        make_fetcher(db, Cdn({}), FakeCollector(), refetch=False) as fetcher,
        pytest.raises(RefetchDisabled),
    ):
        fetcher.fetch(get_media(db, mid), "NOURL", tmp_path)


def test_fresh_url_refused_falls_back_to_refetch(db: Database, tmp_path: Path) -> None:
    _, (mid,) = add_video_item(db, "EXP", remote_url="https://cdn.test/exp.mp4", seen_at=fresh(10))
    cdn = Cdn({"https://cdn.test/exp.mp4": httpx.Response(403), "https://cdn.test/exp2.mp4": VIDEO})
    collector = FakeCollector({"EXP": video_post("https://cdn.test/exp2.mp4")})
    with make_fetcher(db, cdn, collector) as fetcher:
        result = fetcher.fetch(get_media(db, mid), "EXP", tmp_path)
    assert result.refetched
    assert cdn.requests == ["https://cdn.test/exp.mp4", "https://cdn.test/exp2.mp4"]


def test_refetches_share_one_login_and_are_throttled(db: Database, tmp_path: Path) -> None:
    media_ids = [add_video_item(db, f"P{i}")[1][0] for i in range(3)]
    posts = {f"P{i}": video_post(f"https://cdn.test/p{i}.mp4") for i in range(3)}
    cdn = Cdn({f"https://cdn.test/p{i}.mp4": VIDEO for i in range(3)})
    collector = FakeCollector(posts)
    sleeps: list[float] = []
    with make_fetcher(db, cdn, collector, sleeps=sleeps) as fetcher:
        for i, mid in enumerate(media_ids):
            (tmp_path / str(i)).mkdir()
            fetcher.fetch(get_media(db, mid), f"P{i}", tmp_path / str(i))
    assert fetcher.factory_calls == [1] and collector.entered == 1  # type: ignore[attr-defined]
    assert collector.fetched == ["P0", "P1", "P2"]
    assert len(sleeps) == 2 and all(20 <= s <= 60 for s in sleeps)  # no pause before the 1st


@pytest.mark.parametrize("error", [InstagramRateLimited("429"), InstagramAuthRequired("nope")])
def test_rate_limit_and_auth_errors_propagate(
    db: Database, tmp_path: Path, error: BaseException
) -> None:
    _, (mid,) = add_video_item(db, "RL")
    with (
        make_fetcher(db, Cdn({}), FakeCollector(errors={"RL": error})) as fetcher,
        pytest.raises(type(error)),
    ):
        fetcher.fetch(get_media(db, mid), "RL", tmp_path)
    assert get_media(db, mid).remote_url is None


def test_login_failure_propagates(db: Database, tmp_path: Path) -> None:
    _, (mid,) = add_video_item(db, "X")
    collector = FakeCollector(enter_error=InstagramAuthRequired("no session"))
    with make_fetcher(db, Cdn({}), collector) as fetcher, pytest.raises(InstagramAuthRequired):
        fetcher.fetch(get_media(db, mid), "X", tmp_path)


@pytest.mark.parametrize(
    "error",
    [
        QueryReturnedNotFoundException("404 not found"),
        ProfileNotExistsException("profile gone"),
    ],
)
def test_deleted_posts_are_unavailable(db: Database, tmp_path: Path, error: Exception) -> None:
    _, (mid,) = add_video_item(db, "GONE")
    with (
        make_fetcher(db, Cdn({}), FakeCollector(errors={"GONE": error})) as fetcher,
        pytest.raises(MediaUnavailable),
    ):
        fetcher.fetch(get_media(db, mid), "GONE", tmp_path)


def test_post_without_video_is_unavailable(db: Database, tmp_path: Path) -> None:
    _, (mid,) = add_video_item(db, "IMG")
    post = SimpleNamespace(typename="GraphImage", is_video=False, video_url=None)
    with (
        make_fetcher(db, Cdn({}), FakeCollector({"IMG": post})) as fetcher,
        pytest.raises(MediaUnavailable, match="no video"),
    ):
        fetcher.fetch(get_media(db, mid), "IMG", tmp_path)


def test_other_refetch_errors_are_retryable(db: Database, tmp_path: Path) -> None:
    _, (mid,) = add_video_item(db, "ERR")
    collector = FakeCollector(errors={"ERR": RuntimeError("socket closed")})
    with (
        make_fetcher(db, Cdn({}), collector) as fetcher,
        pytest.raises(FetchError, match="socket closed"),
    ):
        fetcher.fetch(get_media(db, mid), "ERR", tmp_path)


def test_size_cap(db: Database, tmp_path: Path) -> None:
    _, (mid,) = add_video_item(db, "BIG", remote_url="https://cdn.test/big.mp4", seen_at=fresh())
    cdn = Cdn({"https://cdn.test/big.mp4": b"x" * (2 * 1024 * 1024)})
    work = tmp_path / "work"
    work.mkdir()
    with (
        make_fetcher(db, cdn, max_download_mb=1) as fetcher,
        pytest.raises(FetchError, match=r"too large|size cap"),
    ):
        fetcher.fetch(get_media(db, mid), "BIG", work)
    assert list(work.iterdir()) == []  # partial file removed


def test_http_errors_are_fetch_errors(db: Database, tmp_path: Path) -> None:
    _, (mid,) = add_video_item(db, "E5", remote_url="https://cdn.test/e5.mp4", seen_at=fresh())
    cdn = Cdn({"https://cdn.test/e5.mp4": httpx.Response(503)})
    with make_fetcher(db, cdn) as fetcher, pytest.raises(FetchError, match="HTTP 503"):
        fetcher.fetch(get_media(db, mid), "E5", tmp_path)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    fetcher = InstagramVideoFetcher(
        db,
        TranscriptionOptions(),
        refetch=False,
        clock=lambda: NOW,
        http_client=httpx.Client(transport=httpx.MockTransport(boom)),
    )
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(FetchError, match="ReadTimeout"):
        fetcher.fetch(get_media(db, mid), "E5", work)
    assert list(work.iterdir()) == []


def test_video_url_for_single_and_sidecar() -> None:
    single = ig_post(ig_node("V", "GraphVideo", video_url="https://cdn.test/v.mp4"))
    assert video_url_for(single, 0) == "https://cdn.test/v.mp4"
    assert video_url_for(single, 1) is None
    sidecar = ig_post(
        ig_node(
            "S",
            "GraphSidecar",
            children=[
                {"is_video": False, "display_url": "https://cdn.test/0.jpg"},
                {
                    "is_video": True,
                    "display_url": "https://cdn.test/1.jpg",
                    "video_url": "https://cdn.test/1.mp4",
                },
            ],
        )
    )
    assert video_url_for(sidecar, 1) == "https://cdn.test/1.mp4"
    assert video_url_for(sidecar, 0) is None
    assert video_url_for(sidecar, 5) is None


def test_metadata_failed_is_retryable_not_unavailable(db: Database, tmp_path: Path) -> None:
    """Instagram answers soft-blocked sessions with "metadata failed" -> retry, never skip."""
    _, (mid,) = add_video_item(db, "SOFT")
    collector = FakeCollector(
        errors={"SOFT": BadResponseException("Fetching Post metadata failed.")}
    )
    with (
        make_fetcher(db, Cdn({}), collector) as fetcher,
        pytest.raises(RefetchError, match="metadata failed") as info,
    ):
        fetcher.fetch(get_media(db, mid), "SOFT", tmp_path)
    assert isinstance(info.value, FetchError)
    assert not isinstance(info.value, MediaUnavailable)
