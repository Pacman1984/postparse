"""E2E search workflow: list, filter, paginate and open items through the API."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_browse_search_and_open(e2e_client: TestClient) -> None:
    # 1. Everything, newest first; the undated post sorts by its collection time.
    data = e2e_client.get("/api/v1/items").json()
    assert data["total"] == 7
    assert data["items"][-1]["external_id"] == "TCH1"

    # 2. Full-text search across both sources with snippets.
    found = e2e_client.get("/api/v1/items", params={"q": "pasta"}).json()["items"]
    assert {i["external_id"] for i in found} == {"RCP1", "42:1001"}
    assert all("[pasta]" in i["snippet"].lower() for i in found)

    # 3. Narrow down with tags and source, then open the item.
    recipe_posts = e2e_client.get(
        "/api/v1/items", params={"tag": "#recipe", "source": "instagram"}
    ).json()["items"]
    assert [i["external_id"] for i in recipe_posts] == ["RCP1", "RCP2"]
    detail = e2e_client.get(f"/api/v1/items/{recipe_posts[0]['id']}").json()
    assert detail["detail"]["instagram"]["shortcode"] == "RCP1"
    assert detail["media"][0]["transcript_status"] == "pending"


def test_legacy_search_endpoints(e2e_client: TestClient) -> None:
    posts = e2e_client.get(
        "/api/v1/search/posts", params={"hashtags": "recipe", "content_type": "video"}
    ).json()
    assert [p["shortcode"] for p in posts["results"]] == ["RCP1"]
    assert posts["results"][0]["is_video"] is True

    owner = e2e_client.get("/api/v1/search/posts", params={"owner_username": "baker_bob"}).json()
    assert [p["shortcode"] for p in owner["results"]] == ["RCP2"]

    messages = e2e_client.get("/api/v1/search/messages", params={"hashtags": "news"}).json()
    assert [m["message_id"] for m in messages["results"]] == [1002]

    tags = {h["tag"]: h for h in e2e_client.get("/api/v1/search/hashtags").json()["hashtags"]}
    assert tags["recipe"]["count"] == 3 and tags["recipe"]["source"] == "both"


def test_paginate_posts_with_cursor(e2e_client: TestClient) -> None:
    seen: list[str] = []
    params: dict[str, object] = {"limit": 3}
    while True:
        page = e2e_client.get("/api/v1/instagram/posts", params=params).json()
        seen.extend(p["shortcode"] for p in page["items"])
        if not page["has_more"]:
            break
        params = {"limit": 3, "cursor": page["next_cursor"]}
    assert seen == ["RCP1", "RCP2", "TRV1", "TCH1"]


def test_health_and_stats(e2e_client: TestClient) -> None:
    assert e2e_client.get("/health").json()["details"]["database"]["items"] == 7
    stats = e2e_client.get("/api/v1/stats").json()
    assert stats["items_total"] == 7
