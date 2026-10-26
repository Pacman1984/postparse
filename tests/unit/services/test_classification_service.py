"""Tests for ClassificationService on a seeded tmp schema v2 database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from postparse.classification import TaxonomyClassifier, TaxonomySpec, prompt_sha256
from postparse.core.db import Database
from postparse.core.db.models import InstagramDetail, ItemFilter, ItemUpsert, MediaInput
from postparse.core.db.repos import (
    ClassificationRepo,
    ItemsRepo,
    LinksRepo,
    MediaRepo,
    SummariesRepo,
    TranscriptsRepo,
)
from postparse.services.classification import (
    ClassificationService,
    ProgressUpdate,
    compose_inputs,
)

OLD = "2020-01-01T00:00:00.000Z"
TAXONOMY_CREATED = "2023-01-01T00:00:00.000Z"
TOPICS = TaxonomySpec(
    name="topics",
    mode="multi",
    labels=["recipe", "travel", "tech"],
)


class FakeLLM:
    """FunctionModel behaviour keyed on words in the prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = str(messages[0].parts[-1].content)  # type: ignore[union-attr]
        self.prompts.append(prompt)
        if "EXPLODE" in prompt:
            raise ConnectionError("llm down")
        labels = [w for w in ("recipe", "travel", "tech") if w in prompt.lower()]
        return ModelResponse(
            parts=[TextPart(json.dumps({"reasoning": "kw", "labels": labels, "confidence": 0.8}))]
        )


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database.open(tmp_path / "classify.db")


def _add(
    conn,
    ext: str,
    text: str | None,
    *,
    collected_at: str | None = None,
    kind: str = "text",
    media: tuple[MediaInput, ...] | None = None,
    source: str = "instagram",
) -> int:
    detail = InstagramDetail(ext) if source == "instagram" else None
    item_id, _ = ItemsRepo(conn).upsert(
        ItemUpsert(
            source,
            ext if source == "instagram" else f"1:{ext}",
            kind,  # type: ignore[arg-type]
            text=text,
            collected_at=collected_at,
            media=media,
            detail=detail,
        )
    )
    return item_id


@pytest.fixture
def seeded(db: Database) -> dict[str, int]:
    ids: dict[str, int] = {}
    with db.transaction() as conn:
        repo = ClassificationRepo(conn)
        tax = repo.ensure_taxonomy(TOPICS.name, TOPICS.mode, TOPICS.db_labels())
        conn.execute(
            "UPDATE taxonomies SET created_at = ? WHERE id = ?", (TAXONOMY_CREATED, tax.id)
        )
        other = repo.ensure_taxonomy("legacy_other", "multi", ["x"])

        ids["new"] = _add(conn, "new", "A pasta recipe with tomatoes")
        ids["old_classified"] = _add(conn, "oldc", "Old travel post", collected_at=OLD)
        ids["old_never"] = _add(conn, "oldn", "Old tech post", collected_at=OLD)
        ids["empty"] = _add(conn, "empty", "   ")
        ids["video_pending"] = _add(
            conn, "vp", "Watch this", kind="video", media=(MediaInput(0, "video"),)
        )
        ids["video_done"] = _add(conn, "vd", None, kind="video", media=(MediaInput(0, "video"),))
        media = MediaRepo(conn).for_item(ids["video_done"])[0]
        TranscriptsRepo(conn).add(
            media.id, backend="whisper", model="small", text="today we cook a recipe"
        )
        MediaRepo(conn).mark_transcribed(media.id)

        run = repo.create_run(other.id)
        repo.add_result(run, ids["old_classified"], "ok", ["x"])
    return ids


def make_service(db: Database, llm: FakeLLM, **kwargs) -> ClassificationService:
    def factory(spec: TaxonomySpec, provider: str | None) -> TaxonomyClassifier:
        return TaxonomyClassifier(
            spec,
            FunctionModel(llm),
            "native",
            max_concurrency=2,
            provider_name=provider or "fake",
            model_name="fake-model",
        )

    return ClassificationService(
        db, taxonomies={"topics": TOPICS}, classifier_factory=factory, **kwargs
    )


