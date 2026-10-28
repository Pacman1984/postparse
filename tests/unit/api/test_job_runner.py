"""Unit tests for the generic JobRunner."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest

from postparse.api.jobs.runner import JobRunner, error_code_for, in_thread, report_to_dict
from postparse.api.schemas.telegram import ExtractionStatus
from postparse.api.services.cache_manager import CacheManager
from postparse.api.services.job_manager import JobManager
from postparse.collectors.base import (
    CredentialsMissing,
    InstagramAuthRequired,
    InstagramFeedUnavailable,
    TelegramRateLimited,
)


class RecordingWS:
    """WebSocket manager double recording broadcast payloads."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def broadcast_progress(self, job_id: str, payload: dict[str, Any]) -> None:
        await asyncio.sleep(0)  # yield, like a real send
        self.events.append(payload)


class CountingCache(CacheManager):
    def __init__(self) -> None:
        super().__init__(True)
        self.invalidations = 0

    def invalidate(self, prefix: str = "") -> int:
        self.invalidations += 1
        return 0


@dataclasses.dataclass
class Report:
    processed: int
    stopped_reason: str | None = None
    error: str | None = None


def _runner() -> tuple[JobRunner, JobManager, RecordingWS, CountingCache]:
    jobs, ws, cache = JobManager(), RecordingWS(), CountingCache()
    return JobRunner(jobs, ws, cache), jobs, ws, cache  # type: ignore[arg-type]


async def test_thread_progress_is_delivered_in_order() -> None:
    runner, jobs, ws, cache = _runner()

    def work(progress: Any) -> Report:
        for n in range(1, 51):
            progress(n, 50, f"step {n}")
        return Report(processed=50)

    job_id = runner.submit("transcribe", {"limit": 50}, in_thread(work))
    await runner.wait(job_id, timeout=10)
    job = jobs.get_job(job_id)
    assert job.status == ExtractionStatus.COMPLETED
    assert job.result == {"processed": 50, "stopped_reason": None, "error": None}
    running = [e["messages_processed"] for e in ws.events if e["status"] == "running"]
    assert running == [0, *range(1, 51)]
    assert ws.events[-1]["status"] == "completed"
    assert max(e["progress"] for e in ws.events[:-1]) == 99  # 100 only when finished
    assert cache.invalidations == 1


async def test_report_stop_reason_fails_job_and_keeps_counts() -> None:
    runner, jobs, _ws, cache = _runner()

    async def work(progress: Any) -> Report:
        return Report(processed=4, stopped_reason="suspected_block", error="blocked")

    job_id = runner.submit("transcribe", {}, work)
    await runner.wait(job_id, timeout=5)
    job = jobs.get_job(job_id)
    assert (job.status, job.error_code, job.messages_processed) == (
        ExtractionStatus.FAILED,
        "suspected_block",
        4,
    )
    assert job.errors == ["blocked"]
    assert cache.invalidations == 1  # partial runs may have written data


async def test_feed_unavailable_report_fails_the_job() -> None:
    runner, jobs, _ws, _cache = _runner()

    async def work(progress: Any) -> Report:
        return Report(processed=2, stopped_reason="feed_unavailable", error="feed refused")

    job_id = runner.submit("instagram_extract", {}, work)
    await runner.wait(job_id, timeout=5)
    job = jobs.get_job(job_id)
    assert (job.status, job.error_code, job.messages_processed) == (
        ExtractionStatus.FAILED,
        "feed_unavailable",
        2,
    )


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (CredentialsMissing("Telegram", ("TELEGRAM_API_ID",)), "credentials_missing"),
        (InstagramAuthRequired(), "auth_required"),
        (TelegramRateLimited(30), "rate_limited"),
        (InstagramFeedUnavailable("web", "something went wrong"), "feed_unavailable"),
        (ValueError("bad provider"), "invalid_request"),
        (KeyError("taxonomy"), "invalid_request"),
        (RuntimeError("boom"), "internal_error"),
    ],
)
async def test_exceptions_become_error_codes(exc: Exception, code: str) -> None:
    runner, jobs, ws, _cache = _runner()

    async def work(progress: Any) -> None:
        raise exc

    job_id = runner.submit("telegram_extract", {}, work)
    await runner.wait(job_id, timeout=5)
    job = jobs.get_job(job_id)
    assert job.status == ExtractionStatus.FAILED
    assert job.error_code == code == error_code_for(exc)
    assert ws.events[-1]["error_code"] == code


async def test_shutdown_cancels_running_jobs() -> None:
    runner, jobs, _ws, _cache = _runner()

    async def work(progress: Any) -> None:
        await asyncio.sleep(30)

    job_id = runner.submit("summarize", {}, work)
    await asyncio.sleep(0.01)
    assert runner.running == [job_id]
    await runner.shutdown()
    job = jobs.get_job(job_id)
    assert (job.status, job.error_code) == (ExtractionStatus.FAILED, "cancelled")
    assert runner.running == []


async def test_unknown_kind_is_rejected() -> None:
    runner, *_ = _runner()

    async def work(progress: Any) -> None:
        return None

    with pytest.raises(ValueError):
        runner.submit("nope", {}, work)


async def test_sensitive_params_are_not_stored() -> None:
    runner, jobs, *_ = _runner()

    async def work(progress: Any) -> None:
        return None

    job_id = runner.submit("telegram_extract", {"api_hash": "secret", "limit": 3}, work)
    await runner.wait(job_id, timeout=5)
    assert jobs.get_job(job_id).metadata == {"limit": 3}


def test_report_to_dict_variants() -> None:
    assert report_to_dict(None) is None
    assert report_to_dict({"a": 1}) == {"a": 1}
    assert report_to_dict(Report(1)) == {"processed": 1, "stopped_reason": None, "error": None}
    assert report_to_dict(42) == {"value": "42"}
