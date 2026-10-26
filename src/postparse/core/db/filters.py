"""Translate :class:`ItemFilter` into SQL and build safe FTS5 queries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from postparse.core.db.models import ItemFilter
from postparse.core.db.repos.tags import parse_tag_query
from postparse.core.timeutil import to_db_ts

__all__ = ["FilterSQL", "build_filter", "fts_query"]

_TOKEN_RE = re.compile(r'"([^"]*)"|(\S+)')


def _quote(term: str) -> str:
    """Quote a term as an FTS5 string (embedded quotes doubled)."""
    return '"' + term.replace('"', '""') + '"'


def fts_query(q: str | None) -> str | None:
    """Turn user input into a safe FTS5 MATCH expression.

    Every term is quoted, so FTS5 operators and column filters in the input
    are treated as text. ``"two words"`` stays a phrase, ``word*`` becomes a
    prefix query. Terms are combined with AND.

    Args:
        q: Raw user query.

    Returns:
        MATCH expression, or ``None`` if the input contains no searchable term.
    """
    if not q:
        return None
    parts: list[str] = []
    for match in _TOKEN_RE.finditer(q):
        phrase, word = match.group(1), match.group(2)
        if phrase is not None:
            if any(ch.isalnum() for ch in phrase):
                parts.append(_quote(phrase))
            continue
        prefix = word.endswith("*")
        term = word.rstrip("*").replace('"', "")
        if not any(ch.isalnum() for ch in term):
            continue
        parts.append(_quote(term) + ("*" if prefix else ""))
    return " ".join(parts) if parts else None


def _bound(value: datetime | date | str, *, upper: bool) -> tuple[str, str]:
    """Return ``(operator, timestamp)`` for a date filter bound."""
    if isinstance(value, date) and not isinstance(value, datetime):
        start = datetime.combine(value, time.min, tzinfo=UTC)
        if upper:
            return "<", to_db_ts(start + timedelta(days=1))
        return ">=", to_db_ts(start)
    return ("<=" if upper else ">="), to_db_ts(value, assume_tz=UTC)


@dataclass(slots=True)
class FilterSQL:
    """SQL fragments for an item filter over ``items AS i``.

    Attributes:
        where: Conditions to AND together (never contains the FTS MATCH).
        params: Positional parameters for ``where`` in order.
        match: Safe FTS5 expression, or ``None`` when no text query is given.
    """

    where: list[str] = field(default_factory=list)
    params: list[object] = field(default_factory=list)
    match: str | None = None

    def where_with_fts_subquery(self) -> tuple[list[str], list[object]]:
        """Return conditions including the text query as an ``IN`` subquery."""
        where, params = list(self.where), list(self.params)
        if self.match is not None:
            where.append("i.id IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)")
            params.append(self.match)
        return where, params


def build_filter(item_filter: ItemFilter | None) -> FilterSQL:
    """Build SQL conditions for ``item_filter`` against ``items AS i``.

    Args:
        item_filter: Filter; ``None`` matches everything.

    Returns:
        SQL fragments and parameters.
    """
    sql = FilterSQL()
    if item_filter is None:
        return sql
    f = item_filter
    if f.source is not None:
        sql.where.append("i.source = ?")
        sql.params.append(f.source)
    if f.kinds:
        sql.where.append(f"i.kind IN ({', '.join('?' for _ in f.kinds)})")
        sql.params.extend(f.kinds)
    if f.authors:
        sql.where.append(f"i.author IN ({', '.join('?' for _ in f.authors)})")
        sql.params.extend(f.authors)
    if f.tags:
        conditions: list[str] = []
        for raw in f.tags:
            kind, name = parse_tag_query(raw)
            if not name:
                continue
            if kind is None:
                conditions.append("t.name = ?")
                sql.params.append(name)
            else:
                conditions.append("(t.kind = ? AND t.name = ?)")
                sql.params.extend([kind, name])
        if conditions:
            sql.where.append(
                "i.id IN (SELECT it.item_id FROM item_tags AS it "
                "JOIN tags AS t ON t.id = it.tag_id WHERE " + " OR ".join(conditions) + ")"
            )
    if f.date_from is not None:
        op, ts = _bound(f.date_from, upper=False)
        sql.where.append(f"i.sort_at {op} ?")
        sql.params.append(ts)
    if f.date_to is not None:
        op, ts = _bound(f.date_to, upper=True)
        sql.where.append(f"i.sort_at {op} ?")
        sql.params.append(ts)
    if f.labels is not None:
        clause = (
            "i.id IN (SELECT v.item_id FROM v_current_classification AS v "
            "JOIN taxonomies AS tx ON tx.id = v.taxonomy_id"
        )
        if f.labels.labels:
            clause += (
                " JOIN result_labels AS rl ON rl.result_id = v.result_id"
                f" WHERE tx.name = ? AND rl.label IN ({', '.join('?' for _ in f.labels.labels)}))"
            )
            sql.params.extend([f.labels.taxonomy, *f.labels.labels])
        else:
            clause += " WHERE tx.name = ? AND v.status = 'ok')"
            sql.params.append(f.labels.taxonomy)
        sql.where.append(clause)
    if f.has_transcript is not None:
        exists = (
            "EXISTS (SELECT 1 FROM media AS m JOIN transcripts AS tr ON tr.media_id = m.id "
            "WHERE m.item_id = i.id)"
        )
        sql.where.append(exists if f.has_transcript else f"NOT {exists}")
    sql.match = fts_query(f.q)
    return sql