def _results(db: Database) -> dict[int, tuple[str, tuple[str, ...]]]:
    with db.read() as conn:
        rows = conn.execute(
            "SELECT cr.item_id, cr.status, group_concat(rl.label) FROM classification_results cr "
            "JOIN taxonomies t ON t.id = cr.taxonomy_id LEFT JOIN result_labels rl "
            "ON rl.result_id = cr.id WHERE t.name = 'topics' GROUP BY cr.id"
        ).fetchall()
    return {r[0]: (r[1], tuple(sorted((r[2] or "").split(",")) if r[2] else ())) for r in rows}


def test_default_scope_classifies_new_and_never_classified(db, seeded, llm) -> None:
    report = make_service(db, llm).classify_pending("topics")
    results = _results(db)
    assert set(results) == {seeded["new"], seeded["old_never"], seeded["video_done"]}
    assert results[seeded["new"]] == ("ok", ("recipe",))
    assert results[seeded["old_never"]] == ("ok", ("tech",))
    assert results[seeded["video_done"]] == ("ok", ("recipe",))
    assert seeded["old_classified"] not in results
    assert report.ok == 3
    assert report.skipped_empty == 1
    assert report.skipped_waiting_transcript == 1
    assert report.status == "done"
    assert report.candidates == 5


def test_backfill_includes_old_classified_items(db, seeded, llm) -> None:
    service = make_service(db, llm)
    service.classify_pending("topics")
    report = service.classify_pending("topics", scope="backfill")
    assert report.ok == 1
    assert _results(db)[seeded["old_classified"]] == ("ok", ("travel",))
    # Nothing left: a second backfill only meets the skipped items.
    again = service.classify_pending("topics", scope="backfill")
    assert again.classified == 0
    assert again.skipped == 2


def test_reprocess_classifies_done_items_again(db, seeded, llm) -> None:
    service = make_service(db, llm)
    service.classify_pending("topics")
    report = service.classify_pending("topics", scope="reprocess", filters=ItemFilter(q="pasta"))
    assert report.candidates == 1
    assert report.ok == 1
    with db.read() as conn:
        n = conn.execute(
            "SELECT count(*) FROM classification_results WHERE item_id = ?", (seeded["new"],)
        ).fetchone()[0]
    assert n == 2


def test_empty_input_is_skipped_without_result(db, seeded, llm) -> None:
    make_service(db, llm).classify_pending("topics", scope="backfill")
    assert seeded["empty"] not in _results(db)
    assert not any("<content>\n\n</content>" in p for p in llm.prompts)


def test_wait_for_transcripts(db, seeded, llm) -> None:
    service = make_service(db, llm)
    service.classify_pending("topics")
    assert seeded["video_pending"] not in _results(db)
    report = service.classify_pending("topics", wait_for_transcripts=False)
    assert report.skipped_waiting_transcript == 0
    assert _results(db)[seeded["video_pending"]][0] == "no_labels"


def test_errors_stay_pending_and_no_labels_are_done(db, llm) -> None:
    with db.transaction() as conn:
        failing = _add(conn, "f", "EXPLODE please")
        nothing = _add(conn, "n", "Good morning everyone")
    service = make_service(db, llm)
    report = service.classify_pending("topics")
    assert (report.errors, report.no_labels, report.ok) == (1, 1, 0)
    assert report.error_samples and report.error_samples[0][0] == failing
    assert "llm down" in report.error_samples[0][1]
    results = _results(db)
    assert results[failing] == ("error", ())
    assert results[nothing] == ("no_labels", ())
    with db.read() as conn:
        error = conn.execute(
            "SELECT error FROM classification_results WHERE item_id = ?", (failing,)
        ).fetchone()[0]
    assert "llm down" in error

    retry = service.classify_pending("topics")
    assert retry.candidates == 1  # only the failed item is pending again
    assert retry.errors == 1


