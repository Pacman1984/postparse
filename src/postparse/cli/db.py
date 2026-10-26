"""Database commands for the PostParse CLI (schema v2).

- ``stats``: counts per source/kind, tags, transcription queue, links,
  classification coverage, summaries, size and schema version
  (also available as the top-level ``postparse stats``)
- ``export``: items as JSON or CSV with the search filters
- ``migrate`` / ``check`` / ``reindex`` / ``migrate-v1``: maintenance

The database is ``--db`` or ``Settings.db_path`` (default ``data/postparse.db``).
The schema v1 key ``[database] default_db_path`` is ignored.

Example:
    $ postparse stats
    $ postparse db stats --detailed --top 20
    $ postparse db export items.json
    $ postparse db export recipes.csv --format csv --label topics:recipe
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import rich_click as click
from rich.panel import Panel
from rich.table import Table

from postparse.cli.filters import build_item_filter, filter_options
from postparse.cli.utils import (
    config_path_from_ctx,
    emit_json,
    format_duration,
    get_console,
    legacy_db_key_warning,
    open_database,
    print_error,
    print_info,
    print_success,
    print_warning,
    resolve_db_path,
)

if TYPE_CHECKING:
    from postparse.services.stats import DatabaseStats

_DB_OPTION_HELP = "Schema v2 database file (default: Settings.db_path)"


@click.group()
def db() -> None:
    """💾 Database statistics, exports and maintenance (schema v2)."""


def _human_size(size: int) -> str:
    """Format a byte count."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:,.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"  # pragma: no cover


def _max_attempts(ctx: click.Context) -> int:
    """Return ``[transcription] max_attempts`` (default 5)."""
    try:
        from postparse.core.utils.config import ConfigManager
        from postparse.media.options import TranscriptionOptions

        return TranscriptionOptions.from_config(
            ConfigManager(config_path_from_ctx(ctx))
        ).max_attempts
    except (FileNotFoundError, ValueError):
        return 5


def _metric_table(title: str) -> Table:
    """Return an empty two-column metric table."""
    table = Table(title=title, show_header=True, header_style="bold cyan", title_justify="left")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")
    return table


