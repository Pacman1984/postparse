"""Tests for `postparse check ...` (no network: collectors, ASR and LLM probes are faked)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

from postparse.cli import check as check_mod
from postparse.cli.main import cli
from postparse.collectors import InstagramAuthRequired, TelegramAuthRequired
from postparse.config import Settings
from postparse.llm.health import HealthResult
from postparse.media.options import ApiAsrOptions, LocalAsrOptions, TranscriptionOptions


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fail loudly if a collector would be created, fake LLM/ASR probes."""
    calls: dict[str, Any] = {"telegram": 0, "instagram": 0}

    def forbidden(name: str):
        def factory(*args: Any, **kwargs: Any) -> Any:
            calls[name] += 1
            raise AssertionError(f"{name} collector created without --login")

        return factory

    monkeypatch.setattr(check_mod, "_make_telegram_collector", forbidden("telegram"))
    monkeypatch.setattr(check_mod, "_make_instagram_collector", forbidden("instagram"))
    monkeypatch.setattr(check_mod, "_resolve_model", lambda cfg, timeout: cfg)
    monkeypatch.setattr(
        check_mod,
        "_check_provider",
        lambda cfg, chat, timeout: HealthResult(
            cfg.name, cfg.model, "available", ["m1"], True, None, 12.0
        ),
    )
    monkeypatch.setattr(check_mod, "_cuda_info", lambda: (0, []))
    return calls


# -- telegram / instagram (offline) ------------------------------------------------


def test_telegram_status_without_credentials(settings: Settings) -> None:
    result = check_mod.telegram_status(settings, env={})
    assert result.status == "fail"
    assert not result.configured
    assert ("TELEGRAM_API_ID", "[red]missing[/red]") in result.rows