def test_run_row_records_counts_and_hashes(db, seeded, llm) -> None:
    with db.transaction() as conn:
        _add(conn, "boom", "EXPLODE")
    report = make_service(db, llm).classify_pending("topics", provider="local")
    with db.read() as conn:
        repo = ClassificationRepo(conn)
        run = repo.get_run(report.run_id)  # type: ignore[arg-type]
        taxonomy = repo.get_taxonomy("topics")
    assert run is not None and taxonomy is not None
    assert run.status == "done"
    assert (run.n_ok, run.n_failed) == (3, 1)
    assert run.provider == "local"
    assert run.model == "fake-model"
    assert run.label_set_sha256 == TOPICS.label_set_sha256 == taxonomy.label_set_sha256
    assert run.prompt_sha256 == prompt_sha256(TOPICS)
    assert run.params["scope"] == "default"
    assert run.params["output_mode"] == "native"
    assert run.finished_at is not None


def test_limit_counts_only_classified_items(db, seeded, llm) -> None:
    updates: list[ProgressUpdate] = []
    report = make_service(db, llm, chunk_size=2).classify_pending(
        "topics", limit=2, progress=updates.append
    )
    assert report.classified == 2
    assert len(_results(db)) == 2
    assert updates[-1].report is report
    assert {u.status for u in updates} >= {"ok"}
    assert updates[-1].handled == len(updates)


def test_nothing_pending_creates_no_run(db, llm) -> None:
    report = make_service(db, llm).classify_pending("topics")
    assert report.run_id is None
    assert report.candidates == 0
    with db.read() as conn:
        assert conn.execute("SELECT count(*) FROM classification_runs").fetchone()[0] == 0
        # The taxonomy is still ensured.
        assert ClassificationRepo(conn).get_taxonomy("topics") is not None


