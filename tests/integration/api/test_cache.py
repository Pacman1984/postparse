"""Response cache: off by default, Redis (fakeredis) or memory when on, invalidated
after jobs and after persisted classifications."""

from __future__ import annotations

import fakeredis
import pytest
from fastapi.testclient import TestClient

from postparse.api.services.cache_manager import KEY_NAMESPACE, CacheManager
from tests.integration.api.conftest import services_of, wait_for_job
from tests.integration.api.test_jobs import FakeEnrichment


@pytest.fixture
def redis_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture(params=["redis", "memory"])
def cached_client(request, make_client, seeded, redis_client) -> TestClient:
    client = redis_client if request.param == "redis" else None
    cache = CacheManager(True, client=client, search_ttl=60)
    return make_client(cache=cache, enrichment=FakeEnrichment())


def _rename_item(client: TestClient, item_id: int, text: str) -> None:
    """Change an item behind the API's back (simulates a job writing data)."""
    with services_of(client).db.transaction() as conn:
        conn.execute("UPDATE items SET text = ? WHERE id = ?", (text, item_id))


class TestCacheDisabled:
    def test_every_request_is_a_miss(self, client: TestClient, seeded) -> None:
        for _ in range(2):
            assert client.get("/api/v1/items").headers["X-Cache-Status"] == "MISS"
        _rename_item(client, seeded["cake"], "changed")
        texts = [i["text"] for i in client.get("/api/v1/items").json()["items"]]
        assert "changed" in texts


class TestCacheEnabled:
    @pytest.mark.parametrize(
        "path", ["/api/v1/items", "/api/v1/search/posts", "/api/v1/search/messages"]
    )
    def test_second_request_hits(self, cached_client: TestClient, path: str) -> None:
        first = cached_client.get(path)
        second = cached_client.get(path)
        assert first.headers["X-Cache-Status"] == "MISS"
        assert second.headers["X-Cache-Status"] == "HIT"
        assert first.json() == second.json()
        other = cached_client.get(path, params={"limit": 1})
        assert other.headers["X-Cache-Status"] == "MISS"

    def test_keys_are_namespaced(self, make_client, seeded, redis_client) -> None:
        client = make_client(cache=CacheManager(True, client=redis_client))
        client.get("/api/v1/items", params={"q": "pasta"})
        client.get("/api/v1/search/posts")
        keys = sorted(redis_client.keys("*"))
        assert len(keys) == 2
        assert all(k.startswith(KEY_NAMESPACE) for k in keys)
        assert {k.split(":")[2] for k in keys} == {"items", "search"}
        assert all(redis_client.ttl(k) > 0 for k in keys)

    def test_job_invalidates_cache(self, cached_client: TestClient, seeded) -> None:
        cached_client.get("/api/v1/items")
        _rename_item(cached_client, seeded["cake"], "renamed by a job")
        stale = cached_client.get("/api/v1/items")
        assert stale.headers["X-Cache-Status"] == "HIT"
        job_id = cached_client.post("/api/v1/enrichment/run", json={}).json()["job_id"]
        assert wait_for_job(cached_client, job_id)["status"] == "completed"
        fresh = cached_client.get("/api/v1/items")
        assert fresh.headers["X-Cache-Status"] == "MISS"
        assert "renamed by a job" in [i["text"] for i in fresh.json()["items"]]

    def test_persisted_classification_invalidates_cache(
        self, cached_client: TestClient, seeded
    ) -> None:
        params = {"label": "topics:travel"}
        assert cached_client.get("/api/v1/items", params=params).json()["total"] == 0
        cached_client.post(
            "/api/v1/classify/topics",
            json={"text": "beach trip", "persist": True, "item_id": seeded["carousel"]},
        )
        response = cached_client.get("/api/v1/items", params=params)
        assert response.headers["X-Cache-Status"] == "MISS"
        assert response.json()["total"] == 1

    def test_not_persisted_classification_keeps_cache(self, cached_client: TestClient) -> None:
        cached_client.get("/api/v1/items")
        cached_client.post("/api/v1/classify/topics", json={"text": "beach trip"})
        assert cached_client.get("/api/v1/items").headers["X-Cache-Status"] == "HIT"


class TestCacheManagerUnit:
    def test_disabled_is_noop(self) -> None:
        cache = CacheManager(False)
        assert cache.set("k", 1) is False
        assert cache.get("k") is None
        assert cache.invalidate() == 0
        assert cache.backend == "disabled"

    def test_redis_unavailable_falls_back_to_memory(self) -> None:
        # tests/conftest.py makes redis.from_url refuse every connection.
        cache = CacheManager(True)
        assert cache.backend == "memory"
        key = cache.key("items", q="x")
        cache.set(key, {"a": 1})
        assert cache.get(key) == {"a": 1}

    def test_memory_ttl_and_eviction(self) -> None:
        now = [0.0]
        cache = CacheManager(True, max_entries=2, clock=lambda: now[0])
        cache.set("postparse:v2:a:1", 1, ttl=10)
        cache.set("postparse:v2:a:2", 2, ttl=10)
        cache.set("postparse:v2:b:3", 3, ttl=10)
        assert cache.get("postparse:v2:a:1") is None  # evicted
        now[0] = 11
        assert cache.get("postparse:v2:a:2") is None  # expired

    def test_invalidate_prefix(self, redis_client) -> None:
        cache = CacheManager(True, client=redis_client)
        cache.set(cache.key("items", q=1), 1)
        cache.set(cache.key("search:posts", q=1), 2)
        redis_client.set("foreign:key", "x")
        assert cache.invalidate("search") == 1
        assert cache.invalidate() == 1
        assert redis_client.get("foreign:key") == "x"

    def test_key_is_stable_and_ignores_none(self) -> None:
        assert CacheManager.key("items", a=1, b=None) == CacheManager.key("items", a=1)
        assert CacheManager.key("items", tags=["x", "y"]) != CacheManager.key(
            "items", tags=["y", "x"]
        )

    def test_from_config(self, config) -> None:
        assert CacheManager.from_config(config).enabled is False
        assert CacheManager.from_config(None).enabled is False
