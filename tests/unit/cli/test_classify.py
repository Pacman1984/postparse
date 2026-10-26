"""Unit tests for the `postparse classify` CLI (run / text / taxonomies / db alias).

The LLM is replaced by a deterministic pydantic-ai FunctionModel
(``tests/fake_llm.py``); databases are fresh schema v2 files in ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from postparse.classification import TaxonomyClassifier
from postparse.cli.main import cli
from postparse.core.db import Database
from postparse.core.db.models import InstagramDetail, ItemUpsert, MediaInput
from postparse.core.db.repos import ClassificationRepo, ItemsRepo
from tests.fake_llm import FAIL_MARKER, keyword_model

OLD = "2020-01-01T00:00:00.000Z"


@pytest.fixture
def prompts() -> list[str]:
    return []


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch: pytest.MonkeyPatch, prompts: list[str]) -> None:
    """Make TaxonomyClassifier.from_provider use the keyword FunctionModel."""
    model = keyword_model(calls=prompts)

    def from_provider(cls, spec, provider, **kwargs):
        return TaxonomyClassifier(spec, model, "native", provider_name=provider.name,
                                  model_name="fake-model")

    monkeypatch.setattr(TaxonomyClassifier, "from_provider", classmethod(from_provider))


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A schema v2 database with a few items (one old classified item)."""
    path = tmp_path / "cli.db"
    db = Database.open(path)
    with db.transaction() as conn:
        items = ItemsRepo(conn)

        def add(ext: str, text: str | None, source: str = "instagram", **kwargs) -> int:
            external = ext if source == "instagram" else f"1:{ext}"
            detail = InstagramDetail(ext) if source == "instagram" else None
            item_id, _ = items.upsert(ItemUpsert(source, external, kwargs.pop("kind", "text"),
                                                 text=text, detail=detail, **kwargs))
            return item_id

        add("p1", "Pasta recipe with tomato sauce", hashtags=("food",))
        add("p2", "Great movie last night")
        add("t1", "pip install fastapi", source="telegram")
        add("empty", "")
        add("video", "watch", kind="video", media=(MediaInput(0, "video"),))
        old = add("old", "Old pasta post", collected_at=OLD)
        repo = ClassificationRepo(conn)
        other = repo.ensure_taxonomy("legacy", "multi", ["x"])
        repo.add_result(repo.create_run(other.id), old, "ok", ["x"])
    return path


def invoke(*args: str, input: str | None = None):
    return CliRunner().invoke(cli, ["classify", *args], input=input, catch_exceptions=False)


def _labels(db_path: Path, taxonomy: str = "topics") -> dict[str, tuple[str, ...]]:
    with Database.open(db_path).read() as conn:
        rows = conn.execute(
            "SELECT i.external_id, cr.status, group_concat(rl.label) "
            "FROM classification_results cr JOIN items i ON i.id = cr.item_id "
            "JOIN taxonomies t ON t.id = cr.taxonomy_id "
            "LEFT JOIN result_labels rl ON rl.result_id = cr.id WHERE t.name = ? GROUP BY cr.id",
            (taxonomy,),
        ).fetchall()
    result: dict[str, tuple[str, ...]] = {}
    for external_id, status, labels in rows:
        result[external_id] = (status, *sorted(labels.split(","))) if labels else (status,)
    return result


# -- classify run ---------------------------------------------------------------


def test_run_default_scope(db_path: Path) -> None:
    result = invoke("run", "--taxonomy", "topics", "--db", str(db_path))
    assert result.exit_code == 0, result.output
    labels = _labels(db_path)
    assert labels["p1"] == ("ok", "recipe")
    assert labels["p2"] == ("ok", "movie_review")
    assert labels["1:t1"] == ("ok", "python_package")
    assert "old" not in labels and "empty" not in labels and "video" not in labels
    assert "Classification run" in result.output
    assert "waiting for transcript" in result.output


