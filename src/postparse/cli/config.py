"""Config commands: show, validate and list environment variables.

- ``show``: resolved paths (``Settings``) and the config sections, secrets masked
- ``validate``: paths writable, database present / migrated, LLM providers,
  taxonomies, transcription / summarization / enrichment options
- ``env``: expected environment variables and whether they are set (never values)

Example:
    $ postparse config show --section transcription
    $ postparse config validate --fix
    $ postparse config env
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import rich_click as click
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from postparse.cli.utils import (
    config_path_from_ctx,
    get_console,
    legacy_db_key_warning,
    print_error,
    print_info,
    print_success,
    print_warning,
)

SECTIONS = (
    "paths",
    "database",
    "llm",
    "api",
    "telegram",
    "instagram",
    "transcription",
    "summarization",
    "enrichment",
    "classification",
)

_SECRET_MARKERS = ("key", "secret", "password", "token", "hash")

#: Environment variables PostParse reads, by area.
ENV_VARS: dict[str, list[tuple[str, str]]] = {
    "Telegram": [
        ("TELEGRAM_API_ID", "required for extract/check telegram"),
        ("TELEGRAM_API_HASH", "required for extract/check telegram"),
        ("TELEGRAM_PHONE", "optional, used for the first login"),
    ],
    "Instagram": [
        ("INSTAGRAM_USERNAME", "required for extract/check instagram"),
        ("INSTAGRAM_PASSWORD", "optional when a valid session file exists"),
    ],
    "LLM": [
        ("OPENAI_API_KEY", "openai / lm_studio providers, transcription api backend"),
        ("ANTHROPIC_API_KEY", "anthropic provider"),
    ],
    "Paths": [
        ("POSTPARSE_DATA_DIR", "overrides [paths] data_dir"),
        ("POSTPARSE_DB_PATH", "overrides [database] db_path"),
        ("POSTPARSE_SESSIONS_DIR", "overrides [paths] sessions_dir"),
        ("POSTPARSE_DOWNLOADS_DIR", "overrides [paths] downloads_dir"),
        ("POSTPARSE_TMP_DIR", "overrides [paths] tmp_dir"),
    ],
    "API": [
        ("JWT_SECRET_KEY", "API authentication secret"),
    ],
}


@click.group()
def config() -> None:
    """⚙️  View and validate configuration."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_secret(key: str) -> bool:
    lowered = key.lower()
    if lowered.endswith("_env"):  # names of env vars, not secrets
        return False
    return any(marker in lowered for marker in _SECRET_MARKERS)


