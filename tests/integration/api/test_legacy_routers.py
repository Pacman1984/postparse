"""Tests for the kept Instagram/Telegram/search endpoints on schema v2."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestInstagramPosts:
    def test_list_posts_with_hashtags_and_total(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        response = client.get("/api/v1/instagram/posts")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total"] == 3
        assert [p["shortcode"] for p in data["items"]] == ["SC_PASTA", "SC_CAKE", "SC_TRIP"]
        pasta = data["items"][0]
        assert sorted(pasta["hashtags"]) == ["dinner", "pasta"]
        assert pasta["mentions"] == ["friend"]
        assert pasta["is_video"] is True
        assert pasta["likes"] == 120
        assert pasta["media_url"] == "https://cdn.example/pasta.mp4"
        assert pasta["metadata"]["item_id"] == seeded["pasta"]

    def test_owner_and_tag_filters(self, client: TestClient) -> None:
        data = client.get("/api/v1/instagram/posts", params={"owner_username": "chef"}).json()
        assert [p["shortcode"] for p in data["items"]] == ["SC_PASTA", "SC_TRIP"]
        assert data["total"] == 2
        data = client.get("/api/v1/instagram/posts", params={"tags": "dessert"}).json()
        assert [p["shortcode"] for p in data["items"]] == ["SC_CAKE"]

    def test_cursor_and_offset(self, client: TestClient) -> None:
        first = client.get("/api/v1/instagram/posts", params={"limit": 2}).json()
        assert first["has_more"] is True
        second = client.get(
            "/api/v1/instagram/posts", params={"limit": 2, "cursor": first["next_cursor"]}
        ).json()
        assert [p["shortcode"] for p in second["items"]] == ["SC_TRIP"]
        by_offset = client.get("/api/v1/instagram/posts", params={"limit": 2, "offset": 2}).json()
        assert [p["shortcode"] for p in by_offset["items"]] == ["SC_TRIP"]
        assert by_offset["offset"] == 2
        conflict = client.get(
            "/api/v1/instagram/posts", params={"offset": 1, "cursor": first["next_cursor"]}
        )
        assert conflict.status_code == 400

    def test_get_post(self, client: TestClient) -> None:
        data = client.get("/api/v1/instagram/posts/SC_CAKE").json()
        assert data["caption"] == "Chocolate cake recipe"
        assert data["hashtags"] == ["dessert"]
        assert data["comments"] == 1
        assert client.get("/api/v1/instagram/posts/NOPE").status_code == 404


class TestTelegramMessages:
    def test_list_messages(self, client: TestClient, seeded: dict[str, int]) -> None:
        data = client.get("/api/v1/telegram/messages").json()
        assert data["total"] == 3
        assert [m["message_id"] for m in data["items"]] == [1, 3, 2]
        first = data["items"][0]
        assert first["hashtags"] == ["python"]
        assert first["channel_username"] == "pychannel"
        assert first["metadata"]["chat_id"] == 100

    def test_channel_filter_maps_to_author(self, client: TestClient) -> None:
        data = client.get(
            "/api/v1/telegram/messages", params={"channel_username": "@pychannel"}
        ).json()
        assert [m["message_id"] for m in data["items"]] == [1, 2]

    def test_offset_pagination(self, client: TestClient) -> None:
        data = client.get("/api/v1/telegram/messages", params={"offset": 1, "limit": 1}).json()
        assert [m["message_id"] for m in data["items"]] == [3]
        assert data["has_more"] is True

    def test_get_message(self, client: TestClient) -> None:
        data = client.get("/api/v1/telegram/messages/2").json()
        assert data["content"] == "Undated pasta document"
        assert data["created_at"] is None
        assert data["hashtags"] == ["pasta"]
        assert client.get("/api/v1/telegram/messages/2", params={"chat_id": 5}).status_code == 404
        assert client.get("/api/v1/telegram/messages/999").status_code == 404


class TestSearch:
    def test_search_posts_by_hashtags(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/search/posts", params=[("hashtags", "pasta"), ("hashtags", "dessert")]
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert [r["shortcode"] for r in data["results"]] == ["SC_PASTA", "SC_CAKE"]
        assert data["total_count"] == 2
        assert data["filters_applied"] == {"hashtags": ["pasta", "dessert"]}
        assert response.headers["X-Cache-Status"] == "MISS"

    def test_search_posts_content_type_and_dates(self, client: TestClient) -> None:
        data = client.get("/api/v1/search/posts", params={"content_type": "image"}).json()
        assert [r["shortcode"] for r in data["results"]] == ["SC_CAKE", "SC_TRIP"]
        data = client.get(
            "/api/v1/search/posts",
            params={"start_date": "2024-01-01", "end_date": "2024-02-28T00:00:00Z"},
        ).json()
        assert [r["shortcode"] for r in data["results"]] == ["SC_CAKE"]
        bad = client.get(
            "/api/v1/search/posts", params={"start_date": "2024-03-01", "end_date": "2024-01-01"}
        )
        assert bad.status_code == 400

    def test_search_posts_text_query_and_pagination(self, client: TestClient) -> None:
        data = client.get("/api/v1/search/posts", params={"q": "chocolate"}).json()
        assert [r["shortcode"] for r in data["results"]] == ["SC_CAKE"]
        assert "[Chocolate]" in data["results"][0]["snippet"]
        page = client.get("/api/v1/search/posts", params={"limit": 1}).json()
        assert page["pagination"]["has_more"] is True
        nxt = client.get(
            "/api/v1/search/posts",
            params={"limit": 1, "cursor": page["pagination"]["next_cursor"]},
        ).json()
        assert [r["shortcode"] for r in nxt["results"]] == ["SC_CAKE"]
        assert client.get("/api/v1/search/posts", params={"cursor": "%%%"}).status_code == 400

    def test_search_messages(self, client: TestClient) -> None:
        data = client.get(
            "/api/v1/search/messages", params={"channel_username": "pychannel", "hashtags": "pasta"}
        ).json()
        assert [r["message_id"] for r in data["results"]] == [2]
        assert data["results"][0]["chat_id"] == 100
        data = client.get("/api/v1/search/messages", params={"content_type": "document"}).json()
        assert [r["content_type"] for r in data["results"]] == ["document"]

    def test_hashtags(self, client: TestClient) -> None:
        data = client.get("/api/v1/search/hashtags").json()["hashtags"]
        pasta = next(h for h in data if h["tag"] == "pasta")
        assert pasta == {
            "tag": "pasta",
            "count": 2,
            "source": "both",
            "instagram": 1,
            "telegram": 1,
        }
        python = next(h for h in data if h["tag"] == "python")
        assert python["source"] == "telegram"
        limited = client.get("/api/v1/search/hashtags", params={"limit": 2}).json()
        assert len(limited["hashtags"]) == 2


class TestRoot:
    def test_root(self, client: TestClient) -> None:
        data = client.get("/").json()
        assert data["endpoints"]["items"] == "/api/v1/items"
