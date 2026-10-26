"""E2E classification workflow: classify texts, persist results, run a taxonomy over
the database and find items by their labels."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient


def _wait(client: TestClient, job_id: str) -> dict:
    for _ in range(500):
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError(job)


def test_adhoc_recipe_classification(e2e_client: TestClient) -> None:
    recipe = e2e_client.post("/api/v1/classify/recipe",
                             json={"text": "Mix flour and eggs, bake 30 minutes"}).json()
    assert recipe["label"] == "recipe"
    other = e2e_client.post("/api/v1/classify/recipe",
                            json={"text": "Just bought a new phone"}).json()
    assert other["label"] == "not_recipe"


def test_run_taxonomy_then_filter_by_label(e2e_client: TestClient) -> None:
    taxonomies = e2e_client.get("/api/v1/taxonomies").json()["taxonomies"]
    assert [t["name"] for t in taxonomies] == ["topics"]

    response = e2e_client.post("/api/v1/classify/run", json={
        "taxonomy": "topics", "scope": "backfill", "wait_for_transcripts": False})
    assert response.status_code == 202
    job = _wait(e2e_client, response.json()["job_id"])
    assert job["status"] == "completed", job
    assert job["result"]["ok"] >= 3

    recipes = e2e_client.get("/api/v1/items", params={"label": "topics:recipe"}).json()
    assert {i["external_id"] for i in recipes["items"]} >= {"RCP1", "RCP2", "42:1001"}
    assert all("recipe" in i["labels"]["topics"] for i in recipes["items"])


def test_persist_single_result(e2e_client: TestClient) -> None:
    item = e2e_client.get("/api/v1/items", params={"q": "Market report"}).json()["items"][0]
    assert item["labels"] == {}
    result = e2e_client.post("/api/v1/classify/topics", json={
        "text": "a python laptop review", "persist": True, "item_id": item["id"]}).json()
    assert result["persisted"]["run_id"] >= 1
    detail = e2e_client.get(f"/api/v1/items/{item['id']}").json()
    assert detail["classifications"][0]["labels"] == ["python_package"]