def _print_stats(stats: DatabaseStats, *, detailed: bool) -> None:
    """Render the statistics as tables."""
    console = get_console()
    overview = Table.grid(padding=(0, 3))
    for _ in range(4):
        overview.add_column(justify="center")
    counts = {s.source: s.items for s in stats.sources}
    overview.add_row("📸 Instagram", "📱 Telegram", "📊 Total", "💾 Size / schema")
    overview.add_row(
        f"[bold green]{counts.get('instagram', 0):,}[/bold green]",
        f"[bold blue]{counts.get('telegram', 0):,}[/bold blue]",
        f"[bold yellow]{stats.items_total:,}[/bold yellow]",
        f"{_human_size(stats.size_bytes)} / v{stats.schema_version}",
    )
    console.print(
        Panel(
            overview,
            title="[bold cyan]📊 Database Overview[/bold cyan]",
            subtitle=f"[dim]{stats.path}[/dim]",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    if stats.schema_version < stats.latest_schema_version:
        print_warning(
            f"Schema v{stats.schema_version} < v{stats.latest_schema_version}: "
            "run `postparse db migrate`"
        )
    if stats.items_total == 0:
        print_warning(
            "Database is empty. Run `postparse extract telegram` / "
            "`postparse extract instagram` (or `postparse db migrate-v1`)."
        )
        return

    items = Table(title="Items", show_header=True, header_style="bold cyan", title_justify="left")
    items.add_column("Source", style="cyan")
    items.add_column("Kind")
    items.add_column("Items", justify="right", style="green")
    items.add_column("Oldest", style="dim")
    items.add_column("Newest", style="dim")
    for source in stats.sources:
        items.add_row(
            source.source,
            "all",
            f"{source.items:,}",
            (source.oldest or "")[:10],
            (source.newest or "")[:10],
        )
        for kind, n in source.kinds.items():
            items.add_row("", f"└─ {kind}", f"{n:,}", "", "")
    console.print(items)

    media = _metric_table("Media & transcripts")
    media.add_row("Media", ", ".join(f"{k} {v:,}" for k, v in stats.media.items()) or "0")
    for source_name, states in stats.transcript_status.items():
        relevant = {k: v for k, v in states.items() if k != "none"}
        if relevant:
            media.add_row(
                f"Transcript status ({source_name})",
                ", ".join(f"{k} {v:,}" for k, v in relevant.items()),
            )
    due = sum(stats.transcription_due.values())
    exhausted = sum(stats.transcription_exhausted.values())
    media.add_row("Queue: due now / gave up", f"{due:,} / {exhausted:,}")
    media.add_row("Transcripts (items)", f"{stats.transcripts:,} ({stats.items_with_transcript:,})")
    media.add_row("Transcribed audio", format_duration(stats.transcribed_seconds))
    media.add_row("Summaries (items)", f"{stats.summaries:,} ({stats.items_with_summary:,})")
    console.print(media)

    links = _metric_table("Links")
    links.add_row("Links (items with links)", f"{stats.links:,} ({stats.items_with_links:,})")
    links.add_row(
        "Newest fetch status", ", ".join(f"{k} {v:,}" for k, v in stats.link_status.items()) or "-"
    )
    if stats.link_fetchers:
        links.add_row(
            "Newest fetch by fetcher",
            ", ".join(f"{k} {v:,}" for k, v in stats.link_fetchers.items()),
        )
    console.print(links)

    if stats.taxonomies:
        tax = Table(
            title="Classification", show_header=True, header_style="bold cyan", title_justify="left"
        )
        tax.add_column("Taxonomy", style="cyan")
        tax.add_column("Mode")
        tax.add_column("Classified", justify="right", style="green")
        tax.add_column("Pending (default / backfill)", justify="right", style="yellow")
        tax.add_column("Errors", justify="right")
        tax.add_column("Top labels", overflow="fold")
        for info in stats.taxonomies:
            name = info.name + (" (legacy)" if info.is_legacy else "") + f" v{info.version}"
            tax.add_row(
                name,
                info.mode,
                f"{info.classified_items:,}",
                f"{info.pending_default:,} / {info.pending_backfill:,}",
                f"{info.results.get('error', 0):,}",
                ", ".join(f"{label} {n:,}" for label, n in info.top_labels) or "-",
            )
        console.print(tax)
    else:
        print_info("No classifications yet (`postparse classify run --taxonomy topics`)")

    if detailed:
        for title, pairs in (
            ("Top hashtags", stats.top_hashtags),
            ("Top mentions", stats.top_mentions),
        ):
            if not pairs:
                continue
            table = Table(
                title=title, show_header=True, header_style="bold cyan", title_justify="left"
            )
            table.add_column("#", justify="right", style="dim")
            table.add_column("Tag", style="green")
            table.add_column("Items", justify="right", style="yellow")
            for rank, (tag, n) in enumerate(pairs, 1):
                table.add_row(str(rank), tag, f"{n:,}")
            console.print(table)
        print_info(f"Distinct tags in use: {stats.tags_distinct:,}")
    elif stats.top_hashtags:
        print_info(
            "Top hashtags: "
            + ", ".join(f"{t} ({n:,})" for t, n in stats.top_hashtags[:5])
            + "  [dim](--detailed for more)[/dim]"
        )


@db.command()
@click.option("--detailed", is_flag=True, help="Also list top hashtags and mentions")
@click.option(
    "--top",
    type=click.IntRange(1, 200),
    default=10,
    show_default=True,
    help="Number of tags / labels to list",
)
@click.option(
    "--no-pending",
    is_flag=True,
    help="Skip the pending classification counts (faster on large databases)",
)
@click.option("--json", "as_json", is_flag=True, help="Print JSON instead of tables")
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.pass_context
def stats(
    ctx: click.Context,
    detailed: bool,
    top: int,
    no_pending: bool,
    as_json: bool,
    db_path: str | None,
) -> None:
    """📊 Show database statistics (counts, queues, coverage, size).

    Examples:
        postparse stats
        postparse db stats --detailed --top 20
        postparse stats --json
    """
    from postparse.services.stats import collect_stats

    database = open_database(ctx, db_path)
    result = collect_stats(
        database,
        top_tags=top,
        top_labels=top,
        max_attempts=_max_attempts(ctx),
        with_pending=not no_pending,
    )
    if as_json:
        emit_json(result.to_dict())
        return
    _print_stats(result, detailed=detailed)


_SOURCE_ALIASES = {
    "posts": "instagram",
    "messages": "telegram",
    "all": "all",
    "instagram": "instagram",
    "telegram": "telegram",
}


@db.command()
@click.argument("output", type=click.Path(dir_okay=False, allow_dash=True))
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "csv"]),
    default=None,
    help="Export format (default: from the file extension, else json)",
)
@click.option(
    "--source",
    type=click.Choice(sorted(_SOURCE_ALIASES)),
    default="all",
    show_default=True,
    help="What to export (posts = instagram, messages = telegram)",
)
@click.option("--query", "-q", help="Full-text query")
@filter_options(source=False)
@click.option("--limit", type=click.IntRange(min=1), help="Maximum number of items (newest first)")
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.pass_context
def export(
    ctx: click.Context,
    output: str,
    fmt: str | None,
    source: str,
    query: str | None,
    tags: tuple[str, ...],
    authors: tuple[str, ...],
    kinds: tuple[str, ...],
    labels: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    has_transcript: bool | None,
    limit: int | None,
    db_path: str | None,
) -> None:
    """💾 Export items to a JSON array or a CSV file (`-` writes to stdout).

    One row per item with tags and current labels; filters as in `search items`.

    Examples:
        postparse db export items.json
        postparse db export posts.csv --source posts
        postparse db export recipes.json --label topics:recipe --from 2024-01-01
        postparse db export - --format csv --tag pasta --limit 100
    """
    from postparse.services.query import QueryService

    if fmt is None:
        fmt = "csv" if output.lower().endswith(".csv") else "json"
    flt = build_item_filter(
        q=query,
        source=_SOURCE_ALIASES[source],
        tags=tags,
        authors=authors,
        kinds=kinds,
        labels=labels,
        date_from=date_from,
        date_to=date_to,
        has_transcript=has_transcript,
    )
    service = QueryService(open_database(ctx, db_path))
    if output == "-":
        service.export(flt, fmt, sys.stdout, limit=limit)  # type: ignore[arg-type]  # click.Choice values are typed str
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        count = service.export(flt, fmt, path, limit=limit)  # type: ignore[arg-type]  # click.Choice values are typed str
    except OSError as exc:
        raise click.ClickException(f"Could not write {path}: {exc}") from exc
    print_success(f"Exported {count:,} item(s) to {path} ({fmt})")


