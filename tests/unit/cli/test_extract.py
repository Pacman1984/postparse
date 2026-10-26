"""Tests of the ``extract`` CLI commands (ExtractionService with fake collectors)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from instaloader.exceptions import LoginException, TooManyRequestsException

from postparse.cli.main import cli
from postparse.collectors.base import InstagramFeedUnavailable
from postparse.collectors.instagram.collector import iter_saved_feed
from postparse.config import Settings
from postparse.core.db import Database
from postparse.services.extraction import ExtractionService
from tests.unit.collectors.fakes import (
    IG_SAVED_FEED,
    IG_USER_INFO,
    THROTTLED_401,
    FakeLoader,
    FakeTelegramClient,
    Feed,
    SleepRecorder,
    client_factory,
    ig_error,
    ig_node,
    ig_post,
    loader_factory,
    no_sleep,
    tg_text,
)

SECRETS = {
    "TELEGRAM_API_ID": "424242",
    "TELEGRAM_API_HASH": "tg-hash-secret",
    "TELEGRAM_PHONE": "+4915550000",
    "INSTAGRAM_USERNAME": "me",
    "INSTAGRAM_PASSWORD": "ig-pass-secret",
}


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch the CLI's service factory; returns a dict to configure the fakes."""
    monkeypatch.chdir(tmp_path)
    settings = Settings(data_dir=tmp_path / "data")
    state: dict = {
        "client": FakeTelegramClient([tg_text(1, "a"), tg_text(2, "b")]),
        "loader": FakeLoader(),
        "feed": Feed([ig_post(ig_node("p1")), ig_post(ig_node("p2"))]),
        "db_paths": [],
    }

    def build(ctx, db_path):
        path = Path(db_path) if db_path else settings.db_path
        state["db_paths"].append(path)
        return ExtractionService(
            Database.open(path),
            settings,
            telegram_overrides={
                "client_factory": client_factory(state["client"]),
                "sleep": no_sleep,
            },
            instagram_overrides={
                "loader_factory": loader_factory(state["loader"]),
                "saved_posts": state["feed"],
                "sleep": SleepRecorder(),
            },
        )

    monkeypatch.setattr("postparse.cli.extract._build_service", build)
    return state


def invoke(args: list[str], env_vars: dict[str, str] | None = None):
    return CliRunner().invoke(cli, ["extract", *args], env=env_vars or {})


def assert_no_secrets(output: str) -> None:
    for name in ("TELEGRAM_API_HASH", "TELEGRAM_PHONE", "INSTAGRAM_PASSWORD"):
        assert SECRETS[name] not in output


def test_telegram_success(env) -> None:
    result = invoke(["telegram", "--limit", "5"], SECRETS)
    assert result.exit_code == 0, result.output
    assert "Telegram extraction" in result.output
    assert "completed" in result.output
    assert env["client"].iter_calls[0]["limit"] == 5
    assert_no_secrets(result.output)


def test_telegram_full_and_force_alias(env) -> None:
    invoke(["telegram"], SECRETS)
    invoke(["telegram", "--force"], SECRETS)
    assert [c["min_id"] for c in env["client"].iter_calls] == [0, 0]
    invoke(["telegram"], SECRETS)
    assert env["client"].iter_calls[-1]["min_id"] == 2


def test_telegram_auth_required_exit_2(env) -> None:
    env["client"] = FakeTelegramClient(authorized=False)
    result = invoke(["telegram", "--no-interactive"], SECRETS)
    assert result.exit_code == 2, result.output
    assert "login required" in result.output.lower()
    assert_no_secrets(result.output)


def test_telegram_missing_credentials_exit_2(env) -> None:
    result = invoke(["telegram"], {})
    assert result.exit_code == 2
    assert "TELEGRAM_API_ID" in result.output


def test_telegram_unexpected_error_exit_1(env) -> None:
    env["client"] = FakeTelegramClient([tg_text(1)], fail_after=0)
    result = invoke(["telegram"], SECRETS)
    assert result.exit_code == 1
    assert "connection lost" in result.output


def test_custom_db_option(env, tmp_path: Path) -> None:
    target = tmp_path / "other.db"
    result = invoke(["telegram", "--db", str(target)], SECRETS)
    assert result.exit_code == 0, result.output
    assert env["db_paths"] == [target]
    assert target.exists()


def test_instagram_success(env) -> None:
    result = invoke(["instagram", "--stop-after-known", "5"], SECRETS)
    assert result.exit_code == 0, result.output
    assert "Instagram extraction" in result.output
    assert "Known (skipped)" in result.output
    assert_no_secrets(result.output)


def test_instagram_rate_limited_exit_3(env) -> None:
    env["feed"] = Feed(
        [ig_post(ig_node(c)) for c in "abc"], fail_at=2, error=TooManyRequestsException("429")
    )
    result = invoke(["instagram"], SECRETS)
    assert result.exit_code == 3, result.output
    assert "rate limit" in result.output.lower()
    assert "kept" in result.output


def test_instagram_throttled_session_check_exit_3(env, tmp_path: Path) -> None:
    session = Settings(data_dir=tmp_path / "data").sessions_dir / "instagram_me"
    session.parent.mkdir(parents=True)
    session.write_text("original-session")
    env["loader"] = FakeLoader(check_error=ig_error(THROTTLED_401))

    result = invoke(["instagram"], SECRETS)

    assert result.exit_code == 3, result.output
    text = " ".join(result.output.split())
    assert "No password login was attempted" in text
    assert "nothing was lost" in text
    assert env["loader"].logins == []
    assert session.read_text() == "original-session"
    assert_no_secrets(result.output)