def test_run_backfill_flag_and_source_filter(db_path: Path) -> None:
    invoke("run", "--db", str(db_path))
    result = invoke("run", "--backfill", "--source", "instagram", "--db", str(db_path))
    assert result.exit_code == 0, result.output
    assert _labels(db_path)["old"] == ("ok", "recipe")


def test_run_limit_since_and_no_wait(db_path: Path) -> None:
    result = invoke("run", "--limit", "1", "--db", str(db_path))
    assert result.exit_code == 0
    assert len(_labels(db_path)) == 1
    invoke("run", "--no-wait-transcripts", "--since", "2000-01-01", "--db", str(db_path))
    assert _labels(db_path)["video"] == ("no_labels",)


def test_run_reprocess_with_transcript_filter(db_path: Path) -> None:
    invoke("run", "--db", str(db_path))
    result = invoke("run", "--reprocess", "--with-transcript", "--db", str(db_path))
    assert result.exit_code == 0
    assert "Nothing to classify" in result.output


def test_run_errors(db_path: Path, tmp_path: Path) -> None:
    missing = CliRunner().invoke(cli, ["classify", "run", "--db", str(tmp_path / "nope.db")])
    assert missing.exit_code != 0
    assert "Database not found" in missing.output
    unknown = CliRunner().invoke(cli, ["classify", "run", "-t", "nope", "--db", str(db_path)])
    assert unknown.exit_code != 0 and "Unknown taxonomy" in unknown.output
    both = CliRunner().invoke(cli, ["classify", "run", "--backfill", "--reprocess",
                                    "--db", str(db_path)])
    assert both.exit_code != 0
    bad_date = CliRunner().invoke(cli, ["classify", "run", "--since", "yesterday",
                                        "--db", str(db_path)])
    assert bad_date.exit_code != 0
    bad_provider = CliRunner().invoke(cli, ["classify", "run", "--provider", "missing",
                                            "--db", str(db_path)])
    assert bad_provider.exit_code != 0 and "not found" in bad_provider.output


def test_run_reports_llm_errors(db_path: Path) -> None:
    with Database.open(db_path).transaction() as conn:
        ItemsRepo(conn).upsert(ItemUpsert("instagram", "boom", "text", text=FAIL_MARKER,
                                          detail=InstagramDetail("boom")))
    result = invoke("run", "--db", str(db_path))
    assert result.exit_code == 0
    assert _labels(db_path)["boom"] == ("error",)
    assert "fake LLM unavailable" in result.output


# -- classify text ----------------------------------------------------------------


def test_text_with_labels_multi_and_single(prompts: list[str]) -> None:
    text = "Spaghetti Carbonara recipe on a beach trip"
    multi = invoke("text", text, "--labels", "recipe,travel,tech", "--mode", "multi",
                   "--output", "json")
    assert multi.exit_code == 0, multi.output
    data = json.loads(multi.output)
    assert data["labels"] == ["recipe", "travel"]
    assert data["mode"] == "multi"
    assert data["model"] == "fake-model"
    assert data["provider"] == "lm_studio"
    single = invoke("text", text, "--labels", "recipe,travel,tech", "--mode", "single",
                    "--output", "json")
    assert json.loads(single.output)["label"] == "recipe"
    assert "Carbonara" in prompts[0]


def test_text_with_taxonomy_panel_output() -> None:
    result = invoke("text", "Great movie", "--taxonomy", "topics")
    assert result.exit_code == 0
    assert "movie_review" in result.output
    assert "Confidence" in result.output


def test_text_default_taxonomy_and_stdin() -> None:
    result = invoke("text", "-", "--output", "json", input="pip install fastapi\n")
    assert json.loads(result.output)["labels"] == ["python_package"]


def test_text_empty_input_does_not_call_llm(prompts: list[str]) -> None:
    result = invoke("text", "   ")
    assert result.exit_code == 0
    assert "nothing to classify" in result.output.lower()
    assert prompts == []


