"""Tests for `postparse stats` / `db stats` / `db export` against a seeded v2 database."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from postparse.cli.main import cli
from postparse.core.db import Database
from postparse.services.stats import collect_stats, database_size


def _stats_json(path: Path, *args: str) -> dict:
    result = CliRunner().invoke(cli, ["stats", "--db", str(path), "--json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


class TestStats:
    def test_counts_per_source_and_kind(self, v2_db: tuple[Path, dict[str, int]]) -> None:
        path, _ = v2_db
        data = _stats_json(path)
        assert data["items_total"] == 4
        sources = {s["source"]: s for s in data["sources"]}
        assert sources["instagram"]["items"] == 2
        assert sources["instagram"]["kinds"] == {"image": 1, "video": 1}
        assert sources["telegram"]["oldest"].startswith("2024-01-15")
        assert sources["telegram"]["newest"].startswith("2024-03-31")
        assert data["schema_version"] == data["latest_schema_version"] > 0
        assert data["size_bytes"] > 0

    def test_tags_media_links_summaries(self, v2_db: tuple[Path, dict[str, int]]) -> None:
        path, _ = v2_db
        data = _stats_json(path, "--top", "2")
        assert data["top_hashtags"][0] == ["#pasta", 2]
        assert len(data["top_hashtags"]) == 2
        assert data["tags_distinct"] == 3
        assert data["media"] == {"video": 1}
        assert data["transcripts"] == 1 and data["items_with_transcript"] == 1
        assert data["links"] == 2 and data["items_with_links"] == 2
        assert data["link_status"] == {"ok": 1, "never": 1}
        assert data["link_fetchers"] == {"trafilatura": 1}
        assert data["summaries"] == 1 and data["items_with_summary"] == 1

    def test_classification_coverage(self, v2_db: tuple[Path, dict[str, int]]) -> None:
        path, _ = v2_db
        (topics,) = _stats_json(path)["taxonomies"]
        assert topics["name"] == "topics"
        assert topics["classified_items"] == 3
        assert topics["results"] == {"ok": 3, "no_labels": 0, "error": 0}
        assert topics["top_labels"] == [["food", 2], ["tech", 1]]
        assert topics["pending_default"] == 1  # the unclassified document
        assert topics["pending_backfill"] == 1

    def test_no_pending_skips_the_counts(self, v2_db: tuple[Path, dict[str, int]]) -> None:
        path, _ = v2_db
        (topics,) = _stats_json(path, "--no-pending")["taxonomies"]
        assert topics["pending_default"] == 0

    def test_table_output(self, v2_db: tuple[Path, dict[str, int]]) -> None:
        path, _ = v2_db
        result = CliRunner().invoke(cli, ["db", "stats", "--db", str(path), "--detailed"])
        assert result.exit_code == 0, result.output
        for text in ("Database Overview", "Items", "Media & transcripts", "Links",
                     "Classification", "topics", "Top hashtags", "#pasta"):
            assert text in result.output

    def test_empty_database_hint(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.db"
        Database.open(path)
        result = CliRunner().invoke(cli, ["stats", "--db", str(path)])
        assert result.exit_code == 0, result.output
        assert "Database is empty" in result.output

    def test_missing_database_fails_without_creating_it(self, tmp_path: Path) -> None:
        path = tmp_path / "nope.db"
        result = CliRunner().invoke(cli, ["stats", "--db", str(path)])
        assert result.exit_code == 1
        assert "Database not found" in result.output
        assert not path.exists()

    def test_outdated_schema_asks_for_migrate(self, tmp_path: Path) -> None:
        import sqlite3

        path = tmp_path / "old.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE x (a)")
        conn.commit()
        conn.close()
        result = CliRunner().invoke(cli, ["stats", "--db", str(path)])
        assert result.exit_code == 1
        assert "db migrate" in result.output

    def test_collect_stats_is_read_only(self, v2_db: tuple[Path, dict[str, int]]) -> None:
        path, _ = v2_db
        before = path.read_bytes()
        stats = collect_stats(Database(path, migrate=False))
        assert stats.items_total == 4
        assert path.read_bytes() == before
        assert database_size(path) >= len(before)


class TestExport:
    def test_json_export_all(self, v2_db: tuple[Path, dict[str, int]], tmp_path: Path) -> None:
        path, ids = v2_db
        out = tmp_path / "out" / "items.json"
        result = CliRunner().invoke(cli, ["db", "export", str(out), "--db", str(path)])
        assert result.exit_code == 0, result.output
        assert "Exported 4 item(s)" in result.output
        data = json.loads(out.read_text(encoding="utf-8"))
        assert [d["id"] for d in data] == [ids["python"], ids["pasta"], ids["cake"], ids["doc"]]
        assert data[1]["labels"] == {"topics": ["food"]}

    def test_csv_export_with_filters(self, v2_db: tuple[Path, dict[str, int]],
                                     tmp_path: Path) -> None:
        path, ids = v2_db
        out = tmp_path / "posts.csv"
        result = CliRunner().invoke(
            cli, ["db", "export", str(out), "--db", str(path), "--source", "posts",
                  "--label", "topics:food"],
        )
        assert result.exit_code == 0, result.output
        rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8"))))
        assert [int(r["id"]) for r in rows] == [ids["pasta"], ids["cake"]]
        assert rows[0]["tags"] == "#dinner #pasta"
        assert rows[0]["labels"] == "topics:food"

    @pytest.mark.parametrize(
        ("args", "count"),
        [
            (["--source", "messages"], 2),
            (["--query", "pasta"], 3),
            (["--tag", "dessert"], 1),
            (["--limit", "2"], 2),
            (["--from", "2024-03-01", "--to", "2024-03-31"], 2),
        ],
    )
    def test_export_filters_and_limit(self, v2_db: tuple[Path, dict[str, int]],
                                      tmp_path: Path, args: list[str], count: int) -> None:
        path, _ = v2_db
        out = tmp_path / "items.json"
        result = CliRunner().invoke(cli, ["db", "export", str(out), "--db", str(path), *args])
        assert result.exit_code == 0, result.output
        assert len(json.loads(out.read_text(encoding="utf-8"))) == count

    def test_export_to_stdout(self, v2_db: tuple[Path, dict[str, int]]) -> None:
        path, _ = v2_db
        result = CliRunner().invoke(
            cli, ["db", "export", "-", "--format", "csv", "--db", str(path), "--limit", "1"]
        )
        assert result.exit_code == 0, result.output
        lines = [line for line in result.output.splitlines() if line.strip()]
        assert lines[0].startswith("id,source,external_id")
        assert len(lines) == 2

    def test_format_from_extension(self, v2_db: tuple[Path, dict[str, int]],
                                   tmp_path: Path) -> None:
        path, _ = v2_db
        out = tmp_path / "x.csv"
        result = CliRunner().invoke(cli, ["db", "export", str(out), "--db", str(path)])
        assert result.exit_code == 0
        assert out.read_text(encoding="utf-8").startswith("id,source")

    def test_empty_result(self, v2_db: tuple[Path, dict[str, int]], tmp_path: Path) -> None:
        path, _ = v2_db
        out = tmp_path / "none.json"
        result = CliRunner().invoke(
            cli, ["db", "export", str(out), "--db", str(path), "--query", "zzzz"]
        )
        assert result.exit_code == 0
        assert json.loads(out.read_text(encoding="utf-8")) == []


class TestHelp:
    @pytest.mark.parametrize("args", [["db"], ["db", "stats"], ["db", "export"], ["stats"]])
    def test_help(self, args: list[str]) -> None:
        result = CliRunner().invoke(cli, [*args, "--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output
