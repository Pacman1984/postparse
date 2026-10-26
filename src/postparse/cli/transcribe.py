"""Transcribe commands: video transcripts for the schema v2 database.

Thin adapters over :class:`postparse.services.transcription.TranscriptionService`.

- ``run``: work through the transcription queue (throttled; re-fetches expired
  Instagram URLs with one login per run)
- ``status``: queue counts per source and status, next retries, totals

Exit codes (as ``extract``): 0 success, 1 error / ASR backend unavailable,
2 Instagram login required, 3 rate limited / suspected Instagram block,
130 interrupted.

Configuration: ``[transcription]`` (see :mod:`postparse.media.options`).

Example:
    $ postparse transcribe run --limit 50
    $ postparse transcribe run --backend api --no-refetch
    $ postparse transcribe run --item 123 --item 124
    $ postparse transcribe status
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import rich_click as click
from rich.table import Table

from postparse.cli.utils import (
    create_progress,
    format_duration,
    get_console,
    print_error,
    print_info,
    print_success,
    print_warning,
)

if TYPE_CHECKING:
    from postparse.services.transcription import TranscriptionReport, TranscriptionService

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_AUTH = 2
EXIT_RATE_LIMITED = 3
EXIT_INTERRUPTED = 130

_DB_OPTION_HELP = "Schema v2 database file (default: Settings.db_path)"

_REASONS = {
    "done": "completed",
    "rate_limited": "Instagram rate limit",
    "auth_required": "Instagram login required",
    "backend_unavailable": "ASR backend unavailable",
    "suspected_block": "suspected Instagram block",
    "interrupted": "interrupted",
}


def _config_path(ctx: click.Context) -> str | None:
    return (ctx.obj or {}).get("config")


def _load_config(ctx: click.Context) -> Any:
    from postparse.core.utils.config import get_config

    try:
        return get_config(_config_path(ctx))
    except FileNotFoundError:
        return None


def _build_service(
    ctx: click.Context, db_path: str | None, *, interactive: bool = False
) -> TranscriptionService:
    """Create the transcription service for ``--db`` / settings and the TOML config."""
    from postparse.config import get_settings
    from postparse.core.db import Database
    from postparse.services.transcription import TranscriptionService

    settings = get_settings(_config_path(ctx))
    path = Path(db_path).resolve() if db_path else settings.db_path
    assert path is not None
    try:
        return TranscriptionService(
            Database.open(path), settings, _load_config(ctx), interactive=interactive
        )
    except ValueError as exc:
        raise click.ClickException(f"Invalid [transcription] config: {exc}") from exc


def report_table(report: TranscriptionReport, title: str = "Transcription") -> Table:
    """Render a transcription report."""
    table = Table(title=title, show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")
    rows: list[tuple[str, Any]] = [
        ("Backend / model", f"{report.backend or '-'} / {report.model or '-'}"),
        ("Selected", report.candidates),
        ("Transcribed", report.transcribed),
        ("No audio / no speech", report.no_audio),
        ("Skipped", report.skipped),
        ("Failed (retried later)", report.failed),
    ]
    if report.deferred:
        rows.append(("Deferred (needs re-fetch)", report.deferred))
    rows += [
        ("Re-fetched posts", report.refetched),
        ("Audio transcribed", format_duration(report.audio_seconds)),
        ("ASR time", format_duration(report.transcribe_seconds)),
        ("Stopped", _REASONS.get(report.stopped_reason or "", "error")),
        ("Duration", format_duration(report.duration_s)),
    ]
    for name, value in rows:
        table.add_row(name, str(value))
    return table


def exit_code(report: TranscriptionReport) -> int:
    """Map a report to an exit code (printing the reason)."""
    if report.stopped_reason == "auth_required":
        print_error(report.error or "Instagram login required.")
        print_info("Run `postparse extract instagram` in a terminal to log in, then retry.")
        return EXIT_AUTH
    if report.stopped_reason == "rate_limited":
        print_warning(report.error or "Rate limited; retry later.")
        print_info("Everything transcribed before the limit was hit has been kept.")
        return EXIT_RATE_LIMITED
    if report.stopped_reason == "suspected_block":
        print_warning(report.error or "Instagram re-fetches keep failing.")
        print_info(
            "Instagram is probably soft-blocking this session. Wait a few hours before "
            "the next run; nothing committed so far is lost."
        )
        return EXIT_RATE_LIMITED
    if report.stopped_reason == "backend_unavailable":
        print_error(report.error or "Transcription backend unavailable.")
        return EXIT_ERROR
    return EXIT_OK


def run_transcription(
    ctx: click.Context,
    service: TranscriptionService,
    *,
    source: str | None,
    limit: int | None,
    backend: str | None,
    refetch: bool,
    item_ids: list[int] | None,
    title: str = "Transcription",
) -> tuple[TranscriptionReport | None, int]:
    """Run the service with a progress bar; return ``(report, exit code)``."""
    from postparse.services.transcription import TranscriptionProgress

    quiet = bool((ctx.obj or {}).get("quiet"))
    try:
        with create_progress() as progress:
            task = progress.add_task("Transcribing", total=None, visible=not quiet)

            def on_progress(update: TranscriptionProgress) -> None:
                r = update.report
                progress.update(
                    task,
                    total=update.total,
                    completed=update.index,
                    description=(
                        f"ok {r.transcribed} · no audio {r.no_audio} · skip {r.skipped}"
                        f" · fail {r.failed}"
                    ),
                )

            report = service.run(
                source=source,  # type: ignore[arg-type]
                limit=limit,
                backend=backend,  # type: ignore[arg-type]
                refetch=refetch,
                item_ids=item_ids,
                progress=on_progress,
            )
    except KeyboardInterrupt:
        print_warning("Interrupted; media transcribed so far are kept, scratch files removed.")
        return None, EXIT_INTERRUPTED
    get_console().print(report_table(report, title))
    for message in report.errors[:5]:
        print_warning(message)
    code = exit_code(report)
    if code == EXIT_OK:
        print_success(f"Transcription completed ({report.transcribed} transcribed).")
    return report, code


@click.group()
def transcribe() -> None:
    """🎙️ Transcribe saved videos (local faster-whisper or an OpenAI-compatible API).

    Commands:
    - run: work through the transcription queue
    - status: queue counts, next retries and totals
    """


@transcribe.command()
@click.option("--source", type=click.Choice(["instagram", "telegram", "all"]),
              default="instagram", show_default=True, help="Restrict to one source")
@click.option("--limit", type=click.IntRange(min=1),
              help="Maximum media this run (default: transcription.limit = 50)")
@click.option("--backend", type=click.Choice(["local", "api"]),
              help="ASR backend (default: transcription.backend)")
@click.option("--no-refetch", is_flag=True,
              help="Never re-fetch Instagram posts; media without a fresh URL stay pending")
@click.option("--item", "item_ids", type=int, multiple=True,
              help="Only media of this item id (repeatable; ignores retry backoff)")
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.option("--interactive/--no-interactive", default=False, show_default=True,
              help="Allow an Instagram 2FA prompt if a re-fetch needs a new login")
@click.pass_context
def run(ctx: click.Context, source: str, limit: int | None, backend: str | None,
        no_refetch: bool, item_ids: tuple[int, ...], db_path: str | None,
        interactive: bool) -> None:
    """Transcribe pending videos and store transcripts (no media files are kept).

    Videos whose stored URL is older than transcription.remote_url_max_age_hours
    are re-fetched from Instagram (throttled, 20-60 s apart). A rate limit or an
    invalid session stops the run cleanly; rerun later to continue.

    Examples:
        postparse transcribe run --limit 50
        postparse transcribe run --backend api
        postparse transcribe run --item 42
    """
    service = _build_service(ctx, db_path, interactive=interactive)
    _report, code = run_transcription(
        ctx, service,
        source=None if source == "all" else source,
        limit=limit, backend=backend, refetch=not no_refetch,
        item_ids=list(item_ids) or None,
    )
    if code:
        ctx.exit(code)


@transcribe.command()
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.pass_context
def status(ctx: click.Context, db_path: str | None) -> None:
    """Show the transcription queue per source and status.

    Examples:
        postparse transcribe status
    """
    service = _build_service(ctx, db_path)
    stats = service.status()
    console = get_console()
    counts: dict[tuple[str, str], int] = stats["counts"]
    statuses = ("pending", "failed", "transcribed", "no_audio", "skipped", "none")
    sources = sorted({s for s, _ in counts})
    table = Table(title="Transcription queue", show_header=True, header_style="bold cyan")
    table.add_column("Media status")
    for source in sources:
        table.add_column(source, justify="right")
    for name in statuses:
        table.add_row(name, *(str(counts.get((source, name), 0)) for source in sources))
    table.add_section()
    table.add_row("due now", *(str(stats["due"].get(s, 0)) for s in sources))
    table.add_row("gave up (max attempts)", *(str(stats["exhausted"].get(s, 0)) for s in sources))
    table.add_row("next retry", *((stats["next_attempt_at"].get(s) or "-") for s in sources))
    console.print(table)
    console.print(
        f"Transcripts: {stats['transcripts']} · audio transcribed: "
        f"{format_duration(stats['transcribed_seconds'])} · "
        f"max attempts: {stats['max_attempts']}"
    )
