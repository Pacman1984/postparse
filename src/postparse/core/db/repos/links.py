"""Links found in items and their fetched contents."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from postparse.core.db.models import FetchStatus, Link, LinkFetch
from postparse.core.db.repos.search import SearchRepo
from postparse.core.timeutil import from_db_ts, to_db_ts
from postparse.core.urls import normalize_url, url_domain

__all__ = ["LEGACY_FETCHER", "LinkEnrichmentState", "LinksRepo"]

logger = logging.getLogger(__name__)

#: Fetcher name of the link texts migrated from schema v1.
LEGACY_FETCHER = "legacy_v1"


@dataclass(frozen=True, slots=True)
class LinkEnrichmentState:
    """Fetch history summary of one linked URL (see :meth:`LinksRepo.enrichment_states`).

    Attributes:
        link: The link.
        last_fetcher: Fetcher of the newest non-legacy fetch (``None``: never fetched).
        last_status: Its status.
        last_fetched_at: Its time.
        failures: Non-legacy ``error`` fetches since the last non-error fetch.
        has_ok: A non-legacy fetch succeeded at some point.
        has_legacy_ok: A ``legacy_v1`` fetch with text exists.
    """

    link: Link
    last_fetcher: str | None
    last_status: FetchStatus | None
    last_fetched_at: datetime | None
    failures: int
    has_ok: bool
    has_legacy_ok: bool


class LinksRepo:
    """Access to ``links``, ``item_links`` and ``link_fetches``.

    Args:
        conn: Open connection; the caller controls the transaction.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ensure(self, url: str) -> int:
        """Return the id of the link for ``url`` (normalized), creating it if needed.

        Raises:
            ValueError: If ``url`` is not an absolute http(s) URL.
        """
        normalized = normalize_url(url)
        row = self.conn.execute(
            "INSERT INTO links (url, domain) VALUES (?, ?) "
            "ON CONFLICT (url) DO UPDATE SET domain = excluded.domain RETURNING id",
            (normalized, url_domain(normalized)),
        ).fetchone()
        return int(row[0])

    def get(self, link_id: int) -> Link | None:
        """Return one link or ``None``."""
        row = self.conn.execute("SELECT id, url, domain FROM links WHERE id = ?", (link_id,))
        found = row.fetchone()
        return Link(found[0], found[1], found[2]) if found else None

    def set_item_links(self, item_id: int, urls: Iterable[str], *, refresh: bool = True) -> None:
        """Replace an item's links (in order; duplicates after normalization dropped).

        Invalid URLs are skipped with a debug log message.

        Args:
            item_id: Item id.
            urls: URLs in order of appearance.
            refresh: Refresh the item's search document.
        """
        self.conn.execute("DELETE FROM item_links WHERE item_id = ?", (item_id,))
        position = 0
        seen: set[int] = set()
        for url in urls:
            try:
                link_id = self.ensure(url)
            except ValueError:
                logger.debug("Skipping invalid URL %r for item %s", url, item_id)
                continue
            if link_id in seen:
                continue
            seen.add(link_id)
            self.conn.execute(
                "INSERT INTO item_links (item_id, link_id, position) VALUES (?, ?, ?)",
                (item_id, link_id, position),
            )
            position += 1
        if refresh:
            SearchRepo(self.conn).refresh([item_id])

    def for_items(self, item_ids: Sequence[int]) -> dict[int, list[Link]]:
        """Return the links of several items, ordered by position."""
        result: dict[int, list[Link]] = {}
        if not item_ids:
            return result
        rows = self.conn.execute(
            "SELECT il.item_id, l.id, l.url, l.domain FROM item_links AS il "
            "JOIN links AS l ON l.id = il.link_id "
            "WHERE il.item_id IN (SELECT value FROM json_each(?)) "
            "ORDER BY il.item_id, il.position",
            (json.dumps(list(item_ids)),),
        ).fetchall()
        for row in rows:
            result.setdefault(row[0], []).append(Link(row[1], row[2], row[3]))
        return result

    def add_fetch(
        self,
        link_id: int,
        *,
        fetcher: str,
        status: FetchStatus,
        http_status: int | None = None,
        title: str | None = None,
        text: str | None = None,
        metadata: Any = None,
        error: str | None = None,
        fetched_at: datetime | None = None,
    ) -> int:
        """Record a fetch attempt; refreshes search docs of linking items on success.

        Returns:
            Fetch id.
        """
        columns = ["link_id", "fetcher", "status", "http_status", "title", "text",
                   "metadata", "error"]
        values: list[object] = [
            link_id, fetcher, status, http_status, title, text,
            json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
            error,
        ]
        if fetched_at is not None:
            columns.append("fetched_at")
            values.append(to_db_ts(fetched_at))
        placeholders = ", ".join("?" for _ in columns)
        row = self.conn.execute(
            f"INSERT INTO link_fetches ({', '.join(columns)}) VALUES ({placeholders}) "
            "RETURNING id",
            values,
        ).fetchone()
        if status == "ok":
            item_ids = [
                r[0]
                for r in self.conn.execute(
                    "SELECT item_id FROM item_links WHERE link_id = ?", (link_id,)
                ).fetchall()
            ]
            SearchRepo(self.conn).refresh(item_ids)
        return int(row[0])

    def latest_ok_fetch(self, link_id: int) -> LinkFetch | None:
        """Return the newest successful fetch of a link."""
        row = self.conn.execute(
            "SELECT * FROM link_fetches WHERE link_id = ? AND status = 'ok' "
            "ORDER BY fetched_at DESC, id DESC LIMIT 1",
            (link_id,),
        ).fetchone()
        return LinkFetch.from_row(row) if row else None

    def latest_ok_fetches(self, link_ids: Sequence[int]) -> dict[int, LinkFetch]:
        """Return the newest successful fetch for several links."""
        if not link_ids:
            return {}
        rows = self.conn.execute(
            "SELECT lf.* FROM links AS l JOIN link_fetches AS lf ON lf.id = ("
            " SELECT lf2.id FROM link_fetches AS lf2 WHERE lf2.link_id = l.id"
            " AND lf2.status = 'ok' ORDER BY lf2.fetched_at DESC, lf2.id DESC LIMIT 1)"
            " WHERE l.id IN (SELECT value FROM json_each(?))",
            (json.dumps(list(link_ids)),),
        ).fetchall()
        return {row["link_id"]: LinkFetch.from_row(row) for row in rows}

    def links_needing_fetch(
        self,
        *,
        fetcher: str | None = None,
        limit: int = 100,
        include_failed: bool = False,
    ) -> list[Link]:
        """Return linked URLs without a successful fetch.

        Args:
            fetcher: Only consider fetches by this fetcher (``None``: any).
            limit: Maximum rows.
            include_failed: Also return links whose earlier attempts failed or
                were skipped (default: only never-attempted links).

        Returns:
            Links referenced by at least one item, oldest first.
        """
        fetcher_clause = "AND lf.fetcher = :fetcher" if fetcher is not None else ""
        status_clause = "AND lf.status = 'ok'" if include_failed else ""
        rows = self.conn.execute(
            f"""
            SELECT l.id, l.url, l.domain FROM links AS l
            WHERE EXISTS (SELECT 1 FROM item_links AS il WHERE il.link_id = l.id)
              AND NOT EXISTS (
                  SELECT 1 FROM link_fetches AS lf
                  WHERE lf.link_id = l.id {fetcher_clause} {status_clause})
            ORDER BY l.id LIMIT :limit
            """,
            {"fetcher": fetcher, "limit": limit},
        ).fetchall()
        return [Link(row[0], row[1], row[2]) for row in rows]

    def enrichment_states(
        self,
        *,
        source: str | None = None,
        domains: Sequence[str] | None = None,
    ) -> list[LinkEnrichmentState]:
        """Summarize the fetch history of every linked URL (legacy fetches separated).

        Args:
            source: Only links of items from this source (``None``: all).
            domains: Only links on these domains (``links.domain``; ``None``: all).

        Returns:
            States ordered by link id; only links referenced by an item.
        """
        params: dict[str, Any] = {"legacy": LEGACY_FETCHER, "source": source,
                                  "domains": json.dumps(list(domains or []))}
        domain_clause = (
            "AND l.domain IN (SELECT value FROM json_each(:domains))" if domains else ""
        )
        rows = self.conn.execute(
            f"""
            WITH scope AS (
                SELECT l.id, l.url, l.domain,
                       (SELECT lf.id FROM link_fetches AS lf
                         WHERE lf.link_id = l.id AND lf.fetcher <> :legacy
                         ORDER BY lf.fetched_at DESC, lf.id DESC LIMIT 1) AS last_id,
                       (SELECT max(lf.fetched_at) FROM link_fetches AS lf
                         WHERE lf.link_id = l.id AND lf.fetcher <> :legacy
                           AND lf.status <> 'error') AS last_good_at
                  FROM links AS l
                 WHERE EXISTS (
                        SELECT 1 FROM item_links AS il JOIN items AS i ON i.id = il.item_id
                         WHERE il.link_id = l.id AND (:source IS NULL OR i.source = :source))
                   {domain_clause}
            )
            SELECT s.id, s.url, s.domain, lf.fetcher, lf.status, lf.fetched_at,
                   (SELECT count(*) FROM link_fetches AS e
                     WHERE e.link_id = s.id AND e.fetcher <> :legacy AND e.status = 'error'
                       AND e.fetched_at > coalesce(s.last_good_at, '')) AS failures,
                   EXISTS (SELECT 1 FROM link_fetches AS o
                            WHERE o.link_id = s.id AND o.fetcher <> :legacy
                              AND o.status = 'ok') AS has_ok,
                   EXISTS (SELECT 1 FROM link_fetches AS o
                            WHERE o.link_id = s.id AND o.fetcher = :legacy
                              AND o.status = 'ok') AS has_legacy_ok
              FROM scope AS s LEFT JOIN link_fetches AS lf ON lf.id = s.last_id
             ORDER BY s.id
            """,
            params,
        ).fetchall()
        return [
            LinkEnrichmentState(
                link=Link(row[0], row[1], row[2]),
                last_fetcher=row[3],
                last_status=row[4],
                last_fetched_at=from_db_ts(row[5]) if row[5] else None,
                failures=int(row[6]),
                has_ok=bool(row[7]),
                has_legacy_ok=bool(row[8]),
            )
            for row in rows
        ]

    def items_for_link(self, link_id: int) -> list[int]:
        """Return the ids of the items linking to ``link_id``."""
        rows = self.conn.execute(
            "SELECT item_id FROM item_links WHERE link_id = ? ORDER BY item_id", (link_id,)
        ).fetchall()
        return [int(row[0]) for row in rows]

    def legacy_text_settled(self, item_id: int) -> bool:
        """True if every link of the item has a fresh (non-legacy) result.

        A link counts as settled when a non-legacy fetch succeeded or when its
        newest non-legacy fetch was ``skipped`` by the ``instagram`` fetcher
        (Instagram links never had scraped text). Items without links are
        never settled.
        """
        row = self.conn.execute(
            """
            SELECT count(*),
                   sum(EXISTS (SELECT 1 FROM link_fetches AS o
                                WHERE o.link_id = il.link_id AND o.fetcher <> :legacy
                                  AND (o.status = 'ok'
                                       OR (o.status = 'skipped' AND o.fetcher = 'instagram'))))
              FROM item_links AS il WHERE il.item_id = :item
            """,
            {"legacy": LEGACY_FETCHER, "item": item_id},
        ).fetchone()
        total, settled = int(row[0]), int(row[1] or 0)
        return total > 0 and settled == total
