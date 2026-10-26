"""Fixtures for media / transcription tests: isolated settings and a v2 database."""

from __future__ import annotations

from pathlib import Path

import pytest

from postparse.config import Settings
from postparse.core.db import Database


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    for name in ("POSTPARSE_DATA_DIR", "POSTPARSE_DB_PATH", "POSTPARSE_SESSIONS_DIR",
                 "POSTPARSE_DOWNLOADS_DIR", "POSTPARSE_TMP_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def db(settings: Settings) -> Database:
    assert settings.db_path is not None
    return Database.open(settings.db_path)
