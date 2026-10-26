"""Typed application settings (paths and database location).

Values are resolved in this order (later wins):

1. Built-in defaults: everything lives under ``data_dir`` (default ``data``).
2. The TOML config file found by :class:`~postparse.core.utils.config.ConfigManager`
   (explicit ``--config`` path or the standard search locations):
   ``[paths] data_dir / sessions_dir / downloads_dir / tmp_dir`` and
   ``[database] db_path``. The schema v1 keys ``database.path`` and
   ``database.default_db_path`` are deliberately ignored: they point at the
   legacy database, which stays with the old DB layer.
3. Environment variables ``POSTPARSE_DATA_DIR``, ``POSTPARSE_DB_PATH``,
   ``POSTPARSE_SESSIONS_DIR``, ``POSTPARSE_DOWNLOADS_DIR``, ``POSTPARSE_TMP_DIR``.

Relative paths resolve against the current working directory at load time.
Other config sections (LLM, API, ...) are still read through ``ConfigManager``.

Example:
    >>> settings = get_settings()
    >>> settings.db_path.name
    'postparse.db'
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

__all__ = ["Settings", "clear_settings_cache", "get_settings", "load_file_values"]

logger = logging.getLogger(__name__)

_PATH_KEYS = ("data_dir", "sessions_dir", "downloads_dir", "tmp_dir")


class Settings(BaseSettings):
    """Filesystem locations used by PostParse.

    Attributes:
        data_dir: Root directory for all local data.
        db_path: Schema v2 SQLite database file (default ``<data_dir>/postparse.db``).
        sessions_dir: Login session files (default ``<data_dir>/sessions``).
        downloads_dir: Downloaded media; ``media.local_path`` is relative to it
            (default ``<data_dir>/downloads``).
        tmp_dir: Scratch space (default ``<data_dir>/tmp``).
    """

    model_config = SettingsConfigDict(env_prefix="POSTPARSE_", extra="ignore")

    data_dir: Path = Path("data")
    db_path: Path | None = None
    sessions_dir: Path | None = None
    downloads_dir: Path | None = None
    tmp_dir: Path | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Let environment variables override init kwargs (which carry file values)."""
        return (env_settings, init_settings)

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        """Fill directory defaults below ``data_dir`` and make all paths absolute."""
        base = Path.cwd()
        data_dir = _absolute(self.data_dir, base)
        self.data_dir = data_dir
        self.db_path = _absolute(self.db_path or data_dir / "postparse.db", base)
        self.sessions_dir = _absolute(self.sessions_dir or data_dir / "sessions", base)
        self.downloads_dir = _absolute(self.downloads_dir or data_dir / "downloads", base)
        self.tmp_dir = _absolute(self.tmp_dir or data_dir / "tmp", base)
        return self


def _absolute(path: Path, base: Path) -> Path:
    """Return ``path`` made absolute against ``base`` (``~`` expanded)."""
    path = Path(path).expanduser()
    return path if path.is_absolute() else (base / path)


def load_file_values(config_path: str | Path | None = None) -> dict[str, Any]:
    """Read the settings-relevant keys from the TOML config file.

    Args:
        config_path: Explicit config file; ``None`` uses ConfigManager's search.

    Returns:
        Mapping of :class:`Settings` field names to raw values. Empty if no
        config file was found during implicit discovery.

    Raises:
        FileNotFoundError: If an explicit ``config_path`` does not exist.
    """
    from postparse.core.utils.config import ConfigManager

    try:
        manager = ConfigManager(config_path)
    except FileNotFoundError:
        if config_path is not None:
            raise
        logger.debug("No config file found; using default settings")
        return {}

    values: dict[str, Any] = {}
    paths = manager.get_section("paths") or {}
    for key in _PATH_KEYS:
        if paths.get(key):
            values[key] = paths[key]
    database = manager.get_section("database") or {}
    if database.get("db_path"):
        values["db_path"] = database["db_path"]
    return values


@lru_cache(maxsize=16)
def _cached_settings(config_key: str | None) -> Settings:
    """Build settings for a normalized config path key."""
    return Settings(**load_file_values(config_key))


def get_settings(config_path: str | Path | None = None) -> Settings:
    """Return settings for ``config_path``, cached per path.

    Args:
        config_path: Explicit config file (for example the CLI ``--config``
            option); ``None`` uses the standard search locations.

    Returns:
        Resolved :class:`Settings`. Call ``get_settings.cache_clear()`` after
        changing the working directory or environment.
    """
    key = str(Path(config_path).resolve()) if config_path is not None else None
    return _cached_settings(key)


def clear_settings_cache() -> None:
    """Forget cached settings (after changing cwd, env or the config file)."""
    _cached_settings.cache_clear()