# ---------------------------------------------------------------------------
# Schema v2 database maintenance (postparse.core.db)
# ---------------------------------------------------------------------------


def _v2_db_path(ctx: click.Context, db_path: str | None) -> Path:
    """Resolve the schema v2 database path from ``--db`` or the settings."""
    return resolve_db_path(ctx, db_path)


@db.command()
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.pass_context
def migrate(ctx: click.Context, db_path: str | None) -> None:
    """🧱 Apply pending schema v2 migrations (creates the database if needed)."""
    from postparse.core.db import MigrationError, connect
    from postparse.core.db.migrate import migrate as run_migrations

    path = _v2_db_path(ctx, db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        applied = run_migrations(conn)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    except MigrationError as exc:
        print_error(str(exc))
        ctx.exit(1)
        return
    finally:
        conn.close()
    if applied:
        names = ", ".join(f"{m.version:04d}_{m.name}" for m in applied)
        print_success(f"Applied {len(applied)} migration(s) to {path}: {names}")
    else:
        print_info(f"{path} is up to date")
    print_info(f"Schema version: {version}")


def run_db_check(path: Path, config_path: str | None = None) -> bool:
    """Verify integrity, foreign keys, schema version and the search index.

    Prints the findings; a schema v1 database key in the config is reported
    as a warning.

    Args:
        path: Database file.
        config_path: Config file for the legacy-key warning.

    Returns:
        ``True`` when no problems were found.
    """
    from postparse.core.db import MigrationError, connect
    from postparse.core.db.migrate import discover_migrations, pending_migrations
    from postparse.core.db.repos import SearchRepo

    warning = legacy_db_key_warning(config_path)
    if warning:
        print_warning(warning)
    if not path.is_file():
        print_error(f"Database not found: {path} (run `postparse db migrate`)")
        return False

    problems: list[str] = []
    conn = connect(path)
    try:
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
        if integrity != ["ok"]:
            problems.append("integrity_check: " + "; ".join(map(str, integrity[:10])))

        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_rows:
            problems.append(f"foreign_key_check: {len(fk_rows)} violation(s)")

        migrations = discover_migrations()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        try:
            pending = pending_migrations(conn, migrations)
        except MigrationError as exc:
            problems.append(str(exc))
            pending = []
        if pending:
            problems.append(f"{len(pending)} pending migration(s); run `postparse db migrate`")
        expected = migrations[-1].version if migrations else 0
        if not pending and version != expected:
            problems.append(f"user_version is {version}, expected {expected}")

        if not pending and version > 0:
            search = SearchRepo(conn)
            items = conn.execute("SELECT count(*) FROM items").fetchone()[0]
            docs = conn.execute("SELECT count(*) FROM search_docs").fetchone()[0]
            indexed = search.indexed_count()
            if not (items == docs == indexed):
                problems.append(
                    f"search index out of sync: items={items}, search_docs={docs}, "
                    f"fts={indexed} (run `postparse db reindex`)"
                )
            if not search.integrity_check():
                problems.append("FTS integrity-check failed (run `postparse db reindex`)")
            print_info(f"Items: {items:,}  indexed: {indexed:,}")
    finally:
        conn.close()

    print_info(f"Database: {path}")
    print_info(f"Schema version: {version}")
    if problems:
        for problem in problems:
            print_error(problem)
        return False
    print_success("Database check passed")
    return True


@db.command()
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.pass_context
def check(ctx: click.Context, db_path: str | None) -> None:
    """🩺 Verify integrity, foreign keys, schema version and the search index."""
    if not run_db_check(_v2_db_path(ctx, db_path), config_path_from_ctx(ctx)):
        ctx.exit(1)


@db.command()
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.pass_context
def reindex(ctx: click.Context, db_path: str | None) -> None:
    """🔎 Rebuild all search documents and optimize the full-text index."""
    from postparse.core.db import Database
    from postparse.core.db.repos import SearchRepo

    path = _v2_db_path(ctx, db_path)
    if not path.exists():
        print_error(f"Database not found: {path} (run `postparse db migrate`)")
        ctx.exit(1)
        return
    database = Database.open(path)
    with database.transaction() as conn:
        search = SearchRepo(conn)
        count = search.rebuild_all()
        search.optimize()
    print_success(f"Reindexed {count:,} item(s) in {path}")


def _report_table(report) -> Table:
    """Build the counts-only summary table of a v1 migration report."""
    table = Table(title="v1 -> v2 migration", show_header=True)
    table.add_column("Section", style="cyan")
    table.add_column("Metric", style="white")
    table.add_column("Value", style="green", justify="right")
    sections = (
        ("items", report.items),
        ("dropped", report.dropped),
        ("timestamps", report.timestamps),
        ("tags", report.tags),
        ("media", report.media),
        ("links", report.links),
        ("expanded", report.expanded),
    )
    for name, values in sections:
        for key, value in values.items():
            if isinstance(value, dict):
                value = ", ".join(f"{k}={v}" for k, v in value.items())
            table.add_row(
                name,
                key,
                f"{value:,}"
                if isinstance(value, int) and not isinstance(value, bool)
                else str(value),
            )
    cls = report.classification
    for tax in cls.get("taxonomies", []):
        table.add_row(
            "taxonomy",
            tax["name"],
            f"{tax['mode']}, {tax['labels']} labels" + (", legacy" if tax["is_legacy"] else ""),
        )
    for run in cls.get("runs", []):
        table.add_row(
            "run",
            f"#{run['run_id']} {run['taxonomy']} {run['model']}",
            f"{run['results']:,} results / {run['labels']:,} labels",
        )
    for key in (
        "results",
        "labels",
        "superseded_rows",
        "duplicate_label_rows_removed",
        "rows_unmapped",
        "rows_unknown_classifier",
        "rows_test_dropped",
    ):
        if key in cls:
            table.add_row("classification", key, f"{cls[key]:,}")
    for key, value in report.checks.items():
        table.add_row("checks", key, str(value))
    passed = sum(1 for check in report.verification if check["ok"])
    table.add_row("verification", "passed", f"{passed}/{len(report.verification)}")
    table.add_row("timing", "total_s", str(report.timings_s.get("total", "")))
    table.add_row("target", "size_bytes", f"{report.target_size_bytes:,}")
    return table


@db.command(name="migrate-v1")
@click.option(
    "--source",
    "source_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Schema v1 database (read-only)",
)
@click.option(
    "--target",
    "target_path",
    required=True,
    type=click.Path(dir_okay=False),
    help="Schema v2 database to create",
)
@click.option(
    "--downloads-dir",
    type=click.Path(file_okay=False),
    help="Media folder the v1 paths refer to (default: Settings.downloads_dir)",
)
@click.option(
    "--report",
    "report_path",
    type=click.Path(dir_okay=False),
    help="Write the JSON report to this file",
)
@click.option(
    "--instagram-tz",
    default="Europe/Berlin",
    show_default=True,
    help="Time zone of the naive v1 Instagram timestamps",
)
@click.option("--overwrite", is_flag=True, help="Replace an existing target database")
@click.pass_context
def migrate_v1_command(
    ctx: click.Context,
    source_path: str,
    target_path: str,
    downloads_dir: str | None,
    report_path: str | None,
    instagram_tz: str,
    overwrite: bool,
) -> None:
    """🚚 Migrate a schema v1 database into a new schema v2 database."""
    from postparse.core.db.legacy_v1 import LegacyMigrationError, migrate_v1

    if downloads_dir:
        downloads = Path(downloads_dir).resolve()
    else:
        from postparse.config import get_settings

        settings = get_settings(config_path_from_ctx(ctx))
        assert settings.downloads_dir is not None
        downloads = settings.downloads_dir

    console = get_console()
    report = None
    try:
        report = migrate_v1(
            Path(source_path),
            Path(target_path),
            downloads_dir=downloads,
            instagram_tz=instagram_tz,
            overwrite=overwrite,
        )
    except FileExistsError as exc:
        print_error(str(exc))
        ctx.exit(1)
        return
    except LegacyMigrationError as exc:
        report = exc.report
        print_error(str(exc))
    if report is not None:
        console.print(_report_table(report))
        if report_path:
            Path(report_path).parent.mkdir(parents=True, exist_ok=True)
            Path(report_path).write_text(report.to_json(), encoding="utf-8")
            print_info(f"Report written to {report_path}")
    if report is None or not report.ok:
        ctx.exit(1)
        return
    print_success(f"Migrated into {report.target}")
