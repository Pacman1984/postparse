"""Extract commands: collect Telegram / Instagram saved items into the schema v2 database.

Thin adapters over :class:`postparse.services.extraction.ExtractionService`.
Credentials come from the environment (``config/.env`` is loaded by the CLI):
``TELEGRAM_API_ID``, ``TELEGRAM_API_HASH``, ``TELEGRAM_PHONE`` and
``INSTAGRAM_USERNAME``, ``INSTAGRAM_PASSWORD``.

Exit codes: 0 success, 1 unexpected error, 2 login required, 3 rate limited.

Example:
    $ postparse extract telegram              # new messages only
    $ postparse extract telegram --full       # re-read everything
    $ postparse extract instagram --stop-after-known 20
    $ postparse extract instagram --refresh-dates --refresh-limit 50
    $ postparse extract all
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import rich_click as click
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from postparse.cli.utils import (
    format_duration,
    get_console,
    print_error,
    print_info,
    print_success,
    print_warning,
)

if TYPE_CHECKING:
    from postparse.collectors.base import ProgressEvent
    from postparse.services.extraction import ExtractionReport, ExtractionService

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_AUTH = 2
EXIT_RATE_LIMITED = 3

_DB_OPTION_HELP = "Schema v2 database file (default: Settings.db_path)"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_path(ctx: click.Context) -> str | None:
    return (ctx.obj or {}).get("config")


def _build_service(ctx: click.Context, db_path: str | None) -> ExtractionService:
    """Create the extraction service for ``--db`` / settings and the TOML config."""
    from postparse.config import get_settings
    from postparse.core.db import Database
    from postparse.core.utils.config import get_config
    from postparse.services.extraction import ExtractionService

    settings = get_settings(_config_path(ctx))
    path = Path(db_path).resolve() if db_path else settings.db_path
    assert path is not None
    try:
        config: Any = get_config(_config_path(ctx))
    except FileNotFoundError:
        config = None
    return ExtractionService(Database.open(path), settings, config)


class _ProgressView:
    """Rich spinner with live counters, started lazily on the first event.

    Starting lazily keeps login prompts (Telegram code, Instagram 2FA) readable.
    """

    def __init__(self, label: str) -> None:
        self.label = label
        self.progress: Progress | None = None
        self.task: Any = None

    def __call__(self, event: ProgressEvent) -> None:
        if self.progress is None:
            self.progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                TextColumn("{task.fields[counts]}"),
                TimeElapsedColumn(),
                console=get_console(),
                transient=True,
            )
            self.progress.start()
            self.task = self.progress.add_task(self.label, counts="")
        phase = "refreshing dates" if event.phase == "refresh_dates" else "seen"
        counts = (
            f"{phase} {event.processed}{'/' + str(event.total) if event.total else ''} · "
            f"new {event.new} · updated {event.updated}"
        )
        if event.known_skipped:
            counts += f" · known {event.known_skipped}"
        self.progress.update(self.task, counts=counts)

    def stop(self) -> None:
        if self.progress is not None:
            self.progress.stop()
            self.progress = None


_REASONS = {
    "end_of_feed": "reached the end",
    "early_stop": "stopped at known posts",
    "limit": "limit reached",
    "rate_limited": "rate limited",
    "auth_required": "login required",
}


def _print_report(report: ExtractionReport, title: str) -> None:
    """Print the summary table of a report."""
    console = get_console()
    table = Table(title=title, show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")
    table.add_row("New", str(report.new))
    table.add_row("Updated", str(report.updated))
    if report.source == "instagram":
        table.add_row("Known (skipped)", str(report.known_skipped))
        if report.dates_refreshed:
            table.add_row("Dates refreshed", str(report.dates_refreshed))
    else:
        table.add_row("Media downloaded", str(report.media_downloaded))
    table.add_row("Batches committed", str(report.batches_committed))
    if report.last_external_id:
        table.add_row("Last stored", report.last_external_id)
    table.add_row("Stopped", _REASONS.get(report.stopped_reason or "", "error"))
    table.add_row("Duration", format_duration(report.duration_s))
    item_errors = [e for e in report.errors if e != report.error]
    if item_errors:
        table.add_row("Item errors", str(len(item_errors)))
    console.print()
    console.print(table)
    for message in item_errors[:10]:
        print_warning(message)


def _exit_code(report: ExtractionReport) -> int:
    """Map a report to the command's exit code (and print the reason)."""
    if report.stopped_reason == "auth_required":
        print_error(report.error or "Login required.")
        return EXIT_AUTH
    if report.stopped_reason == "rate_limited":
        print_warning(report.error or "Rate limited; retry later.")
        print_info("Everything committed before the limit was hit has been kept.")
        return EXIT_RATE_LIMITED
    print_success(f"{report.source.capitalize()} extraction completed.")
    return EXIT_OK


