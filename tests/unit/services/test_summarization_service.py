"""Summarizer and SummarizationService with pydantic-ai FunctionModel / TestModel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.repos import MediaRepo, SummariesRepo, TranscriptsRepo
from postparse.llm.config import LLMConfig, ProviderConfig
from postparse.services.summarization import SummarizationService, compose_summary_input
from postparse.summarization import (
    Summarizer,
    SummaryOutput,
    format_summary_text,
    parse_summary_text,
)
from postparse.summarization.summarizer import prompt_sha256
from tests.unit.media.helpers import add_video_item

PAYLOAD = {
    "summary": "Ein schnelles Rezept für Pasta mit Tomaten. Es dauert zehn Minuten.",
    "key_points": ["200 g Spaghetti", "Tomaten anbraten", "", "  Basilikum  "],
}


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.chdir(tmp_path)
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def db(settings: Settings) -> Database:
    assert settings.db_path is not None
    return Database.open(settings.db_path)


def json_model(
    payload: dict[str, Any], prompts: list[str] | None = None, fail: bool = False
) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if prompts is not None:
            for message in messages:
                for part in getattr(message, "parts", []):
                    if isinstance(part, UserPromptPart):
                        prompts.append(str(part.content))
        if fail:
            raise RuntimeError("server exploded")
        return ModelResponse(parts=[TextPart(json.dumps(payload))])

    return FunctionModel(respond)


def add_transcript(db: Database, media_id: int, text: str, language: str = "de") -> None:
    with db.transaction() as conn:
        TranscriptsRepo(conn).add(media_id, backend="fake", model="m", text=text, language=language)
        MediaRepo(conn).mark_transcribed(media_id)


def make_service(db: Database, model: Any, *, provider: str = "local") -> SummarizationService:
    return SummarizationService(
        db,
        summarizer_factory=lambda name: Summarizer(
            model, "native", provider_name=provider, model_name="test-llm"
        ),
    )


# -- schema / text format ----------------------------------------------------


def test_output_schema_cleans_and_caps_key_points() -> None:
    out = SummaryOutput.model_validate(
        {"summary": "  Zwei   Sätze.  ", "key_points": [f"- p{i}" for i in range(8)]}
    )
    assert out.summary == "Zwei Sätze." and out.key_points == ["p0", "p1", "p2", "p3", "p4"]
    assert SummaryOutput.model_json_schema()["properties"]["key_points"]["maxItems"] == 5
    with pytest.raises(ValueError):
        SummaryOutput.model_validate({"summary": "   ", "key_points": []})


def test_text_format_round_trip() -> None:
    text = format_summary_text("Kurz gesagt.", ["A", "B"])
    assert text == "Kurz gesagt.\n\n- A\n- B"
    assert parse_summary_text(text) == ("Kurz gesagt.", ["A", "B"])
    assert parse_summary_text("Nur Text.\n\nZweiter Absatz.") == (
        "Nur Text.\n\nZweiter Absatz.",
        [],
    )
    assert format_summary_text("Ohne Punkte.") == "Ohne Punkte."


def test_summarizer_native_output() -> None:
    summarizer = Summarizer(json_model(PAYLOAD), "native", model_name="x")
    outcome = summarizer.summarize("[Transcript]\nHeute machen wir Pasta")
    assert outcome.summary.startswith("Ein schnelles Rezept")
    assert outcome.key_points == ("200 g Spaghetti", "Tomaten anbraten", "Basilikum")
    assert outcome.requests == 1
    assert outcome.text.endswith("- Basilikum")
    assert summarizer.prompt_sha256 == prompt_sha256() and len(prompt_sha256()) == 64


def test_summarizer_tool_mode_with_test_model() -> None:
    summarizer = Summarizer(TestModel(), "tool")
    with summarizer.agent.override(
        model=TestModel(custom_output_args={"summary": "Kurz.", "key_points": ["a"]})
    ):
        outcome = summarizer.summarize("Hallo")
    assert outcome.summary == "Kurz." and outcome.key_points == ("a",)


def test_summarizer_rejects_blank_input() -> None:
    with pytest.raises(ValueError):
        Summarizer(TestModel(), "tool").summarize("   ")


def test_from_provider_uses_provider_output_mode() -> None:
    local = Summarizer.from_provider(
        ProviderConfig(name="llama_cpp", model="qwen", api_base="http://127.0.0.1:9/v1")
    )
    assert local.output_mode == "native" and local.max_concurrency == 1
    assert local.provider_name == "llama_cpp" and local.model_name == "qwen"


# -- service -------------------------------------------------------------------


def test_service_summarizes_items_with_transcripts(db: Database) -> None:
    item_id, (mid,) = add_video_item(db, "S1", caption="Pasta! #rezept")
    no_transcript, _ = add_video_item(db, "S2")
    add_transcript(db, mid, "Heute machen wir Pasta mit Tomaten")
    prompts: list[str] = []
    svc = make_service(db, json_model(PAYLOAD, prompts))
    report = svc.run()
    assert report.candidates == 1 and report.summarized == 1 and report.errors == 0
    assert report.provider == "local" and report.model == "test-llm"
    assert report.item_ids == [item_id] and no_transcript not in report.item_ids
    assert "[Caption]\nPasta! #rezept" in prompts[0]
    assert "[Transcript (language: de)]\nHeute machen wir Pasta" in prompts[0]
    with db.read() as conn:
        summary = SummariesRepo(conn).latest(item_id)
        hits = conn.execute(
            "SELECT rowid FROM items_fts WHERE items_fts MATCH 'Basilikum'"
        ).fetchall()
    assert summary is not None
    assert summary.provider == "local" and summary.model == "test-llm"
    assert summary.prompt_sha256 == prompt_sha256()
    assert parse_summary_text(summary.text)[1] == [
        "200 g Spaghetti",
        "Tomaten anbraten",
        "Basilikum",
    ]
    assert [h[0] for h in hits] == [item_id]  # key points are searchable
    # Nothing left to do; a new transcript makes the item due again.
    assert svc.run().candidates == 0
    assert svc.run(force=True).summarized == 1


def test_newer_transcript_makes_item_due_again(db: Database) -> None:
    item_id, (mid,) = add_video_item(db, "S1")
    add_transcript(db, mid, "erste Fassung")
    svc = make_service(db, json_model(PAYLOAD))
    assert svc.run().summarized == 1
    with db.transaction() as conn:
        conn.execute("UPDATE summaries SET created_at = '2000-01-01T00:00:00.000Z'")
    assert svc.pending() == [item_id]


def test_service_counts_errors_and_keeps_item_due(db: Database) -> None:
    item_id, (mid,) = add_video_item(db, "E1")
    add_transcript(db, mid, "Text")
    svc = make_service(db, json_model(PAYLOAD, fail=True))
    report = svc.run()
    assert report.errors == 1 and report.summarized == 0
    assert report.error_samples[0][0] == item_id
    assert svc.pending() == [item_id]


def test_service_skips_empty_inputs(db: Database) -> None:
    _item_id, (mid,) = add_video_item(db, "EMPTY", caption=None)
    add_transcript(db, mid, "   ")
    report = make_service(db, json_model(PAYLOAD)).run()
    assert report.skipped_empty == 1 and report.summarized == 0


def test_service_limit_and_item_ids(db: Database) -> None:
    ids = []
    for i in range(3):
        item_id, (mid,) = add_video_item(db, f"L{i}")
        add_transcript(db, mid, f"Text {i}")
        ids.append(item_id)
    svc = make_service(db, json_model(PAYLOAD))
    assert svc.run(item_ids=[ids[2]]).item_ids == [ids[2]]
    assert svc.run(limit=1).item_ids == [ids[0]]
    with pytest.raises(ValueError):
        svc.run(limit=0)


def test_service_provider_from_config(db: Database) -> None:
    llm = LLMConfig(
        default_provider="a",
        providers=[
            ProviderConfig(name="a", model="ma", api_base="http://127.0.0.1:9/v1"),
            ProviderConfig(name="b", model="mb", api_base="http://127.0.0.1:9/v1"),
        ],
    )
    svc = SummarizationService(db, llm_config=llm)
    assert svc.summarizer().provider_name == "a"
    assert svc.summarizer("b").model_name == "mb"
    with pytest.raises(ValueError):
        svc.summarizer("missing")
    with pytest.raises(ValueError, match="No LLM providers"):
        SummarizationService(db).summarizer()


def test_compose_includes_link_texts_and_respects_budget(db: Database) -> None:
    from postparse.core.db.repos import LinksRepo

    item_id, (mid,) = add_video_item(db, "LINK", caption="Rezept unter https://koch.test/r")
    add_transcript(db, mid, "Wort " * 500)
    with db.transaction() as conn:
        (link,) = LinksRepo(conn).for_items([item_id])[item_id]
        LinksRepo(conn).add_fetch(
            link.id, fetcher="test", status="ok", title="Pasta", text="Zutaten: Nudeln"
        )
    with db.read() as conn:
        text = compose_summary_input(conn, [item_id], max_chars=4000)[item_id]
        short = compose_summary_input(conn, [item_id], max_chars=300)[item_id]
    assert "[Linked page (koch.test): Pasta]\nZutaten: Nudeln" in text
    assert len(short) <= 300 and short.startswith("[Caption]")
