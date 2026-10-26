"""Tests for postparse.config.Settings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from postparse.config import Settings, clear_settings_cache, get_settings


def _write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_defaults_resolve_under_cwd_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    assert settings.data_dir == tmp_path / "data"
    assert settings.db_path == tmp_path / "data" / "postparse.db"
    assert settings.sessions_dir == tmp_path / "data" / "sessions"
    assert settings.downloads_dir == tmp_path / "data" / "downloads"
    assert settings.tmp_dir == tmp_path / "data" / "tmp"


def test_isolated_test_config_points_into_session_dir() -> None:
    settings = get_settings()
    assert settings.db_path == Path.cwd() / "data" / "postparse.db"
    assert settings.downloads_dir == Path.cwd() / "data" / "downloads"


def test_file_values_and_legacy_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(
        tmp_path / "custom.toml",
        '[database]\ndefault_db_path = "data/social_media.db"\npath = "legacy.db"\n'
        'db_path = "store/v2.db"\n[paths]\ndata_dir = "var"\ndownloads_dir = "dl"\n',
    )
    settings = get_settings(config)
    assert settings.db_path == tmp_path / "store" / "v2.db"
    assert settings.data_dir == tmp_path / "var"
    assert settings.downloads_dir == tmp_path / "dl"
    assert settings.sessions_dir == tmp_path / "var" / "sessions"
    assert get_settings(config) is settings  # cached per path


def test_env_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "c.toml", '[database]\ndb_path = "from_file.db"\n')
    monkeypatch.setenv("POSTPARSE_DB_PATH", str(tmp_path / "from_env.db"))
    monkeypatch.setenv("POSTPARSE_DATA_DIR", "envdata")
    clear_settings_cache()
    settings = get_settings(config)
    assert settings.db_path == tmp_path / "from_env.db"
    assert settings.tmp_dir == tmp_path / "envdata" / "tmp"


def test_missing_explicit_config_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        get_settings(tmp_path / "missing.toml")


def test_no_config_file_uses_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from postparse.core.utils.config import ConfigManager

    def _not_found(self: ConfigManager, config_path: object = None) -> Path:
        raise FileNotFoundError("none")

    monkeypatch.setattr(ConfigManager, "_find_config_file", _not_found)
    clear_settings_cache()
    assert get_settings().db_path == tmp_path / "data" / "postparse.db"
    assert "POSTPARSE_DB_PATH" not in os.environ
