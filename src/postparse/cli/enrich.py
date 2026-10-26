"""Enrich commands: fetch the pages, documents, videos and posts that items link to.

Thin adapters over :class:`postparse.services.enrichment.EnrichmentService`
(schema v2 database).

- ``run``: fetch due links (never-fetched, legacy v1 texts, due retries)
- ``status``: links per fetcher/status and domain, due retries
- ``scrape``: deprecated alias of ``run``
- ``urls``: deprecated no-op (links are extracted when items are stored)

Exit codes: 0 success, 1 error, 130 interrupted.

Configuration: ``[enrichment]`` (see :mod:`postparse.enrichment.options`).

Example:
    $ postparse enrich run --limit 200
    $ postparse enrich run --source telegram --domain youtube.com
    $ postparse enrich run --force --domain example.org
    $ postparse enrich status
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
    print_info,
    print_success,
    print_warning,
)

if TYPE_CHECKING:
    from postparse.services.enrichment import EnrichmentReport, EnrichmentService

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INTERRUPTED = 130

_DB_OPTION_HELP = "Schema v2 database file (default: Settings.db_path)"
_STATUSES = ("ok", "error", "skipped", "legacy", "never")


def _config_path(ctx: click.Context) -> str | None:
    return (ctx.obj or {}).get("config")


def _load_config(ctx: click.Context) -> Any:
    from postparse.core.utils.config import get_config

    try:
        return get_config(_config_path(ctx))
    except FileNotFoundError:
        return None


def _build_service(ctx: click.Context, db_path: str | None) -> EnrichmentService:
    """Create the enrichment service for ``--db`` / settings and the TOML config."""
    from postparse.config import get_settings
    from postparse.core.db import Database
    from postparse.services.enrichment import EnrichmentService

    settings = get_settings(_config_path(ctx))
    path = Path(db_path).resolve() if db_path else settings.db_path
    assert path is not None
    try:
        return EnrichmentService(Database.open(path), settings, _load_config(ctx))
    except ValueError as exc:
        raise click.ClickException(f"Invalid [enrichment] config: {exc}") from exc


def report_table(report: EnrichmentReport) -> Table:
    """Render an enrichment report (totals and per-fetcher counts)."""
    table = Table(title="Enrichment", show_header=True)
    table.add_column("Fetcher", style="cyan")
    for status in ("ok", "error", "skipped"):
        table.add_column(status, justify="right")
    for fetcher in sorted(report.by_fetcher):
        counts = report.by_fetcher[fetcher]
        table.add_row(fetcher, *(str(counts.get(s, 0)) for s in ("ok", "error", "skipped")))
    table.add_section()
    table.add_row(
        "total", str(report.ok), str(report.errors_count), str(report.skipped), style="bold"
    )
    return table


def _run(
    ctx: click.Context,
    *,
    source: str,
    limit: int | None,
    force: bool,
    refresh_legacy: bool,
    domains: tuple[str, ...],
    db_path: str | None,
) -> None:
    from postparse.services.enrichment import EnrichmentProgress

    service = _build_service(ctx, db_path)
    quiet = bool((ctx.obj or {}).get("quiet"))
    try:
        with create_progress() as progress:
            task = progress.add_task("Enriching links", total=None, visible=not quiet)

            def on_progress(update: EnrichmentProgress) -> None:
                r = update.report
                progress.update(
                    task,
                    total=update.total,
                    completed=update.index,
                    description=f"ok {r.ok} · error {r.errors_count} · skipped {r.skipped}",
                )

            report = service.run(
                source=source,  # type: ignore[arg-type]
                limit=limit,
                force=force,
                refresh_legacy=refresh_legacy,
                domains=list(domains) or None,
                progress=on_progress,
            )
    except KeyboardInterrupt:
        print_warning("Interrupted; links fetched so far are stored.")
        ctx.exit(EXIT_INTERRUPTED)
        return
    console = get_console()
    if not report.candidates:
        print_info("No links need a fetch.")
        return
    console.print(report_table(report))
    console.print(
        f"Selected {report.candidates} · legacy texts replaced {report.legacy_refreshed} · "
        f"legacy expanded texts removed {report.legacy_texts_removed} · "
        f"search docs refreshed {report.items_refreshed} · "
        f"{format_duration(report.duration_s)}"
    )
    for message in report.errors[:5]:
        print_warning(message)
    print_success(f"Enrichment completed ({report.ok} links fetched).")


_RUN_OPTIONS = [
    click.option(
        "--source",
        type=click.Choice(["all", "telegram", "instagram"]),
        default="all",
        show_default=True,
        help="Only links of items from this source",
    ),
    click.option("--limit", type=click.IntRange(min=1), help="Maximum links this run"),
    click.option(
        "--force",
        is_flag=True,
        help="Refetch every link in scope (ignores earlier results and backoff)",
    ),
    click.option(
        "--no-legacy",
        is_flag=True,
        help="Do not re-enrich links whose only text was migrated from v1",
    ),
    click.option(
        "--domain",
        "domains",
        multiple=True,
        help="Only links on this domain (repeatable, e.g. youtube.com)",
    ),
    click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP),
]


def _run_options(func: Any) -> Any:
    for option in reversed(_RUN_OPTIONS):
        func = option(func)
    return func


@click.group()
def enrich() -> None:
    """🔗 Fetch linked pages, documents, YouTube videos and X posts.

    Commands:
    - run: fetch due links (new, legacy v1 texts, due retries)
    - status: links per fetcher/status and domain
    """


@enrich.command()
@_run_options
@click.pass_context
def run(
    ctx: click.Context,
    source: str,
    limit: int | None,
    force: bool,
    no_legacy: bool,
    domains: tuple[str, ...],
    db_path: str | None,
) -> None:
    """Fetch linked URLs and store their text for search.

    Instagram links are never fetched (skipped). Requests are throttled per
    domain (enrichment.min_domain_interval) and failed links are retried with
    exponential backoff on later runs.

    Examples:
        postparse enrich run --limit 200
        postparse enrich run --domain youtube.com --domain youtu.be
        postparse enrich run --no-legacy
    """
    _run(
        ctx,
        source=source,
        limit=limit,
        force=force,
        refresh_legacy=not no_legacy,
        domains=domains,
        db_path=db_path,
    )


@enrich.command()
@click.option(
    "--source",
    type=click.Choice(["all", "telegram", "instagram"]),
    default="all",
    show_default=True,
    help="Only links of items from this source",
)
@click.option(
    "--domains",
    "top",
    type=click.IntRange(min=1),
    default=15,
    show_default=True,
    help="Number of domains to list",
)
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.pass_context
def status(ctx: click.Context, source: str, top: int, db_path: str | None) -> None:
    """Show links per fetcher/status and domain, plus due retries.

    "legacy" links only have the text migrated from v1; "never" links have
    not been fetched at all.

    Examples:
        postparse enrich status
        postparse enrich status --source telegram --domains 30
    """
    service = _build_service(ctx, db_path)
    stats = service.status(source=source, top_domains=top)  # type: ignore[arg-type]
    console = get_console()
    by_state: dict[tuple[str, str], int] = stats["by_state"]
    table = Table(title=f"Links ({stats['links']})", show_header=True, header_style="bold cyan")
    table.add_column("Fetcher")
    table.add_column("Status")
    table.add_column("Links", justify="right")
    for (fetcher, state), count in sorted(by_state.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        table.add_row(fetcher, state, str(count))
    console.print(table)

    domains = Table(title="Top domains", show_header=True, header_style="bold cyan")
    domains.add_column("Domain")
    for name in _STATUSES:
        domains.add_column(name, justify="right")
    for domain, counts in stats["domains"]:
        domains.add_row(domain, *(str(counts.get(name, 0)) for name in _STATUSES))
    if stats["other_domains"]:
        domains.add_row(f"... {stats['other_domains']} more", *("" for _ in _STATUSES))
    console.print(domains)
    console.print(
        f"Due now: {stats['due']} · retries due: {stats['retry_due']} · "
        f"gave up (max {stats['max_attempts']} attempts): {stats['gave_up']} · "
        f"next retry: {stats['next_retry_at'] or '-'}"
    )


@enrich.command(deprecated=True)
@_run_options
@click.option("--timeout", type=float, hidden=True, help="Ignored (use enrichment.timeout)")
@click.pass_context
def scrape(
    ctx: click.Context,
    source: str,
    limit: int | None,
    force: bool,
    no_legacy: bool,
    domains: tuple[str, ...],
    db_path: str | None,
    timeout: float | None,
) -> None:
    """Deprecated alias of `postparse enrich run`."""
    print_warning("`enrich scrape` is deprecated; use `postparse enrich run`.")
    _run(
        ctx,
        source=source,
        limit=limit,
        force=force,
        refresh_legacy=not no_legacy,
        domains=domains,
        db_path=db_path,
    )


@enrich.command(
    deprecated=True, context_settings={"ignore_unknown_options": True, "allow_extra_args": True}
)
@click.pass_context
def urls(ctx: click.Context) -> None:
    """Deprecated no-op: links are extracted automatically when items are stored."""
    print_info(
        "`enrich urls` is no longer needed: links are extracted when items are stored. "
        "Use `postparse enrich run` to fetch them."
    )
