"""TranscriptionService with fake backends / fetchers: status transitions, backoff, cleanup."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from postparse.collectors.base import InstagramAuthRequired, InstagramRateLimited
from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.repos import MediaRepo, SearchRepo, TranscriptsRepo
from postparse.media.fetch import (
    FetchError,
    InstagramVideoFetcher,
    MediaUnavailable,
    RefetchError,
)
from postparse.media.options import TranscriptionOptions
from postparse.media.transcription import BackendUnavailable, TranscriptionError
from postparse.services.transcription import TranscriptionService
from tests.unit.media.helpers import (
    NOW,
    FakeBackend,
    FakeFetcher,
    add_video_item,
    fresh,
    get_media,
    make_media_file,
)


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    for name in ("POSTPARSE_DATA_DIR", "POSTPARSE_DB_PATH", "POSTPARSE_SESSIONS_DIR",
                 "POSTPARSE_DOWNLOADS_DIR", "POSTPARSE_TMP_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def db(settings: Settings) -> Database:
    assert settings.db_path is not None
    return Database.open(settings.db_path)


def service(db: Database, settings: Settings, backend: Any = None, fetcher: Any = None,
            **options: Any) -> TranscriptionService:
    backend = backend or FakeBackend()
    fetcher = fetcher or FakeFetcher()
    svc = TranscriptionService(
        db, settings,
        options=TranscriptionOptions(**options),
        backend_factory=lambda kind: backend,
        fetcher_factory=lambda refetch: setattr(fetcher, "refetch", refetch) or fetcher,
        clock=lambda: NOW,
    )
    return svc


def scratch_files(settings: Settings) -> list[Path]:
    assert settings.tmp_dir is not None
    return list(settings.tmp_dir.rglob("*")) if settings.tmp_dir.exists() else []


def test_transcribes_pending_media_and_cleans_up(db: Database, settings: Settings) -> None:
    item_id, (mid,) = add_video_item(db, "A1")
    backend = FakeBackend("Heute kochen wir eine schnelle Tomatensoße")
    fetcher = FakeFetcher()
    updates: list[Any] = []
    report = service(db, settings, backend, fetcher).run(progress=updates.append)
    assert report.ok and report.transcribed == 1 and report.candidates == 1
    assert report.backend == "fake-asr" and report.model == "fake-model"
    assert report.audio_seconds == 6.0 and report.item_ids == [item_id]
    media = get_media(db, mid)
    assert media.transcript_status == "transcribed" and media.duration_s == 6.0
    with db.read() as conn:
        transcript = TranscriptsRepo(conn).current_for_media(mid)
        hits = conn.execute(
            "SELECT rowid FROM items_fts WHERE items_fts MATCH 'Tomatensoße'"
        ).fetchall()
    assert transcript is not None and transcript.language == "de"
    assert transcript.segments[0] == {"start": 0.0, "end": 1.0, "text": "Heute"}
    assert [h[0] for h in hits] == [item_id]  # FTS document refreshed
    assert updates[0].status == "transcribed" and updates[0].index == 1
    # Downloaded video and backend intermediates are gone; no scratch dirs remain.
    assert not fetcher.fetched[0][2].exists()
    assert scratch_files(settings) == []
    assert fetcher.closed


def test_no_audio_stream(db: Database, settings: Settings) -> None:
    _, (mid,) = add_video_item(db, "SILENT")
    backend = FakeBackend()
    report = service(db, settings, backend, FakeFetcher(audio=False)).run()
    assert report.no_audio == 1 and backend.calls == []
    media = get_media(db, mid)
    assert media.transcript_status == "no_audio" and media.last_error == "no audio stream"


def test_no_speech_is_no_audio(db: Database, settings: Settings) -> None:
    _, (mid,) = add_video_item(db, "MUSIC")
    report = service(db, settings, FakeBackend("   ")).run()
    assert report.no_audio == 1
    assert get_media(db, mid).transcript_status == "no_audio"
    with db.read() as conn:
        assert TranscriptsRepo(conn).current_for_media(mid) is None


def test_unavailable_post_is_skipped(db: Database, settings: Settings) -> None:
    _, (mid,) = add_video_item(db, "GONE")
    fetcher = FakeFetcher(errors={"GONE": MediaUnavailable("post not available")})
    report = service(db, settings, fetcher=fetcher).run()
    assert report.skipped == 1 and report.ok
    media = get_media(db, mid)
    assert media.transcript_status == "skipped" and media.last_error == "post not available"
    assert scratch_files(settings) == []


def test_too_long_media_is_skipped(db: Database, settings: Settings) -> None:
    _, (mid,) = add_video_item(db, "LONG")
    backend = FakeBackend()
    report = service(db, settings, backend, max_duration_minutes=0.001).run()
    assert report.skipped == 1 and backend.calls == []
    assert "too long" in (get_media(db, mid).last_error or "")


def test_failures_back_off_exponentially_until_max_attempts(
    db: Database, settings: Settings
) -> None:
    _, (mid,) = add_video_item(db, "FLAKY")
    backend = FakeBackend(error=TranscriptionError("decoder crashed"))
    svc = service(db, settings, backend, backoff_minutes=10, max_backoff_hours=24,
                  max_attempts=3)
    report = svc.run()
    assert report.failed == 1 and report.ok and "decoder crashed" in report.errors[0]
    media = get_media(db, mid)
    assert media.transcript_status == "failed" and media.attempts == 1
    assert media.next_attempt_at == NOW + timedelta(minutes=10)
    assert "decoder crashed" in (media.last_error or "")
    assert scratch_files(settings) == []

    assert svc.run().candidates == 0  # not due yet
    for attempt, delay in ((2, 20), (3, 40)):
        due_at = get_media(db, mid).next_attempt_at
        svc._clock = lambda due_at=due_at: due_at  # type: ignore[misc]
        assert svc.run().failed == 1
        media = get_media(db, mid)
        assert media.attempts == attempt
        assert media.next_attempt_at - svc._clock() == timedelta(minutes=delay)
    svc._clock = lambda: NOW + timedelta(days=30)
    assert svc.run().candidates == 0  # max attempts reached
    stats = svc.status()
    assert stats["exhausted"]["instagram"] == 1 and stats["due"]["instagram"] == 0


def test_failed_media_succeeds_on_retry(db: Database, settings: Settings) -> None:
    _, (mid,) = add_video_item(db, "RETRY")
    fetcher = FakeFetcher(errors={"RETRY": FetchError("HTTP 503")})
    svc = service(db, settings, fetcher=fetcher)
    assert svc.run().failed == 1
    fetcher.errors.clear()
    svc._clock = lambda: NOW + timedelta(hours=1)
    assert svc.run().transcribed == 1
    media = get_media(db, mid)
    assert media.transcript_status == "transcribed" and media.last_error is None


@pytest.mark.parametrize(("error", "reason"), [
    (InstagramRateLimited("429"), "rate_limited"),
    (InstagramAuthRequired("checkpoint"), "auth_required"),
])
def test_rate_limit_or_auth_stops_the_run(db: Database, settings: Settings,
                                          error: Exception, reason: str) -> None:
    _, (m1,) = add_video_item(db, "OK1")
    _, (m2,) = add_video_item(db, "STOP")
    _, (m3,) = add_video_item(db, "LATER")
    fetcher = FakeFetcher(errors={"STOP": error})
    report = service(db, settings, fetcher=fetcher).run()
    assert report.stopped_reason == reason and not report.ok
    assert report.transcribed == 1 and report.error
    assert get_media(db, m1).transcript_status == "transcribed"
    # The media that hit the limit is untouched (no failed attempt counted).
    assert get_media(db, m2).transcript_status == "pending"
    assert get_media(db, m2).attempts == 0
    assert get_media(db, m3).transcript_status == "pending"
    assert [f[1] for f in fetcher.fetched] == ["OK1", "STOP"]
    assert scratch_files(settings) == []


def test_backend_unavailable_stops_before_fetching(db: Database, settings: Settings) -> None:
    add_video_item(db, "A")
    fetcher = FakeFetcher()
    backend = FakeBackend(unavailable=BackendUnavailable("install the asr extra"))
    report = service(db, settings, backend, fetcher).run()
    assert report.stopped_reason == "backend_unavailable" and "asr" in (report.error or "")
    assert fetcher.fetched == []


def test_interrupt_cleans_up_and_keeps_progress(db: Database, settings: Settings) -> None:
    _, (m1,) = add_video_item(db, "DONE")
    _, (m2,) = add_video_item(db, "CTRLC")
    seen: list[Path] = []

    def interrupt(path: Path, work_dir: Path | None) -> None:
        seen.append(path)
        if path.name.startswith("CTRLC"):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        service(db, settings, FakeBackend(on_transcribe=interrupt)).run()
    assert get_media(db, m1).transcript_status == "transcribed"
    assert get_media(db, m2).transcript_status == "pending"
    assert all(not p.exists() for p in seen)
    assert scratch_files(settings) == []


def test_refetch_disabled_defers_media(db: Database, settings: Settings) -> None:
    _, (mid,) = add_video_item(db, "OLD", remote_url="https://cdn.test/old.mp4",
                               seen_at=NOW - timedelta(days=3))
    svc = TranscriptionService(
        db, settings, options=TranscriptionOptions(), clock=lambda: NOW,
        backend_factory=lambda kind: FakeBackend(),
    )
    report = svc.run(refetch=False)
    assert report.deferred == 1 and report.handled == 0 and report.ok
    assert get_media(db, mid).transcript_status == "pending"
    assert scratch_files(settings) == []


def test_item_ids_ignore_backoff_and_source(db: Database, settings: Settings) -> None:
    item_id, (mid,) = add_video_item(db, "X")
    other, _ = add_video_item(db, "Y")
    with db.transaction() as conn:
        MediaRepo(conn).mark_failed(mid, "boom", now=NOW)
    report = service(db, settings).run(item_ids=[item_id], source=None)
    assert report.candidates == 1 and report.transcribed == 1
    assert get_media(db, mid).transcript_status == "transcribed"
    assert report.item_ids == [item_id] and other not in report.item_ids


def test_limit(db: Database, settings: Settings) -> None:
    for i in range(4):
        add_video_item(db, f"L{i}")
    report = service(db, settings).run(limit=3)
    assert report.candidates == 3 and report.transcribed == 3
    assert service(db, settings).run(limit=None).candidates == 1  # default limit 50


def test_kept_local_file_is_used_and_not_deleted(db: Database, settings: Settings) -> None:
    assert settings.downloads_dir is not None
    local = settings.downloads_dir / "telegram" / "clip.mp4"
    local.parent.mkdir(parents=True)
    make_media_file(local)
    _, (mid,) = add_video_item(db, "100:5", source="telegram", kind="video",
                               local_path="telegram/clip.mp4")
    fetcher = FakeFetcher()
    report = service(db, settings, fetcher=fetcher).run(source="telegram")
    assert report.transcribed == 1 and fetcher.fetched == []
    assert local.exists()  # files the user keeps are never deleted


def test_status_counts(db: Database, settings: Settings) -> None:
    _, (m1,) = add_video_item(db, "S1")
    add_video_item(db, "S2")
    with db.transaction() as conn:
        MediaRepo(conn).mark_failed(m1, "boom", now=NOW)
    stats = service(db, settings).status()
    assert stats["counts"][("instagram", "pending")] == 1
    assert stats["counts"][("instagram", "failed")] == 1
    assert stats["due"]["instagram"] == 1
    assert stats["next_attempt_at"]["instagram"].startswith("2026-10-26T12:10")
    assert stats["transcripts"] == 0 and stats["max_attempts"] == 5


def test_telegram_media_with_status_none_is_ignored(db: Database, settings: Settings) -> None:
    with db.transaction() as conn:
        from postparse.core.db.models import ItemUpsert, MediaInput
        from postparse.core.db.repos import ItemsRepo

        ItemsRepo(conn).upsert(ItemUpsert(
            source="telegram", external_id="1:1", kind="video", text="voice",
            media=(MediaInput(position=0, media_type="audio", transcript_status="none"),),
        ))
    report = service(db, settings).run(source=None)
    assert report.candidates == 0 and report.ok


# ---------------------------------------------------------------------------
# Real InstagramVideoFetcher wired through the service (fake collector + mock CDN)
# ---------------------------------------------------------------------------


def test_service_with_real_fetcher_refetch_and_throttle(
    db: Database, settings: Settings, tmp_path: Path
) -> None:
    video = make_media_file(tmp_path / "src.mp4").read_bytes()
    _, (fresh_id,) = add_video_item(db, "NEW", remote_url="https://cdn.test/new.mp4",
                                    seen_at=fresh())
    _, (old_id,) = add_video_item(db, "OLD1")
    _, (old2_id,) = add_video_item(db, "OLD2")
    _, (rl_id,) = add_video_item(db, "OLD3")

    class Collector:
        entered = 0

        def __enter__(self) -> Collector:
            Collector.entered += 1
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def fetch_post(self, shortcode: str) -> Any:
            if shortcode == "OLD3":
                raise InstagramRateLimited("429 Too Many Requests")
            return SimpleNamespace(typename="GraphVideo", is_video=True,
                                   video_url=f"https://cdn.test/{shortcode}.mp4")

    sleeps: list[float] = []
    http = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=video)))
    options = TranscriptionOptions(refetch_min_delay=20, refetch_max_delay=60)
    svc = TranscriptionService(
        db, settings, options=options, clock=lambda: NOW,
        backend_factory=lambda kind: FakeBackend(),
        fetcher_factory=lambda refetch: InstagramVideoFetcher(
            db, options, collector_factory=Collector, refetch=refetch, http_client=http,
            sleep=sleeps.append, clock=lambda: NOW),
    )
    report = svc.run()
    assert report.stopped_reason == "rate_limited"
    assert report.transcribed == 3 and report.refetched == 2
    assert Collector.entered == 1  # one login for the whole run
    assert len(sleeps) == 2  # pauses before the 2nd and 3rd re-fetch
    assert get_media(db, old_id).remote_url == "https://cdn.test/OLD1.mp4"
    assert get_media(db, rl_id).transcript_status == "pending"
    assert {get_media(db, m).transcript_status for m in (fresh_id, old_id, old2_id)} == {
        "transcribed"}
    assert scratch_files(settings) == []
    with db.read() as conn:
        assert SearchRepo(conn).integrity_check()


def test_consecutive_refetch_failures_open_the_circuit(db: Database, settings: Settings) -> None:
    """Three re-fetch failures in a row -> stop with suspected_block, rest untouched."""
    ids = [add_video_item(db, code)[1][0] for code in ("B1", "B2", "B3", "B4")]
    soft = RefetchError("Re-fetch failed: BadResponseException: metadata failed")
    fetcher = FakeFetcher(errors={code: soft for code in ("B1", "B2", "B3", "B4")})
    report = service(db, settings, fetcher=fetcher, max_consecutive_refetch_failures=3).run()
    assert report.stopped_reason == "suspected_block" and not report.ok
    assert report.failed == 3 and "soft-blocked" in (report.error or "")
    assert [f[1] for f in fetcher.fetched] == ["B1", "B2", "B3"]
    # Failed media are retried later (never skipped); the fourth one is untouched.
    assert [get_media(db, m).transcript_status for m in ids] == [
        "failed", "failed", "failed", "pending"
    ]


def test_successful_fetch_resets_the_refetch_failure_streak(
    db: Database, settings: Settings
) -> None:
    for code in ("F1", "F2", "OK", "F3", "F4"):
        add_video_item(db, code)
    soft = RefetchError("metadata failed")
    fetcher = FakeFetcher(errors={code: soft for code in ("F1", "F2", "F3", "F4")})
    report = service(db, settings, fetcher=fetcher, max_consecutive_refetch_failures=3).run()
    assert report.ok and report.failed == 4 and report.transcribed == 1


def test_other_fetch_errors_do_not_count_towards_the_circuit(
    db: Database, settings: Settings
) -> None:
    for code in ("D1", "D2", "D3", "D4"):
        add_video_item(db, code)
    fetcher = FakeFetcher(errors={c: FetchError("HTTP 500") for c in ("D1", "D2", "D3", "D4")})
    report = service(db, settings, fetcher=fetcher, max_consecutive_refetch_failures=3).run()
    assert report.ok and report.failed == 4


def test_circuit_breaker_option_from_config() -> None:
    config = SimpleNamespace(
        get_section=lambda name: {"max_consecutive_refetch_failures": 5}
    )
    assert TranscriptionOptions.from_config(config).max_consecutive_refetch_failures == 5
    assert TranscriptionOptions().max_consecutive_refetch_failures == 3
