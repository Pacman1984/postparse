"""Classify commands for the PostParse CLI (thin adapters over the classification service).

Commands:

- ``run``: classify pending items of a taxonomy and store the results (schema v2 DB)
- ``text``: classify a text ad hoc (nothing is stored)
- ``taxonomies``: list configured and stored taxonomies
- ``db``: deprecated alias for ``run --taxonomy topics``

Example:
    $ postparse classify run --taxonomy topics --limit 100
    $ postparse classify run --taxonomy topics --backfill --source instagram
    $ postparse classify text "Spaghetti Carbonara ..." --labels recipe,travel,tech --mode multi
    $ postparse classify taxonomies
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import rich_click as click
from rich.table import Table

from postparse.cli.utils import (
    create_progress,
    format_duration,
    get_console,
    load_config,
    parse_date,
    print_info,
    print_panel,
    print_warning,
)

if TYPE_CHECKING:
    from postparse.classification import ClassificationOutcome
    from postparse.services.classification import ClassificationService, RunReport

logger = logging.getLogger(__name__)

_DB_OPTION_HELP = "Schema v2 database file (default: Settings.db_path)"


@click.group()
def classify() -> None:
    """🤖 Classify content into taxonomies with an LLM.

    Commands:
    - run: classify pending database items of a taxonomy and store results
    - text: classify free-form text (ad hoc, nothing is stored)
    - taxonomies: list configured and stored taxonomies
    - db: deprecated alias for `classify run --taxonomy topics`
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_path(ctx: click.Context) -> str | None:
    """Return the ``--config`` value of the root command."""
    return (ctx.obj or {}).get("config")


def _db_path(ctx: click.Context, db_path: str | None) -> Path:
    """Resolve the schema v2 database path from ``--db`` or the settings."""
    if db_path:
        return Path(db_path).resolve()
    from postparse.config import get_settings

    settings = get_settings(_config_path(ctx))
    assert settings.db_path is not None
    return settings.db_path


def _build_service(
    ctx: click.Context, db_path: str | None, *, require_db: bool = True
) -> ClassificationService:
    """Create the classification service for the CLI context.

    Raises:
        click.ClickException: If the database is missing or the config is invalid.
    """
    from postparse.config import get_settings
    from postparse.core.db import Database
    from postparse.services.classification import ClassificationService

    config = load_config(_config_path(ctx))
    path = _db_path(ctx, db_path)
    if require_db and not path.exists():
        raise click.ClickException(
            f"Database not found: {path} (run `postparse db migrate` first)"
        )
    # Never create a database as a side effect of read-only commands.
    database = Database.open(path) if path.exists() else None
    try:
        return ClassificationService(database, get_settings(_config_path(ctx)), config=config)
    except ValueError as exc:
        raise click.ClickException(f"Invalid classification config: {exc}") from exc


def _parse_labels(raw: str) -> list[str]:
    """Split ``a,b,c`` into label names."""
    labels = [part.strip() for part in raw.split(",") if part.strip()]
    if not labels:
        raise click.BadParameter("at least one label is required", param_hint="--labels")
    return labels


def _parse_classes(raw: str) -> dict[str, str]:
    """Parse the legacy ``--classes`` JSON object (or ``@file``)."""
    try:
        if raw.startswith("@"):
            data = json.loads(Path(raw[1:]).read_text(encoding="utf-8"))
        else:
            data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise click.BadParameter(f"invalid JSON: {exc}", param_hint="--classes") from exc
    if not isinstance(data, Mapping) or not data:
        raise click.BadParameter("must be a non-empty JSON object", param_hint="--classes")
    return {str(k): str(v or "") for k, v in data.items()}


def _read_text_argument(content: str | None) -> str:
    """Return the text argument, reading stdin for ``-`` or a piped input."""
    if content is None or content == "-":
        if content is None and sys.stdin.isatty():
            raise click.UsageError("No text given. Use: postparse classify text TEXT (or pipe it)")
        content = sys.stdin.read()
    return content


