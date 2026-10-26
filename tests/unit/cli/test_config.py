"""Tests for `postparse config show | validate | env` (uses the test config from conftest)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

from postparse.cli.config import display_validation_results, mask_secrets
from postparse.cli.main import cli


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


class TestShow:
    def test_json_contains_paths_and_feature_sections(self) -> None:
        result = CliRunner().invoke(cli, ["config", "show", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["paths"]["db_path"].endswith("postparse.db")
        assert "sessions_dir" in data["paths"]
        assert data["transcription"]["backend"] == "local"
        assert data["transcription"]["api"]["api_key_env"] == "OPENAI_API_KEY"
        assert data["enrichment"]["concurrency"] >= 1
        assert data["classification"]["taxonomies"][0]["name"] == "topics"
        assert "summarization" in data
        assert "note" in data["database"]  # legacy default_db_path in the test config

    def test_secrets_are_masked(self) -> None:
        result = CliRunner().invoke(cli, ["config", "show", "--format", "json"])
        data = json.loads(result.output)
        assert data["api"]["auth"]["secret_key"] == "***"
        lm = data["llm"]["providers"][0]
        assert lm["api_key"] == "***"
        assert "test-secret-key-not-for-production" not in result.output

    def test_single_section_text(self) -> None:
        result = CliRunner().invoke(cli, ["config", "show", "--section", "transcription"])
        assert result.exit_code == 0, result.output
        assert "large-v3-turbo" in result.output
        assert "Configuration file" in result.output

    def test_missing_config_file(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli, ["--config", str(tmp_path / "x.toml"), "config", "show"]
        )
        assert result.exit_code != 0

    def test_mask_secrets(self) -> None:
        data = {"api_key": "abc", "api_key_env": "OPENAI_API_KEY", "nested": [{"password": "p"}],
                "token": "", "name": "x"}
        assert mask_secrets(data) == {"api_key": "***", "api_key_env": "OPENAI_API_KEY",
                                      "nested": [{"password": "***"}], "token": "", "name": "x"}


class TestValidate:
    def test_test_config_validates_with_warnings(self) -> None:
        result = CliRunner().invoke(cli, ["config", "validate"])
        assert result.exit_code == 0, result.output
        assert "Legacy database key" in result.output
        assert "Taxonomies" in result.output
        assert "Transcription" in result.output
        assert "Enrichment" in result.output

    def test_fix_creates_directories(self, tmp_path: Path) -> None:
        cfg = _write_config(tmp_path, f'[paths]\ndata_dir = "{(tmp_path / "d").as_posix()}"\n')
        result = CliRunner().invoke(cli, ["--config", str(cfg), "config", "validate", "--fix"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "d" / "sessions").is_dir()
        assert (tmp_path / "d" / "tmp").is_dir()

    @pytest.mark.parametrize(
        ("body", "check"),
        [
            ('[transcription]\nbackend = "cloud"\n', "Transcription"),
            ("[enrichment]\nconcurrency = 0\n", "Enrichment"),
            ('[[classification.taxonomies]]\nname = "t"\nmode = "weird"\nlabels = ["a"]\n',
             "Taxonomies"),
            ('[llm]\ndefault_provider = "a"\n[[llm.providers]]\nname = "a"\nmodel = "m"\n'
             'api_base = "http://x"\n[summarization]\nprovider = "missing"\n', "Summarization"),
            ("[api]\nport = 80\n", "API port"),
        ],
    )
    def test_invalid_sections_fail(self, tmp_path: Path, body: str, check: str) -> None:
        cfg = _write_config(tmp_path, body)
        result = CliRunner().invoke(cli, ["--config", str(cfg), "config", "validate"])
        assert result.exit_code == 1, result.output
        assert check in result.output
        assert "Validation failed" in result.output

    def test_reports_existing_database(self, tmp_path: Path,
                                       v2_db: tuple[Path, dict[str, int]]) -> None:
        path, _ = v2_db
        cfg = _write_config(tmp_path, f'[database]\ndb_path = "{path.as_posix()}"\n')
        result = CliRunner().invoke(cli, ["--config", str(cfg), "config", "validate"])
        assert result.exit_code == 0, result.output
        assert "schema v" in result.output
        assert "Legacy database key" not in result.output

    def test_display_validation_results(self) -> None:
        console = Console(record=True, width=120)
        display_validation_results(console, [
            {"check": "A", "status": "pass", "message": "ok"},
            {"check": "B", "status": "warning", "message": "hm"},
            {"check": "C", "status": "fail", "message": "[bad]"},
        ])
        text = console.export_text()
        assert "Pass" in text and "Warning" in text and "Fail" in text
        assert "[bad]" in text


class TestEnv:
    def test_lists_names_never_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_API_HASH", "supersecretvalue")
        monkeypatch.setenv("POSTPARSE_DB_PATH", "/some/where.db")
        result = CliRunner().invoke(cli, ["config", "env"])
        assert result.exit_code == 0, result.output
        for name in ("TELEGRAM_API_ID", "INSTAGRAM_PASSWORD", "OPENAI_API_KEY",
                     "POSTPARSE_DATA_DIR", "JWT_SECRET_KEY"):
            assert name in result.output
        assert "supersecretvalue" not in result.output
        assert "where.db" not in result.output
        assert "✓ set" in result.output

    def test_reports_loaded_env_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_POSTPARSE_ENV_FILE", "/tmp/.env")
        result = CliRunner().invoke(cli, ["config", "env"])
        assert "Loaded environment from" in result.output

    def test_custom_transcription_key_env(self, tmp_path: Path) -> None:
        cfg = _write_config(tmp_path, '[transcription.api]\napi_key_env = "GROQ_API_KEY"\n')
        result = CliRunner().invoke(cli, ["--config", str(cfg), "config", "env"])
        assert "GROQ_API_KEY" in result.output


@pytest.mark.parametrize("sub", ["show", "validate", "env"])
def test_help(sub: str) -> None:
    result = CliRunner().invoke(cli, ["config", sub, "--help"])
    assert result.exit_code == 0
