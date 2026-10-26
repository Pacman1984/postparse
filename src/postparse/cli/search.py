"""Search commands over the schema v2 database (thin adapters over ``QueryService``).

- ``items [QUERY]``: unified full-text search with snippets and all filters
- ``posts [QUERY]``: Instagram only (alias of ``items --source instagram``)
- ``messages [QUERY]``: Telegram only (alias of ``items --source telegram``)

Results are newest first. Pass ``--cursor`` with the printed next cursor to get
the following page. ``--json`` prints ``{"total", "items", "next_cursor"}``.

Example:
    $ postparse search items pasta --source instagram --limit 10
    $ postparse search items "creamy pasta" --label topics:recipe --has-transcript
    $ postparse search posts --hashtag recipe --type video
    $ postparse search messages --from 2024-01-01 --to 2024-06-30 --json
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import rich_click as click
from rich.markup import escape
from rich.table import Table

from postparse.cli.filters import build_item_filter, filter_options
from postparse.cli.utils import (
    emit_json,
    get_console,
    open_database,
    print_info,
    print_warning,
    truncate_text,
)

if TYPE_CHECKING:
    from postparse.core.db.models import ItemFilter
    from postparse.services.query import ItemView

logger = logging.getLogger(__name__)

_DB_OPTION_HELP = "Schema v2 database file (default: Settings.db_path)"

#: ``search messages --type`` values of the old CLI mapped to item kinds.
_MESSAGE_TYPES = {"text": "text", "photo": "image", "image": "image", "video": "video",
                  "document": "document", "audio": "audio"}
_POST_TYPES = {"image": "image", "video": "video", "carousel": "carousel"}


@click.group()
def search() -> None:
    """🔍 Search saved items (full text, tags, labels, dates).

    Commands:
    - items: all sources, full-text query with snippets
    - posts: Instagram posts (alias of `items --source instagram`)
    - messages: Telegram messages (alias of `items --source telegram`)
    """


def _results_table(views: list[ItemView], title: str) -> Table:
    """Render one page of results."""
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", justify="right")
    table.add_column("Source", style="cyan")
    table.add_column("Date", style="green", no_wrap=True)
    table.add_column("Author", style="yellow")
    table.add_column("Kind")
    table.add_column("Text", overflow="fold")
    table.add_column("Tags / labels", style="magenta", overflow="fold")
    for view in views:
        text = view.snippet or (view.text or "").replace("\n", " ")
        tags = " ".join(view.tags[:6]) + (" …" if len(view.tags) > 6 else "")
        labels = "; ".join(f"{tx}:{','.join(lbs)}" for tx, lbs in view.labels.items() if lbs)
        table.add_row(
            str(view.id),
            view.source,
            view.sort_at.date().isoformat(),
            escape(view.author or ""),
            view.kind,
            escape(truncate_text(text, 120)),
            escape(" ".join(part for part in (tags, labels) if part)),
        )
    return table


def run_search(
    ctx: click.Context,
    item_filter: ItemFilter,
    *,
    limit: int,
    cursor: str | None,
    as_json: bool,
    db_path: str | None,
    title: str,
) -> None:
    """Run a search and print the page (shared by all search commands).

    Raises:
        click.ClickException: For a missing database or a bad cursor.
    """
    from postparse.services.query import MAX_PAGE_SIZE, InvalidCursorError, QueryService

    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise click.BadParameter(f"must be between 1 and {MAX_PAGE_SIZE}", param_hint="--limit")
    service = QueryService(open_database(ctx, db_path))
    try:
        page = service.search(item_filter, cursor=cursor, limit=limit)
    except InvalidCursorError as exc:
        raise click.BadParameter(str(exc), param_hint="--cursor") from exc
    total = service.count(item_filter)

    if as_json:
        emit_json({
            "total": total,
            "items": [view.to_dict() for view in page.items],
            "next_cursor": page.next_cursor,
        })
        return

    console = get_console()
    if not page.items:
        print_warning("No matching items")
        return
    console.print(_results_table(page.items, f"{title} ({total:,} match(es))"))
    shown = len(page.items)
    print_info(f"Showing {shown} of {total:,}")
    if page.next_cursor:
        console.print(f"[dim]Next page:[/dim] --cursor {page.next_cursor}", soft_wrap=True)


def _page_options(func: Any) -> Any:
    """Add ``--limit``, ``--cursor``, ``--json`` / ``--output`` and ``--db``."""
    for option in reversed([
        click.option("--limit", type=int, default=20, show_default=True,
                     help="Page size (1-500)"),
        click.option("--cursor", help="Continue after a previous page (printed next cursor)"),
        click.option("--json", "as_json", is_flag=True, help="Print JSON instead of a table"),
        click.option("--output", type=click.Choice(["table", "json"]), default=None,
                     help="Output format (same as --json when 'json')"),
        click.option("--db", "db_path", type=click.Path(dir_okay=False), help=_DB_OPTION_HELP),
    ]):
        func = option(func)
    return func


@search.command()
@click.argument("query", required=False)
@filter_options(source=True)
@_page_options
@click.pass_context
def items(
    ctx: click.Context,
    query: str | None,
    source: str,
    tags: tuple[str, ...],
    authors: tuple[str, ...],
    kinds: tuple[str, ...],
    labels: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    has_transcript: bool | None,
    limit: int,
    cursor: str | None,
    as_json: bool,
    output: str | None,
    db_path: str | None,
) -> None:
    """Search all items; QUERY is a full-text query (words AND, "phrases", prefix*).

    The text index covers item text, transcripts, summaries, fetched link
    texts and tags. Matched terms are shown in square brackets in the snippet.

    Examples:
        postparse search items pasta
        postparse search items "pasta carbonara" --source instagram --limit 5
        postparse search items --tag recipe --label topics:recipe --from 2024-01-01
        postparse search items rezept --has-transcript --json
    """
    flt = build_item_filter(
        q=query, source=source, tags=tags, authors=authors, kinds=kinds, labels=labels,
        date_from=date_from, date_to=date_to, has_transcript=has_transcript,
    )
    run_search(ctx, flt, limit=limit, cursor=cursor, as_json=as_json or output == "json",
               db_path=db_path, title="Items")


@search.command()
@click.argument("query", required=False)
@click.option("--type", "content_type", type=click.Choice(sorted(_POST_TYPES)),
              help="Post type (same as --kind)")
@filter_options(source=False, author_aliases=("--username", "--owner"))
@_page_options
@click.pass_context
def posts(
    ctx: click.Context,
    query: str | None,
    content_type: str | None,
    tags: tuple[str, ...],
    authors: tuple[str, ...],
    kinds: tuple[str, ...],
    labels: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    has_transcript: bool | None,
    limit: int,
    cursor: str | None,
    as_json: bool,
    output: str | None,
    db_path: str | None,
) -> None:
    """Search Instagram posts (alias of `search items --source instagram`).

    Examples:
        postparse search posts --hashtag recipe
        postparse search posts --hashtag recipe --hashtag cooking --type video
        postparse search posts --from 2024-01-01 --to 2024-12-31 --limit 100
        postparse search posts --username myuser --output json
    """
    if content_type:
        kinds = (*kinds, _POST_TYPES[content_type])
    flt = build_item_filter(
        q=query, source="instagram", tags=tags, authors=authors, kinds=kinds, labels=labels,
        date_from=date_from, date_to=date_to, has_transcript=has_transcript,
    )
    run_search(ctx, flt, limit=limit, cursor=cursor, as_json=as_json or output == "json",
               db_path=db_path, title="Instagram posts")


@search.command()
@click.argument("query", required=False)
@click.option("--type", "content_type", type=click.Choice(sorted(_MESSAGE_TYPES)),
              help="Message type (photo = image; same as --kind)")
@filter_options(source=False)
@_page_options
@click.pass_context
def messages(
    ctx: click.Context,
    query: str | None,
    content_type: str | None,
    tags: tuple[str, ...],
    authors: tuple[str, ...],
    kinds: tuple[str, ...],
    labels: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    has_transcript: bool | None,
    limit: int,
    cursor: str | None,
    as_json: bool,
    output: str | None,
    db_path: str | None,
) -> None:
    """Search Telegram messages (alias of `search items --source telegram`).

    Examples:
        postparse search messages --hashtag recipe
        postparse search messages --type photo --from 2024-01-01
        postparse search messages python --output json
    """
    if content_type:
        kinds = (*kinds, _MESSAGE_TYPES[content_type])
    flt = build_item_filter(
        q=query, source="telegram", tags=tags, authors=authors, kinds=kinds, labels=labels,
        date_from=date_from, date_to=date_to, has_transcript=has_transcript,
    )
    run_search(ctx, flt, limit=limit, cursor=cursor, as_json=as_json or output == "json",
               db_path=db_path, title="Telegram messages")
