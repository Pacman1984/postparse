"""CLI: ``transcribe run/status``, ``summarize run`` and ``extract instagram --transcribe``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from postparse.cli.main import cli
from postparse.collectors.base import InstagramAuthRequired, InstagramRateLimited
from postparse.config import Settings
from postparse.core.db import Database
from postparse.core.db.repos import SummariesRepo, TranscriptsRepo
from postparse.media.options import TranscriptionOptions
from postparse.media.transcription import BackendUnavailable
from postparse.services.extraction import ExtractionService
from postparse.services.summarization import SummarizationService
from postparse.services.transcription import TranscriptionService
from postparse.summarization import Summarizer
from tests.unit.collectors.fakes import (
    FakeLoader,
    Feed,
    SleepRecorder,
    ig_node,
    ig_post,
    loader_factory,
)
from tests.unit.media.helpers import FakeBackend, FakeFetcher, add_video_item, get_media


def summary_model() -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(json.dumps(
            {"summary": "Ein kurzes Rezept.", "key_points": ["Nudeln kochen"]}))])

    return FunctionModel(respond)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.chdir(tmp_path)
    settings = Settings(data_dir=tmp_path / "data")
    assert settings.db_path is not None
    db = Database.open(settings.db_path)
    state: dict[str, Any] = {
        "db": db, "settings": settings, "backend": FakeBackend(), "fetcher": FakeFetcher(),
        "runs": [],
    }

    def build_transcription(ctx, db_path, *, interactive=False):
        svc = TranscriptionService(
            db, settings, options=TranscriptionOptions(),
            backend_factory=lambda kind: state["backend"],
            fetcher_factory=lambda refetch: state["runs"].append(refetch) or state["fetcher"],
        )
        return svc

    def build_summaries(ctx, db_path):
        return SummarizationService(
            db, summarizer_factory=lambda name: Summarizer(
                summary_model(), "native", provider_name=name or "default", model_name="llm"),
        )

    monkeypatch.setattr("postparse.cli.transcribe._build_service", build_transcription)
    monkeypatch.setattr("postparse.cli.summarize._build_service", build_summaries)
    monkeypatch.setattr("postparse.cli.extract._build_transcription_service",
                        lambda ctx, db_path: build_transcription(ctx, db_path))
    monkeypatch.setattr("postparse.cli.extract._build_summarization_service", build_summaries)
    return state


def invoke(*args: str, env_vars: dict[str, str] | None = None):
    return CliRunner().invoke(cli, list(args), env=env_vars or {})


def test_transcribe_run_success(env) -> None:
    _, (mid,) = add_video_item(env["db"], "A")
    result = invoke("transcribe", "run", "--limit", "5")
    assert result.exit_code == 0, result.output
    assert "Transcribed" in result.output and "completed" in result.output
    assert get_media(env["db"], mid).transcript_status == "transcribed"
    assert env["runs"] == [True]


def test_transcribe_run_no_refetch_and_item(env) -> None:
    item_id, (mid,) = add_video_item(env["db"], "A")
    add_video_item(env["db"], "B")
    result = invoke("transcribe", "run", "--no-refetch", "--item", str(item_id))
    assert result.exit_code == 0, result.output
    assert env["runs"] == [False]
    assert [f[0] for f in env["fetcher"].fetched] == [mid]


@pytest.mark.parametrize(("error", "code"), [
    (InstagramRateLimited("429"), 3),
    (InstagramAuthRequired("checkpoint"), 2),
])
def test_transcribe_run_exit_codes(env, error: Exception, code: int) -> None:
    add_video_item(env["db"], "X")
    env["fetcher"].errors["X"] = error
    result = invoke("transcribe", "run")
    assert result.exit_code == code, result.output


def test_transcribe_run_backend_unavailable(env) -> None:
    add_video_item(env["db"], "X")
    env["backend"].unavailable = BackendUnavailable("uv sync --extra asr")
    result = invoke("transcribe", "run", "--backend", "local")
    assert result.exit_code == 1
    assert "extra asr" in result.output


def test_transcribe_run_interrupted(env) -> None:
    add_video_item(env["db"], "X")

    def interrupt(path, work_dir):
        raise KeyboardInterrupt

    env["backend"].on_transcribe = interrupt
    result = invoke("transcribe", "run")
    assert result.exit_code == 130
    assert "Interrupted" in result.output


def test_transcribe_status(env) -> None:
    add_video_item(env["db"], "A")
    add_video_item(env["db"], "B")
    invoke("transcribe", "run", "--limit", "1")
    result = invoke("transcribe", "status")
    assert result.exit_code == 0, result.output
    assert "instagram" in result.output and "Transcripts: 1" in result.output


def test_summarize_run(env) -> None:
    item_id, (mid,) = add_video_item(env["db"], "A")
    invoke("transcribe", "run")
    result = invoke("summarize", "run", "--limit", "3")
    assert result.exit_code == 0, result.output
    assert "1 summaries stored" in result.output
    with env["db"].read() as conn:
        assert SummariesRepo(conn).latest(item_id) is not None
    again = invoke("summarize", "run")
    assert "Nothing to summarize" in again.output


def test_extract_instagram_transcribe(env, monkeypatch: pytest.MonkeyPatch) -> None:
    db: Database = env["db"]
    feed = Feed([
        ig_post(ig_node("VID1", "GraphVideo", video_url="https://cdn.test/vid1.mp4")),
        ig_post(ig_node("IMG1")),
        ig_post(ig_node("VID2", "GraphVideo")),  # no video_url in the feed node
    ])
    old_item, (old_mid,) = add_video_item(db, "OLD")  # backlog: must not be touched

    def build(ctx, db_path):
        return ExtractionService(
            db, env["settings"],
            instagram_overrides={"loader_factory": loader_factory(FakeLoader()),
                                 "saved_posts": feed, "sleep": SleepRecorder()},
        )

    monkeypatch.setattr("postparse.cli.extract._build_service", build)
    result = invoke("extract", "instagram", "--transcribe",
                    env_vars={"INSTAGRAM_USERNAME": "me", "INSTAGRAM_PASSWORD": "pw"})
    assert result.exit_code == 0, result.output
    assert "Transcription of new videos" in result.output
    assert "1 summaries stored" in result.output
    assert env["runs"] == [False]  # no re-fetch after collection
    assert [f[1] for f in env["fetcher"].fetched] == ["VID1"]
    with db.read() as conn:
        vid1 = conn.execute("SELECT id FROM items WHERE external_id = 'VID1'").fetchone()[0]
        assert TranscriptsRepo(conn).current_for_items([vid1])
        assert SummariesRepo(conn).latest(vid1) is not None
    assert get_media(db, old_mid).transcript_status == "pending"


def test_extract_instagram_without_transcribe_flag(env, monkeypatch) -> None:
    feed = Feed([ig_post(ig_node("VID1", "GraphVideo", video_url="https://cdn.test/v.mp4"))])
    monkeypatch.setattr("postparse.cli.extract._build_service", lambda ctx, db_path:
                        ExtractionService(env["db"], env["settings"], instagram_overrides={
                            "loader_factory": loader_factory(FakeLoader()),
                            "saved_posts": feed, "sleep": SleepRecorder()}))
    result = invoke("extract", "instagram",
                    env_vars={"INSTAGRAM_USERNAME": "me", "INSTAGRAM_PASSWORD": "pw"})
    assert result.exit_code == 0, result.output
    assert env["runs"] == [] and "Transcription" not in result.output


def test_transcribe_run_suspected_block_exit_3(env) -> None:
    from postparse.media.fetch import RefetchError

    for code in ("S1", "S2", "S3"):
        add_video_item(env["db"], code)
        env["fetcher"].errors[code] = RefetchError("metadata failed")
    result = invoke("transcribe", "run")
    assert result.exit_code == 3, result.output
    assert "hours" in result.output and "lost" in result.output
