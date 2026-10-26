"""Health checks: database, transcription backend, collector sessions and LLM providers.

- ``db``: same as ``postparse db check``
- ``transcription``: ASR backend availability (no model download unless ``--load-model``)
- ``telegram`` / ``instagram``: which session file would be used and whether
  credentials are set (names only). Only ``--login`` contacts the service
  (interactive prompts are allowed); the default makes no network call.
- ``llm``: list models, discovered model, chat ping and latency per provider
- ``all``: everything above (``--login`` passes through); also the default

Exit codes: 0 ok (warnings allowed), 1 problems found.

Example:
    $ postparse check
    $ postparse check telegram --login
    $ postparse check transcription --load-model
    $ postparse check llm --provider llama_cpp
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import rich_click as click
from rich.markup import escape
from rich.table import Table

from postparse.cli.utils import (
    config_path_from_ctx,
    get_console,
    print_error,
    print_info,
    print_success,
    print_warning,
    resolve_db_path,
)

if TYPE_CHECKING:
    from postparse.config import Settings
    from postparse.llm.config import ProviderConfig
    from postparse.llm.health import HealthResult
    from postparse.media.options import TranscriptionOptions

logger = logging.getLogger(__name__)

Status = Literal["ok", "warn", "fail", "skip"]

_DB_OPTION_HELP = "Schema v2 database file (default: Settings.db_path)"
_STYLE = {"ok": "green", "warn": "yellow", "fail": "red", "skip": "dim"}
_ICON = {"ok": "✓", "warn": "⚠", "fail": "✗", "skip": "-"}


@dataclass(slots=True)
class CheckResult:
    """Outcome of one check.

    Attributes:
        name: Check name (``telegram``, ``llm``, ...).
        status: ``ok``, ``warn``, ``fail`` or ``skip``.
        summary: One-line verdict.
        rows: ``(key, value)`` detail rows (never secret values).
        hints: Follow-up suggestions.
        configured: For collector checks: any credential or session file exists.
    """

    name: str
    status: Status = "ok"
    summary: str = ""
    rows: list[tuple[str, str]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    configured: bool = True

    def worsen(self, status: Status) -> None:
        """Lower the status to ``status`` if that is worse."""
        order = {"skip": 0, "ok": 1, "warn": 2, "fail": 3}
        if order[status] > order[self.status]:
            self.status = status


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _settings(ctx: click.Context) -> Settings:
    from postparse.config import get_settings

    return get_settings(config_path_from_ctx(ctx))


def _config(ctx: click.Context) -> Any:
    """Return the ``ConfigManager`` or ``None`` when no config file exists."""
    from postparse.core.utils.config import ConfigManager

    try:
        return ConfigManager(config_path_from_ctx(ctx))
    except FileNotFoundError:
        return None


def _is_set(env: Mapping[str, str], name: str) -> bool:
    return bool((env.get(name) or "").strip())


def _env_row(env: Mapping[str, str], name: str, *, required: bool) -> tuple[str, str]:
    """Return a credential row showing only whether ``name`` is set."""
    if _is_set(env, name):
        return name, "[green]set[/green]"
    return name, "[red]missing[/red]" if required else "[dim]not set (optional)[/dim]"


def _file_row(path: Path) -> str:
    """Describe a session file (existence, size, modification date)."""
    if not path.exists():
        return f"{escape(str(path))} [yellow](not found)[/yellow]"
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    return f"{escape(str(path))} [green]({stat.st_size / 1024:.1f} KB, {modified})[/green]"


def print_result(result: CheckResult) -> None:
    """Print one check result as a table."""
    console = get_console()
    style = _STYLE[result.status]
    table = Table(
        title=f"[bold {style}]{_ICON[result.status]} {result.name}: {escape(result.summary)}"
        f"[/bold {style}]",
        show_header=False,
        title_justify="left",
        box=None,
        padding=(0, 2),
    )
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", overflow="fold")
    for key, value in result.rows:
        table.add_row(key, value)
    console.print(table)
    for hint in result.hints:
        console.print(f"  [dim]→ {hint}[/dim]")
    console.print()


def _finish(ctx: click.Context, results: list[CheckResult]) -> None:
    """Exit with 1 if any check failed."""
    if any(result.status == "fail" for result in results):
        ctx.exit(1)


# ---------------------------------------------------------------------------
# Telegram / Instagram (no network unless --login)
# ---------------------------------------------------------------------------


def telegram_status(
    settings: Settings, env: Mapping[str, str] | None = None, session: str | None = None
) -> CheckResult:
    """Describe the Telegram session file and credentials (no network).

    Args:
        settings: Application settings.
        env: Environment (default ``os.environ``).
        session: ``--session`` override.

    Returns:
        ``fail`` without API id/hash, ``warn`` without a session file.
    """
    from postparse.collectors.telegram import resolve_session_path

    env = os.environ if env is None else env
    result = CheckResult("telegram")
    path = resolve_session_path(settings, session)
    result.rows.append(("Session file", _file_row(path)))
    for name, required in (
        ("TELEGRAM_API_ID", True),
        ("TELEGRAM_API_HASH", True),
        ("TELEGRAM_PHONE", False),
    ):
        result.rows.append(_env_row(env, name, required=required))
    missing = [n for n in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH") if not _is_set(env, n)]
    result.configured = path.exists() or len(missing) < 2
    if missing:
        result.worsen("fail")
        result.summary = "credentials missing"
        result.hints.append(f"Set {' and '.join(missing)} (e.g. in config/.env)")
    elif not path.exists():
        result.worsen("warn")
        result.summary = "no session file yet"
        result.hints.append(
            "`postparse check telegram --login` (or the first extract) "
            "logs in interactively and creates it"
        )
    else:
        result.summary = "session file and credentials present (not verified)"
        result.hints.append("Verify the login with `postparse check telegram --login`")
    return result


def _make_telegram_collector(
    settings: Settings, credentials: Any, config: Any, session: str | None
) -> Any:
    """Create the Telegram collector used by ``--login`` (tests replace this)."""
    from postparse.collectors.telegram import TelegramCollector, TelegramOptions
    from postparse.core.db import Database

    assert settings.db_path is not None
    # The collector never touches the database while connecting; migrate=False
    # keeps the handle inert.
    return TelegramCollector(
        Database(settings.db_path, migrate=False),
        settings,
        credentials,
        TelegramOptions.from_config(config),
        interactive=True,
        session=session,
    )


def telegram_login(settings: Settings, config: Any, session: str | None) -> CheckResult:
    """Connect to Telegram and verify the session (interactive login allowed)."""
    from postparse.collectors import CollectorError, telegram_credentials

    result = CheckResult("telegram login")
    try:
        collector = _make_telegram_collector(settings, telegram_credentials(), config, session)
    except CollectorError as exc:
        return CheckResult("telegram login", "fail", str(exc))

    async def connect() -> None:
        async with collector:
            pass

    try:
        asyncio.run(connect())
    except CollectorError as exc:
        result.worsen("fail")
        result.summary = str(exc)
        return result
    result.summary = "session is authorized"
    result.rows.append(("Session file", _file_row(Path(collector.session_path))))
    return result


def instagram_status(
    settings: Settings,
    env: Mapping[str, str] | None = None,
    username: str | None = None,
    session: str | None = None,
) -> CheckResult:
    """Describe the Instagram session file and credentials (no network).

    Args:
        settings: Application settings.
        env: Environment (default ``os.environ``).
        username: ``--username`` override of ``INSTAGRAM_USERNAME``.
        session: ``--session`` override (file path).

    Returns:
        ``fail`` without a username or without both session and password,
        ``warn`` when only the password is available.
    """
    from postparse.collectors.instagram import resolve_session_path

    env = os.environ if env is None else env
    result = CheckResult("instagram")
    user = (username or "").strip() or (env.get("INSTAGRAM_USERNAME") or "").strip()
    result.rows.append(_env_row(env, "INSTAGRAM_USERNAME", required=not username))
    result.rows.append(_env_row(env, "INSTAGRAM_PASSWORD", required=False))
    has_password = _is_set(env, "INSTAGRAM_PASSWORD")
    if not user:
        assert settings.sessions_dir is not None
        found = sorted(settings.sessions_dir.glob("instagram_*")) if session is None else []
        for path in found:
            result.rows.append(("Session file found", _file_row(path)))
        result.configured = bool(found) or has_password
        result.worsen("fail")
        result.summary = "INSTAGRAM_USERNAME not set"
        result.hints.append("Set INSTAGRAM_USERNAME (or pass --username) to pick the session")
        return result
    load_path, save_path = resolve_session_path(settings, user, session)
    result.rows.insert(0, ("Session file", _file_row(load_path)))
    if save_path != load_path:
        result.rows.insert(1, ("Saved to", escape(str(save_path))))
    if load_path.exists():
        result.summary = "session file present (not verified)"
        result.hints.append("Verify the login with `postparse check instagram --login`")
    elif has_password:
        result.worsen("warn")
        result.summary = "no session file; extract never logs in with the password"
        result.hints.append("Log in once with `postparse check instagram --login` (in a terminal)")
    else:
        result.worsen("fail")
        result.summary = "no session file and INSTAGRAM_PASSWORD not set"
        result.hints.append(
            "Set INSTAGRAM_PASSWORD once and run `postparse check instagram "
            "--login` to create the session"
        )
    return result


def _print_session_event(event: Any) -> None:
    """Print the session outcome of ``--login`` (a password login as a warning)."""
    if event.phase == "login":
        print_warning(
            escape(
                f"{event.message}. This is the only command that logs in with the password; "
                "Instagram may ask for a 2FA code or a confirmation in the Instagram app."
            )
        )
    elif event.phase == "session" and event.message:
        print_info(escape(event.message))


def _make_instagram_collector(
    settings: Settings, credentials: Any, config: Any, session: str | None
) -> Any:
    """Create the Instagram collector used by ``--login`` (tests replace this).

    The only collector created with ``allow_password_login=True``: an
    interactive, explicitly requested login. Extract runs, transcription
    re-fetches and API jobs never log in with the password.
    """
    from postparse.collectors.instagram import InstagramCollector, InstagramOptions
    from postparse.core.db import Database

    assert settings.db_path is not None
    return InstagramCollector(
        Database(settings.db_path, migrate=False),
        settings,
        credentials,
        InstagramOptions.from_config(config),
        interactive=True,
        session=session,
        allow_password_login=True,
        progress=_print_session_event,
    )


def instagram_login(
    settings: Settings, config: Any, username: str | None, session: str | None
) -> CheckResult:
    """Verify the saved Instagram session, or log in with the password, and save it.

    The password login (with a 2FA prompt if needed) only happens here, and
    only when there is no usable session; a throttled session check never
    leads to one.
    """
    from postparse.collectors import CollectorError, instagram_credentials

    result = CheckResult("instagram login")
    try:
        credentials = instagram_credentials(username=username)
        collector = _make_instagram_collector(settings, credentials, config, session)
        with collector:
            pass
    except CollectorError as exc:
        result.worsen("fail")
        result.summary = str(exc)
        return result
    result.summary = "session is valid"
    result.rows.append(("Session file", _file_row(Path(collector.save_path))))
    return result


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------


def _module_version(name: str) -> str | None:
    """Return the installed distribution version, or ``None``."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _cuda_info() -> tuple[int, list[str]]:
    """Return ``(CUDA devices usable by CTranslate2, GPU names from nvidia-smi)``."""
    import importlib.util

    count = 0
    if importlib.util.find_spec("ctranslate2") is not None:
        from postparse.media.transcription.local_faster_whisper import register_cuda_dlls

        register_cuda_dlls()
        try:
            import ctranslate2

            count = int(ctranslate2.get_cuda_device_count())
        except Exception:
            logger.debug("CUDA device query failed", exc_info=True)
    names: list[str] = []
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            completed = subprocess.run(
                [smi, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            names = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        except (OSError, subprocess.SubprocessError):
            logger.debug("nvidia-smi failed", exc_info=True)
    return count, names


def _probe_endpoint(base_url: str, api_key: str | None, timeout: float) -> tuple[bool, str]:
    """GET ``<base_url>/models``; any HTTP answer counts as reachable."""
    import httpx

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = httpx.get(base_url.rstrip("/") + "/models", headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        return False, type(exc).__name__
    return True, f"HTTP {response.status_code}"


def _load_local_model(options: TranscriptionOptions) -> Any:
    """Build the local backend and load its model (tests replace this)."""
    from postparse.media.transcription import build_backend

    # The local backend (unlike the TranscriptionBackend protocol) has load().
    backend: Any = build_backend(options, "local")
    backend.load()
    return backend


def transcription_status(
    options: TranscriptionOptions,
    *,
    backend: str | None = None,
    load_model: bool = False,
    env: Mapping[str, str] | None = None,
    timeout: float = 5.0,
) -> CheckResult:
    """Check the configured (or requested) ASR backend.

    Args:
        options: ``[transcription]`` options.
        backend: ``local`` / ``api`` overriding ``options.backend``.
        load_model: Load the faster-whisper model (may download it).
        env: Environment for the API key lookup.
        timeout: HTTP timeout of the API reachability probe.

    Returns:
        Check result.
    """
    import importlib.util

    env = os.environ if env is None else env
    kind = backend or options.backend
    result = CheckResult("transcription")
    result.rows.append(("Backend", kind))
    if kind == "local":
        local = options.local
        result.rows.append(
            ("Model / device / compute", f"{local.model} / {local.device} / {local.compute_type}")
        )
        fw_version = _module_version("faster-whisper")
        if importlib.util.find_spec("faster_whisper") is None:
            result.rows.append(("faster-whisper", "[red]not installed[/red]"))
            result.worsen("fail")
            result.summary = "faster-whisper is not installed"
            result.hints.append("uv sync --extra asr")
            return result
        result.rows.append(("faster-whisper", fw_version or "installed"))
        result.rows.append(("ctranslate2", _module_version("ctranslate2") or "-"))
        count, names = _cuda_info()
        result.rows.append(("CUDA devices", str(count)))
        for name in names:
            result.rows.append(("GPU", escape(name)))
        if count == 0 and local.device == "cuda":
            result.worsen("warn")
            result.summary = "device = cuda but no CUDA device found"
        else:
            result.summary = f"faster-whisper ready ({'cuda' if count else 'cpu'})"
        if load_model:
            try:
                loaded = _load_local_model(options)
            except Exception as exc:
                result.worsen("fail")
                result.summary = f"model load failed: {exc}"
                return result
            result.rows.append(
                (
                    "Model loaded",
                    f"{loaded.active_device} / {loaded.active_compute_type} "
                    f"in {loaded.load_seconds:.1f}s",
                )
            )
            result.summary = f"model loaded on {loaded.active_device}"
        else:
            result.hints.append("--load-model loads (and if needed downloads) the model")
        return result

    api = options.api
    base_url = api.base_url or "https://api.openai.com/v1"
    result.rows.append(("Endpoint", escape(base_url)))
    result.rows.append(("Model", api.model))
    result.rows.append(_env_row(env, api.api_key_env, required=api.base_url is None))
    key = (env.get(api.api_key_env) or "").strip() or None
    if key is None and api.base_url is None:
        result.worsen("fail")
        result.summary = f"{api.api_key_env} not set"
        return result
    reachable, detail = _probe_endpoint(base_url, key, timeout)
    result.rows.append(("Reachable", f"{'yes' if reachable else 'no'} ({detail})"))
    if not reachable:
        result.worsen("fail")
        result.summary = "endpoint not reachable"
    elif detail in ("HTTP 401", "HTTP 403"):
        result.worsen("warn")
        result.summary = "endpoint reachable but rejected the API key"
    else:
        result.summary = "endpoint reachable"
    return result


# ---------------------------------------------------------------------------
# LLM providers
# ---------------------------------------------------------------------------


def _resolve_model(cfg: ProviderConfig, timeout: float) -> ProviderConfig:
    """Return ``cfg`` with the served model of a local server (tests replace this)."""
    from postparse.llm.model_discovery import resolve_provider_model

    return resolve_provider_model(cfg, timeout=timeout)


def _check_provider(cfg: ProviderConfig, *, chat: bool, timeout: float) -> HealthResult:
    """Run the health check of one provider (tests replace this)."""
    from postparse.llm.health import check_provider

    return check_provider(cfg, chat=chat, timeout=timeout)


def llm_status(
    config: Any, *, provider: str | None = None, chat: bool = True, timeout: float = 10.0
) -> CheckResult:
    """Check configured LLM providers.

    The result fails when the default (or the requested) provider does not
    answer; other unavailable providers only warn.
    """
    from postparse.llm.config import LLMConfig

    result = CheckResult("llm")
    if config is None:
        return CheckResult("llm", "fail", "no config file found")
    try:
        llm_config = LLMConfig.from_config_manager(config)
    except (ValueError, TypeError) as exc:
        return CheckResult("llm", "fail", f"invalid [llm] config: {exc}")
    providers = llm_config.providers
    target = provider or llm_config.default_provider
    if provider:
        providers = [p for p in providers if p.name.lower() == provider.lower()]
        if not providers:
            names = ", ".join(p.name for p in llm_config.providers)
            return CheckResult("llm", "fail", f"provider {provider!r} not configured ({names})")

    available = 0
    for cfg in providers:
        resolved = _resolve_model(cfg, min(timeout, 5.0))
        health = _check_provider(resolved, chat=chat, timeout=timeout)
        is_target = cfg.name.lower() == target.lower()
        label = cfg.name + (" *" if cfg.name.lower() == llm_config.default_provider.lower() else "")
        model = cfg.model if resolved.model == cfg.model else f"{resolved.model} (discovered)"
        parts = [f"[green]{health.status}[/green]" if health.ok else f"[red]{health.status}[/red]"]
        if health.latency_ms is not None:
            parts.append(f"{health.latency_ms:.0f} ms")
        if health.models:
            parts.append(f"{len(health.models)} model(s)")
        if health.error and not health.ok:
            parts.append(escape(health.error[:80]))
        endpoint = escape(cfg.api_base or "(cloud)")
        result.rows.append((label, f"{escape(model)} @ {endpoint} — " + ", ".join(parts)))
        if health.ok:
            available += 1
        elif is_target:
            result.worsen("fail")
        else:
            result.worsen("warn")
    result.summary = f"{available}/{len(providers)} provider(s) available"
    if result.status == "fail":
        result.summary += f"; {target} is not answering"
    result.hints.append("* = default provider")
    return result


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@click.group(invoke_without_command=True)
@click.pass_context
def check(ctx: click.Context) -> None:
    """🔍 Health checks (database, transcription, sessions, LLM providers).

    Without a subcommand this runs `check all`. Only `--login` and `check llm`
    talk to external services.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(all_checks)


@check.command(name="db")
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.pass_context
def db_check(ctx: click.Context, db_path: str | None) -> None:
    """🩺 Database integrity, schema version and search index (= `db check`)."""
    from postparse.cli.db import run_db_check

    if not run_db_check(resolve_db_path(ctx, db_path), config_path_from_ctx(ctx)):
        ctx.exit(1)


@check.command()
@click.option("--session", help="Session name or file (default: Settings.sessions_dir)")
@click.option(
    "--login",
    is_flag=True,
    help="Connect to Telegram and verify the session (may prompt for a code)",
)
@click.pass_context
def telegram(ctx: click.Context, session: str | None, login: bool) -> None:
    """📱 Telegram session file and credentials (`--login` verifies online).

    Examples:
        postparse check telegram
        postparse check telegram --login
    """
    settings = _settings(ctx)
    results = [telegram_status(settings, session=session)]
    print_result(results[0])
    if login and results[0].status != "fail":
        results.append(telegram_login(settings, _config(ctx), session))
        print_result(results[-1])
    _finish(ctx, results)


@check.command()
@click.option("--username", help="Instagram username (default: INSTAGRAM_USERNAME)")
@click.option("--session", help="Session file (default: <sessions_dir>/instagram_<username>)")
@click.option(
    "--login",
    is_flag=True,
    help=(
        "Verify the saved session; without a usable one log in with INSTAGRAM_PASSWORD "
        "(may prompt for a 2FA code). The only command that uses the password."
    ),
)
@click.pass_context
def instagram(ctx: click.Context, username: str | None, session: str | None, login: bool) -> None:
    """📸 Instagram session file and credentials (`--login` verifies online).

    Examples:
        postparse check instagram
        postparse check instagram --login
    """
    settings = _settings(ctx)
    results = [instagram_status(settings, username=username, session=session)]
    print_result(results[0])
    if login and results[0].status != "fail":
        results.append(instagram_login(settings, _config(ctx), username, session))
        print_result(results[-1])
    _finish(ctx, results)


def _transcription_options(ctx: click.Context) -> TranscriptionOptions:
    from postparse.media.options import TranscriptionOptions

    try:
        return TranscriptionOptions.from_config(_config(ctx))
    except ValueError as exc:
        raise click.ClickException(f"Invalid [transcription] config: {exc}") from exc


@check.command()
@click.option(
    "--backend",
    type=click.Choice(["local", "api"]),
    help="Backend to check (default: transcription.backend)",
)
@click.option(
    "--load-model", is_flag=True, help="Load the faster-whisper model (downloads it on first use)"
)
@click.pass_context
def transcription(ctx: click.Context, backend: str | None, load_model: bool) -> None:
    """🎙️ Transcription backend: faster-whisper / CUDA, or API endpoint reachability.

    Examples:
        postparse check transcription
        postparse check transcription --load-model
        postparse check transcription --backend api
    """
    result = transcription_status(
        _transcription_options(ctx), backend=backend, load_model=load_model
    )
    print_result(result)
    _finish(ctx, [result])


@check.command()
@click.option("--provider", help="Check only this provider (default: all configured)")
@click.option("--no-chat", is_flag=True, help="Only list models, skip the chat ping")
@click.option(
    "--timeout", type=float, default=10.0, show_default=True, help="Request timeout in seconds"
)
@click.option("--verbose", "-v", is_flag=True, hidden=True, help="Accepted for compatibility")
@click.pass_context
def llm(
    ctx: click.Context, provider: str | None, no_chat: bool, timeout: float, verbose: bool
) -> None:
    """🤖 LLM providers: model list, discovered model, chat ping and latency.

    Examples:
        postparse check llm
        postparse check llm --provider llama_cpp --timeout 30
    """
    result = llm_status(_config(ctx), provider=provider, chat=not no_chat, timeout=timeout)
    print_result(result)
    _finish(ctx, [result])


def _not_configured(result: CheckResult) -> bool:
    """True when a collector check failed only because nothing is set up."""
    return result.status == "fail" and not result.configured


@check.command(name="all")
@click.option("--login", is_flag=True, help="Also verify Telegram/Instagram sessions online")
@click.option("--skip-llm", is_flag=True, help="Skip the LLM provider check")
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.pass_context
def all_checks(
    ctx: click.Context, login: bool = False, skip_llm: bool = False, db_path: str | None = None
) -> None:
    """✅ Run all checks (no Telegram/Instagram network calls without --login).

    Telegram / Instagram are reported as skipped when neither credentials nor
    a session file exist.

    Examples:
        postparse check
        postparse check all --login
    """
    from postparse.cli.db import run_db_check

    console = get_console()
    settings = _settings(ctx)
    config = _config(ctx)
    results: list[CheckResult] = []

    console.print("[bold cyan]Database[/bold cyan]")
    db_ok = run_db_check(resolve_db_path(ctx, db_path), config_path_from_ctx(ctx))
    console.print()
    results.append(
        CheckResult("db", "ok" if db_ok else "fail", "passed" if db_ok else "problems found")
    )

    try:
        from postparse.media.options import TranscriptionOptions

        options = TranscriptionOptions.from_config(config)
        results.append(transcription_status(options))
    except ValueError as exc:
        results.append(CheckResult("transcription", "fail", f"invalid config: {exc}"))
    print_result(results[-1])

    tg = telegram_status(settings)
    if _not_configured(tg):
        tg.status, tg.summary = "skip", "not configured"
    results.append(tg)
    print_result(tg)
    if login and tg.status in ("ok", "warn"):
        results.append(telegram_login(settings, config, None))
        print_result(results[-1])

    ig = instagram_status(settings)
    if _not_configured(ig):
        ig.status, ig.summary = "skip", "not configured"
    results.append(ig)
    print_result(ig)
    if login and ig.status in ("ok", "warn"):
        results.append(instagram_login(settings, config, None, None))
        print_result(results[-1])

    if not skip_llm:
        results.append(llm_status(config))
        print_result(results[-1])

    summary = Table(
        title="Summary", show_header=True, header_style="bold cyan", title_justify="left"
    )
    summary.add_column("Check", style="cyan")
    summary.add_column("Status")
    summary.add_column("Details", overflow="fold")
    for result in results:
        style = _STYLE[result.status]
        summary.add_row(
            result.name,
            f"[{style}]{_ICON[result.status]} {result.status}[/{style}]",
            escape(result.summary),
        )
    console.print(summary)
    failed = [r.name for r in results if r.status == "fail"]
    if failed:
        print_error(f"Problems: {', '.join(failed)}")
    elif any(r.status == "warn" for r in results):
        print_warning("All checks passed with warnings")
    else:
        print_success("All checks passed")
    _finish(ctx, results)
