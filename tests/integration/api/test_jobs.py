"""Job endpoints: every job kind with success, failure, login and rate-limit outcomes,
WebSocket progress order and the platform-specific aliases.

Extraction, transcription, summarization and enrichment run on fake services
that call the progress callback like the real ones; classification runs on the
real :class:`ClassificationService` with the fake keyword model.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from postparse.collectors.base import (
    CredentialsMissing,
    InstagramRateLimited,
    ProgressEvent,
    TelegramAuthRequired,
)
from postparse.services.enrichment import EnrichmentReport
from postparse.services.extraction import ExtractionReport
from postparse.services.summarization import SummarizationReport
from postparse.services.transcription import TranscriptionReport
from tests.integration.api.conftest import services_of, wait_for_job

TELEGRAM_BODY = {"api_id": 12345, "api_hash": "0123456789abcdef0123456789abcdef", "limit": 3}
INSTAGRAM_BODY = {"username": "tester", "password": "pw", "limit": 3}


#: Environment variables recorded by FakeExtraction (never the whole environment).
RECORDED_ENV = ("TELEGRAM_API_ID", "TELEGRAM_PHONE", "INSTAGRAM_USERNAME", "INSTAGRAM_PASSWORD")


class FakeExtraction:
    """Extraction service double; ``outcome`` selects what the next run does."""

    def __init__(self, outcome: str = "ok") -> None:
        self.outcome = outcome
        self.env: dict[str, str] | None = None
        self.calls: list[dict[str, Any]] = []

    def _finish(self, source: str, progress: Any) -> ExtractionReport:
        for n in (1, 2, 3):
            progress(ProgressEvent(source, "collect", n, n, 0, 0))  # type: ignore[arg-type]
        if self.outcome == "auth":
            raise TelegramAuthRequired("Session is not authorized.")
        if self.outcome == "missing":
            raise CredentialsMissing("Instagram", ("INSTAGRAM_USERNAME",))
        if self.outcome == "rate":
            raise InstagramRateLimited("429")
        if self.outcome == "rate_report":
            return ExtractionReport(source=source, new=2, processed=2,
                                    stopped_reason="rate_limited", error="FloodWait")
        if self.outcome == "boom":
            raise RuntimeError("collector exploded")
        return ExtractionReport(source=source, new=3, processed=3, stopped_reason="end_of_feed")

    async def telegram_async(self, **kwargs: Any) -> ExtractionReport:
        self.calls.append({"env": self._env(), **kwargs})
        return self._finish("telegram", kwargs["progress"])

    def instagram(self, **kwargs: Any) -> ExtractionReport:
        self.calls.append({"env": self._env(), **kwargs})
        return self._finish("instagram", kwargs["progress"])

    def _env(self) -> dict[str, str]:
        env = self.env or {}
        return {k: env[k] for k in RECORDED_ENV if k in env}


class FakeTranscription:
    """Transcription double (blocking, runs in a worker thread)."""

    def __init__(self, outcome: str = "ok", gate: threading.Event | None = None) -> None:
        self.outcome = outcome
        self.gate = gate
        self.options = SimpleNamespace(max_attempts=5, backend="local")
        self.calls: list[dict[str, Any]] = []

    def run(self, **kwargs: Any) -> TranscriptionReport:
        self.calls.append(kwargs)
        if self.gate is not None:
            assert self.gate.wait(10)
        report = TranscriptionReport(source=kwargs["source"], backend="fake", candidates=3)
        for index in (1, 2, 3):
            report.transcribed += 1
            kwargs["progress"](SimpleNamespace(index=index, total=3, media_id=index,
                                               status="transcribed", report=report))
        if self.outcome == "block":
            report.stopped_reason = "suspected_block"
            report.error = "Instagram stopped serving videos"
        elif self.outcome == "backend":
            report.stopped_reason = "backend_unavailable"
            report.error = "faster-whisper is not installed"
        elif self.outcome == "auth":
            report.stopped_reason = "auth_required"
        elif self.outcome == "boom":
            raise RuntimeError("asr crashed")
        else:
            report.stopped_reason = "done"
        return report


class FakeSummarization:
    def __init__(self, outcome: str = "ok") -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def arun(self, **kwargs: Any) -> SummarizationReport:
        self.calls.append(kwargs)
        if self.outcome == "provider":
            raise ValueError("Provider 'x' not found")
        report = SummarizationReport(candidates=2, summarized=2, provider="fake")
        for handled in (1, 2):
            kwargs["progress"](SimpleNamespace(item_id=handled, status="summarized",
                                               handled=handled, total=2, report=report))
        return report


class FakeEnrichment:
    def __init__(self, outcome: str = "ok") -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def run(self, source: str, limit: int | None, **kwargs: Any) -> EnrichmentReport:
        self.calls.append({"source": source, "limit": limit, **kwargs})
        if self.outcome == "boom":
            raise RuntimeError("router failed")
        report = EnrichmentReport(source=source, candidates=1, ok=1, stopped_reason="done")
        kwargs["progress"](SimpleNamespace(link=SimpleNamespace(domain="example.com"),
                                           fetcher="generic", status="ok", index=1, total=1,
                                           report=report))
        return report


def _start(client: TestClient, path: str, body: dict[str, Any]) -> str:
    response = client.post(path, json=body)
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


class TestTelegramExtraction:
    def test_success_passes_request_credentials_and_never_prompts(
        self, make_client, seeded
    ) -> None:
        fake = FakeExtraction()
        client = make_client(extraction=fake)
        job_id = _start(client, "/api/v1/telegram/extract",
                        {**TELEGRAM_BODY, "phone": "+4912345", "force_update": True})
        job = wait_for_job(client, job_id)
        assert job["status"] == "completed", job
        assert job["job_type"] == "telegram_extract"
        assert job["result"]["new"] == 3
        assert job["messages_processed"] == 3
        call = fake.calls[0]
        assert call["interactive"] is False
        assert call["full"] is True and call["limit"] == 3
        assert call["env"]["TELEGRAM_API_ID"] == "12345"
        assert call["env"]["TELEGRAM_PHONE"] == "+4912345"
        # Credentials never end up in the job state.
        stored = services_of(client).jobs.get_job(job_id)
        assert "api_hash" not in str(stored.metadata)
        assert "0123456789abcdef" not in str(job)
        assert fake.env is None  # the shared service was not modified

    @pytest.mark.parametrize(
        ("outcome", "code"),
        [("auth", "auth_required"), ("rate_report", "rate_limited"), ("boom", "internal_error")],
    )
    def test_failures_have_error_codes(self, make_client, seeded, outcome, code) -> None:
        client = make_client(extraction=FakeExtraction(outcome))
        job = wait_for_job(client, _start(client, "/api/v1/telegram/extract", TELEGRAM_BODY))
        assert job["status"] == "failed"
        assert job["error_code"] == code
        assert job["errors"]
        if outcome == "rate_report":
            assert job["result"]["new"] == 2  # partial counts are kept

    def test_platform_alias_and_unified_status_agree(self, make_client, seeded) -> None:
        client = make_client(extraction=FakeExtraction())
        job_id = _start(client, "/api/v1/telegram/extract", TELEGRAM_BODY)
        wait_for_job(client, job_id)
        alias = client.get(f"/api/v1/telegram/jobs/{job_id}").json()
        assert alias == client.get(f"/api/v1/jobs/{job_id}").json()
        assert client.get(f"/api/v1/instagram/jobs/{job_id}").status_code == 200
        assert client.get("/api/v1/jobs/unknown").status_code == 404

    def test_invalid_request_is_422(self, make_client, seeded) -> None:
        client = make_client(extraction=FakeExtraction())
        response = client.post("/api/v1/telegram/extract", json={"api_id": 1, "api_hash": "x"})
        assert response.status_code == 422


class TestInstagramExtraction:
    def test_success_runs_in_thread_with_username(self, make_client, seeded) -> None:
        fake = FakeExtraction()
        client = make_client(extraction=fake)
        job = wait_for_job(client, _start(client, "/api/v1/instagram/extract", INSTAGRAM_BODY))
        assert job["status"] == "completed", job
        assert job["job_type"] == "instagram_extract"
        call = fake.calls[0]
        assert call["interactive"] is False
        assert call["username"] == "tester"
        assert call["stop_after_known"] == 20
        assert call["env"]["INSTAGRAM_PASSWORD"] == "pw"

    def test_force_update_walks_the_whole_feed(self, make_client, seeded) -> None:
        fake = FakeExtraction()
        client = make_client(extraction=fake)
        body = {"username": "tester", "force_update": True}
        wait_for_job(client, _start(client, "/api/v1/instagram/extract", body))
        assert fake.calls[0]["stop_after_known"] is None
        assert "INSTAGRAM_PASSWORD" not in fake.calls[0]["env"]

    @pytest.mark.parametrize(
        ("outcome", "code"),
        [("missing", "credentials_missing"), ("rate", "rate_limited"),
         ("auth", "auth_required"), ("boom", "internal_error")],
    )
    def test_failures(self, make_client, seeded, outcome, code) -> None:
        client = make_client(extraction=FakeExtraction(outcome))
        job = wait_for_job(client, _start(client, "/api/v1/instagram/extract", INSTAGRAM_BODY))
        assert (job["status"], job["error_code"]) == ("failed", code)

    def test_platform_api_is_rejected(self, make_client, seeded) -> None:
        client = make_client(extraction=FakeExtraction())
        response = client.post("/api/v1/instagram/extract",
                               json={"username": "tester", "use_api": True})
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Processing jobs
# ---------------------------------------------------------------------------


class TestTranscriptionJob:
    def test_success(self, make_client, seeded) -> None:
        fake = FakeTranscription()
        client = make_client(transcription=fake)
        response = client.post("/api/v1/transcription/run",
                               json={"source": "all", "limit": 3, "item_ids": [seeded["pasta"]]})
        assert response.status_code == 202
        body = response.json()
        assert body["status_url"] == f"/api/v1/jobs/{body['job_id']}"
        job = wait_for_job(client, body["job_id"])
        assert job["status"] == "completed"
        assert job["progress"] == 100
        assert job["result"]["transcribed"] == 3
        assert job["messages_processed"] == 3
        assert fake.calls[0]["source"] is None
        assert fake.calls[0]["item_ids"] == [seeded["pasta"]]

    @pytest.mark.parametrize(
        ("outcome", "code"),
        [("block", "suspected_block"), ("backend", "backend_unavailable"),
         ("auth", "auth_required"), ("boom", "internal_error")],
    )
    def test_stop_reasons_fail_the_job(self, make_client, seeded, outcome, code) -> None:
        client = make_client(transcription=FakeTranscription(outcome))
        job = wait_for_job(client, _start(client, "/api/v1/transcription/run", {}))
        assert (job["status"], job["error_code"]) == ("failed", code)
        if outcome != "boom":
            assert job["result"]["transcribed"] == 3


class TestSummarizationJob:
    def test_success(self, make_client, seeded) -> None:
        fake = FakeSummarization()
        client = make_client(summarization=fake)
        job = wait_for_job(client, _start(client, "/api/v1/summaries/run",
                                          {"limit": 2, "force": True}))
        assert job["status"] == "completed"
        assert job["result"]["summarized"] == 2
        assert fake.calls[0]["force"] is True

    def test_invalid_provider(self, make_client, seeded) -> None:
        client = make_client(summarization=FakeSummarization("provider"))
        job = wait_for_job(client, _start(client, "/api/v1/summaries/run", {}))
        assert (job["status"], job["error_code"]) == ("failed", "invalid_request")


class TestEnrichmentJob:
    def test_success(self, make_client, seeded) -> None:
        fake = FakeEnrichment()
        client = make_client(enrichment=fake)
        job = wait_for_job(client, _start(client, "/api/v1/enrichment/run",
                                          {"source": "telegram", "domains": ["example.com"]}))
        assert job["status"] == "completed"
        assert job["message"] == "example.com: ok"
        assert fake.calls[0]["source"] == "telegram"
        assert fake.calls[0]["domains"] == ["example.com"]

    def test_failure(self, make_client, seeded) -> None:
        client = make_client(enrichment=FakeEnrichment("boom"))
        job = wait_for_job(client, _start(client, "/api/v1/enrichment/run", {}))
        assert (job["status"], job["error_code"]) == ("failed", "internal_error")


class TestClassifyRunJob:
    def test_reprocess_stores_results(self, client: TestClient, seeded) -> None:
        job_id = _start(client, "/api/v1/classify/run", {
            "taxonomy": "topics", "scope": "reprocess",
            "filters": {"source": "telegram"}, "wait_for_transcripts": False,
        })
        job = wait_for_job(client, job_id)
        assert job["status"] == "completed", job
        assert job["result"]["taxonomy"] == "topics"
        assert job["result"]["candidates"] == 3
        labels = client.get(f"/api/v1/items/{seeded['python']}").json()["labels"]
        assert labels == {"topics": ["tech"]}

    def test_unknown_taxonomy_is_404(self, client: TestClient) -> None:
        assert client.post("/api/v1/classify/run", json={"taxonomy": "nope"}).status_code == 404

    def test_invalid_filter_is_400(self, client: TestClient) -> None:
        response = client.post("/api/v1/classify/run", json={
            "taxonomy": "topics", "filters": {"date_from": "yesterday"}})
        assert response.status_code == 400

    def test_unknown_provider_fails_job(self, client: TestClient) -> None:
        job = wait_for_job(client, _start(client, "/api/v1/classify/run",
                                          {"taxonomy": "topics", "provider": "missing"}))
        assert (job["status"], job["error_code"]) == ("failed", "invalid_request")


# ---------------------------------------------------------------------------
# WebSocket progress
# ---------------------------------------------------------------------------


class TestWebSocketProgress:
    @pytest.mark.parametrize(
        "path",
        ["/api/v1/jobs/{id}/ws", "/api/v1/jobs/ws/progress/{id}",
         "/api/v1/telegram/ws/progress/{id}", "/api/v1/instagram/ws/progress/{id}"],
    )
    def test_events_arrive_in_order(self, make_client, seeded, path: str) -> None:
        gate = threading.Event()
        client = make_client(transcription=FakeTranscription(gate=gate))
        job_id = _start(client, "/api/v1/transcription/run", {"limit": 3})
        with client.websocket_connect(path.format(id=job_id)) as ws:
            first = ws.receive_json()
            assert first["job_id"] == job_id
            assert first["status"] in ("pending", "running")
            gate.set()
            events = [first]
            while events[-1]["status"] not in ("completed", "failed"):
                events.append(ws.receive_json())
        processed = [e["messages_processed"] for e in events if e["status"] == "running"]
        assert processed == sorted(processed)
        assert processed[-3:] == [1, 2, 3]
        assert [e["message"] for e in events if e["messages_processed"] == 2][0] == (
            "media 2: transcribed"
        )
        final = events[-1]
        assert final["status"] == "completed"
        assert final["progress"] == 100
        assert final["result"]["transcribed"] == 3
        assert all("timestamp" in e for e in events)

    def test_unknown_job(self, client: TestClient) -> None:
        with client.websocket_connect("/api/v1/jobs/nope/ws") as ws:
            assert ws.receive_json() == {"error": "Job nope not found", "job_id": "nope"}


class TestJobList:
    def test_lists_jobs_by_kind(self, make_client, seeded) -> None:
        client = make_client(enrichment=FakeEnrichment(), summarization=FakeSummarization())
        wait_for_job(client, _start(client, "/api/v1/enrichment/run", {}))
        wait_for_job(client, _start(client, "/api/v1/summaries/run", {}))
        assert len(client.get("/api/v1/jobs").json()) == 2
        only = client.get("/api/v1/jobs", params={"job_type": "enrich"}).json()
        assert [j["job_type"] for j in only] == ["enrich"]
        metrics = client.get("/metrics").json()
        assert metrics["jobs"]["enrich"] == {"completed": 1}
