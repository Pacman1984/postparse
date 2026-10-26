"""Regression tests: the test session never loads the repository's ``.env`` files.

Assertions only ever compare variable *names* and the guard's violation list,
so a failure can never print environment values.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest
from click.testing import CliRunner


def test_session_disables_dotenv() -> None:
    assert os.environ.get("POSTPARSE_NO_DOTENV") == "1"


def test_cli_and_api_imports_and_help_never_touch_repo_env(isolation_guard) -> None:
    before = isolation_guard.dotenv_violations

    # import_module + reload: other tests may have dropped the modules from sys.modules.
    cli_main = importlib.reload(importlib.import_module("postparse.cli.main"))
    importlib.reload(importlib.import_module("postparse.api.main"))
    assert cli_main._loaded_env is None

    result = CliRunner().invoke(cli_main.cli, ["--help"])
    assert result.exit_code == 0

    assert isolation_guard.dotenv_violations == before
    assert isolation_guard.set_credential_env_vars() == []


def test_load_env_files_never_reads_repo_env_even_when_enabled(
    isolation_guard, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the switch removed, the project-root lookup is still blocked by the guard."""
    import postparse.cli.main as cli_main

    repo_env = isolation_guard.repo_root / "config" / ".env"
    monkeypatch.delenv("POSTPARSE_NO_DOTENV")
    monkeypatch.chdir(tmp_path)  # no .env here, so the project-root files are tried
    before = isolation_guard.dotenv_violations

    cli_main.load_env_files()

    new = [m for m in isolation_guard.dotenv_violations if m not in before]
    isolation_guard.forget(new)  # expected: recorded and blocked, not a session failure
    if repo_env.exists() or (isolation_guard.repo_root / ".env").exists():
        assert len(new) == 1
        assert str(isolation_guard.repo_root) in new[0]
    # load_env_files() records which file it tried (a path, undone after the test);
    # no variable from the file itself may appear.
    leaked = [n for n in isolation_guard.set_credential_env_vars() if n != "_POSTPARSE_ENV_FILE"]
    assert leaked == []


@pytest.mark.parametrize("entry", ["load_dotenv", "dotenv_values", "main.dotenv_values"])
def test_guard_blocks_every_dotenv_entry_point(isolation_guard, entry: str) -> None:
    import dotenv
    import dotenv.main

    target = isolation_guard.repo_root / "config" / ".env.guard-selftest-missing"
    before = isolation_guard.dotenv_violations
    func = getattr(dotenv.main, entry.split(".")[-1]) if "." in entry else getattr(dotenv, entry)

    result = func(target)

    new = [m for m in isolation_guard.dotenv_violations if m not in before]
    isolation_guard.forget(new)
    assert len(new) == 1
    assert not result


def test_guard_hides_repo_env_from_find_dotenv(isolation_guard, monkeypatch) -> None:
    import dotenv

    monkeypatch.chdir(isolation_guard.repo_root)
    before = isolation_guard.dotenv_violations
    found = dotenv.find_dotenv(usecwd=True)
    new = [m for m in isolation_guard.dotenv_violations if m not in before]
    isolation_guard.forget(new)
    assert found == "" or not Path(found).resolve().is_relative_to(isolation_guard.repo_root)