def _run(
    ctx: click.Context, label: str, title: str, call: Callable[[_ProgressView], ExtractionReport]
) -> int:
    """Run one extraction with progress display and summary; return the exit code."""
    view = _ProgressView(label)
    try:
        report = call(view)
    except click.exceptions.Exit:
        raise
    except Exception as exc:
        view.stop()
        logger.debug("Extraction failed", exc_info=True)
        print_error(f"{title} failed: {type(exc).__name__}: {exc}")
        if (ctx.obj or {}).get("verbose"):
            get_console().print_exception()
        return EXIT_ERROR
    view.stop()
    _print_report(report, title)
    return _exit_code(report)


def _telegram(
    ctx: click.Context, *, db_path: str | None, session: str | None, limit: int | None,
    full: bool, interactive: bool,
) -> int:
    service = _build_service(ctx, db_path)
    print_info("Collecting Telegram Saved Messages" + (" (full re-read)" if full else ""))
    return _run(
        ctx, "Telegram", "Telegram extraction",
        lambda view: service.telegram(
            limit=limit, full=full, interactive=interactive, session=session, progress=view
        ),
    )


def _instagram(
    ctx: click.Context, *, db_path: str | None, username: str | None, session: str | None,
    limit: int | None, stop_after_known: int | None, batch_size: int, refresh_dates: bool,
    refresh_limit: int | None, interactive: bool,
) -> int:
    service = _build_service(ctx, db_path)
    mode = "full walk" if stop_after_known is None else f"stop after {stop_after_known} known"
    print_info(f"Collecting saved Instagram posts ({mode})")
    return _run(
        ctx, "Instagram", "Instagram extraction",
        lambda view: service.instagram(
            limit=limit, stop_after_known=stop_after_known, batch_size=batch_size,
            refresh_dates=refresh_dates, interactive=interactive, session=session,
            progress=view, username=username, refresh_limit=refresh_limit,
        ),
    )


def _stop_after(force: bool, stop_after_known: int) -> int | None:
    return None if force or stop_after_known <= 0 else stop_after_known