def _outcome_panel(outcome: ClassificationOutcome, title: str, provider: str | None,
                   model: str | None) -> None:
    """Print one classification outcome."""
    if outcome.status == "empty":
        print_warning("Empty text: nothing to classify (the model was not called)")
        return
    if outcome.labels:
        lines = ["[bold]Labels:[/bold] " + ", ".join(outcome.labels)]
    else:
        lines = ["[bold]Labels:[/bold] (none apply)"]
    if outcome.confidence is not None:
        lines.append(f"[bold]Confidence:[/bold] {outcome.confidence:.0%}")
    if outcome.reasoning:
        lines.append(f"[bold]Reasoning:[/bold] {outcome.reasoning}")
    lines.append(
        f"[dim]{provider or '?'} / {model or '?'} · {outcome.latency_s:.2f}s"
        f" · {outcome.requests} request(s)[/dim]"
    )
    print_panel("\n".join(lines), title=title, style="green" if outcome.labels else "cyan")


def _report_table(report: RunReport) -> Table:
    """Render a run report as a table."""
    table = Table(title=f"Classification run · {report.taxonomy} (v{report.taxonomy_version})",
                  show_header=True, header_style="bold cyan")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    rows: list[tuple[str, Any]] = [
        ("Run id", report.run_id if report.run_id is not None else "-"),
        ("Scope", report.scope),
        ("Provider / model", f"{report.provider} / {report.model}"),
        ("Pending candidates", report.candidates),
        ("Classified (ok)", report.ok),
        ("No labels", report.no_labels),
        ("Errors (stay pending)", report.errors),
        ("Skipped: empty input", report.skipped_empty),
        ("Skipped: waiting for transcript", report.skipped_waiting_transcript),
        ("Duration", format_duration(report.duration_s)),
    ]
    if report.classified:
        rows.append(("Avg per item", f"{report.duration_s / report.classified:.2f}s"))
    for name, value in rows:
        table.add_row(name, str(value))
    return table


def _run_classification(
    ctx: click.Context,
    *,
    taxonomy: str,
    source: str,
    scope: str,
    with_transcript: bool,
    since: str | None,
    limit: int | None,
    provider: str | None,
    db_path: str | None,
    wait_transcripts: bool,
    tags: tuple[str, ...] = (),
) -> RunReport:
    """Shared implementation of ``classify run`` and the ``classify db`` alias."""
    from postparse.core.db.models import ItemFilter
    from postparse.services.classification import ProgressUpdate

    service = _build_service(ctx, db_path)
    try:
        date_from = parse_date(since).date() if since else None
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--since") from exc
    item_filter = ItemFilter(
        source=None if source == "all" else source,  # type: ignore[arg-type]
        tags=tags,
        date_from=date_from,
        has_transcript=True if with_transcript else None,
    )
    console = get_console()
    quiet = bool((ctx.obj or {}).get("quiet"))

    with create_progress() as progress:
        task = progress.add_task(f"Classifying {taxonomy}", total=None, visible=not quiet)

        def on_progress(update: ProgressUpdate) -> None:
            r = update.report
            progress.update(
                task,
                total=update.total,
                completed=update.handled,
                description=(
                    f"{taxonomy}: ok {r.ok} · none {r.no_labels} · err {r.errors}"
                    f" · skip {r.skipped}"
                ),
            )

        try:
            report = service.classify_pending(
                taxonomy,
                scope=scope,  # type: ignore[arg-type]
                filters=item_filter,
                limit=limit,
                provider=provider,
                wait_for_transcripts=wait_transcripts,
                progress=on_progress,
            )
        except KeyError as exc:
            raise click.ClickException(str(exc.args[0] if exc.args else exc)) from exc
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    if report.run_id is None:
        print_info(f"Nothing to classify for taxonomy '{taxonomy}' (scope: {scope})")
    console.print(_report_table(report))
    for item_id, message in report.error_samples[:5]:
        print_warning(f"item {item_id}: {message}")
    return report


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@classify.command()
@click.option("--taxonomy", "-t", default="topics", show_default=True,
              help="Taxonomy to classify into (see `classify taxonomies`)")
@click.option("--source", type=click.Choice(["all", "instagram", "telegram"]), default="all",
              show_default=True, help="Restrict to one source")
@click.option("--scope", type=click.Choice(["default", "backfill", "reprocess"]),
              default="default", show_default=True,
              help="default: new + never classified items; backfill: everything not yet "
                   "classified for the current label set; reprocess: everything matching")
@click.option("--backfill", "backfill_flag", is_flag=True, help="Alias for --scope backfill")
@click.option("--reprocess", "reprocess_flag", is_flag=True, help="Alias for --scope reprocess")
@click.option("--with-transcript", is_flag=True, help="Only items that have a transcript")
@click.option("--since", help="Only items dated on/after DATE (YYYY-MM-DD)")
@click.option("--limit", type=click.IntRange(min=1), help="Maximum items sent to the LLM")
@click.option("--provider", help="LLM provider from [llm.providers] (default: default_provider)")
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.option("--no-wait-transcripts", is_flag=True,
              help="Also classify items whose video transcripts are still pending")
