"""Tests for the unified /api/v1/items endpoints on a seeded schema v2 database."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _ids(response) -> list[int]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


class TestListItems:
    def test_lists_all_items_newest_first(self, client: TestClient, seeded: dict[str, int]) -> None:
        response = client.get("/api/v1/items")
        data = response.json()
        assert data["total"] == 6
        assert data["has_more"] is False
        # Undated items sort by collected_at (2024-01-15); ties by id descending.
        assert _ids(response) == [
            seeded["python"], seeded["pasta"], seeded["cake"], seeded["undated2"],
            seeded["undated"], seeded["carousel"],
        ]

    def test_item_fields_include_tags_and_labels(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        items = client.get("/api/v1/items", params={"source": "instagram"}).json()["items"]
        pasta = next(i for i in items if i["id"] == seeded["pasta"])
        assert set(pasta["tags"]) == {"#pasta", "#dinner", "@friend"}
        assert pasta["labels"] == {"topics": ["recipe"]}
        assert pasta["snippet"] is None

    def test_full_text_query_returns_snippets(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        response = client.get("/api/v1/items", params={"q": "rezept"})
        assert _ids(response) == [seeded["pasta"]]
        assert "[rezept]" in response.json()["items"][0]["snippet"]

    def test_query_matches_transcript_text(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        assert _ids(client.get("/api/v1/items", params={"q": "guanciale"})) == [seeded["pasta"]]

    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"source": "telegram"}, ["python", "undated2", "undated"]),
            ({"tag": "#pasta"}, ["pasta", "undated"]),
            ({"tag": ["dessert", "travel"]}, ["cake", "carousel"]),
            ({"author": "chef"}, ["pasta", "carousel"]),
            ({"kind": ["image", "carousel"]}, ["cake", "carousel"]),
            ({"label": "topics:recipe"}, ["pasta", "cake"]),
            ({"label": "topics"}, ["python", "pasta", "cake"]),
            ({"label": ["topics:tech", "topics:recipe"]}, ["python", "pasta", "cake"]),
            ({"has_transcript": "true"}, ["pasta"]),
            ({"has_transcript": "false", "source": "instagram"}, ["cake", "carousel"]),
            ({"date_from": "2024-02-01", "date_to": "2024-03-10"}, ["pasta", "cake"]),
            ({"date_to": "2024-01-15"}, ["undated2", "undated", "carousel"]),
            ({"q": "pasta", "source": "telegram"}, ["undated"]),
            ({"q": "pasta", "tag": "dinner", "author": "chef"}, ["pasta"]),
        ],
    )
    def test_filter_combinations(
        self, client: TestClient, seeded: dict[str, int], params: dict, expected: list[str]
    ) -> None:
        response = client.get("/api/v1/items", params=params)
        assert _ids(response) == [seeded[name] for name in expected]
        assert response.json()["total"] == len(expected)

    @pytest.mark.parametrize(
        "params",
        [
            {"label": ["topics:recipe", "other:x"]},
            {"date_from": "2024/01/01"},
            {"date_from": "2024-03-01", "date_to": "2024-01-01"},
            {"kind": "photo"},
            {"cursor": "not-a-cursor"},
        ],
    )
    def test_invalid_filters_are_400(self, client: TestClient, params: dict) -> None:
        response = client.get("/api/v1/items", params=params)
        assert response.status_code == 400, response.text
        assert response.json()["error_code"] == "HTTP_400"

    def test_keyset_pagination_over_null_dates(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        """Pages of 1 walk every item exactly once, including the undated ties."""
        seen: list[int] = []
        cursor = None
        for _ in range(10):
            params = {"limit": 1, **({"cursor": cursor} if cursor else {})}
            data = client.get("/api/v1/items", params=params).json()
            seen.extend(item["id"] for item in data["items"])
            cursor = data["next_cursor"]
            assert data["has_more"] is (cursor is not None)
            if cursor is None:
                break
        assert seen == _ids(client.get("/api/v1/items"))
        assert len(set(seen)) == 6

    def test_offset_is_translated_into_keyset(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        everything = _ids(client.get("/api/v1/items"))
        page = client.get("/api/v1/items", params={"offset": 2, "limit": 2})
        assert _ids(page) == everything[2:4]
        empty = client.get("/api/v1/items", params={"offset": 50}).json()
        assert empty["items"] == [] and empty["has_more"] is False

    def test_offset_with_cursor_is_400(self, client: TestClient) -> None:
        cursor = client.get("/api/v1/items", params={"limit": 1}).json()["next_cursor"]
        response = client.get("/api/v1/items", params={"cursor": cursor, "offset": 1})
        assert response.status_code == 400
        assert "offset" in response.json()["detail"]

    def test_count_can_be_skipped(self, client: TestClient) -> None:
        assert client.get("/api/v1/items", params={"count": "false"}).json()["total"] is None


class TestItemDetail:
    def test_detail_contains_everything(self, client: TestClient, seeded: dict[str, int]) -> None:
        response = client.get(f"/api/v1/items/{seeded['pasta']}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["source"] == "instagram"
        assert data["detail"]["instagram"]["shortcode"] == "SC_PASTA"
        assert data["detail"]["instagram"]["likes"] == 120
        assert set(data["tags"]) == {"#pasta", "#dinner", "@friend"}
        media = data["media"][0]
        assert media["transcript_status"] == "transcribed"
        assert media["has_transcript"] is True
        assert data["transcript"] == "stir the guanciale"
        assert data["transcript_segments"][0]["text"] == "stir the guanciale"
        assert data["summary"]["summary"] == "A carbonara video."
        assert data["summary"]["key_points"] == ["Use guanciale", "No cream"]
        assert data["links"][0]["url"].startswith("https://example.com/carbonara")
        assert data["links"][0]["title"] == "Carbonara"
        assert data["classifications"][0]["taxonomy"] == "topics"
        assert data["classifications"][0]["labels"] == ["recipe"]

    def test_detail_of_telegram_item(self, client: TestClient, seeded: dict[str, int]) -> None:
        data = client.get(f"/api/v1/items/{seeded['undated']}").json()
        assert data["created_at"] is None
        assert data["detail"]["telegram"] == {
            "chat_id": 100, "message_id": 2, "views": None, "forwards": None,
            "reply_to_msg_id": None, "fwd_from_name": None, "fwd_from_id": None,
            "fwd_from_post_id": None,
        }
        assert data["summary"] is None and data["transcript"] is None

    def test_unknown_item_is_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/items/99999").status_code == 404

    def test_transcript_endpoint(self, client: TestClient, seeded: dict[str, int]) -> None:
        data = client.get(f"/api/v1/items/{seeded['pasta']}/transcript").json()
        assert data["text"] == "stir the guanciale"
        assert data["media"][0]["transcript"]["language"] == "it"
        assert data["media"][0]["transcript"]["segments"][0]["end"] == 1.5
        empty = client.get(f"/api/v1/items/{seeded['cake']}/transcript").json()
        assert empty["text"] is None
        assert empty["media"][0]["transcript"] is None
        assert client.get("/api/v1/items/99999/transcript").status_code == 404

    def test_summary_endpoint(self, client: TestClient, seeded: dict[str, int]) -> None:
        data = client.get(f"/api/v1/items/{seeded['pasta']}/summary").json()
        assert data == {
            "item_id": seeded["pasta"], "summary": "A carbonara video.",
            "key_points": ["Use guanciale", "No cream"], "provider": "fake",
            "model": "fake-model", "created_at": data["created_at"],
        }
        assert client.get(f"/api/v1/items/{seeded['cake']}/summary").status_code == 404