def mask_secrets(value: Any, key: str = "") -> Any:
    """Return ``value`` with secret-looking keys replaced by ``***``.

    Args:
        value: Config value (mappings and lists are processed recursively).
        key: Key of ``value`` in its parent mapping.

    Returns:
        Masked copy.
    """
    if isinstance(value, Mapping):
        return {k: mask_secrets(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_secrets(v, key) for v in value]
    if key and _is_secret(key) and value not in (None, ""):
        return "***"
    return value


def _load_manager(ctx: click.Context) -> Any:
    """Return the ``ConfigManager`` (``click.ClickException`` if no file exists)."""
    from postparse.core.utils.config import ConfigManager

    try:
        return ConfigManager(config_path_from_ctx(ctx))
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc


def _settings_dict(ctx: click.Context) -> dict[str, str]:
    from postparse.config import get_settings

    settings = get_settings(config_path_from_ctx(ctx))
    return {
        name: str(getattr(settings, name))
        for name in ("data_dir", "db_path", "sessions_dir", "downloads_dir", "tmp_dir")
    }


def _options_dict(factory: Any, manager: Any) -> dict[str, Any]:
    """Return the effective options of an options dataclass, or the error."""
    try:
        return asdict(factory.from_config(manager))
    except ValueError as exc:
        return {"error": str(exc)}


def _classification_dict(manager: Any) -> dict[str, Any]:
    from postparse.classification.taxonomy import load_taxonomies

    section = dict(manager.get_section("classification") or {})
    result: dict[str, Any] = {
        k: v for k, v in section.items() if k not in ("taxonomies", "classes")
    }
    try:
        specs = load_taxonomies(section)
        result["taxonomies"] = [
            {"name": s.name, "mode": s.mode, "labels": list(s.label_names)} for s in specs.values()
        ]
    except ValueError as exc:
        result["taxonomies"] = {"error": str(exc)}
    return result


def build_config_view(ctx: click.Context, manager: Any, section: str | None) -> dict[str, Any]:
    """Collect the (masked) configuration for ``config show``."""
    from postparse.enrichment.options import EnrichmentOptions
    from postparse.media.options import TranscriptionOptions

    view: dict[str, Any] = {}
    wanted = (section,) if section else SECTIONS
    for name in wanted:
        if name == "paths":
            view["paths"] = {"config_file": str(manager.config_path), **_settings_dict(ctx)}
        elif name == "database":
            raw = dict(manager.get_section("database") or {})
            view["database"] = {"db_path (effective)": _settings_dict(ctx)["db_path"], **raw}
            if legacy_db_key_warning(config_path_from_ctx(ctx)):
                view["database"]["note"] = "default_db_path / path are schema v1 keys (ignored)"
        elif name == "transcription":
            view["transcription"] = _options_dict(TranscriptionOptions, manager)
        elif name == "enrichment":
            view["enrichment"] = _options_dict(EnrichmentOptions, manager)
        elif name == "classification":
            view["classification"] = _classification_dict(manager)
        else:
            view[name] = dict(manager.get_section(name) or {})
    return mask_secrets(view)


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@config.command()
@click.option("--section", type=click.Choice(SECTIONS), help="Show one section")
@click.option(
    "--format", "fmt", type=click.Choice(["text", "json"]), default="text", help="Output format"
)
@click.pass_context
def show(ctx: click.Context, section: str | None, fmt: str) -> None:
    """📄 Display resolved paths and configuration (secrets masked).

    Examples:
        postparse config show
        postparse config show --section transcription --format json
    """
    manager = _load_manager(ctx)
    view = build_config_view(ctx, manager, section)
    text = json.dumps(view, indent=2, ensure_ascii=False, default=str)
    if fmt == "json":
        click.echo(text)
        return
    console = get_console()
    print_info(f"Configuration file: {manager.config_path}")
    console.print(
        Panel(
            Syntax(text, "json", theme="monokai", word_wrap=True),
            title="Configuration",
            border_style="cyan",
        )
    )


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def _add(results: list[dict[str, str]], check: str, status: str, message: str) -> None:
    results.append({"check": check, "status": status, "message": message})


def _writable_dir(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK)


def _validate_paths(ctx: click.Context, results: list[dict[str, str]], fix: bool) -> None:
    """Check that data directories exist (or can be created) and are writable."""
    paths = _settings_dict(ctx)
    dirs = {
        name: Path(paths[name]) for name in ("data_dir", "sessions_dir", "downloads_dir", "tmp_dir")
    }
    dirs["db_path (parent)"] = Path(paths["db_path"]).parent
    for name, path in dirs.items():
        if not path.exists() and fix:
            try:
                path.mkdir(parents=True, exist_ok=True)
                _add(results, f"Path {name}", "pass", f"Created {path}")
                continue
            except OSError as exc:
                _add(results, f"Path {name}", "fail", f"Cannot create {path}: {exc}")
                continue
        if not path.exists():
            _add(results, f"Path {name}", "warning", f"{path} does not exist (use --fix)")
        elif _writable_dir(path):
            _add(results, f"Path {name}", "pass", f"{path} is writable")
        else:
            _add(results, f"Path {name}", "fail", f"{path} is not a writable directory")


def _validate_database(ctx: click.Context, results: list[dict[str, str]]) -> None:
    """Check the schema v2 database file and the legacy key."""
    from postparse.core.db import connect, latest_version

    warning = legacy_db_key_warning(config_path_from_ctx(ctx))
    if warning:
        _add(results, "Legacy database key", "warning", warning)
    db_path = Path(_settings_dict(ctx)["db_path"])
    if not db_path.is_file():
        _add(
            results,
            "Database",
            "warning",
            f"{db_path} not found (run `postparse db migrate` or `db migrate-v1`)",
        )
        return
    try:
        conn = connect(db_path)
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - report unreadable files
        _add(results, "Database", "fail", f"{db_path}: {exc}")
        return
    latest = latest_version()
    if version < latest:
        _add(
            results,
            "Database",
            "warning",
            f"schema v{version} < v{latest} (run `postparse db migrate`)",
        )
    else:
        _add(results, "Database", "pass", f"{db_path} (schema v{version})")


def _validate_llm(manager: Any, results: list[dict[str, str]]) -> set[str]:
    """Validate ``[llm]``; return the configured provider names (lower case)."""
    from postparse.llm.config import LLMConfig

    if not manager.get_section("llm"):
        _add(
            results,
            "LLM providers",
            "warning",
            "No [llm] section: classification and summaries are unavailable",
        )
        return set()
    try:
        llm = LLMConfig.from_config_manager(manager)
    except (ValueError, TypeError) as exc:
        _add(results, "LLM providers", "fail", f"Invalid [llm] config: {exc}")
        return set()
    _add(
        results,
        "LLM providers",
        "pass",
        f"{len(llm.providers)} provider(s), default {llm.default_provider}",
    )
    for provider in llm.providers:
        where = provider.api_base or "cloud API"
        if not provider.api_base and not provider.api_key:
            _add(
                results,
                f"Provider {provider.name}",
                "warning",
                f"{provider.model} @ {where}: no API key configured",
            )
        else:
            _add(results, f"Provider {provider.name}", "pass", f"{provider.model} @ {where}")
    return {p.name.lower() for p in llm.providers}


def _validate_features(manager: Any, results: list[dict[str, str]], providers: set[str]) -> None:
    """Validate taxonomies and the transcription / summarization / enrichment options."""
    import importlib.util

    from postparse.classification.taxonomy import load_taxonomies
    from postparse.enrichment.options import EnrichmentOptions
    from postparse.media.options import TranscriptionOptions

    try:
        specs = load_taxonomies(manager)
        if specs:
            names = ", ".join(
                f"{s.name} ({len(s.labels)} labels, {s.mode})" for s in specs.values()
            )
            _add(results, "Taxonomies", "pass", names)
        else:
            _add(results, "Taxonomies", "warning", "No taxonomies configured in [classification]")
    except ValueError as exc:
        _add(results, "Taxonomies", "fail", str(exc))

    try:
        options = TranscriptionOptions.from_config(manager)
        message = f"backend {options.backend}"
        status = "pass"
        if options.backend == "local":
            message += f", model {options.local.model}, device {options.local.device}"
            if importlib.util.find_spec("faster_whisper") is None:
                status, message = "warning", message + "; faster-whisper not installed"
        else:
            message += f", endpoint {options.api.base_url or 'api.openai.com'}"
        _add(results, "Transcription", status, message)
    except ValueError as exc:
        _add(results, "Transcription", "fail", str(exc))

    section = manager.get_section("summarization") or {}
    provider = str(section.get("provider") or "").strip()
    if provider and providers and provider.lower() not in providers:
        _add(results, "Summarization", "fail", f"provider {provider!r} is not in [[llm.providers]]")
    else:
        _add(results, "Summarization", "pass", f"provider {provider or '(llm default)'}")

    try:
        enrichment = EnrichmentOptions.from_config(manager)
        _add(
            results,
            "Enrichment",
            "pass",
            f"concurrency {enrichment.concurrency}, timeout {enrichment.timeout:g}s",
        )
    except ValueError as exc:
        _add(results, "Enrichment", "fail", str(exc))


@config.command()
@click.option("--fix", is_flag=True, help="Create missing data directories")
@click.pass_context
def validate(ctx: click.Context, fix: bool) -> None:
    """✅ Validate configuration, paths and feature settings.

    Exit code 1 when a check fails (warnings are allowed).
    """
    console = get_console()
    results: list[dict[str, str]] = []
    try:
        manager = _load_manager(ctx)
    except click.ClickException as exc:
        _add(results, "Config file", "fail", exc.message)
        display_validation_results(console, results)
        ctx.exit(1)
        return
    _add(results, "Config file", "pass", f"Found at {manager.config_path}")

    _validate_paths(ctx, results, fix)
    _validate_database(ctx, results)
    providers = _validate_llm(manager, results)
    _validate_features(manager, results, providers)

    port = manager.get("api.port", default=8000)
    if isinstance(port, int) and 1024 <= port <= 65535:
        _add(results, "API port", "pass", f"Port {port} is valid")
    else:
        _add(results, "API port", "fail", f"Port {port} is invalid. Use 1024-65535.")

    display_validation_results(console, results)
    passed = sum(1 for r in results if r["status"] == "pass")
    warnings = sum(1 for r in results if r["status"] == "warning")
    failed = sum(1 for r in results if r["status"] == "fail")
    console.print()
    if failed:
        print_error(f"Validation failed: {passed} passed, {warnings} warnings, {failed} failed")
        ctx.exit(1)
    elif warnings:
        print_warning(f"Validation completed with warnings: {passed} passed, {warnings} warnings")
    else:
        print_success(f"Validation passed: {passed} checks passed")


def display_validation_results(console: Console, results: list[dict[str, str]]) -> None:
    """Display validation results in a table.

    Args:
        console: Rich console.
        results: ``{"check", "status" (pass/warning/fail), "message"}`` dicts.
    """
    table = Table(title="Validation Results", show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details", overflow="fold")
    labels = {"pass": "[green]✓ Pass[/green]", "warning": "[yellow]⚠ Warning[/yellow]"}
    for result in results:
        table.add_row(
            result["check"],
            labels.get(result["status"], "[red]✗ Fail[/red]"),
            escape(result["message"]),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# env
# ---------------------------------------------------------------------------


@config.command()
@click.pass_context
def env(ctx: click.Context) -> None:
    """📋 List expected environment variables and whether they are set (never values)."""
    console = get_console()
    loaded_file = os.getenv("_POSTPARSE_ENV_FILE")
    if loaded_file:
        print_success(f"Loaded environment from: [cyan]{escape(loaded_file)}[/cyan]")
    else:
        print_warning("No .env file loaded. Searched: config/.env, .env")
    console.print()

    groups = {name: list(rows) for name, rows in ENV_VARS.items()}
    try:
        from postparse.media.options import TranscriptionOptions

        api_env = TranscriptionOptions.from_config(_load_manager(ctx)).api.api_key_env
        if api_env and api_env not in {n for rows in groups.values() for n, _ in rows}:
            groups["LLM"].append((api_env, "transcription.api.api_key_env"))
    except (click.ClickException, ValueError):
        pass

    for category, rows in groups.items():
        table = Table(title=f"{category}", show_header=True, box=None, title_justify="left")
        table.add_column("Variable", style="cyan", width=26)
        table.add_column("Status", width=10)
        table.add_column("Used for", style="dim")
        for name, purpose in rows:
            is_set = bool((os.getenv(name) or "").strip())
            table.add_row(
                name, "[green]✓ set[/green]" if is_set else "[dim]✗ not set[/dim]", purpose
            )
        console.print(table)
        console.print()
    console.print("[dim]Current working directory:[/dim]")
    console.print(f"  {escape(str(Path.cwd()))}")