_interactive_option = click.option(
    "--interactive/--no-interactive",
    default=True,
    show_default=True,
    help="Allow login prompts (Telegram code / 2FA, Instagram 2FA code) in the terminal.",
)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@click.group(invoke_without_command=True)
@click.pass_context
def extract(ctx: click.Context) -> None:
    """📥 Extract saved items from Telegram and Instagram (schema v2 database).

    Runs 'extract all' by default if no platform is specified.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(all_platforms)


@extract.command()
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.option(
    "--session",
    help="Session file path or name (default: <sessions_dir>/telegram.session, "
    "falling back to data/cache/telegram_session.session).",
)
@click.option("--limit", type=click.IntRange(min=1), help="Maximum messages to process.")
@click.option("--full", is_flag=True, help="Re-read all saved messages and update stored ones.")
@click.option("--force", is_flag=True, help="Alias for --full.")
@_interactive_option
@click.pass_context
def telegram(
    ctx: click.Context, db_path: str | None, session: str | None, limit: int | None,
    full: bool, force: bool, interactive: bool,
) -> None:
    """Collect Telegram Saved Messages (only new ones unless --full).

    Credentials: TELEGRAM_API_ID, TELEGRAM_API_HASH (and optionally
    TELEGRAM_PHONE) from the environment or config/.env.

    Examples:
        postparse extract telegram
        postparse extract telegram --limit 100
        postparse extract telegram --full

    Note:
        On the first run Telegram sends a login code (and asks for your 2FA
        password if set); enter them in this terminal.
    """
    code = _telegram(
        ctx, db_path=db_path, session=session, limit=limit, full=full or force,
        interactive=interactive,
    )
    if code:
        ctx.exit(code)


@extract.command()
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.option(
    "--username", envvar="INSTAGRAM_USERNAME",
    help="Instagram username (default: INSTAGRAM_USERNAME).",
)
@click.option(
    "--session",
    help="Session file path (default: <sessions_dir>/instagram_<username>, "
    "falling back to ./instagram_session).",
)
@click.option("--limit", type=click.IntRange(min=1), help="Maximum posts to store.")
@click.option(
    "--stop-after-known", type=int, default=20, show_default=True,
    help="Stop after N consecutive already stored posts (0 = walk the whole feed).",
)
@click.option(
    "--force", is_flag=True,
    help="Walk the whole saved feed and update known posts too.",
)
@click.option(
    "--batch-size", type=click.IntRange(min=1), default=25, show_default=True,
    help="Posts per database transaction.",
)
@click.option(
    "--refresh-dates", is_flag=True,
    help="Afterwards re-fetch publication dates of posts migrated from schema v1.",
)
@click.option(
    "--refresh-limit", type=click.IntRange(min=1),
    help="Maximum posts for --refresh-dates (default: all unverified).",
)
@_interactive_option
@click.pass_context
def instagram(
    ctx: click.Context, db_path: str | None, username: str | None, session: str | None,
    limit: int | None, stop_after_known: int, force: bool, batch_size: int,
    refresh_dates: bool, refresh_limit: int | None, interactive: bool,
) -> None:
    """Collect saved Instagram posts (newest first, stops at known posts).

    Credentials: INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD from the environment
    or config/.env (the password is only needed when the session is invalid).

    Examples:
        postparse extract instagram
        postparse extract instagram --limit 50
        postparse extract instagram --force
        postparse extract instagram --refresh-dates --refresh-limit 100

    Note:
        New posts are throttled (several seconds each). If Instagram asks for a
        confirmation, confirm the login in the Instagram app and retry.
    """
    code = _instagram(
        ctx, db_path=db_path, username=username, session=session, limit=limit,
        stop_after_known=_stop_after(force, stop_after_known), batch_size=batch_size,
        refresh_dates=refresh_dates, refresh_limit=refresh_limit, interactive=interactive,
    )
    if code:
        ctx.exit(code)


@extract.command(name="all")
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.option("--limit", type=click.IntRange(min=1), help="Maximum items per platform.")
@click.option(
    "--force", is_flag=True,
    help="Telegram: re-read everything; Instagram: walk the whole feed.",
)
@_interactive_option
@click.pass_context
def all_platforms(
    ctx: click.Context, db_path: str | None = None, limit: int | None = None,
    force: bool = False, interactive: bool = True,
) -> None:
    """Extract from every platform whose credentials are configured.

    Telegram runs when TELEGRAM_API_ID/TELEGRAM_API_HASH are set, Instagram
    when INSTAGRAM_USERNAME is set. The exit code is the most severe one of
    the platforms (3 rate limited > 2 login required > 1 error).

    Examples:
        postparse extract all
        postparse extract all --limit 100
        postparse extract
    """
    console = get_console()
    codes: dict[str, int] = {}
    if os.getenv("TELEGRAM_API_ID") and os.getenv("TELEGRAM_API_HASH"):
        codes["telegram"] = _telegram(
            ctx, db_path=db_path, session=None, limit=limit, full=force,
            interactive=interactive,
        )
    else:
        print_warning("Skipping Telegram (set TELEGRAM_API_ID and TELEGRAM_API_HASH).")
    console.print()
    if os.getenv("INSTAGRAM_USERNAME"):
        codes["instagram"] = _instagram(
            ctx, db_path=db_path, username=None, session=None, limit=limit,
            stop_after_known=_stop_after(force, 20), batch_size=25, refresh_dates=False,
            refresh_limit=None, interactive=interactive,
        )
    else:
        print_warning("Skipping Instagram (set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD).")
    console.print()
    if not codes:
        print_warning("No platform configured; nothing extracted.")
        return
    failed = [name for name, code in codes.items() if code]
    if failed:
        print_warning(f"Problems with: {', '.join(failed)}")
        severity = {EXIT_RATE_LIMITED: 3, EXIT_AUTH: 2, EXIT_ERROR: 1}
        ctx.exit(max(codes.values(), key=lambda c: severity.get(c, 0)))
    print_success(f"Extraction completed for {len(codes)} platform(s).")
