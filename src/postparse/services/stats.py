"""Database statistics for the schema v2 database (``postparse stats``).

One read-only snapshot with counts per source/kind, top tags, the
transcription queue, link enrichment status, classification coverage per
taxonomy, summaries and file/schema information.

Example:
    >>> stats = collect_stats(Database(settings.db_path, migrate=False))
    >>> stats.items_total, stats.schema_version
    (10432, 2)
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from postparse.core.db.connection import Database
from postparse.core.db.migrate import latest_version
from postparse.core.db.models import TagCount
from postparse.core.db.repos import ClassificationRepo, MediaRepo, TagsRepo

__all__ = ["DatabaseStats", "SourceStats", "TaxonomyStats", "collect_stats", "database_size"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SourceStats:
    """Item counts of one source.

    Attributes:
        source: ``instagram`` or ``telegram``.
        items: Number of items.
        kinds: ``{kind: n}``.
        oldest: Oldest ``sort_at`` (ISO string) or ``None``.
        newest: Newest ``sort_at`` (ISO string) or ``None``.
    """

    source: str
    items: int = 0
    kinds: dict[str, int] = field(default_factory=dict)
    oldest: str | None = None
    newest: str | None = None


@dataclass(slots=True)
class TaxonomyStats:
    """Classification coverage of one stored taxonomy.

    Attributes:
        classified_items: Items with a current (ok / no_labels) result.
        results: Stored result rows per status (all runs).
        top_labels: ``[(label, items)]`` over current results.
        pending_default: Items ``classify run`` would pick (default scope).
        pending_backfill: Items ``classify run --backfill`` would pick.
    """

    name: str
    mode: str
    version: int
    is_legacy: bool
    labels: int
    runs: int = 0
    classified_items: int = 0
    results: dict[str, int] = field(default_factory=dict)
    top_labels: list[tuple[str, int]] = field(default_factory=list)
    pending_default: int = 0
    pending_backfill: int = 0


@dataclass(slots=True)
class DatabaseStats:
    """Snapshot of the database contents.

    Attributes:
        path: Database file.
        size_bytes: File size including ``-wal`` / ``-shm`` files.
        schema_version: ``PRAGMA user_version``.
        latest_schema_version: Highest known migration.
        items_total: Number of items.
        sources: Per-source counts.
        tags_distinct: Number of distinct tags in use.
        top_hashtags: Most used hashtags.
        top_mentions: Most used mentions.
        media: ``{media_type: n}``.
        transcript_status: ``{source: {status: n}}``.
        transcription_due: Media in the queue that are due now, per source.
        transcription_exhausted: Media that ran out of attempts, per source.
        transcripts: Stored transcripts.
        transcribed_seconds: Total transcribed audio.
        items_with_transcript: Items with at least one transcript.
        links: Distinct links.
        items_with_links: Items with at least one link.
        link_status: ``{status: n}`` of the newest fetch per link (``never``
            for links without any fetch).
        link_fetchers: ``{fetcher: n}`` of the newest fetch per link.
        summaries: Stored summaries.
        items_with_summary: Items with at least one summary.
        taxonomies: Classification coverage per stored taxonomy.
    """

    path: str
    size_bytes: int
    schema_version: int
    latest_schema_version: int
    items_total: int = 0
    sources: list[SourceStats] = field(default_factory=list)
    tags_distinct: int = 0
    top_hashtags: list[tuple[str, int]] = field(default_factory=list)
    top_mentions: list[tuple[str, int]] = field(default_factory=list)
    media: dict[str, int] = field(default_factory=dict)
    transcript_status: dict[str, dict[str, int]] = field(default_factory=dict)
    transcription_due: dict[str, int] = field(default_factory=dict)
    transcription_exhausted: dict[str, int] = field(default_factory=dict)
    transcripts: int = 0
    transcribed_seconds: float = 0.0
    items_with_transcript: int = 0
    links: int = 0
    items_with_links: int = 0
    link_status: dict[str, int] = field(default_factory=dict)
    link_fetchers: dict[str, int] = field(default_factory=dict)
    summaries: int = 0
    items_with_summary: int = 0
    taxonomies: list[TaxonomyStats] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict."""
        return asdict(self)


def database_size(path: str | Path) -> int:
    """Return the size of a SQLite file plus its ``-wal`` / ``-shm`` companions."""
    base = Path(path)
    total = 0
    for candidate in (base, base.with_name(base.name + "-wal"), base.with_name(base.name + "-shm")):
        try:
            total += candidate.stat().st_size
        except OSError:
            continue
    return total