FEED_FAIL = (
    '200 OK - "fail" status, message "We\'re sorry, but something went wrong. Please try again."'
)


def test_instagram_feed_refused_exit_3_keeps_progress(env, tmp_path: Path) -> None:
    env["feed"] = Feed(
        [ig_post(ig_node(c)) for c in "abc"],
        fail_at=2,
        error=InstagramFeedUnavailable("web", "We're sorry, but something went wrong."),
    )
    result = invoke(["instagram", "--batch-size", "1"], SECRETS)

    assert result.exit_code == 3, result.output
    text = " ".join(result.output.split())
    assert "feed refused by Instagram" in text
    assert "session is fine" in text and 'instagram.feed_api = "iphone"' in text
    assert "Everything committed before the feed was refused has been kept." in text
    assert "ConnectionException" not in text
    with Database.open(Settings(data_dir=tmp_path / "data").db_path).read() as conn:
        assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 2
    assert_no_secrets(result.output)


def test_instagram_feed_fail_status_from_the_web_feed_exit_3(env, tmp_path: Path) -> None:
    """The real feed iterator against the fake context: one request, typed error."""
    session = Settings(data_dir=tmp_path / "data").sessions_dir / "instagram_me"
    session.parent.mkdir(parents=True)
    session.write_text("original-session")
    loader = FakeLoader(session_user="me")
    loader.context.web_responses[IG_SAVED_FEED] = ig_error(FEED_FAIL, IG_SAVED_FEED)
    env["loader"] = loader
    env["feed"] = lambda ldr: iter_saved_feed(ldr.context, "web", "me")

    result = invoke(["instagram"], SECRETS)

    assert result.exit_code == 3, result.output
    assert [r[:2] for r in loader.context.requests] == [
        ("iphone", IG_USER_INFO),
        ("web", IG_SAVED_FEED),
    ]
    assert "something went wrong" in " ".join(result.output.split())
    assert loader.logins == []


def test_instagram_prints_verified_session(env, tmp_path: Path) -> None:
    session = Settings(data_dir=tmp_path / "data").sessions_dir / "instagram_me"
    session.parent.mkdir(parents=True)
    session.write_text("original-session")
    env["loader"] = FakeLoader(session_user="me")
    result = invoke(["instagram"], SECRETS)
    assert result.exit_code == 0, result.output
    assert "Instagram session verified (no password login)" in result.output
    assert "password (" not in result.output
    assert_no_secrets(result.output)


def test_instagram_prints_password_login(env) -> None:
    result = invoke(["instagram"], SECRETS)  # no session file
    assert result.exit_code == 0, result.output
    text = " ".join(result.output.split())
    assert "Logging in to Instagram with the password (no session file)" in text
    assert "session verified" not in text
    assert_no_secrets(result.output)


def test_instagram_invalid_feed_api_is_a_clear_error(env, monkeypatch: pytest.MonkeyPatch) -> None:
    from postparse.collectors.instagram import InstagramOptions

    def broken(config):
        return InstagramOptions(feed_api="graphql")  # type: ignore[arg-type]

    monkeypatch.setattr(InstagramOptions, "from_config", staticmethod(broken))
    result = invoke(["instagram"], SECRETS)
    assert result.exit_code == 1
    assert "instagram.feed_api must be one of 'web', 'iphone'" in " ".join(result.output.split())
    assert env["loader"].logins == []


def test_instagram_checkpoint_exit_2(env) -> None:
    env["loader"] = FakeLoader(login_error=LoginException("Checkpoint required"))
    result = invoke(["instagram"], SECRETS)
    assert result.exit_code == 2
    assert "Instagram app" in result.output
    assert_no_secrets(result.output)


def test_instagram_force_walks_everything(env) -> None:
    invoke(["instagram"], SECRETS)
    feed = Feed([ig_post(ig_node("p1")), ig_post(ig_node("p2"))])
    env["feed"] = feed
    result = invoke(["instagram", "--force"], SECRETS)
    assert result.exit_code == 0
    assert feed.consumed == 2
    assert "Updated" in result.output


def test_all_without_credentials(env) -> None:
    result = invoke(["all"], {})
    assert result.exit_code == 0
    assert "Skipping Telegram" in result.output and "Skipping Instagram" in result.output
    assert "nothing extracted" in result.output


def test_default_invokes_all(env) -> None:
    result = invoke([], {})
    assert "Skipping Telegram" in result.output


def test_all_runs_both_and_uses_highest_exit_code(env) -> None:
    env["loader"] = FakeLoader(login_error=TooManyRequestsException("429"))
    env["client"] = FakeTelegramClient(authorized=False)
    result = invoke(["all", "--no-interactive"], SECRETS)
    assert result.exit_code == 3, result.output
    assert "Telegram extraction" in result.output and "Instagram extraction" in result.output


def test_all_success(env) -> None:
    result = invoke(["all"], SECRETS)
    assert result.exit_code == 0, result.output
    assert "2 platform(s)" in result.output


@pytest.mark.parametrize("command", ["telegram", "instagram", "all"])
def test_help(command: str) -> None:
    result = CliRunner().invoke(cli, ["extract", command, "--help"])
    assert result.exit_code == 0
    assert "--limit" in result.output
    # Only `extract instagram` chains transcription (WP6).
    assert ("--transcribe" in result.output) == (command == "instagram")


def test_help_lists_new_options() -> None:
    tg = CliRunner().invoke(cli, ["extract", "telegram", "--help"]).output
    ig = CliRunner().invoke(cli, ["extract", "instagram", "--help"]).output
    assert "--full" in tg and "--session" in tg and "--db" in tg
    assert "--stop-after-known" in ig and "--refresh-dates" in ig and "--force" in ig