@click.pass_context
def run(ctx: click.Context, taxonomy: str, source: str, scope: str, backfill_flag: bool,
        reprocess_flag: bool, with_transcript: bool, since: str | None, limit: int | None,
        provider: str | None, db_path: str | None, no_wait_transcripts: bool) -> None:
    """Classify pending database items of a taxonomy and store the results.

    Old posts are never re-classified automatically: the default scope only
    picks items collected after the taxonomy was created and items without
    any classification. Use --backfill / --reprocess explicitly for the rest.

    Examples:
        postparse classify run --taxonomy topics --limit 100
        postparse classify run -t topics --backfill --source instagram --since 2024-01-01
    """
    if backfill_flag and reprocess_flag:
        raise click.UsageError("--backfill and --reprocess are mutually exclusive")
    if backfill_flag:
        scope = "backfill"
    elif reprocess_flag:
        scope = "reprocess"
    _run_classification(
        ctx, taxonomy=taxonomy, source=source, scope=scope, with_transcript=with_transcript,
        since=since, limit=limit, provider=provider, db_path=db_path,
        wait_transcripts=not no_wait_transcripts,
    )


@classify.command()
@click.argument("content", required=False)
@click.option("--taxonomy", "-t", help="Configured taxonomy (default: topics)")
@click.option("--labels", help="Ad-hoc labels, comma separated (e.g. recipe,travel,tech)")
@click.option("--mode", type=click.Choice(["single", "multi"]), default="multi",
              show_default=True, help="Mode for --labels")
@click.option("--provider", help="LLM provider from [llm.providers] (default: default_provider)")
@click.option("--output", type=click.Choice(["text", "json"]), default="text",
              show_default=True, help="Output format")
@click.option("--classifier", type=click.Choice(["recipe", "multiclass", "multilabel"]),
              hidden=True, help="Deprecated: use --labels/--mode or --taxonomy")
@click.option("--classes", "classes_arg", hidden=True,
              help="Deprecated: JSON object of labels → descriptions (or @file)")
@click.pass_context
def text(ctx: click.Context, content: str | None, taxonomy: str | None, labels: str | None,
         mode: str, provider: str | None, output: str, classifier: str | None,
         classes_arg: str | None) -> None:
    """Classify free-form text (nothing is stored).

    Examples:
        postparse classify text "Spaghetti Carbonara: Guanciale, Eigelb" --labels recipe,travel
        postparse classify text "New FastAPI release" --labels recipe,tech --mode single
        echo "Some text" | postparse classify text - --taxonomy topics --output json
    """
    from postparse.classification import ClassificationError, TaxonomySpec

    content = _read_text_argument(content)
    if taxonomy and (labels or classes_arg or classifier):
        raise click.UsageError("--taxonomy cannot be combined with --labels/--classes")

    spec: TaxonomySpec | None = None
    try:
        if classifier is not None or classes_arg is not None:
            print_warning("--classifier/--classes are deprecated; use --labels/--mode or "
                          "--taxonomy")
            if classifier == "recipe" and not classes_arg:
                spec = TaxonomySpec.adhoc(
                    {"recipe": "Cooking instructions, ingredients or a dish to prepare",
                     "not_recipe": "Anything else"}, mode="single", name="recipe")
            elif classes_arg:
                spec = TaxonomySpec.adhoc(_parse_classes(classes_arg),
                                          mode="multi" if classifier == "multilabel" else "single")
        if spec is None and labels:
            spec = TaxonomySpec.adhoc(_parse_labels(labels), mode=mode)  # type: ignore[arg-type]
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    service = _build_service(ctx, None, require_db=False)
    try:
        if spec is None:
            spec = service.taxonomy_spec(taxonomy or "topics")
        clf = service.classifier_for(spec, provider)
        outcome = clf.classify(content)
    except KeyError as exc:
        raise click.ClickException(str(exc.args[0] if exc.args else exc)) from exc
    except ClassificationError as exc:
        raise click.ClickException(f"Classification failed: {exc}") from exc
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - e.g. missing API key
        raise click.ClickException(f"Classification failed: {exc}") from exc

    if output == "json":
        data = outcome.to_dict()
        data.update(
            label=outcome.label,
            taxonomy=spec.name,
            mode=spec.mode,
            available_labels=list(spec.label_names),
            provider=clf.provider_name,
            model=clf.model_name,
        )
        get_console().print_json(json.dumps(data, ensure_ascii=False))
        return
    _outcome_panel(outcome, f"Classification · {spec.name} ({spec.mode})",
                   clf.provider_name, clf.model_name)


