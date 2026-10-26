"""
Root-level pytest configuration for PostParse tests.

This module provides fixtures and configuration for proper async cleanup,
especially for background tasks from Telethon and other async libraries.

It also isolates the test suite from the developer's real environment:

- The working directory is moved to a throw-away session directory that
  contains a copy of ``tests/fixtures/config/config.toml``. All relative
  default paths (database, sessions, caches, downloads) resolve there.
- Loading ``.env`` files from the repository is disabled and credential
  environment variables are removed.
- ``ConfigManager`` refuses to load the repository's real ``config/config.toml``.
- ``sqlite3.connect`` fails loudly for any path inside ``<repo>/data/``.
- Tests marked ``live`` (talking to real LLM servers / APIs) are skipped unless
  ``--run-live`` is passed. Real network access is blocked by pytest-socket
  (see ``[tool.pytest.ini_options]`` in pyproject.toml).
"""

import asyncio
import os
import shutil
import sqlite3
import tempfile
import pytest
import warnings
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch
from urllib.parse import urlparse


# Configure pytest-asyncio
pytest_plugins = ('pytest_asyncio',)


REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_DATA_DIR = REPO_ROOT / "data"
REPO_CONFIG_FILE = REPO_ROOT / "config" / "config.toml"
TEST_CONFIG_FILE = Path(__file__).resolve().parent / "fixtures" / "config" / "config.toml"

# Environment variables that may carry real credentials. They are removed for
# the whole test session so nothing can accidentally authenticate for real.
_CREDENTIAL_ENV_VARS = (
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_PHONE",
    "INSTAGRAM_USERNAME",
    "INSTAGRAM_PASSWORD",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "JWT_SECRET_KEY",
    "_POSTPARSE_ENV_FILE",
)

_isolation_violations: List[str] = []
_original_cwd: Path = Path.cwd()
_session_dir: Optional[Path] = None
_original_sqlite_connect = sqlite3.connect


class IsolationError(RuntimeError):
    """Raised when a test tries to touch the developer's real data."""


def _is_inside(path: Path, parent: Path) -> bool:
    """Return True if ``path`` equals ``parent`` or lies below it."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _sqlite_target_path(database, uri: bool) -> Optional[Path]:
    """Return the filesystem path a sqlite3.connect() call would open, or None."""
    if isinstance(database, bytes):
        database = database.decode(errors="replace")
    database = os.fspath(database)
    if database in ("", ":memory:"):
        return None
    if uri or database.startswith("file:"):
        parsed = urlparse(database)
        if "mode=memory" in (parsed.query or ""):
            return None
        database = parsed.path or parsed.netloc
        # file:/C:/... on Windows
        if len(database) > 2 and database[0] == "/" and database[2] == ":":
            database = database[1:]
        if database in ("", ":memory:"):
            return None
    return Path(database).resolve()


def _guarded_sqlite_connect(database, *args, **kwargs):
    """sqlite3.connect replacement that refuses paths inside <repo>/data/."""
    target = _sqlite_target_path(database, bool(kwargs.get("uri", False)))
    if target is not None and _is_inside(target, REPO_DATA_DIR):
        message = f"Test tried to open a SQLite database inside the repo data dir: {target}"
        _isolation_violations.append(message)
        raise IsolationError(message)
    return _original_sqlite_connect(database, *args, **kwargs)


def _install_dotenv_guard() -> None:
    """Prevent the code under test from loading the developer's .env files."""
    try:
        import dotenv
        import dotenv.main
    except ImportError:  # pragma: no cover - python-dotenv is a runtime dependency
        return

    original = dotenv.main.load_dotenv

    def _guarded_load_dotenv(dotenv_path=None, stream=None, *args, **kwargs):
        if stream is not None:
            return original(dotenv_path, stream, *args, **kwargs)
        if dotenv_path is not None:
            resolved = Path(dotenv_path).resolve()
            if not _is_inside(resolved, REPO_ROOT):
                return original(dotenv_path, stream, *args, **kwargs)
        # Implicit discovery or a repository .env file: load nothing.
        return False

    dotenv.load_dotenv = _guarded_load_dotenv
    dotenv.main.load_dotenv = _guarded_load_dotenv


def _install_config_guard() -> None:
    """Make ConfigManager refuse to load the repository's real config file."""
    from postparse.core.utils.config import ConfigManager

    original = ConfigManager._find_config_file

    def _guarded_find_config_file(self, config_path=None):
        path = original(self, config_path)
        if Path(path).resolve() == REPO_CONFIG_FILE:
            message = (
                f"Test tried to load the real configuration file {REPO_CONFIG_FILE}. "
                "Use the isolated test config (cwd) or an explicit tmp config."
            )
            _isolation_violations.append(message)
            raise IsolationError(message)
        return path

    ConfigManager._find_config_file = _guarded_find_config_file


def pytest_addoption(parser):
    """Register the --run-live option."""
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Run tests marked 'live' that talk to real LLM servers or APIs.",
    )


@pytest.fixture(scope="session")
def event_loop_policy():
    """
    Set event loop policy for the test session.

    Returns:
        Event loop policy instance.
    """
    policy = asyncio.get_event_loop_policy()
    return policy


