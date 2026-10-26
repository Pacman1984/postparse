"""Hashtags and mentions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence

from postparse.core.db.models import Tag, TagCount, TagKind

__all__ = ["TagsRepo", "normalize_tag_name", "parse_tag_query"]


def normalize_tag_name(name: str) -> str:
    """Normalize a tag name: strip whitespace and ``#``/``@``, lowercase.

    Args:
        name: Raw tag, for example ``"#Pasta"``.

    Returns:
        Normalized name (``"pasta"``); may be empty.
    """
    return name.strip().lstrip("#@").strip().lower()


def parse_tag_query(value: str) -> tuple[TagKind | None, str]:
    """Split a user tag filter into ``(kind, name)``.

    ``#x`` selects hashtags, ``@x`` mentions, a bare name either kind.
    """
    stripped = value.strip()
    kind: TagKind | None = None
    if stripped.startswith("#"):
        kind = "hashtag"
    elif stripped.startswith("@"):
        kind = "mention"
    return kind, normalize_tag_name(stripped)


class TagsRepo:
    """Access to ``tags`` and ``item_tags``.

    Args:
        conn: Open connection; the caller controls the transaction.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ensure(self, kind: TagKind, name: str) -> int:
        """Return the id of tag ``(kind, name)``, creating it if needed.

        Raises:
            ValueError: If the normalized name is empty.
        """
        normalized = normalize_tag_name(name)
        if not normalized:
            raise ValueError(f"Empty tag name: {name!r}")
        row = self.conn.execute(
            "INSERT INTO tags (kind, name) VALUES (?, ?) "
            "ON CONFLICT (kind, name) DO UPDATE SET kind = excluded.kind RETURNING id",
            (kind, normalized),
        ).fetchone()
        return int(row[0])

    def set_item_tags(
        self,
        item_id: int,
        *,
        hashtags: Iterable[str] | None = None,
        mentions: Iterable[str] | None = None,
    ) -> None:
        """Replace an item's hashtags and/or mentions.

        Args:
            item_id: Item id.
            hashtags: New hashtag set; ``None`` keeps the current hashtags.
            mentions: New mention set; ``None`` keeps the current mentions.
        """
        for kind, names in (("hashtag", hashtags), ("mention", mentions)):
            if names is None:
                continue
            self.conn.execute(
                "DELETE FROM item_tags WHERE item_id = ? "
                "AND tag_id IN (SELECT id FROM tags WHERE kind = ?)",
                (item_id, kind),
            )
            tag_ids = {
                self.ensure(kind, name)  # type: ignore[arg-type]
                for name in names
                if normalize_tag_name(name)
            }
            self.conn.executemany(
                "INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                [(item_id, tag_id) for tag_id in sorted(tag_ids)],
            )

    def for_item(self, item_id: int) -> list[Tag]:
        """Return an item's tags ordered by kind and name."""
        return self.for_items([item_id]).get(item_id, [])

    def for_items(self, item_ids: Sequence[int]) -> dict[int, list[Tag]]:
        """Return tags for several items in one query.

        Returns:
            ``{item_id: [Tag, ...]}``; items without tags are absent.
        """
        result: dict[int, list[Tag]] = {}
        if not item_ids:
            return result
        rows = self.conn.execute(
            "SELECT it.item_id, t.id, t.kind, t.name FROM item_tags AS it "
            "JOIN tags AS t ON t.id = it.tag_id "
            "WHERE it.item_id IN (SELECT value FROM json_each(?)) "
            "ORDER BY it.item_id, t.kind, t.name",
            (json.dumps(list(item_ids)),),
        ).fetchall()
        for row in rows:
            result.setdefault(row[0], []).append(Tag(row[1], row[2], row[3]))
        return result

    def counts(
        self, kind: TagKind | None = None, source: str | None = None, limit: int = 100
    ) -> list[TagCount]:
        """Return the most used tags with item counts.

        Args:
            kind: Restrict to hashtags or mentions.
            source: Restrict counting to items of one source.
            limit: Maximum number of tags.

        Returns:
            Tags ordered by count (descending), then name.
        """
        clauses: list[str] = []
        params: list[object] = []
        if kind is not None:
            clauses.append("t.kind = ?")
            params.append(kind)
        if source is not None:
            clauses.append("i.source = ?")
            params.append(source)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.conn.execute(
            "SELECT t.kind, t.name, count(*) AS n FROM item_tags AS it "
            "JOIN tags AS t ON t.id = it.tag_id "
            "JOIN items AS i ON i.id = it.item_id "
            f"{where} GROUP BY t.id ORDER BY n DESC, t.name LIMIT ?",
            params,
        ).fetchall()
        return [TagCount(row[0], row[1], row[2]) for row in rows]