@classify.command()
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.option("--output", type=click.Choice(["text", "json"]), default="text",
              show_default=True, help="Output format")
@click.pass_context
def taxonomies(ctx: click.Context, db_path: str | None, output: str) -> None:
    """List configured and stored taxonomies with versions and result counts."""
    service = _build_service(ctx, db_path, require_db=False)
    infos = service.list_taxonomies()
    if output == "json":
        get_console().print_json(json.dumps([
            {
                "name": i.name, "mode": i.mode, "labels": list(i.labels),
                "configured": i.configured, "in_db": i.in_db, "version": i.version,
                "is_legacy": i.is_legacy, "in_sync": i.in_sync, "runs": i.runs,
                "results": dict(i.results), "classified_items": i.classified_items,
            }
            for i in infos
        ], ensure_ascii=False))
        return
    if not infos:
        print_warning("No taxonomies configured ([[classification.taxonomies]]) or stored")
        return
    table = Table(title="Taxonomies", show_header=True, header_style="bold cyan")
    for column in ("Name", "Mode", "Labels", "Source", "Version", "Runs", "ok", "none",
                   "errors", "Items"):
        table.add_column(column, justify="right" if column in
                         ("Version", "Runs", "ok", "none", "errors", "Items") else "left")
    for info in infos:
        origin = []
        if info.configured:
            origin.append("config")
        if info.in_db:
            origin.append("db" + (" (legacy)" if info.is_legacy else ""))
        if info.in_sync is False:
            origin.append("[yellow]labels changed[/yellow]")
        labels = ", ".join(info.labels)
        table.add_row(
            info.name, info.mode, labels if len(labels) <= 60 else labels[:57] + "...",
            " + ".join(origin), str(info.version or "-"), str(info.runs),
            str(info.results.get("ok", 0)), str(info.results.get("no_labels", 0)),
            str(info.results.get("error", 0)), str(info.classified_items),
        )
    get_console().print(table)


@classify.command(deprecated=True)
@click.option("--source", type=click.Choice(["all", "instagram", "telegram"]), default="all",
              help="Database source to classify (default: all)")
@click.option("--classifier", type=click.Choice(["recipe", "multiclass", "multilabel"]),
              default=None, help="Ignored (the generic 'topics' taxonomy is used)")
@click.option("--classes", "classes_arg", default=None,
              help="Ignored (configure [[classification.taxonomies]] instead)")
@click.option("--limit", type=click.IntRange(min=1), default=None,
              help="Maximum items sent to the LLM (default: 1000)")
@click.option("--filter-hashtag", multiple=True, help="Only items with this hashtag")
@click.option("--provider", help="LLM provider to use (default: from config)")
@click.option("--force", is_flag=True, default=False, help="Reprocess already classified items")
@click.option("--replace", is_flag=True, default=False, help="Ignored (results are versioned)")
@click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP)
@click.pass_context
def db(ctx: click.Context, source: str, classifier: str | None, classes_arg: str | None,
       limit: int | None, filter_hashtag: tuple[str, ...], provider: str | None, force: bool,
       replace: bool, db_path: str | None) -> None:
    """Deprecated: use `postparse classify run --taxonomy topics`.

    Maps to `classify run --taxonomy topics` (--force → --scope reprocess,
    --filter-hashtag → tag filter, default limit 1000).
    """
    print_warning("`classify db` is deprecated; use `postparse classify run --taxonomy topics`")
    if replace and not force:
        raise click.UsageError("--replace requires --force")
    if classifier is not None:
        print_warning(f"--classifier {classifier} is ignored: the generic 'topics' taxonomy is "
                      "used (recipe is a label there)")
    if classes_arg is not None:
        print_warning("--classes is ignored: configure [[classification.taxonomies]] instead")
    if replace:
        print_warning("--replace is ignored: every run keeps its own results")
    _run_classification(
        ctx, taxonomy="topics", source=source, scope="reprocess" if force else "default",
        with_transcript=False, since=None, limit=limit or 1000, provider=provider,
        db_path=db_path, wait_transcripts=True,
        tags=tuple(f"#{tag.lstrip('#')}" for tag in filter_hashtag),
    )
