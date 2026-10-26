"""Health, metrics, stats and processing status endpoints."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from postparse.api.deps import LLMHealthCache
from postparse.llm.health import HealthResult
from tests.integration.api.conftest import services_of


class FakeChecker:
    def __init__(self, status: str = "available") -> None:
        self.status = status
        self.calls = 0

    def __call__(self, provider, chat=True, timeout=None):
        self.calls += 1
        return HealthResult(provider=provider.name, model=provider.model, status=self.status,
                            chat_ok=self.status == "available", latency_ms=1.0)


class OkBackend:
    name = "fake-asr"
    model = "tiny"

    def check(self) -> None:
        return None


def _llm(config, checker) -> LLMHealthCache:
    return LLMHealthCache(config, ttl=60, checker=checker)


class TestHealth:
    def test_health_reports_database(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["status"] == "ok"
        db = data["details"]["database"]
        assert db["status"] == "ok"
        assert db["items"] == 6 and db["fts_indexed"] == 6 and db["fts_in_sync"] is True
        assert db["schema_version"] == db["latest_schema_version"]

    def test_live(self, client: TestClient) -> None:
        assert client.get("/health/live").json() == {"status": "alive"}

    def test_ready_all_ok_and_llm_cached(self, make_client, seeded, config) -> None:
        checker = FakeChecker()
        transcription = services_of_transcription(make_client)
        client = make_client(llm_health=_llm(config, checker), transcription=transcription)
        first = client.get("/health/ready")
        second = client.get("/health/ready")
        assert first.status_code == 200
        data = first.json()
        assert data["status"] == "ok", data
        assert data["details"]["llm"]["provider"] == "lm_studio"
        assert data["details"]["llm"]["cached"] is False
        assert second.json()["details"]["llm"]["cached"] is True
        assert checker.calls == 1
        assert data["details"]["transcription"]["status"] == "available"
        assert data["details"]["cache"] == "disabled"

    def test_ready_degraded_without_llm_or_asr(self, make_client, seeded, config) -> None:
        client = make_client(llm_health=_llm(config, FakeChecker("unavailable")))
        data = client.get("/health/ready").json()
        assert data["status"] == "degraded"
        assert data["details"]["llm"]["status"] == "unavailable"
        skipped = client.get("/health/ready", params={"llm": "false"}).json()
        assert skipped["details"]["llm"] == {"status": "skipped"}

    def test_ready_503_when_database_broken(self, make_client, seeded, config) -> None:
        client = make_client(llm_health=_llm(config, FakeChecker()))
        services_of(client).db.path.unlink()
        services_of(client).db.path.mkdir()
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["details"]["database"]["status"] == "error"

    def test_degraded_when_fts_out_of_sync(self, make_client, seeded, config) -> None:
        client = make_client(llm_health=_llm(config, FakeChecker()))
        with services_of(client).db.transaction() as conn:
            conn.execute("DELETE FROM items_fts WHERE rowid = (SELECT min(id) FROM items)")
        db = client.get("/health").json()["details"]["database"]
        assert db["fts_in_sync"] is False and db["status"] == "degraded"

    def test_llm_not_configured(self) -> None:
        assert LLMHealthCache(None).check()["status"] == "not_configured"

    def test_metrics(self, client: TestClient) -> None:
        data = client.get("/metrics").json()
        assert data["database"] == {"instagram_posts": 3, "telegram_messages": 3, "items": 6}


def services_of_transcription(make_client) -> object:
    """A transcription service double whose backend check succeeds."""
    return SimpleNamespace(
        options=SimpleNamespace(backend="local", max_attempts=5),
        backend=lambda kind=None: OkBackend(),
        status=lambda: {"counts": {("instagram", "pending"): 2}, "due": {"instagram": 2},
                        "exhausted": {}, "next_attempt_at": {}, "transcripts": 1,
                        "transcribed_seconds": 1.5, "max_attempts": 5},
    )


class TestStatsAndStatus:
    def test_stats(self, client: TestClient) -> None:
        data = client.get("/api/v1/stats").json()
        assert data["items_total"] == 6
        assert {s["source"]: s["items"] for s in data["sources"]} == {
            "instagram": 3, "telegram": 3}
        assert data["summaries"] == 1
        assert data["transcripts"] == 1
        assert data["taxonomies"][0]["name"] == "topics"

    def test_transcription_status_real_service(self, client: TestClient) -> None:
        data = client.get("/api/v1/transcription/status").json()
        assert data["status"]["instagram"]["transcribed"] == 1
        assert data["transcripts"] == 1
        assert data["max_attempts"] == 5
        assert data["backend"]["kind"] == "local"
        assert data["backend"]["status"] in ("available", "unavailable")

    def test_transcription_status_with_backend(self, make_client, seeded) -> None:
        client = make_client(transcription=services_of_transcription(make_client))
        data = client.get("/api/v1/transcription/status").json()
        assert data["status"] == {"instagram": {"pending": 2}}
        assert data["backend"] == {"kind": "local", "status": "available",
                                   "name": "fake-asr", "model": "tiny"}

    def test_enrichment_status(self, client: TestClient) -> None:
        data = client.get("/api/v1/enrichment/status").json()
        assert data["links"] == 1
        assert data["by_state"] == [{"fetcher": "generic", "status": "ok", "count": 1}]
        assert data["domains"] == [{"domain": "example.com", "states": {"ok": 1}}]
        assert client.get("/api/v1/enrichment/status",
                          params={"source": "bad"}).status_code == 422


class TestServicesNotStarted:
    def test_endpoints_503_before_lifespan(self, config, settings) -> None:
        from postparse.api.main import create_app

        client = TestClient(create_app(config=config, settings=settings))  # no lifespan
        assert client.get("/health").json()["details"] is None
        assert client.get("/health/ready").status_code == 503
        assert client.get("/api/v1/items").status_code == 503
