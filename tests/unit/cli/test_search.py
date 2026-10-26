"""Tests for `postparse search items | posts | messages` against a seeded v2 database."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from postparse.cli.filters import build_item_filter, parse_label_filter
from postparse.cli.main import cli
from postparse.core.db.models import LabelFilter


def _json(db: Path, *args: str) -> dict:
    result = CliRunner().invoke(cli, ["search", *args, "--db", str(db), "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _ids(data: dict) -> list[int]:
    return [item["id"] for item in data["items"]]


def test_items_full_text_with_snippet(v2_db: tuple[Path, dict[str, int]]) -> None:
    path, ids = v2_db
    data = _json(path, "items", "pasta")
    assert _ids(data) == [ids["pasta"], ids["cake"], ids["doc"]]  # cake via tag "pasta"
    assert data["total"] == 3
    assert data["next_cursor"] is None
    assert "[pasta]" in data["items"][0]["snippet"].lower()


def test_items_transcript_and_link_text_are_searchable(
    v2_db: tuple[Path, dict[str, int]]
) -> None:
    path, ids = v2_db
    assert _ids(_json(path, "items", "guanciale")) == [ids["pasta"]]
    assert _ids(_json(path, "items", "recipe", "--source", "instagram")) == [
        ids["pasta"], ids["cake"]
    ]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--source", "telegram"], ["python", "doc"]),
        (["--tag", "#dessert"], ["cake"]),
        (["--hashtag", "dinner", "--hashtag", "dessert"], ["pasta", "cake"]),
        (["--author", "news"], ["python", "doc"]),
        (["--kind", "video", "--kind", "document"], ["pasta", "doc"]),
        (["--label", "topics:food"], ["pasta", "cake"]),
        (["--label", "topics:food", "--label", "topics:tech"], ["python", "pasta", "cake"]),
        (["--label", "topics"], ["python", "pasta", "cake"]),
        (["--from", "2024-03-01"], ["python", "pasta"]),
        (["--to", "2024-02-01"], ["cake", "doc"]),
        (["--has-transcript"], ["pasta"]),
        (["--no-transcript", "--source", "instagram"], ["cake"]),
    ],
)
def test_items_filters(v2_db: tuple[Path, dict[str, int]], args: list[str],
                       expected: list[str]) -> None:
    path, ids = v2_db
    assert _ids(_json(path, "items", *args)) == [ids[key] for key in expected]


def test_items_pagination_with_cursor(v2_db: tuple[Path, dict[str, int]]) -> None:
    path, ids = v2_db
    first = _json(path, "items", "--limit", "3")
    assert len(first["items"]) == 3 and first["total"] == 4
    assert first["next_cursor"]
    second = _json(path, "items", "--limit", "3", "--cursor", first["next_cursor"])
    assert _ids(second) == [ids["doc"]]
    assert second["next_cursor"] is None


def test_items_table_output_shows_next_cursor(v2_db: tuple[Path, dict[str, int]]) -> None:
    path, _ = v2_db
    result = CliRunner().invoke(cli, ["search", "items", "--db", str(path), "--limit", "1"])
    assert result.exit_code == 0, result.output
    assert "4 match" in result.output
    assert "--cursor" in result.output


def test_items_no_matches(v2_db: tuple[Path, dict[str, int]]) -> None:
    path, _ = v2_db
    result = CliRunner().invoke(cli, ["search", "items", "nothingmatches", "--db", str(path)])
    assert result.exit_code == 0
    assert "No matching items" in result.output


def test_posts_alias_restricts_to_instagram(v2_db: tuple[Path, dict[str, int]]) -> None:
    path, ids = v2_db
    assert _ids(_json(path, "posts", "pasta")) == [ids["pasta"], ids["cake"]]
    assert _ids(_json(path, "posts", "--type", "video")) == [ids["pasta"]]
    assert _ids(_json(path, "posts", "--username", "baker")) == [ids["cake"]]


def test_messages_alias_maps_photo_type(v2_db: tuple[Path, dict[str, int]]) -> None:
    path, ids = v2_db
    assert _ids(_json(path, "messages")) == [ids["python"], ids["doc"]]
    assert _ids(_json(path, "messages", "--type", "photo")) == []
    assert _ids(_json(path, "messages", "--type", "document")) == [ids["doc"]]


def test_output_json_option_matches_json_flag(v2_db: tuple[Path, dict[str, int]]) -> None:
    path, _ = v2_db
    result = CliRunner().invoke(
        cli, ["search", "messages", "--db", str(path), "--output", "json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["total"] == 2


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--cursor", "garbage"], "cursor"),
        (["--from", "01.02.2024"], "YYYY-MM-DD"),
        (["--label", "topics:food", "--label", "other:x"], "same taxonomy"),
        (["--limit", "0"], "between 1 and 500"),
    ],
)
def test_items_rejects_bad_input(v2_db: tuple[Path, dict[str, int]], args: list[str],
                                 message: str) -> None:
    path, _ = v2_db
    result = CliRunner().invoke(cli, ["search", "items", "--db", str(path), *args])
    assert result.exit_code == 2
    assert message in result.output


def test_missing_database_is_reported_and_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    result = CliRunner().invoke(cli, ["search", "items", "--db", str(path)])
    assert result.exit_code == 1
    assert "Database not found" in result.output
    assert not path.exists()


def test_default_db_comes_from_settings(
    v2_db: tuple[Path, dict[str, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = v2_db
    monkeypatch.setenv("POSTPARSE_DB_PATH", str(path))
    result = CliRunner().invoke(cli, ["search", "items", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["total"] == 4


def test_parse_label_filter() -> None:
    assert parse_label_filter([]) is None
    assert parse_label_filter(["topics"]) == LabelFilter("topics", ())
    assert parse_label_filter(["topics:a", "topics:b", "topics:a"]) == LabelFilter(
        "topics", ("a", "b")
    )


def test_build_item_filter_normalizes_values() -> None:
    flt = build_item_filter(q="  ", source="all", kinds=("video", "video"),
                            date_from="2024-01-01")
    assert flt.q is None and flt.source is None and flt.kinds == ("video",)
    assert str(flt.date_from) == "2024-01-01"
