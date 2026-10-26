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
import io
import os
import shutil
import sqlite3
import tempfile
import warnings
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

import pytest

# pytest-asyncio is configured in pyproject.toml (asyncio_mode, loop scopes).
pytest_plugins = ("pytest_asyncio",)


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

_isolation_violations: list[str] = []
_dotenv_violations: list[str] = []
_original_cwd: Path = Path.cwd()
_session_dir: Path | None = None
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


def _sqlite_target_path(database, uri: bool) -> Path | None:
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


def _record_dotenv_attempt(kind: str, path: object) -> None:
    """Remember a blocked attempt to locate or read a repository ``.env`` file."""
    # Only the path is recorded, never any file contents or environment values.
    message = f"Test tried to {kind} a repository .env file: {path}"
    _dotenv_violations.append(message)
    _isolation_violations.append(message)


def _install_dotenv_guard() -> None:
    """Prevent the code under test from loading the developer's .env files.

    Every python-dotenv entry point is covered, however it is imported
    (``from dotenv import load_dotenv``, ``dotenv.main.load_dotenv``,
    ``dotenv_values``, ``find_dotenv``):

    - ``DotEnv._get_stream`` (used by ``load_dotenv`` and ``dotenv_values``)
      yields an empty stream for any path inside the repository;
    - ``find_dotenv`` returns ``""`` instead of a repository ``.env`` file;
    - ``load_dotenv`` without a path or stream loads nothing.

    Each blocked attempt is recorded in ``_dotenv_violations`` (and fails the
    session through ``_isolation_violations``).
    """
    try:
        import dotenv
        import dotenv.main
    except ImportError:  # pragma: no cover - python-dotenv is a runtime dependency
        return

    original_load = dotenv.main.load_dotenv
    original_find = dotenv.main.find_dotenv
    original_get_stream = dotenv.main.DotEnv._get_stream

    @contextmanager
    def _guarded_get_stream(self):
        if self.dotenv_path:
            resolved = Path(os.fspath(self.dotenv_path)).resolve()
            if _is_inside(resolved, REPO_ROOT):
                _record_dotenv_attempt("read", resolved)
                yield io.StringIO("")
                return
        with original_get_stream(self) as stream:
            yield stream

    def _guarded_find_dotenv(*args, **kwargs):
        found = original_find(*args, **kwargs)
        if found and _is_inside(Path(found).resolve(), REPO_ROOT):
            _record_dotenv_attempt("locate", Path(found).resolve())
            return ""
        return found

    def _guarded_load_dotenv(dotenv_path=None, stream=None, *args, **kwargs):
        if dotenv_path is None and stream is None:
            # Implicit discovery: never load anything during tests.
            return False
        return original_load(dotenv_path, stream, *args, **kwargs)

    dotenv.main.DotEnv._get_stream = _guarded_get_stream
    dotenv.find_dotenv = _guarded_find_dotenv
    dotenv.main.find_dotenv = _guarded_find_dotenv
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
                task
                for task in asyncio.all_tasks(loop)
                if not task.done() and task is not asyncio.current_task()
            ]

            if pending:
                # Cancel all pending tasks
                for task in pending:
                    task.cancel()

                # Wait for all tasks to be cancelled with timeout
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True), timeout=5.0
                    )
                except TimeoutError:
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
        "ignore", category=ResourceWarning, message=".*coroutine.*was never awaited.*"
    )

    # Suppress RuntimeWarnings from asyncio during Telethon cleanup
    warnings.filterwarnings(
        "ignore", category=RuntimeWarning, message=".*coroutine.*was never awaited.*"
    )

    # Suppress RuntimeWarnings about event loop closure
    warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*Event loop is closed.*")

    yield


class IsolationGuard:
    """Read-only view on the isolation guard's records (see ``isolation_guard``)."""

    repo_root = REPO_ROOT
    credential_env_vars = tuple(name for name in _CREDENTIAL_ENV_VARS)

    @property
    def violations(self) -> list[str]:
        """All isolation violations recorded so far."""
        return list(_isolation_violations)

    @property
    def dotenv_violations(self) -> list[str]:
        """Blocked attempts to locate or read a repository ``.env`` file."""
        return list(_dotenv_violations)

    def forget(self, messages: list[str]) -> None:
        """Drop expected entries (used by tests of the guard itself)."""
        for message in messages:
            _dotenv_violations.remove(message)
            _isolation_violations.remove(message)

    @staticmethod
    def set_credential_env_vars() -> list[str]:
        """Names (never values) of credential variables present in ``os.environ``."""
        return [name for name in _CREDENTIAL_ENV_VARS if name in os.environ]


@pytest.fixture
def isolation_guard() -> IsolationGuard:
    """Access the session's isolation-guard records without exposing env values."""
    return IsolationGuard()


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
def _no_model_discovery(request, monkeypatch):
    """Skip served-model discovery when building LLM models (unless the test is live).

    Discovery would try ``GET <api_base>/models``; on Windows a refused
    connection takes ~2 s, which the API lifespan warm-up would pay per test.
    Tests of discovery itself call ``postparse.llm.model_discovery`` directly or
    patch ``postparse.llm.client.resolve_provider_model`` themselves.
    """
    if "live" not in request.keywords:
        monkeypatch.setattr(
            "postparse.llm.client.resolve_provider_model", lambda cfg, timeout=5.0: cfg
        )
    yield


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
    from postparse.config import clear_settings_cache
    from postparse.core.utils import config as config_module

    config_module.get_config.cache_clear()
    clear_settings_cache()
    yield
    config_module.get_config.cache_clear()
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

    # Never load .env files during tests, whichever code path asks for them
    # (also inherited by any subprocess). Tests of load_env_files() itself
    # remove the variable with monkeypatch and use tmp .env files.
    os.environ["POSTPARSE_NO_DOTENV"] = "1"

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