def test_failure_marks_run_failed(db, seeded, llm, monkeypatch) -> None:
    service = make_service(db, llm)

    def crash(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(service, "_store_result", crash)
    with pytest.raises(sqlite3.OperationalError):
        service.classify_pending("topics")
    with db.read() as conn:
        status = conn.execute(
            "SELECT ru.status FROM classification_runs ru JOIN taxonomies t "
            "ON t.id = ru.taxonomy_id WHERE t.name = 'topics'"
        ).fetchone()[0]
    assert status == "failed"


def test_label_set_change_bumps_version_and_keeps_cutoff(db, seeded, llm) -> None:
    service = make_service(db, llm)
    service.classify_pending("topics")
    changed = TaxonomySpec(name="topics", mode="multi", labels=["recipe", "travel", "tech", "art"])
    service.taxonomies["topics"] = changed
    report = service.classify_pending("topics")
    assert report.taxonomy_version == 2
    # default scope: new item again (collected after cut-off), old items stay untouched
    assert report.ok == 2  # "new" and "video_done" (collected after the cut-off)
    backfill = service.classify_pending("topics", scope="backfill")
    assert backfill.ok == 2  # old_never + old_classified


def test_sources_restrict_selection(db, llm) -> None:
    with db.transaction() as conn:
        insta = _add(conn, "i1", "recipe one")
        tele = _add(conn, "7", "recipe two", source="telegram")
    spec = TaxonomySpec(name="insta_only", mode="multi", labels=["recipe"], sources=["instagram"])
    service = make_service(db, llm)
    service.taxonomies["insta_only"] = spec
    service.classify_pending("insta_only")
    with db.read() as conn:
        done = {r[0] for r in conn.execute("SELECT item_id FROM classification_results")}
    assert done == {insta}
    assert tele not in done
    with pytest.raises(ValueError, match="only applies"):
        service.classify_pending("insta_only", filters=ItemFilter(source="telegram"))


def test_unknown_taxonomy_and_db_fallback(db, seeded, llm) -> None:
    service = make_service(db, llm)
    with pytest.raises(KeyError):
        service.classify_pending("nope")
    # A taxonomy that only exists in the database can still be used.
    report = service.classify_pending("legacy_other", scope="reprocess", limit=1)
    assert report.taxonomy == "legacy_other"


def test_compose_inputs_sections_and_budget(db) -> None:
    with db.transaction() as conn:
        item = _add(
            conn,
            "c",
            "Caption text https://example.com/a",
            kind="video",
            media=(MediaInput(0, "video"),),
        )
        media = MediaRepo(conn).for_item(item)[0]
        TranscriptsRepo(conn).add(media.id, backend="w", model="m", text="spoken words")
        MediaRepo(conn).mark_transcribed(media.id)
        SummariesRepo(conn).add(item, "short summary")
        link = LinksRepo(conn).for_items([item])[item][0]
        LinksRepo(conn).add_fetch(
            link.id, fetcher="http", status="ok", title="Page", text="page body " * 50
        )
        ItemsRepo(conn).set_legacy_expanded_text(item, "expanded legacy")
    with db.read() as conn:
        composed = compose_inputs(conn, [item], max_chars=8000)[item]
        tight = compose_inputs(conn, [item], max_chars=120)[item]
    assert composed.sections == ("text", "transcript", "summary", "link", "legacy_expanded_text")
    assert composed.text.startswith("[Caption]\nCaption text")
    assert "[Transcript]\nspoken words" in composed.text
    assert "[Summary]\nshort summary" in composed.text
    assert "[Linked page (example.com): Page]" in composed.text
    assert "[Expanded text]\nexpanded legacy" in composed.text
    assert not composed.truncated and not composed.waiting_transcript
    assert len(tight.text) <= 120
    assert tight.truncated


def test_classify_text_without_persistence(db, llm) -> None:
    service = make_service(db, llm)
    outcome = service.classify_text("a recipe for travel", labels=["recipe", "travel"])
    assert outcome.labels == ("recipe", "travel")
    assert service.classify_text("tech news", "topics").labels == ("tech",)
    assert service.classify_text("  ", "topics").status == "empty"
    with db.read() as conn:
        assert conn.execute("SELECT count(*) FROM classification_runs").fetchone()[0] == 0


def test_list_taxonomies(db, seeded, llm) -> None:
    service = make_service(db, llm)
    service.taxonomies["kind"] = TaxonomySpec.adhoc(["a", "b"], mode="single", name="kind")
    service.classify_pending("topics")
    infos = {info.name: info for info in service.list_taxonomies()}
    assert set(infos) == {"topics", "kind", "legacy_other"}
    topics = infos["topics"]
    assert topics.configured and topics.in_db and topics.in_sync
    assert topics.version == 1
    assert topics.results["ok"] == 3
    assert topics.classified_items == 3
    assert topics.runs == 1
    assert infos["kind"].in_db is False and infos["kind"].version is None
    assert infos["legacy_other"].configured is False


def test_from_config_uses_settings_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("POSTPARSE_DB_PATH", str(tmp_path / "from_config.db"))
    from postparse.config import clear_settings_cache

    clear_settings_cache()
    service = ClassificationService.from_config()
    assert service.db.path == (tmp_path / "from_config.db").resolve()
    assert "topics" in service.taxonomies
    assert service.llm_config is not None
    assert service.provider_config().name == "lm_studio"


def test_service_without_database(llm) -> None:
    service = make_service(None, llm)  # type: ignore[arg-type]
    assert service.classify_text("tech", "topics").labels == ("tech",)
    assert [i.name for i in service.list_taxonomies()] == ["topics"]
    with pytest.raises(KeyError):
        service.taxonomy_spec("stored_only")
    with pytest.raises(ValueError, match="needs a database"):
        service.classify_pending("topics")
