"""Tests for QueryService (search, filters, pagination, detail, tags, export)."""

from __future__ import annotations

import base64
import csv
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from postparse.core.db import Database
from postparse.core.db.models import (
    InstagramDetail,
    ItemFilter,
    ItemUpsert,
    LabelFilter,
    MediaInput,
)
from postparse.core.db.repos import (
    ClassificationRepo,
    ItemsRepo,
    LinksRepo,
    SummariesRepo,
    TranscriptsRepo,
)
from postparse.services.query import (
    InvalidCursorError,
    QueryService,
    decode_cursor,
    encode_cursor,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database.open(tmp_path / "query.db")


@pytest.fixture
def seeded(db: Database) -> dict[str, int]:
    """A small corpus covering the filter dimensions."""
    ids: dict[str, int] = {}
    with db.transaction() as conn:
        items = ItemsRepo(conn)

        def add(key: str, **kwargs: object) -> None:
            ids[key], _ = items.upsert(ItemUpsert(**kwargs))  # type: ignore[arg-type]

        add("pasta", source="instagram", external_id="p1", kind="video",
            text="Creamy pasta carbonara", author="chef",
            created_at="2024-03-10T12:00:00Z", hashtags=("pasta", "Dinner"),
            detail=InstagramDetail("p1"), media=(MediaInput(0, "video"),))
        add("cake", source="instagram", external_id="p2", kind="image",
            text="Chocolate cake recipe", author="baker",
            created_at="2024-02-01T08:00:00Z", hashtags=("dessert",), mentions=("chef",))
        add("python", source="telegram", external_id="1:1", kind="text",
            text="New Python release notes", author="news",
            created_at="2024-03-31T23:59:59Z")
        add("undated", source="telegram", external_id="1:2", kind="document",
            text="Undated pasta document", author="news",
            collected_at="2024-01-15T00:00:00Z")

        media_id = conn.execute(
            "SELECT id FROM media WHERE item_id = ?", (ids["pasta"],)
        ).fetchone()[0]
        TranscriptsRepo(conn).add(media_id, backend="whisper", model="small",
                                  text="stir the guanciale")
        SummariesRepo(conn).add(ids["pasta"], "A carbonara video")

        repo = ClassificationRepo(conn)
        tax = repo.ensure_taxonomy("topics", "multi", ["food", "tech"])
        run = repo.create_run(tax.id)
        repo.add_result(run, ids["pasta"], "ok", [("food", 0.9)])
        repo.add_result(run, ids["cake"], "ok", ["food"])
        repo.add_result(run, ids["python"], "ok", ["tech"])
        repo.add_result(run, ids["undated"], "error", error="x")
    return ids


def _ids(service: QueryService, flt: ItemFilter) -> list[int]:
    return [view.id for view in service.search(flt, limit=100).items]


def test_default_order_is_newest_first(db: Database, seeded: dict[str, int]) -> None:
    page = QueryService(db).search()
    assert [v.id for v in page.items] == [
        seeded["python"], seeded["pasta"], seeded["cake"], seeded["undated"]
    ]
    assert page.next_cursor is None
    pasta = page.items[1]
    assert pasta.tags == ("#dinner", "#pasta")
    assert pasta.labels == {"topics": ("food",)}
    assert pasta.snippet is None


@pytest.mark.parametrize(
    ("flt", "expected"),
    [
        (ItemFilter(source="telegram"), ["python", "undated"]),
        (ItemFilter(kinds=("image", "document")), ["cake", "undated"]),
        (ItemFilter(authors=("chef", "baker")), ["pasta", "cake"]),
        (ItemFilter(tags=("#DINNER",)), ["pasta"]),
        (ItemFilter(tags=("dessert", "pasta")), ["pasta", "cake"]),
        (ItemFilter(tags=("chef",)), ["cake"]),  # bare name matches mentions too
        (ItemFilter(tags=("#chef",)), []),
        (ItemFilter(date_from=date(2024, 3, 1)), ["python", "pasta"]),
        (ItemFilter(date_to=date(2024, 3, 31)), ["python", "pasta", "cake", "undated"]),
        (ItemFilter(date_to=date(2024, 3, 30)), ["pasta", "cake", "undated"]),
        (ItemFilter(date_from="2024-02-01T08:00:00Z", date_to=datetime(2024, 3, 10, 12)),
         ["pasta", "cake"]),
        (ItemFilter(labels=LabelFilter("topics", ("food",))), ["pasta", "cake"]),
        (ItemFilter(labels=LabelFilter("topics")), ["python", "pasta", "cake"]),
        (ItemFilter(labels=LabelFilter("unknown", ("food",))), []),
        (ItemFilter(has_transcript=True), ["pasta"]),
        (ItemFilter(has_transcript=False), ["python", "cake", "undated"]),
        (ItemFilter(q="pasta"), ["pasta", "undated"]),
        (ItemFilter(q="guanciale"), ["pasta"]),  # transcript text
        (ItemFilter(q="carb*"), ["pasta"]),
        (ItemFilter(q='"pasta carbonara"'), ["pasta"]),
        (ItemFilter(q="pasta", source="instagram"), ["pasta"]),
    ],
)
def test_filters(db: Database, seeded: dict[str, int], flt: ItemFilter,
                 expected: list[str]) -> None:
    service = QueryService(db)
    assert _ids(service, flt) == [seeded[key] for key in expected]
    assert service.count(flt) == len(expected)


@pytest.mark.parametrize(
    "hostile", ['pasta"', "pasta OR", "NEAR(", "body:pasta", "-pasta", "^pasta", "a AND"]
)
def test_fts_input_is_escaped(db: Database, seeded: dict[str, int], hostile: str) -> None:
    service = QueryService(db)
    service.search(ItemFilter(q=hostile))  # must not raise an FTS syntax error
    service.count(ItemFilter(q=hostile))


def test_snippet_marks_match(db: Database, seeded: dict[str, int]) -> None:
    page = QueryService(db, snippet_markers=("<b>", "</b>")).search(ItemFilter(q="carbonara"))
    (view,) = page.items
    assert view.snippet is not None and "<b>carbonara</b>" in view.snippet.lower()


def test_keyset_pagination_with_null_created_at(db: Database) -> None:
    with db.transaction() as conn:
        items = ItemsRepo(conn)
        for n in range(23):
            kwargs: dict[str, object] = {"collected_at": "2024-01-01T00:00:00Z"}
            if n % 3 == 0:
                kwargs["created_at"] = f"2024-01-{(n % 9) + 1:02d}T00:00:00Z"
            # Many items share the same sort_at: ties are broken by id.
            items.upsert(ItemUpsert("telegram", str(n), "text", text=f"m{n}", **kwargs))  # type: ignore[arg-type]
    service = QueryService(db)
    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        page = service.search(cursor=cursor, limit=5)
        seen.extend(v.id for v in page.items)
        pages += 1
        assert pages <= 10, "pagination loops"
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert len(seen) == len(set(seen)) == 23
    assert pages == 5
    full = [v.id for v in service.search(limit=100).items]
    assert seen == full
    keys = [(v.sort_at, v.id) for v in service.search(limit=100).items]
    assert keys == sorted(keys, reverse=True)


def test_cursor_roundtrip_and_validation() -> None:
    cursor = encode_cursor("2024-01-01T00:00:00.000Z", 7)
    assert decode_cursor(cursor) == ("2024-01-01T00:00:00.000Z", 7)
    bad_payloads = [
        "not base64 !!",
        base64.urlsafe_b64encode(b"[1,2]").decode(),
        base64.urlsafe_b64encode(json.dumps({"v": 1, "s": "2024", "i": 1}).encode()).decode(),
        base64.urlsafe_b64encode(
            json.dumps({"v": 1, "s": "2024-01-01T00:00:00.000Z", "i": "1"}).encode()
        ).decode(),
        base64.urlsafe_b64encode(
            json.dumps({"v": 2, "s": "2024-01-01T00:00:00.000Z", "i": 1}).encode()
        ).decode(),
    ]
    for bad in bad_payloads:
        with pytest.raises(InvalidCursorError):
            decode_cursor(bad)


def test_limit_validation(db: Database) -> None:
    with pytest.raises(ValueError):
        QueryService(db).search(limit=0)


def test_get_item_detail(db: Database, seeded: dict[str, int]) -> None:
    with db.transaction() as conn:
        ItemsRepo(conn).upsert(
            ItemUpsert("instagram", "p1", "video", text="Creamy pasta https://recipes.example/c")
        )
        links = LinksRepo(conn)
        links.add_fetch(links.ensure("https://recipes.example/c"), fetcher="http",
                        status="ok", title="Carbonara", metadata={"lang": "it"})
    detail = QueryService(db).get_item(seeded["pasta"])
    assert detail is not None
    assert detail.instagram is not None and detail.instagram.shortcode == "p1"
    assert detail.telegram is None
    assert [t.display for t in detail.tags] == ["#dinner", "#pasta"]
    assert detail.transcript_text == "stir the guanciale"
    assert detail.summary is not None and detail.summary.text == "A carbonara video"
    (link,) = detail.links
    assert link.fetch is not None and link.fetch.metadata == {"lang": "it"}
    (classification,) = detail.classifications
    assert classification.labels == ("food",)
    assert QueryService(db).get_item(99999) is None


def test_tags_with_counts(db: Database, seeded: dict[str, int]) -> None:
    service = QueryService(db)
    counts = {(t.kind, t.name): t.count for t in service.tags()}
    assert counts == {("hashtag", "pasta"): 1, ("hashtag", "dinner"): 1,
                      ("hashtag", "dessert"): 1, ("mention", "chef"): 1}
    assert [t.name for t in service.tags(kind="mention")] == ["chef"]
    assert service.tags(source="telegram") == []


def test_export_json_and_csv(db: Database, seeded: dict[str, int], tmp_path: Path) -> None:
    service = QueryService(db)
    out = tmp_path / "export.json"
    assert service.export(ItemFilter(source="instagram"), "json", out) == 2
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [row["external_id"] for row in data] == ["p1", "p2"]
    assert data[0]["labels"] == {"topics": ["food"]}

    buffer = io.StringIO()
    assert service.export(ItemFilter(source="telegram"), "csv", buffer) == 2
    rows = list(csv.DictReader(io.StringIO(buffer.getvalue())))
    assert [row["external_id"] for row in rows] == ["1:1", "1:2"]
    assert rows[0]["labels"] == "topics:tech"
    assert rows[1]["created_at"] == ""

    empty = io.StringIO()
    assert service.export(ItemFilter(source="telegram", q="zzzz"), "json", empty) == 0
    assert json.loads(empty.getvalue()) == []
    with pytest.raises(ValueError):
        service.export(None, "xml", empty)  # type: ignore[arg-type]


def test_view_timestamps_are_aware(db: Database, seeded: dict[str, int]) -> None:
    view = QueryService(db).search(ItemFilter(source="telegram")).items[0]
    assert view.created_at == datetime(2024, 3, 31, 23, 59, 59, tzinfo=UTC)
