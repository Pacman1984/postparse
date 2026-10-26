"""Summarize commands: short LLM summaries of transcribed items.

Thin adapter over :class:`postparse.services.summarization.SummarizationService`.
Configuration: ``[summarization]`` (provider, max_input_chars, output_retries)
and the ``[llm]`` providers.

Example:
    $ postparse summarize run --limit 20
    $ postparse summarize run --provider llama_cpp --force
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
    load_config,
    print_info,
    print_success,
    print_warning,
)

if TYPE_CHECKING:
    from postparse.services.summarization import SummarizationReport, SummarizationService

logger = logging.getLogger(__name__)

_DB_OPTION_HELP = "Schema v2 database file (default: Settings.db_path)"


def _config_path(ctx: click.Context) -> str | None:
    return (ctx.obj or {}).get("config")


def _build_service(ctx: click.Context, db_path: str | None) -> SummarizationService:
    """Create the summarization service for the CLI context."""
    from postparse.config import get_settings
    from postparse.core.db import Database
    from postparse.services.summarization import SummarizationService

    settings = get_settings(_config_path(ctx))
    path = Path(db_path).resolve() if db_path else settings.db_path
    assert path is not None
    if not path.exists():
        raise click.ClickException(f"Database not found: {path} (run `postparse db migrate` first)")
    return SummarizationService(
        Database.open(path), settings, config=load_config(_config_path(ctx))
    )


def report_table(report: SummarizationReport) -> Table:
    """Render a summarization report."""
    table = Table(title="Summaries", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")
    rows: list[tuple[str, Any]] = [
        ("Provider / model", f"{report.provider or '-'} / {report.model or '-'}"),
        ("Due items", report.candidates),
        ("Summarized", report.summarized),
        ("Skipped: empty", report.skipped_empty),
        ("Errors (stay due)", report.errors),
        ("Duration", format_duration(report.duration_s)),
    ]
    if report.summarized:
        rows.append(("Avg latency", f"{report.latency_s / report.summarized:.1f}s"))
    for name, value in rows:
        table.add_row(name, str(value))
    return table


def run_summaries(
    ctx: click.Context,
    service: SummarizationService,
    *,
    limit: int | None,
    provider: str | None,
    force: bool,
    item_ids: list[int] | None = None,
) -> SummarizationReport:
    """Run the service with a progress bar and print the report."""
    from postparse.services.summarization import SummarizationProgress

    quiet = bool((ctx.obj or {}).get("quiet"))
    with create_progress() as progress:
        task = progress.add_task("Summarizing", total=None, visible=not quiet)

        def on_progress(update: SummarizationProgress) -> None:
            r = update.report
            progress.update(
                task,
                total=update.total,
                completed=update.handled,
                description=f"ok {r.summarized} · empty {r.skipped_empty} · err {r.errors}",
            )

        try:
            report = service.run(
                limit=limit,
                provider=provider,
                force=force,
                item_ids=item_ids,
                progress=on_progress,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    if not report.candidates:
        print_info("Nothing to summarize (no items with a new transcript).")
        return report
    get_console().print(report_table(report))
    for item_id, message in report.error_samples[:5]:
        print_warning(f"item {item_id}: {message}")
    if not report.errors:
        print_success(f"{report.summarized} summaries stored.")
    return report


@click.group()
def summarize() -> None:
    """📝 Summarize transcribed items with an LLM.

    Commands:
    - run: summarize items whose transcript is newer than their summary
    """


@summarize.command()
@click.option("--limit", type=click.IntRange(min=1), help="Maximum items")
@click.option("--provider", help="LLM provider (default: summarization.provider or llm default)")
@click.option("--force", is_flag=True, help="Re-summarize items that already have a summary")
@click.option("--item", "item_ids", type=int, multiple=True, help="Only this item (repeatable)")
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.pass_context
def run(
    ctx: click.Context,
    limit: int | None,
    provider: str | None,
    force: bool,
    item_ids: tuple[int, ...],
    db_path: str | None,
) -> None:
    """Summarize items with a transcript and no summary newer than it.

    Examples:
        postparse summarize run --limit 20
        postparse summarize run --provider llama_cpp
        postparse summarize run --force --item 42
    """
    service = _build_service(ctx, db_path)
    report = run_summaries(
        ctx,
        service,
        limit=limit,
        provider=provider,
        force=force,
        item_ids=list(item_ids) or None,
    )
    if report.errors and not report.summarized:
        ctx.exit(1)
