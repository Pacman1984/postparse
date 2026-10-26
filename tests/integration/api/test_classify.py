"""Classification endpoints on the shared ClassificationService (fake keyword model)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from postparse.core.db.repos import ClassificationRepo
from tests.fake_llm import FAIL_MARKER
from tests.integration.api.conftest import services_of


class TestLegacyEndpoints:
    def test_recipe(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/classify/recipe", json={"text": "Boil pasta and add the sauce"}
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["label"] == "recipe"
        assert data["details"]["provider"] == "fake"
        assert data["classifier_used"] == "llm"

    def test_recipe_llm_failure_is_503(self, client: TestClient) -> None:
        response = client.post("/api/v1/classify/recipe", json={"text": f"x {FAIL_MARKER}"})
        assert response.status_code == 503

    def test_unknown_provider_is_400(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/classify/recipe", json={"text": "pasta", "provider_name": "missing"}
        )
        assert response.status_code == 400

    def test_multi_defaults_to_configured_classes(self, client: TestClient) -> None:
        data = client.post("/api/v1/classify/multi", json={"text": "new python release"}).json()
        assert data["label"] == "tech"
        assert set(data["available_classes"]) == {"recipe", "tech", "travel"}

    def test_multilabel_with_classes(self, client: TestClient) -> None:
        data = client.post(
            "/api/v1/classify/multilabel",
            json={
                "text": "A python cooking app with a pasta recipe",
                "classes": {"recipe": "Cooking", "tech": "Software", "travel": "Trips"},
            },
        ).json()
        assert {s["label"] for s in data["labels"]} == {"recipe", "tech"}

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/classify/batch",
            "/api/v1/classify/multi/batch",
            "/api/v1/classify/multilabel/batch",
        ],
    )
    def test_batches_keep_per_item_errors(self, client: TestClient, path: str) -> None:
        texts = ["Bake the cake with flour", f"broken {FAIL_MARKER}", "python release"]
        response = client.post(path, json={"texts": texts})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total_processed"] == 3
        assert data["failed_count"] == 1
        assert [r["input_index"] for r in data["results"]] == [0, 2]
        items = data["items"]
        assert [(i["input_index"], i["ok"]) for i in items] == [(0, True), (1, False), (2, True)]
        assert items[1]["error"]["code"] == "llm_error"
        assert "fake LLM unavailable" in items[1]["error"]["message"]
        assert items[1]["result"] is None
        assert items[0]["result"]["input_index"] == 0

    def test_classifiers_listing(self, client: TestClient) -> None:
        data = client.get("/api/v1/classify/classifiers").json()
        assert {c["name"] for c in data["classifiers"]} >= {"recipe", "multi", "taxonomy"}
        assert [t["name"] for t in data["taxonomies"]] == ["topics"]
        assert {p["name"] for p in data["providers"]} == {"lm_studio", "ollama", "openai"}


class TestTaxonomyEndpoints:
    def test_classify_without_persist(self, client: TestClient, seeded) -> None:
        response = client.post("/api/v1/classify/topics", json={"text": "beach hotel trip"})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["taxonomy"] == "topics" and data["mode"] == "multi"
        assert data["labels"] == [{"label": "travel", "confidence": 0.9}]
        assert data["persisted"] is None
        with services_of(client).db.read() as conn:
            assert conn.execute("SELECT count(*) FROM classification_runs").fetchone()[0] == 1

    def test_persist_creates_run_and_current_label(self, client: TestClient, seeded) -> None:
        item_id = seeded["undated2"]
        response = client.post(
            "/api/v1/classify/topics",
            json={"text": "beach trip", "persist": True, "item_id": item_id},
        )
        assert response.status_code == 200, response.text
        persisted = response.json()["persisted"]
        assert persisted["run_id"] > 1 and persisted["result_ids"][0] is not None
        with services_of(client).db.read() as conn:
            run = ClassificationRepo(conn).get_run(persisted["run_id"])
        assert run.status == "done" and run.n_ok == 1
        assert run.params["origin"] == "api"
        assert run.provider == "fake"
        labels = client.get(f"/api/v1/items/{item_id}").json()["labels"]
        assert labels == {"topics": ["travel"]}
        found = client.get("/api/v1/items", params={"label": "topics:travel"}).json()["items"]
        assert item_id in [i["id"] for i in found]

    @pytest.mark.parametrize(
        ("body", "status"),
        [
            ({"text": "x", "persist": True}, 400),
            ({"text": "x", "persist": True, "item_id": 99999}, 404),
        ],
    )
    def test_persist_validation(self, client: TestClient, body: dict, status: int) -> None:
        assert client.post("/api/v1/classify/topics", json=body).status_code == status

    def test_unknown_taxonomy_is_404(self, client: TestClient) -> None:
        assert client.post("/api/v1/classify/nope", json={"text": "x"}).status_code == 404

    def test_stored_only_taxonomy_is_usable(self, client: TestClient, seeded) -> None:
        with services_of(client).db.transaction() as conn:
            ClassificationRepo(conn).ensure_taxonomy("moods", "single", ["happy", "sad"])
        data = client.post("/api/v1/classify/moods", json={"text": "so happy"}).json()
        assert data["label"] == "happy"

    def test_batch_format_and_persist(self, client: TestClient, seeded) -> None:
        texts = ["pasta recipe", "   ", f"oops {FAIL_MARKER}", "python laptop"]
        ids = [seeded["undated"], seeded["undated2"], seeded["carousel"], seeded["cake"]]
        response = client.post(
            "/api/v1/classify/topics/batch", json={"texts": texts, "item_ids": ids, "persist": True}
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["failed_count"] == 2
        results = data["results"]
        assert [r["input_index"] for r in results] == [0, 1, 2, 3]
        assert [r["ok"] for r in results] == [True, False, False, True]
        assert results[0]["result"]["labels"][0]["label"] == "recipe"
        assert results[1]["error"]["code"] == "empty_text"
        assert results[2]["error"]["code"] == "llm_error"
        result_ids = data["persisted"]["result_ids"]
        assert result_ids[1] is None  # empty input: nothing stored
        assert all(r is not None for r in (result_ids[0], result_ids[2], result_ids[3]))
        with services_of(client).db.read() as conn:
            status = conn.execute(
                "SELECT status FROM classification_results WHERE id = ?", (result_ids[2],)
            ).fetchone()[0]
        assert status == "error"
        assert client.get(f"/api/v1/items/{seeded['cake']}").json()["labels"] == {
            "topics": ["tech"]
        }

    def test_batch_validation(self, client: TestClient) -> None:
        mismatch = client.post(
            "/api/v1/classify/topics/batch", json={"texts": ["a", "b"], "item_ids": [1]}
        )
        assert mismatch.status_code == 400
        missing = client.post(
            "/api/v1/classify/topics/batch", json={"texts": ["a"], "persist": True}
        )
        assert missing.status_code == 400
        assert client.post("/api/v1/classify/topics/batch", json={"texts": []}).status_code == 422


class TestTaxonomiesEndpoint:
    def test_lists_configured_and_stored(self, client: TestClient, seeded) -> None:
        data = client.get("/api/v1/taxonomies").json()["taxonomies"]
        topics = next(t for t in data if t["name"] == "topics")
        assert topics["configured"] is True and topics["in_db"] is True
        assert topics["classified_items"] == 3
        assert set(topics["labels"]) == {"recipe", "tech", "travel"}