def test_text_errors() -> None:
    failed = CliRunner().invoke(cli, ["classify", "text", FAIL_MARKER, "--labels", "a,b"])
    assert failed.exit_code != 0 and "Classification failed" in failed.output
    combo = CliRunner().invoke(cli, ["classify", "text", "x", "--taxonomy", "topics",
                                     "--labels", "a,b"])
    assert combo.exit_code != 0
    single = CliRunner().invoke(cli, ["classify", "text", "x", "--labels", "a",
                                      "--mode", "single"])
    assert single.exit_code != 0 and "two labels" in single.output
    provider = CliRunner().invoke(cli, ["classify", "text", "x", "--provider", "missing"])
    assert provider.exit_code != 0 and "not found" in provider.output


def test_text_deprecated_classifier_options() -> None:
    recipe = invoke("text", "Boil pasta", "--classifier", "recipe", "--output", "json")
    assert "deprecated" in recipe.output
    payload = recipe.output[recipe.output.index("{"):]
    assert json.loads(payload)["label"] == "recipe"
    classes = invoke("text", "pip install x", "--classifier", "multiclass", "--classes",
                     '{"python_package": "Python", "movie_review": "Films"}', "--output", "json")
    data = json.loads(classes.output[classes.output.index("{"):])
    assert data["mode"] == "single" and data["label"] == "python_package"


# -- classify taxonomies ----------------------------------------------------------


def test_taxonomies_lists_config_and_db(db_path: Path) -> None:
    invoke("run", "--db", str(db_path))
    result = invoke("taxonomies", "--db", str(db_path), "--output", "json")
    data = {t["name"]: t for t in json.loads(result.output)}
    assert set(data) == {"topics", "legacy"}
    assert data["topics"]["configured"] and data["topics"]["in_db"]
    assert data["topics"]["version"] == 1
    assert data["topics"]["results"]["ok"] == 3
    assert data["legacy"]["configured"] is False
    table = invoke("taxonomies", "--db", str(db_path))
    assert "topics" in table.output and "legacy" in table.output


# -- classify db (deprecated alias) -------------------------------------------------


def test_db_alias_maps_to_run(db_path: Path) -> None:
    result = invoke("db", "--classifier", "recipe", "--source", "instagram",
                    "--db", str(db_path))
    assert result.exit_code == 0, result.output
    assert "deprecated" in result.output.lower()
    assert "--classifier recipe is ignored" in result.output
    labels = _labels(db_path)
    assert set(labels) == {"p1", "p2"}


def test_db_alias_force_and_hashtag(db_path: Path) -> None:
    invoke("db", "--db", str(db_path))
    result = invoke("db", "--force", "--filter-hashtag", "food", "--db", str(db_path))
    assert result.exit_code == 0
    with Database.open(db_path).read() as conn:
        n = conn.execute(
            "SELECT count(*) FROM classification_results cr JOIN items i ON i.id = cr.item_id "
            "WHERE i.external_id = 'p1'"
        ).fetchone()[0]
    assert n == 2
    replace = CliRunner().invoke(cli, ["classify", "db", "--replace", "--db", str(db_path)])
    assert replace.exit_code != 0


def test_help_texts() -> None:
    assert "run" in invoke("--help").output
    run_help = invoke("run", "--help").output
    assert "--backfill" in run_help and "--no-wait-transcripts" in run_help
    text_help = invoke("text", "--help").output
    assert "--labels" in text_help and "--mode" in text_help
    assert "deprecated" in invoke("db", "--help").output.lower()


def test_text_and_taxonomies_never_create_a_database(tmp_path: Path, monkeypatch) -> None:
    from postparse.config import clear_settings_cache

    target = tmp_path / "should_not_exist.db"
    monkeypatch.setenv("POSTPARSE_DB_PATH", str(target))
    clear_settings_cache()
    assert invoke("text", "pasta recipe", "--labels", "recipe,tech").exit_code == 0
    listing = invoke("taxonomies", "--output", "json")
    assert [t["name"] for t in json.loads(listing.output)] == ["topics"]
    assert not target.exists()
