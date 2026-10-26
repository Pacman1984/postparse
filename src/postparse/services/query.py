"""Read-side service over the schema v2 database: search, detail, tags, export.

Example:
    >>> service = QueryService(Database.open(settings.db_path))
    >>> page = service.search(ItemFilter(q="pasta", source="instagram"), limit=20)
    >>> more = service.search(ItemFilter(q="pasta", source="instagram"),
    ...                       cursor=page.next_cursor, limit=20)
"""

from __future__ import annotations

import base64
import binascii
import csv
import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Generic, Literal, TypeVar

from postparse.core.db.connection import Database
from postparse.core.db.filters import build_filter
from postparse.core.db.models import (
    CurrentClassification,
    InstagramDetail,
    Item,
    ItemFilter,
    LabelFilter,
    Link,
    LinkFetch,
    Media,
    Summary,
    Tag,
    TagCount,
    TagKind,
    TelegramDetail,
    Transcript,
)
from postparse.core.db.repos import (
    ClassificationRepo,
    ItemsRepo,
    LinksRepo,
    MediaRepo,
    SummariesRepo,
    TagsRepo,
    TranscriptsRepo,
)
from postparse.core.timeutil import is_db_ts

__all__ = [
    "InvalidCursorError",
    "ItemDetail",
    "ItemFilter",
    "ItemView",
    "LabelFilter",
    "LinkView",
    "MediaView",
    "Page",
    "QueryService",
    "decode_cursor",
    "encode_cursor",
]

logger = logging.getLogger(__name__)

T = TypeVar("T")

MAX_PAGE_SIZE = 500
_CURSOR_VERSION = 1
_ITEM_COLUMNS = (
    "i.id, i.source, i.external_id, i.kind, i.text, i.author, i.url, i.created_at, "
    "i.collected_at, i.updated_at, i.sort_at"
)


class InvalidCursorError(ValueError):
    """Raised for malformed or tampered pagination cursors."""