def _iso(value: str | None) -> str | None:
    """Return a canonical DB timestamp as an ISO string (``None`` stays ``None``)."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return value


def _pairs(tags: list[TagCount]) -> list[tuple[str, int]]:
    """Return ``[(#name / @name, count)]``."""
    return [(("#" if tag.kind == "hashtag" else "@") + tag.name, tag.count) for tag in tags]


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    """Return the first column of the first row as ``int``."""
    return int(conn.execute(sql, params).fetchone()[0] or 0)


def collect_stats(
    db: Database,
    *,
    top_tags: int = 10,
    top_labels: int = 5,
    max_attempts: int = 5,
    with_pending: bool = True,
) -> DatabaseStats:
    """Collect statistics on one read snapshot.

    Args:
        db: Database handle (opened without migrations for read-only use).
        top_tags: Number of hashtags / mentions to list.
        top_labels: Number of labels to list per taxonomy.
        max_attempts: Transcription attempt limit (``[transcription] max_attempts``).
        with_pending: Compute pending classification counts per taxonomy.

    Returns:
        Statistics snapshot.
    """
    with db.read() as conn:
        version = _scalar(conn, "PRAGMA user_version")
        stats = DatabaseStats(
            path=str(db.path),
            size_bytes=database_size(db.path),
            schema_version=version,
            latest_schema_version=latest_version(),
        )
        _items(conn, stats)
        tags = TagsRepo(conn)
        stats.tags_distinct = _scalar(conn, "SELECT count(DISTINCT tag_id) FROM item_tags")
        stats.top_hashtags = _pairs(tags.counts(kind="hashtag", limit=top_tags))
        stats.top_mentions = _pairs(tags.counts(kind="mention", limit=top_tags))
        _media(conn, stats, max_attempts)
        _links(conn, stats)
        stats.summaries = _scalar(conn, "SELECT count(*) FROM summaries")
        stats.items_with_summary = _scalar(conn, "SELECT count(DISTINCT item_id) FROM summaries")
        _classification(conn, stats, top_labels, with_pending)
    return stats


def _items(conn: sqlite3.Connection, stats: DatabaseStats) -> None:
    """Fill item counts per source and kind."""
    by_source: dict[str, SourceStats] = {}
    for row in conn.execute(
        "SELECT source, count(*), min(sort_at), max(sort_at) FROM items GROUP BY source "
        "ORDER BY source"
    ).fetchall():
        by_source[row[0]] = SourceStats(row[0], int(row[1]), {}, _iso(row[2]), _iso(row[3]))
    for row in conn.execute(
        "SELECT source, kind, count(*) FROM items GROUP BY source, kind ORDER BY source, 3 DESC"
    ).fetchall():
        by_source[row[0]].kinds[row[1]] = int(row[2])
    stats.sources = list(by_source.values())
    stats.items_total = sum(s.items for s in stats.sources)


def _media(conn: sqlite3.Connection, stats: DatabaseStats, max_attempts: int) -> None:
    """Fill media and transcription queue counts."""
    stats.media = {
        row[0]: int(row[1])
        for row in conn.execute(
            "SELECT media_type, count(*) FROM media GROUP BY media_type ORDER BY 2 DESC"
        ).fetchall()
    }
    queue = MediaRepo(conn).queue_stats(max_attempts=max_attempts)
    status: dict[str, dict[str, int]] = {}
    for (source, state), n in queue["counts"].items():
        status.setdefault(source, {})[state] = n
    stats.transcript_status = status
    stats.transcription_due = dict(queue["due"])
    stats.transcription_exhausted = dict(queue["exhausted"])
    stats.transcripts = queue["transcripts"]
    stats.transcribed_seconds = queue["transcribed_seconds"]
    stats.items_with_transcript = _scalar(
        conn,
        "SELECT count(DISTINCT m.item_id) FROM media AS m "
        "JOIN transcripts AS t ON t.media_id = m.id",
    )


def _links(conn: sqlite3.Connection, stats: DatabaseStats) -> None:
    """Fill link and newest-fetch counts."""
    stats.links = _scalar(conn, "SELECT count(*) FROM links")
    stats.items_with_links = _scalar(conn, "SELECT count(DISTINCT item_id) FROM item_links")
    status: dict[str, int] = {}
    fetchers: dict[str, int] = {}
    rows = conn.execute(
        "SELECT f.fetcher, f.status FROM links AS l "
        "LEFT JOIN link_fetches AS f ON f.id = ("
        " SELECT f2.id FROM link_fetches AS f2 WHERE f2.link_id = l.id "
        " ORDER BY f2.fetched_at DESC, f2.id DESC LIMIT 1)"
    ).fetchall()
    for fetcher, state in rows:
        key = state or "never"
        status[key] = status.get(key, 0) + 1
        if fetcher:
            fetchers[fetcher] = fetchers.get(fetcher, 0) + 1
    stats.link_status = dict(sorted(status.items(), key=lambda kv: -kv[1]))
    stats.link_fetchers = dict(sorted(fetchers.items(), key=lambda kv: -kv[1]))


def _classification(
    conn: sqlite3.Connection, stats: DatabaseStats, top_labels: int, with_pending: bool
) -> None:
    """Fill per-taxonomy coverage."""
    repo = ClassificationRepo(conn)
    counters = repo.taxonomy_stats()
    for tx in repo.list_taxonomies():
        entry = counters.get(tx.id, {})
        info = TaxonomyStats(
            name=tx.name,
            mode=tx.mode,
            version=tx.version,
            is_legacy=tx.is_legacy,
            labels=len(tx.labels),
            runs=entry.get("runs", 0),
            classified_items=entry.get("classified_items", 0),
            results={k: entry.get(k, 0) for k in ("ok", "no_labels", "error")},
        )
        info.top_labels = [
            (row[0], int(row[1]))
            for row in conn.execute(
                "SELECT rl.label, count(*) FROM v_current_classification AS v "
                "JOIN result_labels AS rl ON rl.result_id = v.result_id "
                "WHERE v.taxonomy_id = ? GROUP BY rl.label ORDER BY 2 DESC, 1 LIMIT ?",
                (tx.id, top_labels),
            ).fetchall()
        ]
        if with_pending:
            info.pending_default = len(repo.pending_items(tx.id, scope="default"))
            info.pending_backfill = len(repo.pending_items(tx.id, scope="backfill"))
        stats.taxonomies.append(info)
