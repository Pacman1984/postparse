"""Shared item filter options for ``search`` and ``db export``.

The options map onto :class:`postparse.core.db.models.ItemFilter`:

- ``--source instagram|telegram``
- ``--tag`` (repeatable, any of; ``#hashtag``, ``@mention`` or a bare name)
- ``--author`` (repeatable, any of; exact match)
- ``--kind`` (repeatable, any of)
- ``--label taxonomy[:label]`` (repeatable; all for the same taxonomy, any label)
- ``--from`` / ``--to`` (``YYYY-MM-DD``, inclusive)
- ``--has-transcript`` / ``--no-transcript``
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any

import rich_click as click

from postparse.core.db.models import ItemFilter, LabelFilter

__all__ = [
    "KINDS",
    "build_item_filter",
    "filter_options",
    "parse_day",
    "parse_label_filter",
]

KINDS = ("text", "image", "video", "carousel", "document", "audio", "other")


def parse_day(value: str | None, option: str) -> date | None:
    """Parse ``YYYY-MM-DD`` for a date option.

    Raises:
        click.BadParameter: For another format.
    """
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise click.BadParameter(
            f"invalid date {value!r}; use YYYY-MM-DD", param_hint=option
        ) from None


def parse_label_filter(values: Sequence[str]) -> LabelFilter | None:
    """Turn ``taxonomy:label`` / ``taxonomy`` values into one label filter.

    Raises:
        click.BadParameter: For an empty taxonomy or several taxonomies.
    """
    if not values:
        return None
    taxonomy: str | None = None
    labels: list[str] = []
    for raw in values:
        name, _, label = raw.partition(":")
        name, label = name.strip(), label.strip()
        if not name:
            raise click.BadParameter(f"{raw!r}: expected taxonomy:label", param_hint="--label")
        if taxonomy is not None and name != taxonomy:
            raise click.BadParameter(
                "all --label values must use the same taxonomy", param_hint="--label"
            )
        taxonomy = name
        if label and label not in labels:
            labels.append(label)
    assert taxonomy is not None
    return LabelFilter(taxonomy, tuple(labels))


def build_item_filter(
    *,
    q: str | None = None,
    source: str | None = None,
    tags: Sequence[str] = (),
    authors: Sequence[str] = (),
    kinds: Sequence[str] = (),
    labels: Sequence[str] = (),
    date_from: str | None = None,
    date_to: str | None = None,
    has_transcript: bool | None = None,
) -> ItemFilter:
    """Build an :class:`ItemFilter` from raw CLI values.

    Raises:
        click.BadParameter: For invalid dates or labels.
    """
    start = parse_day(date_from, "--from")
    end = parse_day(date_to, "--to")
    if start and end and start > end:
        raise click.BadParameter("--from is after --to", param_hint="--from")
    return ItemFilter(
        source=None if source in (None, "all") else source,  # type: ignore[arg-type]
        kinds=tuple(dict.fromkeys(kinds)),  # type: ignore[arg-type]
        tags=tuple(t for t in tags if t.strip()),
        authors=tuple(a for a in authors if a.strip()),
        date_from=start,
        date_to=end,
        labels=parse_label_filter(labels),
        q=(q or "").strip() or None,
        has_transcript=has_transcript,
    )


def filter_options(
    *, source: bool = True, author_aliases: Sequence[str] = ()
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator adding the shared filter options.

    Args:
        source: Add ``--source``.
        author_aliases: Extra flag names for ``--author`` (e.g. ``--username``).

    Returns:
        Decorator for a Click command. The command receives ``source`` (if
        enabled), ``tags``, ``authors``, ``kinds``, ``labels``, ``date_from``,
        ``date_to`` and ``has_transcript``.
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        options = [
            click.option(
                "--tag",
                "--hashtag",
                "tags",
                multiple=True,
                help="Tag filter, repeatable (any of): #hashtag, @mention or name",
            ),
            click.option(
                "--author",
                *author_aliases,
                "authors",
                multiple=True,
                help="Author / owner filter, repeatable (any of)",
            ),
            click.option(
                "--kind",
                "kinds",
                multiple=True,
                type=click.Choice(KINDS),
                help="Item kind, repeatable (any of)",
            ),
            click.option(
                "--label",
                "labels",
                multiple=True,
                metavar="TAXONOMY[:LABEL]",
                help="Current classification label, repeatable (same taxonomy, any "
                "label); a bare taxonomy matches any classified item",
            ),
            click.option(
                "--from", "date_from", metavar="YYYY-MM-DD", help="Items on or after this day (UTC)"
            ),
            click.option(
                "--to", "date_to", metavar="YYYY-MM-DD", help="Items on or before this day (UTC)"
            ),
            click.option(
                "--has-transcript/--no-transcript",
                "has_transcript",
                default=None,
                help="Only items with / without a video transcript",
            ),
        ]
        if source:
            options.insert(
                0,
                click.option(
                    "--source",
                    type=click.Choice(["instagram", "telegram", "all"]),
                    default="all",
                    show_default=True,
                    help="Restrict to one source",
                ),
            )
        for option in reversed(options):
            func = option(func)
        return func

    return decorate