def encode_cursor(sort_at: str, item_id: int) -> str:
    """Encode a keyset position as an opaque URL-safe cursor.

    Args:
        sort_at: Canonical ``sort_at`` timestamp of the last returned item.
        item_id: Id of the last returned item.

    Returns:
        Opaque cursor string.
    """
    payload = json.dumps({"v": _CURSOR_VERSION, "s": sort_at, "i": item_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, int]:
    """Decode and validate a cursor produced by :func:`encode_cursor`.

    Returns:
        ``(sort_at, item_id)``.

    Raises:
        InvalidCursorError: If the cursor is malformed.
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise InvalidCursorError("Malformed cursor") from exc
    if not isinstance(data, dict) or data.get("v") != _CURSOR_VERSION:
        raise InvalidCursorError("Unsupported cursor")
    sort_at, item_id = data.get("s"), data.get("i")
    if not isinstance(sort_at, str) or not is_db_ts(sort_at):
        raise InvalidCursorError("Cursor has an invalid timestamp")
    if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id < 0:
        raise InvalidCursorError("Cursor has an invalid id")
    return sort_at, item_id


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):  # noqa: UP046 - keep pre-PEP 695 syntax
    """One page of results.

    Attributes:
        items: Results in order.
        next_cursor: Cursor for the following page, ``None`` on the last page.
    """

    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ItemView:
    """An item as shown in result lists.

    Attributes:
        tags: Tag display names (``#hashtag`` / ``@mention``).
        labels: ``{taxonomy name: current labels}``.
        snippet: FTS snippet when a text query was given.
    """

    id: int
    source: str
    external_id: str
    kind: str
    text: str | None
    author: str | None
    url: str | None
    created_at: datetime | None
    collected_at: datetime
    sort_at: datetime
    tags: tuple[str, ...] = ()
    labels: dict[str, tuple[str, ...]] = field(default_factory=dict)
    snippet: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly dict (timestamps as ISO strings)."""
        return {
            "id": self.id,
            "source": self.source,
            "external_id": self.external_id,
            "kind": self.kind,
            "text": self.text,
            "author": self.author,
            "url": self.url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "collected_at": self.collected_at.isoformat(),
            "sort_at": self.sort_at.isoformat(),
            "tags": list(self.tags),
            "labels": {name: list(labels) for name, labels in self.labels.items()},
            "snippet": self.snippet,
        }


@dataclass(frozen=True, slots=True)
class MediaView:
    """A media row with its current transcript."""

    media: Media
    transcript: Transcript | None


@dataclass(frozen=True, slots=True)
class LinkView:
    """A link with its newest successful fetch."""

    link: Link
    fetch: LinkFetch | None


@dataclass(frozen=True, slots=True)
class ItemDetail:
    """Everything known about one item."""

    item: ItemView
    instagram: InstagramDetail | None
    telegram: TelegramDetail | None
    tags: list[Tag]
    media: list[MediaView]
    summary: Summary | None
    links: list[LinkView]
    classifications: list[CurrentClassification]

    @property
    def transcript_text(self) -> str | None:
        """Concatenated current transcripts of all media, or ``None``."""
        texts = [m.transcript.text for m in self.media if m.transcript is not None]
        return "\n".join(texts) if texts else None


class QueryService:
    """Read-only queries over a :class:`Database`.

    Args:
        db: Database handle.
        snippet_markers: Strings placed around matched terms in snippets.
        snippet_tokens: Approximate snippet length in tokens.
    """

    def __init__(
        self,
        db: Database,
        *,
        snippet_markers: tuple[str, str] = ("[", "]"),
        snippet_tokens: int = 16,
    ) -> None:
        self.db = db
        self.snippet_markers = snippet_markers
        self.snippet_tokens = snippet_tokens

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        """Open a read unit of work."""
        with self.db.read() as conn:
            yield conn

    def search(
        self,
        item_filter: ItemFilter | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[ItemView]:
        """Return one page of items, newest first (``sort_at``, ``id`` descending).

        Args:
            item_filter: Selection criteria.
            cursor: ``next_cursor`` of the previous page.
            limit: Page size (1..500).

        Returns:
            Page of items with tags, current labels and (for text queries) snippets.

        Raises:
            InvalidCursorError: If ``cursor`` is malformed.
            ValueError: If ``limit`` is out of range.
        """
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        position = decode_cursor(cursor) if cursor else None
        with self._read() as conn:
            return self._search(conn, item_filter, position, limit, with_snippet=True)

    def _search(
        self,
        conn: sqlite3.Connection,
        item_filter: ItemFilter | None,
        position: tuple[str, int] | None,
        limit: int,
        *,
        with_snippet: bool,
    ) -> Page[ItemView]:
        """Run the keyset query on an open connection."""
        flt = build_filter(item_filter)
        select = _ITEM_COLUMNS
        params: list[object] = []
        joins = ""
        where = list(flt.where)
        if flt.match is not None:
            joins = " JOIN items_fts ON items_fts.rowid = i.id"
            if with_snippet:
                select += ", snippet(items_fts, -1, ?, ?, '…', ?) AS snippet"
                params.extend([*self.snippet_markers, self.snippet_tokens])
        params.extend(flt.params)
        if flt.match is not None:
            where.append("items_fts MATCH ?")
            params.append(flt.match)
        if position is not None:
            where.append("(i.sort_at, i.id) < (?, ?)")
            params.extend(position)
        sql = f"SELECT {select} FROM items AS i{joins}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY i.sort_at DESC, i.id DESC LIMIT ?"
        params.append(limit + 1)
        rows = conn.execute(sql, params).fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]
        ids = [row["id"] for row in rows]
        tags = TagsRepo(conn).for_items(ids)
        labels = ClassificationRepo(conn).current_for_items(ids)
        views = [
            _item_view(
                Item.from_row(row),
                tags.get(row["id"], []),
                labels.get(row["id"], []),
                row["snippet"] if with_snippet and flt.match is not None else None,
            )
            for row in rows
        ]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = encode_cursor(last["sort_at"], last["id"])
        return Page(views, next_cursor)

    def count(self, item_filter: ItemFilter | None = None) -> int:
        """Return the number of items matching ``item_filter``."""
        where, params = build_filter(item_filter).where_with_fts_subquery()
        sql = "SELECT count(*) FROM items AS i"
        if where:
            sql += " WHERE " + " AND ".join(where)
        with self._read() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def get_item(self, item_id: int) -> ItemDetail | None:
        """Return the full detail of one item, or ``None`` if it does not exist."""
        with self._read() as conn:
            items = ItemsRepo(conn)
            item = items.get(item_id)
            if item is None:
                return None
            tags = TagsRepo(conn).for_item(item_id)
            classifications = ClassificationRepo(conn).current_for_items([item_id]).get(
                item_id, []
            )
            transcripts = {
                t.media_id: t
                for t in TranscriptsRepo(conn).current_for_items([item_id]).get(item_id, [])
            }
            media = [
                MediaView(m, transcripts.get(m.id)) for m in MediaRepo(conn).for_item(item_id)
            ]
            links_repo = LinksRepo(conn)
            links = links_repo.for_items([item_id]).get(item_id, [])
            fetches = links_repo.latest_ok_fetches([link.id for link in links])
            return ItemDetail(
                item=_item_view(item, tags, classifications, None),
                instagram=items.instagram_detail(item_id),
                telegram=items.telegram_detail(item_id),
                tags=tags,
                media=media,
                summary=SummariesRepo(conn).latest(item_id),
                links=[LinkView(link, fetches.get(link.id)) for link in links],
                classifications=classifications,
            )

    def tags(
        self, kind: TagKind | None = None, source: str | None = None, limit: int = 100
    ) -> list[TagCount]:
        """Return the most used tags with item counts."""
        with self._read() as conn:
            return TagsRepo(conn).counts(kind=kind, source=source, limit=limit)

    def source_details(
        self, item_ids: list[int]
    ) -> dict[int, tuple[InstagramDetail | None, TelegramDetail | None, list[Media]]]:
        """Return per-source detail rows and media of several items (one snapshot).

        Returns:
            ``{item_id: (instagram_detail, telegram_detail, media)}``.
        """
        if not item_ids:
            return {}
        with self._read() as conn:
            items = ItemsRepo(conn)
            media = MediaRepo(conn).for_items(item_ids)
            return {
                item_id: (
                    items.instagram_detail(item_id),
                    items.telegram_detail(item_id),
                    media.get(item_id, []),
                )
                for item_id in item_ids
            }

    def tag_counts_by_source(
        self, kind: TagKind | None = "hashtag", limit: int = 100
    ) -> list[dict[str, object]]:
        """Return the most used tags with total and per-source item counts.

        Returns:
            ``[{"kind", "tag", "count", "instagram", "telegram"}, ...]`` ordered
            by ``count`` (descending), then name.
        """
        where = "WHERE t.kind = ?" if kind is not None else ""
        params: list[object] = [kind] if kind is not None else []
        params.append(limit)
        with self._read() as conn:
            rows = conn.execute(
                "SELECT t.kind, t.name, count(*) AS n, "
                "sum(i.source = 'instagram') AS ig, sum(i.source = 'telegram') AS tg "
                "FROM item_tags AS it JOIN tags AS t ON t.id = it.tag_id "
                f"JOIN items AS i ON i.id = it.item_id {where} "
                "GROUP BY t.id ORDER BY n DESC, t.name LIMIT ?",
                params,
            ).fetchall()
        return [
            {"kind": r[0], "tag": r[1], "count": r[2], "instagram": r[3] or 0,
             "telegram": r[4] or 0}
            for r in rows
        ]

    def item_id_for(self, source: str, external_id: str) -> int | None:
        """Return the id of the item with ``(source, external_id)``, if any."""
        with self._read() as conn:
            row = conn.execute(
                "SELECT id FROM items WHERE source = ? AND external_id = ?",
                (source, external_id),
            ).fetchone()
        return int(row[0]) if row else None

    def telegram_item_id(self, message_id: int, chat_id: int | None = None) -> int | None:
        """Return the newest item for a Telegram ``message_id`` (optionally in one chat)."""
        sql = "SELECT item_id FROM telegram_messages WHERE message_id = ?"
        params: list[object] = [message_id]
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(chat_id)
        with self._read() as conn:
            row = conn.execute(sql + " ORDER BY item_id DESC LIMIT 1", params).fetchone()
        return int(row[0]) if row else None

    def cursor_after(
        self, item_filter: ItemFilter | None, offset: int
    ) -> tuple[str | None, bool]:
        """Translate a (deprecated) row offset into a keyset cursor.

        Args:
            item_filter: Selection criteria of the listing.
            offset: Number of leading items to skip.

        Returns:
            ``(cursor, exhausted)``: the cursor positioned after ``offset``
            items (``None`` for ``offset == 0``) and whether fewer than
            ``offset`` items exist (the requested page is then empty).
        """
        if offset <= 0:
            return None, False
        position: tuple[str, int] | None = None
        remaining = offset
        with self._read() as conn:
            while remaining > 0:
                batch = min(remaining, MAX_PAGE_SIZE)
                flt = build_filter(item_filter)
                where, params = flt.where_with_fts_subquery()
                if position is not None:
                    where.append("(i.sort_at, i.id) < (?, ?)")
                    params.extend(position)
                sql = "SELECT i.sort_at, i.id FROM items AS i"
                if where:
                    sql += " WHERE " + " AND ".join(where)
                sql += " ORDER BY i.sort_at DESC, i.id DESC LIMIT ?"
                rows = conn.execute(sql, [*params, batch]).fetchall()
                if len(rows) < batch:
                    return None, True
                position = (rows[-1][0], rows[-1][1])
                remaining -= batch
        assert position is not None
        return encode_cursor(*position), False

    def iter_items(
        self, item_filter: ItemFilter | None = None, batch_size: int = MAX_PAGE_SIZE
    ) -> Iterator[ItemView]:
        """Yield all matching items, newest first, on one consistent snapshot."""
        with self._read() as conn:
            position: tuple[str, int] | None = None
            while True:
                page = self._search(conn, item_filter, position, batch_size, with_snippet=False)
                yield from page.items
                if page.next_cursor is None:
                    return
                position = decode_cursor(page.next_cursor)

    def export(
        self,
        item_filter: ItemFilter | None,
        fmt: Literal["json", "csv"] = "json",
        out: str | Path | IO[str] = "-",
        limit: int | None = None,
    ) -> int:
        """Export matching items as a JSON array or CSV.

        CSV columns: id, source, external_id, kind, created_at, collected_at,
        author, url, text, tags (space separated), labels
        (``taxonomy:label|label; ...``).

        Args:
            item_filter: Selection criteria.
            fmt: ``json`` or ``csv``.
            out: File path or an open text stream.
            limit: Export at most this many items (newest first); ``None``: all.

        Returns:
            Number of exported items.

        Raises:
            ValueError: For an unknown format.
        """
        if fmt not in ("json", "csv"):
            raise ValueError(f"Unsupported export format: {fmt!r}")
        if isinstance(out, (str, Path)):
            with open(out, "w", encoding="utf-8", newline="") as handle:
                return self._export(item_filter, fmt, handle, limit)
        return self._export(item_filter, fmt, out, limit)

    def _limited(self, item_filter: ItemFilter | None, limit: int | None) -> Iterator[ItemView]:
        """Yield matching items, stopping after ``limit``."""
        for index, view in enumerate(self.iter_items(item_filter)):
            if limit is not None and index >= limit:
                return
            yield view

    def _export(
        self, item_filter: ItemFilter | None, fmt: str, handle: IO[str], limit: int | None = None
    ) -> int:
        """Write the export to an open stream."""
        count = 0
        if fmt == "json":
            handle.write("[")
            for view in self._limited(item_filter, limit):
                handle.write(",\n" if count else "\n")
                handle.write(json.dumps(view.to_dict(), ensure_ascii=False))
                count += 1
            handle.write("\n]\n" if count else "]\n")
            return count
        writer = csv.writer(handle)
        writer.writerow(
            ["id", "source", "external_id", "kind", "created_at", "collected_at", "author",
             "url", "text", "tags", "labels"]
        )
        for view in self._limited(item_filter, limit):
            data = view.to_dict()
            writer.writerow(
                [
                    view.id, view.source, view.external_id, view.kind, data["created_at"] or "",
                    data["collected_at"], view.author or "", view.url or "", view.text or "",
                    " ".join(view.tags),
                    "; ".join(f"{tx}:{'|'.join(lbs)}" for tx, lbs in view.labels.items()),
                ]
            )
            count += 1
        return count


def _item_view(
    item: Item,
    tags: list[Tag],
    classifications: list[CurrentClassification],
    snippet: str | None,
) -> ItemView:
    """Combine an item row with its tags and current labels."""
    return ItemView(
        id=item.id,
        source=item.source,
        external_id=item.external_id,
        kind=item.kind,
        text=item.text,
        author=item.author,
        url=item.url,
        created_at=item.created_at,
        collected_at=item.collected_at,
        sort_at=item.sort_at,
        tags=tuple(tag.display for tag in tags),
        labels={c.taxonomy: c.labels for c in classifications},
        snippet=snippet,
    )