@pytest.fixture(scope="function")
async def cleanup_tasks():
    """
    Ensure all async tasks are properly cleaned up after each test.

    This fixture yields control to the test, then ensures all pending
    tasks are properly awaited or cancelled before the event loop closes.
    This prevents RuntimeError: Event loop is closed from background tasks.

    Example:
        async def test_something(cleanup_tasks):
            # Test code here
            pass
    """
    yield

    # Get all pending tasks
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Get all tasks except current
            pending = [
                task for task in asyncio.all_tasks(loop)
                if not task.done() and task is not asyncio.current_task()
            ]

            if pending:
                # Cancel all pending tasks
                for task in pending:
                    task.cancel()

                # Wait for all tasks to be cancelled with timeout
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    # Tasks didn't cancel in time, that's okay
                    pass
                except Exception:
                    # Ignore errors during cleanup
                    pass
    except RuntimeError:
        # Event loop already closed or not available
        pass


@pytest.fixture(autouse=True)
def suppress_telethon_warnings():
    """
    Suppress known harmless warnings from Telethon during test cleanup.

    These warnings occur when Telethon background tasks are cleaning up
    and the event loop has already been closed. They don't indicate actual
    problems with the code.
    """
    # Suppress ResourceWarnings from Telethon coroutines
    warnings.filterwarnings(
        "ignore",
        category=ResourceWarning,
        message=".*coroutine.*was never awaited.*"
    )

    # Suppress RuntimeWarnings from asyncio during Telethon cleanup
    warnings.filterwarnings(
        "ignore",
        category=RuntimeWarning,
        message=".*coroutine.*was never awaited.*"
    )

    # Suppress RuntimeWarnings about event loop closure
    warnings.filterwarnings(
        "ignore",
        category=RuntimeWarning,
        message=".*Event loop is closed.*"
    )

    yield


@pytest.fixture(autouse=True)
def _restore_environ():
    """Undo os.environ changes made by a test (e.g. ``os.environ.setdefault``)."""
    with patch.dict(os.environ):
        yield


@pytest.fixture(autouse=True)
def _no_real_redis(monkeypatch):
    """Never connect to a real Redis server; CacheManager falls back to memory."""
    try:
        import redis
    except ImportError:  # pragma: no cover - redis is a runtime dependency
        return

    def _refuse(*args, **kwargs):
        raise redis.ConnectionError("Real Redis connections are disabled in tests")

    monkeypatch.setattr(redis, "from_url", _refuse)


@pytest.fixture(autouse=True)
def _clear_llm_caches():
    """Forget discovered/built LLM models so provider configs never leak between tests."""
    from postparse.llm.client import clear_model_cache

    clear_model_cache()
    yield
    clear_model_cache()


@pytest.fixture(autouse=True)
def _clear_cached_config():
    """Reset lru-cached config singletons so each test sees a fresh config."""
    from postparse.core.utils import config as config_module
    from postparse.api import dependencies
    from postparse.config import clear_settings_cache

    config_module.get_config.cache_clear()
    dependencies.get_config.cache_clear()
    clear_settings_cache()
    yield
    config_module.get_config.cache_clear()
    dependencies.get_config.cache_clear()
    clear_settings_cache()


def pytest_configure(config):
    """
    Configure pytest with custom settings and isolate the test environment.

    Runs before test modules (and their imports of the backend) are collected,
    so module-level ``ConfigManager()`` / ``load_dotenv()`` calls already see
    the isolated environment.

    Args:
        config: Pytest configuration object.
    """
    global _session_dir

    # Set asyncio mode to auto
    config.option.asyncio_mode = "auto"

    # Throw-away working directory with a copy of the minimal test config.
    _session_dir = Path(tempfile.mkdtemp(prefix="postparse-tests-"))
    (_session_dir / "config").mkdir()
    (_session_dir / "data").mkdir()
    shutil.copyfile(TEST_CONFIG_FILE, _session_dir / "config" / "config.toml")
    os.chdir(_session_dir)

    # Live runs may use API keys exported in the shell (never from config/.env).
    if not config.getoption("--run-live"):
        for name in _CREDENTIAL_ENV_VARS:
            os.environ.pop(name, None)

    sqlite3.connect = _guarded_sqlite_connect
    sqlite3.dbapi2.connect = _guarded_sqlite_connect
    _install_dotenv_guard()
    _install_config_guard()

    # Real LLM requests are never allowed in the suite; tests use pydantic-ai's
    # TestModel / FunctionModel (live tests re-enable requests explicitly).
    import pydantic_ai.models

    pydantic_ai.models.ALLOW_MODEL_REQUESTS = bool(config.getoption("--run-live"))


def pytest_unconfigure(config):
    """Restore the working directory and remove the session directory."""
    os.chdir(_original_cwd)
    sqlite3.connect = _original_sqlite_connect
    sqlite3.dbapi2.connect = _original_sqlite_connect
    if _session_dir is not None:
        shutil.rmtree(_session_dir, ignore_errors=True)


def pytest_collection_modifyitems(config, items):
    """Skip tests marked ``live`` unless ``--run-live`` is given."""
    if config.getoption("--run-live"):
        for item in items:
            if "live" in item.keywords:
                item.add_marker(pytest.mark.enable_socket)
        return
    skip_live = pytest.mark.skip(reason="live test: needs --run-live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


def pytest_sessionfinish(session, exitstatus):
    """Fail the run if any test violated isolation, even if the error was swallowed."""
    if _isolation_violations:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_sep("=", "TEST ISOLATION VIOLATIONS", red=True)
            for message in sorted(set(_isolation_violations)):
                reporter.write_line(message)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