def test_telegram_status_never_shows_values(settings: Settings) -> None:
    env = {"TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "secret-hash"}
    result = check_mod.telegram_status(settings, env=env)
    assert result.status == "warn"  # no session file yet
    text = " ".join(f"{k} {v}" for k, v in result.rows)
    assert "12345" not in text and "secret-hash" not in text
    assert str(settings.sessions_dir / "telegram.session") in text


def test_telegram_status_ok_with_session(settings: Settings) -> None:
    assert settings.sessions_dir is not None
    settings.sessions_dir.mkdir(parents=True)
    (settings.sessions_dir / "telegram.session").write_bytes(b"x" * 10)
    env = {"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "h"}
    result = check_mod.telegram_status(settings, env=env)
    assert result.status == "ok"


def test_telegram_legacy_session_is_reported(settings: Settings) -> None:
    legacy = settings.data_dir / "cache" / "telegram_session.session"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"x")
    result = check_mod.telegram_status(
        settings, env={"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "h"}
    )
    assert result.status == "ok"
    assert str(legacy) in result.rows[0][1]


def test_instagram_status_variants(settings: Settings) -> None:
    assert check_mod.instagram_status(settings, env={}).status == "fail"
    no_session = check_mod.instagram_status(
        settings, env={"INSTAGRAM_USERNAME": "me", "INSTAGRAM_PASSWORD": "pw"}
    )
    assert no_session.status == "warn"
    assert "pw" not in " ".join(v for _, v in no_session.rows)
    assert check_mod.instagram_status(settings, env={"INSTAGRAM_USERNAME": "me"}).status == "fail"
    assert settings.sessions_dir is not None
    settings.sessions_dir.mkdir(parents=True)
    (settings.sessions_dir / "instagram_me").write_bytes(b"s")
    ok = check_mod.instagram_status(settings, env={}, username="me")
    assert ok.status == "ok"


@pytest.mark.parametrize("password", [True, False])
def test_instagram_status_recommends_the_session_import(settings: Settings, password: bool) -> None:
    env = {"INSTAGRAM_USERNAME": "me", **({"INSTAGRAM_PASSWORD": "pw"} if password else {})}
    hints = check_mod.instagram_status(settings, env=env).hints
    assert "--import-session" in hints[0] and "no password" in hints[0]
    assert "--login" in hints[1] and "#2487" in hints[1]


def test_check_telegram_command_makes_no_network_call(
    no_network: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "h")
    result = CliRunner().invoke(cli, ["check", "telegram"])
    assert result.exit_code == 0, result.output
    assert "TELEGRAM_API_HASH" in result.output
    assert no_network["telegram"] == 0


def test_check_telegram_fails_without_credentials(no_network: dict[str, Any]) -> None:
    result = CliRunner().invoke(cli, ["check", "telegram", "--login"])
    assert result.exit_code == 1
    assert no_network["telegram"] == 0  # --login is not attempted without credentials


def test_check_instagram_command_offline(
    no_network: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTAGRAM_USERNAME", "me")
    monkeypatch.setenv("INSTAGRAM_PASSWORD", "pw")
    result = CliRunner().invoke(cli, ["check", "instagram"])
    assert result.exit_code == 0, result.output
    assert "instagram_me" in result.output
    assert no_network["instagram"] == 0


# -- --login with fake collectors -------------------------------------------------------


class FakeTelegram:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.session_path = "telegram.session"

    async def __aenter__(self) -> FakeTelegram:
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeInstagram:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.save_path = "instagram_me"

    def __enter__(self) -> FakeInstagram:
        if self.error:
            raise self.error
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.mark.parametrize(("error", "code"), [(None, 0), (TelegramAuthRequired("no"), 1)])
def test_check_telegram_login(
    monkeypatch: pytest.MonkeyPatch, error: Exception | None, code: int
) -> None:
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "h")
    seen: list[Any] = []

    def factory(settings: Settings, credentials: Any, config: Any, session: Any) -> Any:
        seen.append(credentials)
        return FakeTelegram(error)

    monkeypatch.setattr(check_mod, "_make_telegram_collector", factory)
    result = CliRunner().invoke(cli, ["check", "telegram", "--login"])
    assert result.exit_code == code, result.output
    assert seen[0].api_id == 1
    assert ("authorized" in result.output) is (error is None)


@pytest.mark.parametrize(("error", "code"), [(None, 0), (InstagramAuthRequired("2fa"), 1)])
def test_check_instagram_login(
    monkeypatch: pytest.MonkeyPatch, error: Exception | None, code: int
) -> None:
    monkeypatch.setenv("INSTAGRAM_USERNAME", "me")
    monkeypatch.setenv("INSTAGRAM_PASSWORD", "pw")
    monkeypatch.setattr(
        check_mod, "_make_instagram_collector", lambda *a, **k: FakeInstagram(error)
    )
    result = CliRunner().invoke(cli, ["check", "instagram", "--login"])
    assert result.exit_code == code, result.output


@pytest.fixture
def ig_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``check instagram --login`` with the real collector on a fake instaloader."""
    from postparse.collectors.instagram import collector as collector_mod
    from tests.unit.collectors.fakes import FakeLoader

    monkeypatch.chdir(tmp_path)
    settings = Settings(data_dir=tmp_path / "data")
    assert settings.sessions_dir is not None
    session = settings.sessions_dir / "instagram_me"
    session.parent.mkdir(parents=True)
    session.write_text("original-session")
    monkeypatch.setattr(check_mod, "_settings", lambda ctx: settings)
    monkeypatch.setattr(check_mod, "_config", lambda ctx: None)
    state: dict[str, Any] = {"session": session, "loader": FakeLoader(session_user="me")}
    monkeypatch.setattr(collector_mod, "_default_loader_factory", lambda options: state["loader"])

    def invoke() -> Any:
        return CliRunner().invoke(
            cli,
            ["check", "instagram", "--login"],
            env={"INSTAGRAM_USERNAME": "me", "INSTAGRAM_PASSWORD": "pw-secret"},
        )

    state["invoke"] = invoke
    return state


@pytest.mark.parametrize("setup", ["logged_out", "no_file"])
def test_check_instagram_login_is_the_only_password_login(ig_login, setup: str) -> None:
    from tests.unit.collectors.fakes import FakeLoader

    loader = FakeLoader(session_user=None)
    ig_login["loader"] = loader
    if setup == "no_file":
        ig_login["session"].unlink()

    result = ig_login["invoke"]()

    assert result.exit_code == 0, result.output
    text = " ".join(result.output.split())
    why = "session logged out: login_required" if setup == "logged_out" else "no session file"
    assert f"No usable Instagram session ({why}); logging in with the password now" in text
    assert "only command that logs in with the password" in text
    assert loader.logins == ["me"]
    assert loader.saved and ig_login["session"].read_text() == "fake-session"
    assert "pw-secret" not in result.output


def test_check_instagram_login_with_a_valid_session_uses_no_password(ig_login) -> None:
    result = ig_login["invoke"]()
    assert result.exit_code == 0, result.output
    assert "Instagram session verified (no password login)" in result.output
    assert ig_login["loader"].logins == []


def test_check_instagram_login_never_reports_a_session_without_cookie(ig_login) -> None:
    """instaloader #2487: "authenticated" without a sessionid cookie is not a valid session."""
    from tests.unit.collectors.fakes import FakeLoader

    loader = FakeLoader(session_user=None, login_cookies={"csrftoken": "c-new"})
    ig_login["loader"] = loader

    result = ig_login["invoke"]()

    assert result.exit_code == 1, result.output
    text = " ".join(result.output.split())
    assert "returned no session cookie (instaloader issue #2487); nothing was saved" in text
    assert "`postparse check instagram --import-session`" in text
    assert "session is valid" not in text
    assert loader.logins == ["me"] and loader.saved == []
    assert ig_login["session"].read_text() == "original-session"
    assert "pw-secret" not in result.output


def test_check_instagram_login_never_logs_in_on_a_throttled_check(ig_login) -> None:
    from tests.unit.collectors.fakes import THROTTLED_401, FakeLoader, ig_error

    loader = FakeLoader(check_error=ig_error(THROTTLED_401))
    ig_login["loader"] = loader

    result = ig_login["invoke"]()

    assert result.exit_code == 1, result.output
    text = " ".join(result.output.split())
    assert "No password login was attempted" in text
    assert "Please wait a few minutes" in text and "https://" not in text
    assert "logging in with the password" not in text
    assert loader.logins == [] and loader.saved == []
    assert ig_login["session"].read_text() == "original-session"


# -- --import-session (browser session, hidden prompt) -------------------------------

#: Fake browser cookies (never shown in any output).
BROWSER_SID = "4242%3AsecretBrowserSid%3A27%3AAYleakyleaky"
BROWSER_CSRF = "browsercsrfLEAK0123456789abcdefX"


def _assert_no_cookie_values(text: str) -> None:
    for leak in ("secretBrowserSid", "AYleakyleaky", BROWSER_CSRF):
        assert leak not in text


@pytest.fixture
def ig_import(ig_login, monkeypatch: pytest.MonkeyPatch):
    """``check instagram --import-session`` on a terminal (real collector, fake instaloader)."""
    from tests.unit.collectors.fakes import FakeLoader

    monkeypatch.setattr(check_mod, "_stdin_is_tty", lambda: True)
    ig_login["loader"] = FakeLoader(session_user="me")

    def invoke(stdin: str, *args: str, env: dict[str, str] | None = None) -> Any:
        return CliRunner().invoke(
            cli,
            ["check", "instagram", "--import-session", *args],
            input=stdin,
            env={"INSTAGRAM_USERNAME": "me"} if env is None else env,
        )

    ig_login["invoke"] = invoke
    return ig_login


def test_check_instagram_import_session_saves_the_browser_session(ig_import) -> None:
    loader = ig_import["loader"]

    result = ig_import["invoke"](f"{BROWSER_SID}\n\n")

    assert result.exit_code == 0, result.output
    text = " ".join(result.output.split())
    assert "Browser session imported and verified (no password login)" in text
    assert "instagram import: browser session imported and verified" in text
    assert "user_agent" in text and "Do not log out of Instagram in that browser" in text
    assert "(input hidden)" in text
    assert loader.logins == [] and len(loader.context.requests) == 1  # exactly one request
    assert loader.imported[0][1]["sessionid"] == BROWSER_SID
    assert len(loader.imported[0][1]["csrftoken"]) == 32  # generated (Enter)
    assert ig_import["session"].read_text() == "fake-session"
    _assert_no_cookie_values(result.output)


def test_check_instagram_import_session_with_csrftoken_and_session_option(
    ig_import, tmp_path: Path
) -> None:
    target = tmp_path / "custom_session"
    result = ig_import["invoke"](f"{BROWSER_SID}\n{BROWSER_CSRF}\n", "--session", str(target))
    assert result.exit_code == 0, result.output
    assert ig_import["loader"].imported[0][1]["csrftoken"] == BROWSER_CSRF
    assert target.read_text() == "fake-session"
    assert ig_import["session"].read_text() == "original-session"
    _assert_no_cookie_values(result.output)


def test_check_instagram_import_session_needs_no_password(ig_import) -> None:
    ig_import["session"].unlink()
    result = ig_import["invoke"](f"{BROWSER_SID}\n\n")
    assert result.exit_code == 0, result.output  # "no session file" is fixed by the import
    assert ig_import["session"].read_text() == "fake-session"


@pytest.mark.parametrize(
    ("loader_kwargs", "why"),
    [
        ({"new_user": None}, "session logged out: login_required"),
        ({"new_user": "someone_else"}, "the session belongs to another account"),
    ],
    ids=["logged-out", "other-user"],
)
def test_check_instagram_import_session_unusable_saves_nothing(
    ig_import, loader_kwargs: dict, why: str
) -> None:
    from tests.unit.collectors.fakes import FakeLoader

    loader = FakeLoader(**loader_kwargs)
    ig_import["loader"] = loader
    result = ig_import["invoke"](f"{BROWSER_SID}\n{BROWSER_CSRF}\n")
    assert result.exit_code == 1, result.output
    text = " ".join(result.output.split())
    assert "The imported session is not usable" in text and why in text
    assert "nothing was saved" in text
    assert loader.saved == [] and loader.logins == []
    assert ig_import["session"].read_text() == "original-session"
    _assert_no_cookie_values(result.output)


def test_check_instagram_import_session_malformed_value(ig_import) -> None:
    result = ig_import["invoke"]("secretBrowserSid-AYleakyleaky\n\n")
    assert result.exit_code == 1, result.output
    text = " ".join(result.output.split())
    assert "does not look like an Instagram sessionid cookie" in text
    assert ig_import["loader"].context.requests == []
    assert ig_import["session"].read_text() == "original-session"
    _assert_no_cookie_values(result.output)


def test_check_instagram_import_session_needs_a_terminal(
    no_network: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTAGRAM_USERNAME", "me")
    result = CliRunner().invoke(
        cli, ["check", "instagram", "--import-session"], input=f"{BROWSER_SID}\n\n"
    )
    assert result.exit_code == 1, result.output
    assert "needs an interactive terminal" in " ".join(result.output.split())
    assert "(input hidden)" not in result.output  # no prompt
    assert no_network["instagram"] == 0
    _assert_no_cookie_values(result.output)


def test_check_instagram_import_session_needs_a_username(
    no_network: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INSTAGRAM_USERNAME", raising=False)
    monkeypatch.setattr(check_mod, "_stdin_is_tty", lambda: True)
    result = CliRunner().invoke(cli, ["check", "instagram", "--import-session"], input="x\n\n")
    assert result.exit_code == 1, result.output
    assert "INSTAGRAM_USERNAME not set" in result.output
    assert no_network["instagram"] == 0


def test_check_instagram_import_session_and_login_are_exclusive(
    no_network: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTAGRAM_USERNAME", "me")
    result = CliRunner().invoke(cli, ["check", "instagram", "--import-session", "--login"])
    assert result.exit_code == 2, result.output
    assert "cannot be combined" in result.output
    assert no_network["instagram"] == 0


def test_instagram_import_with_an_injected_prompt(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from postparse.collectors.instagram import collector as collector_mod
    from tests.unit.collectors.fakes import FakeLoader

    monkeypatch.setattr(check_mod, "_stdin_is_tty", lambda: False)  # not needed with a prompt
    monkeypatch.delenv("INSTAGRAM_PASSWORD", raising=False)
    loader = FakeLoader(session_user="me")
    monkeypatch.setattr(collector_mod, "_default_loader_factory", lambda options: loader)
    asked: list[tuple[str, bool]] = []

    def prompt(text: str, optional: bool) -> str:
        asked.append((text, optional))
        return BROWSER_SID if not optional else ""

    result = check_mod.instagram_import(settings, None, "me", None, prompt=prompt)
    assert result.status == "ok", result.summary
    assert [optional for _, optional in asked] == [False, True]
    assert all("hidden" in text for text, _ in asked)
    rows = " ".join(f"{k} {v}" for k, v in result.rows) + " ".join(result.hints)
    _assert_no_cookie_values(rows + result.summary)


# -- transcription --------------------------------------------------------------------


def test_transcription_local_missing_faster_whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "faster_whisper" else real(name, *a),
    )
    result = check_mod.transcription_status(TranscriptionOptions())
    assert result.status == "fail"
    assert "faster-whisper" in result.summary


def test_transcription_local_reports_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: object() if name == "faster_whisper" else real(name, *a),
    )
    monkeypatch.setattr(check_mod, "_cuda_info", lambda: (1, ["NVIDIA RTX, 8192 MiB"]))
    loaded: list[Any] = []
    monkeypatch.setattr(check_mod, "_load_local_model", lambda opts: loaded.append(opts))
    result = check_mod.transcription_status(TranscriptionOptions())
    assert result.status == "ok"
    assert ("GPU", "NVIDIA RTX, 8192 MiB") in result.rows
    assert loaded == []  # no model load without --load-model

    monkeypatch.setattr(
        check_mod,
        "_load_local_model",
        lambda opts: SimpleNamespace(
            active_device="cuda", active_compute_type="int8_float16", load_seconds=1.5
        ),
    )
    loaded_result = check_mod.transcription_status(TranscriptionOptions(), load_model=True)
    assert loaded_result.summary == "model loaded on cuda"


def test_transcription_cuda_configured_but_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: object() if name == "faster_whisper" else real(name, *a),
    )
    monkeypatch.setattr(check_mod, "_cuda_info", lambda: (0, []))
    options = TranscriptionOptions(local=LocalAsrOptions(device="cuda"))
    assert check_mod.transcription_status(options).status == "warn"


def test_transcription_api(monkeypatch: pytest.MonkeyPatch) -> None:
    openai_opts = TranscriptionOptions(backend="api")
    assert check_mod.transcription_status(openai_opts, env={}).status == "fail"

    probes: list[tuple[str, Any]] = []

    def probe(url: str, key: Any, timeout: float) -> tuple[bool, str]:
        probes.append((url, key))
        return True, "HTTP 200"

    monkeypatch.setattr(check_mod, "_probe_endpoint", probe)
    local = TranscriptionOptions(
        backend="api", api=ApiAsrOptions(base_url="http://speaches.lan:8000/v1")
    )
    result = check_mod.transcription_status(local, env={})
    assert result.status == "ok"
    assert probes == [("http://speaches.lan:8000/v1", None)]

    monkeypatch.setattr(check_mod, "_probe_endpoint", lambda *a: (False, "ConnectError"))
    assert check_mod.transcription_status(local, env={}).status == "fail"
    monkeypatch.setattr(check_mod, "_probe_endpoint", lambda *a: (True, "HTTP 401"))
    assert check_mod.transcription_status(local, env={}).status == "warn"


# -- llm ---------------------------------------------------------------------------------


def test_check_llm_all_available(no_network: dict[str, Any]) -> None:
    result = CliRunner().invoke(cli, ["check", "llm"])
    assert result.exit_code == 0, result.output
    assert "3/3 provider(s) available" in result.output
    assert "lm_studio *" in result.output


def test_check_llm_default_unavailable_fails(
    no_network: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def health(cfg: Any, chat: bool, timeout: float) -> HealthResult:
        if cfg.name == "lm_studio":
            return HealthResult(cfg.name, cfg.model, "unavailable", error="refused")
        return HealthResult(cfg.name, cfg.model, "available", chat_ok=True, latency_ms=5.0)

    monkeypatch.setattr(check_mod, "_check_provider", health)
    result = CliRunner().invoke(cli, ["check", "llm"])
    assert result.exit_code == 1
    assert "lm_studio is not answering" in result.output


def test_check_llm_other_unavailable_only_warns(
    no_network: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def health(cfg: Any, chat: bool, timeout: float) -> HealthResult:
        status = "available" if cfg.name == "lm_studio" else "no_api_key"
        return HealthResult(cfg.name, cfg.model, status, chat_ok=status == "available")

    monkeypatch.setattr(check_mod, "_check_provider", health)
    result = CliRunner().invoke(cli, ["check", "llm"])
    assert result.exit_code == 0, result.output


def test_check_llm_discovered_model_and_provider_filter(
    no_network: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        check_mod,
        "_resolve_model",
        lambda cfg, timeout: cfg.model_copy(update={"model": "served-7b"}),
    )
    result = CliRunner().invoke(cli, ["check", "llm", "--provider", "ollama"])
    assert result.exit_code == 0, result.output
    assert "served-7b (discovered)" in result.output
    assert "1/1" in result.output
    unknown = CliRunner().invoke(cli, ["check", "llm", "--provider", "nope"])
    assert unknown.exit_code == 1


# -- db / all --------------------------------------------------------------------------


def test_check_db(v2_db: tuple[Path, dict[str, int]], tmp_path: Path) -> None:
    path, _ = v2_db
    ok = CliRunner().invoke(cli, ["check", "db", "--db", str(path)])
    assert ok.exit_code == 0, ok.output
    assert "check passed" in ok.output
    assert "default_db_path" in ok.output  # legacy key in the test config is reported
    missing = CliRunner().invoke(cli, ["check", "db", "--db", str(tmp_path / "x.db")])
    assert missing.exit_code == 1


def test_check_all_offline(
    no_network: dict[str, Any], v2_db: tuple[Path, dict[str, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: object() if name == "faster_whisper" else real(name, *a),
    )
    path, _ = v2_db
    result = CliRunner().invoke(cli, ["check", "all", "--db", str(path)])
    assert result.exit_code == 0, result.output
    assert "Summary" in result.output
    assert "not configured" in result.output  # telegram / instagram skipped
    assert no_network == {"telegram": 0, "instagram": 0}


def test_check_all_fails_on_db_problem(no_network: dict[str, Any], tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli, ["check", "all", "--skip-llm", "--db", str(tmp_path / "missing.db")]
    )
    assert result.exit_code == 1
    assert "Problems: db" in result.output


def test_check_without_subcommand_runs_all(
    no_network: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    monkeypatch.setattr("postparse.cli.db.run_db_check", lambda *a: seen.append(True) or True)
    result = CliRunner().invoke(cli, ["check"])
    assert "Summary" in result.output
    assert seen == [True]


@pytest.mark.parametrize("sub", ["all", "db", "llm", "telegram", "instagram", "transcription"])
def test_help(sub: str) -> None:
    result = CliRunner().invoke(cli, ["check", sub, "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output
