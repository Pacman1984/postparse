"""One-off migration of a schema v1 database (``social_media.db``) into schema v2.

:func:`migrate_v1` opens the v1 file strictly read-only, builds a fresh v2
database next to the target (``<target>.tmp``), verifies it against expected
values computed from the source with SQL, and only then atomically replaces the
target. Rerunning it produces the same logical content (see
:func:`logical_digest`).

Mapping summary:

* Items: Instagram posts (``external_id`` = shortcode) and Telegram messages
  (``external_id`` = ``"<chat_id>:<message_id>"``) with their detail rows; test
  messages (``chat_id`` 123456 by default) and their analysis rows are dropped.
* Timestamps: Instagram ``created_at`` is naive local time (instaloader
  ``post.date``) interpreted in ``instagram_tz`` with ``fold=0``; all other
  naive v1 timestamps (``fetched_at``, ``saved_at``, ``analyzed_at``) are
  SQLite ``CURRENT_TIMESTAMP`` values, i.e. UTC.
* Tags: Instagram from ``instagram_hashtags``/``instagram_mentions``; Telegram
  re-derived from the message text (:mod:`postparse.core.text`).
* Media: Telegram ``media_urls`` plus orphan files recovered from the
  downloads folder; one pending-transcription ``video`` row per Instagram
  ``GraphVideo`` (the expired CDN URLs are not migrated).
* Links from item text; ``content_expanded`` becomes links (raw URL lists),
  ``link_fetches`` (scraped text of a single-link item) or
  ``legacy_expanded_text`` (everything else), optionally repaired with ftfy.
* Classifications: taxonomies ``topics`` (multi) and ``recipe_legacy``
  (single, legacy), one ``legacy`` run per (classifier, provider, model).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, SupportsFloat, SupportsIndex
from zoneinfo import ZoneInfo

from postparse.core.db.connection import connect
from postparse.core.db.migrate import migrate as run_migrations
from postparse.core.db.models import TaxonomyMode
from postparse.core.db.repos.classification import ClassificationRepo
from postparse.core.db.repos.links import LinksRepo
from postparse.core.db.repos.media import normalize_local_path
from postparse.core.db.repos.search import SearchRepo
from postparse.core.db.repos.tags import normalize_tag_name
from postparse.core.text import extract_hashtags, extract_mentions
from postparse.core.timeutil import to_db_ts, utcnow_ts
from postparse.core.urls import extract_urls, normalize_url

__all__ = [
    "LEGACY_FETCHER",
    "LegacyMigrationError",
    "MigrationReport",
    "logical_digest",
    "migrate_v1",
]

logger = logging.getLogger(__name__)

#: ``link_fetches.fetcher`` of texts imported from v1 ``content_expanded``.
LEGACY_FETCHER = "legacy_v1"

#: Telegram chats whose messages are test fixtures in the real v1 database.
DEFAULT_TEST_CHAT_IDS: tuple[int, ...] = (123456,)

_UTC = ZoneInfo("UTC")

_IG_KIND = {"GraphVideo": "video", "GraphSidecar": "carousel", "GraphImage": "image"}
_TG_KIND = {
    "text": "text",
    "image": "image",
    "photo": "image",
    "video": "video",
    "document": "document",
    "audio": "audio",
    "voice": "audio",
}
_MIME = {
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".png": ("image", "image/png"),
    ".gif": ("image", "image/gif"),
    ".webp": ("image", "image/webp"),
    ".heic": ("image", "image/heic"),
    ".mp4": ("video", "video/mp4"),
    ".mov": ("video", "video/quicktime"),
    ".webm": ("video", "video/webm"),
    ".mkv": ("video", "video/x-matroska"),
    ".mp3": ("audio", "audio/mpeg"),
    ".m4a": ("audio", "audio/mp4"),
    ".ogg": ("audio", "audio/ogg"),
    ".oga": ("audio", "audio/ogg"),
    ".opus": ("audio", "audio/opus"),
    ".wav": ("audio", "audio/wav"),
    ".pdf": ("document", "application/pdf"),
    ".txt": ("document", "text/plain"),
    ".zip": ("document", "application/zip"),
    ".doc": ("document", "application/msword"),
    ".docx": (
        "document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
}
_ORPHAN_RE = re.compile(r"^telegram/(\d{4})/(\d{2})/(\d{2})/(\d+)_[^/]+$")
_URL_LINE_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_LEGACY_PREFIX = ("data", "downloads")
_FFFD = chr(0xFFFD)

#: v1 classifier name -> (taxonomy name, mode, is_legacy, fallback labels).
_CLASSIFIERS: dict[str, tuple[str, TaxonomyMode, bool, tuple[str, ...]]] = {
    "multilabel_llm": ("topics", "multi", False, ()),
    "recipe_llm": ("recipe_legacy", "single", True, ("recipe", "not_recipe")),
}

#: Columns that legitimately differ between two runs (wall-clock defaults).
_VOLATILE_COLUMNS = {("taxonomies", "created_at"), ("taxonomies", "updated_at")}
_DIGEST_TABLES = (
    "items",
    "instagram_posts",
    "telegram_messages",
    "tags",
    "item_tags",
    "media",
    "links",
    "item_links",
    "link_fetches",
    "legacy_expanded_text",
    "taxonomies",
    "classification_runs",
    "classification_results",
    "result_labels",
    "search_docs",
)

_N_SAMPLES = 20


class LegacyMigrationError(RuntimeError):
    """Raised when the v1 migration cannot run or its verification fails.

    Attributes:
        report: Report collected so far (``ok`` is False); ``None`` if the
            migration failed before anything was counted.
    """

    def __init__(self, message: str, report: MigrationReport | None = None) -> None:
        super().__init__(message)
        self.report = report


@dataclass
class MigrationReport:
    """Counts-only summary of a v1 -> v2 migration (JSON-serializable).

    Attributes:
        source: Source file.
        target: Target file.
        downloads_dir: Directory media paths are relative to.
        started_at: Start time (UTC, canonical format).
        finished_at: End time.
        ok: True when every check and verification passed.
        assumptions: Interpretation rules applied to ambiguous v1 data.
        source_counts: Row counts of the v1 tables.
        items: Migrated items per source.
        dropped: Rows deliberately not migrated (test rows, CDN URLs, ...).
        timestamps: Timestamp conversion statistics.
        tags: Tag statistics.
        media: Media statistics, including orphan recovery.
        links: Link statistics.
        expanded: ``content_expanded`` handling statistics.
        classification: Taxonomies, runs, results and label statistics.
        checks: Database checks of the result.
        verification: One entry per verification check.
        mismatches: Failed verification checks (empty when ``ok``).
        unmatched_files: Orphan files that matched no message (relative paths).
        ambiguous_files: Orphan files that matched more than one way.
        timings_s: Duration of each phase in seconds.
        target_size_bytes: Size of the finished target file.
        logical_sha256: :func:`logical_digest` of the target.
    """

    source: str
    target: str
    downloads_dir: str
    started_at: str = field(default_factory=utcnow_ts)
    finished_at: str | None = None
    ok: bool = False
    assumptions: list[str] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    items: dict[str, Any] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)
    timestamps: dict[str, int] = field(default_factory=dict)
    tags: dict[str, int] = field(default_factory=dict)
    media: dict[str, int] = field(default_factory=dict)
    links: dict[str, int] = field(default_factory=dict)
    expanded: dict[str, Any] = field(default_factory=dict)
    classification: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, Any] = field(default_factory=dict)
    verification: list[dict[str, Any]] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    unmatched_files: list[str] = field(default_factory=list)
    ambiguous_files: list[str] = field(default_factory=list)
    timings_s: dict[str, float] = field(default_factory=dict)
    target_size_bytes: int = 0
    logical_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the report as plain JSON-compatible data."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Return the report as JSON text."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _timed(report: MigrationReport, phase: str) -> Iterator[None]:
    """Record the duration of a phase in ``report.timings_s``."""
    start = time.perf_counter()
    try:
        yield
    finally:
        report.timings_s[phase] = round(time.perf_counter() - start, 3)


def _open_readonly(path: Path) -> sqlite3.Connection:
    """Open a SQLite file strictly read-only (``mode=ro`` URI)."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    """Return the table names of a database."""
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'").fetchall()
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the column names of a table."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _scalar(conn: sqlite3.Connection, sql: str, params: Sequence[object] = ()) -> int:
    """Return the first column of the first row as int (0 for NULL)."""
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _utc_ts(value: str | None) -> str | None:
    """Convert a v1 timestamp (naive values are UTC) to canonical form."""
    if value is None or not str(value).strip():
        return None
    return to_db_ts(str(value), assume_tz=_UTC)


class _LocalTimeConverter:
    """Convert naive local timestamps to UTC with ``fold=0``, counting DST edge cases."""

    def __init__(self, tz_name: str) -> None:
        self.tz = ZoneInfo(tz_name)
        self.ambiguous = 0
        self.nonexistent = 0

    def __call__(self, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        text = str(value).strip()
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text[-1] in "zZ" else text)
        if parsed.tzinfo is not None:
            return to_db_ts(parsed)
        local = parsed.replace(tzinfo=self.tz, fold=0)
        other = parsed.replace(tzinfo=self.tz, fold=1)
        if local.utcoffset() != other.utcoffset():
            roundtrip = local.astimezone(UTC).astimezone(self.tz).replace(tzinfo=None)
            if roundtrip == parsed:
                self.ambiguous += 1
            else:
                self.nonexistent += 1
        return to_db_ts(local)


def _convert_ig_created(value: str | None, tz_name: str) -> str | None:
    """Stand-alone conversion used by the sample verification."""
    return _LocalTimeConverter(tz_name)(value)


def _confidence(value: object) -> float | None:
    """Return a v1 confidence as float in ``[0, 1]`` (``None`` if missing or invalid)."""
    if value is None:
        return None
    try:
        if not isinstance(value, str | bytes | SupportsFloat | SupportsIndex):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0.0 <= number <= 1.0 else None


def _is_url_list(text: str) -> bool:
    """Return True if every non-empty line of ``text`` is a bare URL."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(lines) and all(_URL_LINE_RE.match(line) for line in lines)


def _load_ftfy() -> Any:
    """Return the ``ftfy`` module or ``None`` if the ``migrate`` extra is missing."""
    try:
        import ftfy
    except ImportError:
        return None
    return ftfy


def _repair(ftfy: Any, text: str) -> str:
    """Repair mojibake conservatively (quotes, widths and ligatures are kept)."""
    if ftfy is None:
        return text
    return str(
        ftfy.fix_text(
            text,
            uncurl_quotes=False,
            fix_character_width=False,
            fix_latin_ligatures=False,
            fix_line_breaks=False,
        )
    )


def _legacy_rel_path(raw: str, downloads_dir: Path) -> str | None:
    """Turn a v1 ``media_urls`` entry into a path relative to ``downloads_dir``."""
    text = raw.strip().replace("\\", "/")
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute() or re.match(r"^[A-Za-z]:/", text):
        try:
            return candidate.resolve().relative_to(downloads_dir.resolve()).as_posix()
        except ValueError:
            return None
    parts = PurePosixPath(text).parts
    if parts[:2] == _LEGACY_PREFIX:
        parts = parts[2:]
    elif parts[:1] == ("downloads",):
        parts = parts[1:]
    if not parts:
        return None
    try:
        return normalize_local_path("/".join(parts))
    except ValueError:
        return None


def _file_facts(path: Path) -> tuple[int, str]:
    """Return ``(size_bytes, sha256)`` of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return path.stat().st_size, digest.hexdigest()


def _media_kind(rel_path: str, fallback: str) -> tuple[str, str | None]:
    """Return ``(media_type, mime)`` from a file extension."""
    suffix = PurePosixPath(rel_path).suffix.lower()
    if suffix in _MIME:
        return _MIME[suffix]
    return fallback, None


# ---------------------------------------------------------------------------
# Logical digest (idempotency check)
# ---------------------------------------------------------------------------


def logical_digest(path: str | Path) -> str:
    """Return a SHA-256 over the logical content of a v2 database.

    Covers every data table in primary-key order and ignores bookkeeping and
    wall-clock columns (``schema_migrations``, ``taxonomies.created_at`` /
    ``updated_at``), so two migrations of the same source compare equal.

    Args:
        path: Schema v2 database file.

    Returns:
        Hex digest.
    """
    conn = _open_readonly(Path(path))
    try:
        digest = hashlib.sha256()
        for table in _DIGEST_TABLES:
            columns = [
                row[1]
                for row in conn.execute(f"PRAGMA table_xinfo({table})").fetchall()
                if (table, row[1]) not in _VOLATILE_COLUMNS
            ]
            order = ", ".join(str(i) for i in range(1, len(columns) + 1))
            digest.update(f"\x00{table}\x00".encode())
            cursor = conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}")
            for row in cursor:
                digest.update(json.dumps(list(row), ensure_ascii=False).encode("utf-8"))
        return digest.hexdigest()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


@dataclass
class _State:
    """Mapping state shared between the phases of one migration."""

    ig_items: dict[int, int] = field(default_factory=dict)  # v1 instagram_posts.id -> item
    tg_items: dict[int, int] = field(default_factory=dict)  # v1 telegram_messages.id -> item
    tg_by_message: dict[int, tuple[int, int, str | None]] = field(default_factory=dict)
    item_text: dict[int, str | None] = field(default_factory=dict)
    item_collected: dict[int, str] = field(default_factory=dict)
    item_links: dict[int, list[str]] = field(default_factory=dict)
    tag_ids: dict[tuple[str, str], int] = field(default_factory=dict)
    tg_has_media: set[int] = field(default_factory=set)  # v1 telegram_messages.id
    test_tg_ids: set[int] = field(default_factory=set)
    referenced_paths: set[str] = field(default_factory=set)


class _Migrator:
    """Performs one migration from an open v1 connection into an open v2 connection."""

    def __init__(
        self,
        src: sqlite3.Connection,
        dst: sqlite3.Connection,
        report: MigrationReport,
        *,
        downloads_dir: Path,
        instagram_tz: str,
        test_chat_ids: Sequence[int],
    ) -> None:
        self.src = src
        self.dst = dst
        self.report = report
        self.downloads_dir = downloads_dir
        self.instagram_tz = instagram_tz
        self.test_chat_ids = tuple(int(c) for c in test_chat_ids)
        self.state = _State()
        self.src_tables = _tables(src)
        self.ig_time = _LocalTimeConverter(instagram_tz)
        self.links_repo = LinksRepo(dst)
        self._ig_expanded: list[tuple[int, str]] = []
        self._tg_expanded: list[tuple[int, str]] = []
        self._samples_compared = 0

    # -- helpers -------------------------------------------------------------

    def _has(self, table: str) -> bool:
        return table in self.src_tables

    def _tag_id(self, kind: str, name: str) -> int | None:
        normalized = normalize_tag_name(name)
        if not normalized:
            return None
        key = (kind, normalized)
        tag_id = self.state.tag_ids.get(key)
        if tag_id is None:
            row = self.dst.execute(
                "INSERT INTO tags (kind, name) VALUES (?, ?) "
                "ON CONFLICT (kind, name) DO UPDATE SET kind = excluded.kind RETURNING id",
                key,
            ).fetchone()
            tag_id = int(row[0])
            self.state.tag_ids[key] = tag_id
        return tag_id

    def _link_item_tags(self, item_id: int, kind: str, names: Iterable[str]) -> int:
        tag_ids = {tid for name in names if (tid := self._tag_id(kind, name)) is not None}
        self.dst.executemany(
            "INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            [(item_id, tid) for tid in sorted(tag_ids)],
        )
        return len(tag_ids)

    def _test_clause(self, alias: str = "") -> tuple[str, list[int]]:
        prefix = f"{alias}." if alias else ""
        if not self.test_chat_ids:
            return "1", []
        marks = ", ".join("?" for _ in self.test_chat_ids)
        return f"({prefix}chat_id IS NULL OR {prefix}chat_id NOT IN ({marks}))", list(
            self.test_chat_ids
        )

    # -- phases --------------------------------------------------------------

    def source_counts(self) -> None:
        counts: dict[str, int] = {}
        for table in sorted(self.src_tables):
            if table.startswith("sqlite_"):
                continue
            counts[table] = _scalar(self.src, f"SELECT count(*) FROM {table}")
        self.report.source_counts = counts

    def instagram(self) -> None:
        if not self._has("instagram_posts"):
            self.report.items["instagram"] = 0
            return
        cols = _columns(self.src, "instagram_posts")
        expanded_col = "content_expanded" if "content_expanded" in cols else "NULL"
        rows = self.src.execute(
            "SELECT id, shortcode, owner_username, owner_id, caption, is_video, media_url, "
            f"typename, likes, comments, created_at, fetched_at, {expanded_col} AS expanded "
            "FROM instagram_posts ORDER BY id"
        ).fetchall()
        kinds: Counter[str] = Counter()
        fallback_collected = 0
        cdn_urls = 0
        videos = 0
        sidecars = 0
        for row in rows:
            typename = row["typename"]
            kind = _IG_KIND.get(typename or "") or ("video" if row["is_video"] else "image")
            kinds[kind] += 1
            created = self.ig_time(row["created_at"])
            collected = _utc_ts(row["fetched_at"]) or created
            if collected is None:
                collected = utcnow_ts()
                fallback_collected += 1
            if row["media_url"]:
                cdn_urls += 1
            item_id = int(
                self.dst.execute(
                    "INSERT INTO items (source, external_id, kind, text, author, url, "
                    "created_at, collected_at, updated_at) VALUES "
                    "('instagram', ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (
                        row["shortcode"],
                        kind,
                        row["caption"],
                        row["owner_username"],
                        f"https://www.instagram.com/p/{row['shortcode']}/",
                        created,
                        collected,
                        collected,
                    ),
                ).fetchone()[0]
            )
            self.dst.execute(
                "INSERT INTO instagram_posts (item_id, shortcode, owner_id, typename, likes, "
                "comments) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    row["shortcode"],
                    row["owner_id"],
                    typename,
                    row["likes"],
                    row["comments"],
                ),
            )
            self.state.ig_items[int(row["id"])] = item_id
            self.state.item_text[item_id] = row["caption"]
            self.state.item_collected[item_id] = collected
            if typename == "GraphVideo":
                self.dst.execute(
                    "INSERT INTO media (item_id, position, media_type, transcript_status, "
                    "updated_at) VALUES (?, 0, 'video', 'pending', ?)",
                    (item_id, collected),
                )
                videos += 1
            elif typename == "GraphSidecar":
                sidecars += 1
        self.report.items["instagram"] = len(rows)
        self.report.items["instagram_by_kind"] = dict(sorted(kinds.items()))
        self.report.dropped["instagram_cdn_media_urls"] = cdn_urls
        self.report.media["instagram_video_pending"] = videos
        self.report.media["instagram_sidecars_without_media"] = sidecars
        self.report.timestamps["instagram_created_ambiguous_dst"] = self.ig_time.ambiguous
        self.report.timestamps["instagram_created_nonexistent_dst"] = self.ig_time.nonexistent
        self.report.timestamps["collected_at_fallback_now"] = fallback_collected

        hashtag_links = mention_links = 0
        if self._has("instagram_hashtags"):
            for post_id, name in self.src.execute(
                "SELECT post_id, hashtag FROM instagram_hashtags ORDER BY id"
            ).fetchall():
                tagged_id = self.state.ig_items.get(post_id)
                if tagged_id is None:
                    self.report.dropped["instagram_hashtags_orphan"] = (
                        self.report.dropped.get("instagram_hashtags_orphan", 0) + 1
                    )
                    continue
                hashtag_links += self._link_item_tags(tagged_id, "hashtag", [name])
        if self._has("instagram_mentions"):
            for post_id, name in self.src.execute(
                "SELECT post_id, username FROM instagram_mentions ORDER BY id"
            ).fetchall():
                tagged_id = self.state.ig_items.get(post_id)
                if tagged_id is None:
                    self.report.dropped["instagram_mentions_orphan"] = (
                        self.report.dropped.get("instagram_mentions_orphan", 0) + 1
                    )
                    continue
                mention_links += self._link_item_tags(tagged_id, "mention", [name])
        self.report.tags["instagram_hashtag_links"] = hashtag_links
        self.report.tags["instagram_mention_links"] = mention_links
        self._ig_expanded = [
            (self.state.ig_items[r["id"]], r["expanded"]) for r in rows if r["expanded"]
        ]

    def telegram(self) -> None:
        if not self._has("telegram_messages"):
            self.report.items["telegram"] = 0
            return
        cols = _columns(self.src, "telegram_messages")
        expanded_col = "content_expanded" if "content_expanded" in cols else "NULL"
        rows = self.src.execute(
            "SELECT id, message_id, chat_id, content, content_type, media_urls, views, "
            f"forwards, reply_to_msg_id, created_at, saved_at, {expanded_col} AS expanded "
            "FROM telegram_messages ORDER BY id"
        ).fetchall()
        kinds: Counter[str] = Counter()
        test_rows = 0
        hashtag_links = mention_links = 0
        media_rows = missing = unresolvable = 0
        null_created = 0
        no_chat = 0
        for row in rows:
            if row["chat_id"] in self.test_chat_ids:
                test_rows += 1
                self.state.test_tg_ids.add(int(row["id"]))
                continue
            if row["chat_id"] is None:
                no_chat += 1
            content_type = (row["content_type"] or "").lower()
            kind = _TG_KIND.get(content_type, "other")
            kinds[kind] += 1
            created = _utc_ts(row["created_at"])
            if created is None:
                null_created += 1
            collected = _utc_ts(row["saved_at"]) or created or utcnow_ts()
            chat_id = int(row["chat_id"]) if row["chat_id"] is not None else 0
            external_id = f"{chat_id}:{int(row['message_id'])}"
            item_id = int(
                self.dst.execute(
                    "INSERT INTO items (source, external_id, kind, text, author, url, "
                    "created_at, collected_at, updated_at) VALUES "
                    "('telegram', ?, ?, ?, NULL, NULL, ?, ?, ?) RETURNING id",
                    (external_id, kind, row["content"], created, collected, collected),
                ).fetchone()[0]
            )
            self.dst.execute(
                "INSERT INTO telegram_messages (item_id, chat_id, message_id, views, forwards, "
                "reply_to_msg_id) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    chat_id,
                    int(row["message_id"]),
                    row["views"],
                    row["forwards"],
                    row["reply_to_msg_id"],
                ),
            )
            self.state.tg_items[int(row["id"])] = item_id
            self.state.tg_by_message[int(row["message_id"])] = (
                int(row["id"]),
                item_id,
                row["created_at"],
            )
            self.state.item_text[item_id] = row["content"]
            self.state.item_collected[item_id] = collected
            hashtag_links += self._link_item_tags(
                item_id, "hashtag", extract_hashtags(row["content"])
            )
            mention_links += self._link_item_tags(
                item_id, "mention", extract_mentions(row["content"])
            )
            if row["expanded"]:
                self._tg_expanded.append((item_id, row["expanded"]))

            if row["media_urls"]:
                try:
                    entries = json.loads(row["media_urls"])
                except json.JSONDecodeError:
                    entries = [row["media_urls"]]
                if isinstance(entries, str):
                    entries = [entries]
                position = 0
                for entry in entries:
                    rel = _legacy_rel_path(str(entry), self.downloads_dir)
                    if rel is None:
                        unresolvable += 1
                        continue
                    if not (self.downloads_dir / rel).is_file():
                        missing += 1
                        rel_for_row: str | None = None
                    else:
                        rel_for_row = rel
                    self._insert_tg_media(item_id, position, rel_for_row, rel, kind, collected)
                    self.state.referenced_paths.add(rel)
                    position += 1
                    media_rows += 1
                if position:
                    self.state.tg_has_media.add(int(row["id"]))
        self.report.items["telegram"] = len(rows) - test_rows
        self.report.items["telegram_by_kind"] = dict(sorted(kinds.items()))
        self.report.dropped["telegram_test_rows"] = test_rows
        self.report.timestamps["telegram_created_null"] = null_created
        self.report.items["telegram_without_chat_id"] = no_chat
        self.report.tags["telegram_hashtag_links"] = hashtag_links
        self.report.tags["telegram_mention_links"] = mention_links
        self.report.media["telegram_referenced"] = media_rows
        self.report.media["telegram_referenced_missing_on_disk"] = missing
        self.report.media["telegram_referenced_unresolvable"] = unresolvable

    def _insert_tg_media(
        self,
        item_id: int,
        position: int,
        local_path: str | None,
        rel_for_type: str,
        kind: str,
        updated_at: str,
    ) -> None:
        fallback = kind if kind in ("image", "video", "audio", "document") else "other"
        media_type, mime = _media_kind(rel_for_type, fallback)
        size = sha = None
        if local_path is not None:
            size, sha = _file_facts(self.downloads_dir / local_path)
        status = "pending" if media_type in ("video", "audio") else "none"
        self.dst.execute(
            "INSERT INTO media (item_id, position, media_type, local_path, mime, size_bytes, "
            "sha256, transcript_status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, position, media_type, local_path, mime, size, sha, status, updated_at),
        )

    def recover_orphans(self) -> None:
        """Attach unreferenced files in ``telegram/YYYY/MM/DD/<message_id>_*``."""
        stats: Counter[str] = Counter()
        candidates: dict[int, list[tuple[str, date]]] = defaultdict(list)
        unmatched: list[str] = []
        ambiguous: list[str] = []
        if self.downloads_dir.is_dir():
            files = sorted(
                p.relative_to(self.downloads_dir).as_posix()
                for p in self.downloads_dir.rglob("*")
                if p.is_file()
            )
        else:
            files = []
        stats["files_on_disk"] = len(files)
        for rel in files:
            if rel in self.state.referenced_paths:
                continue
            match = _ORPHAN_RE.match(rel)
            if not match:
                stats["unreferenced_other"] += 1
                continue
            stats["orphans"] += 1
            year, month, day, message_id = (int(g) for g in match.groups())
            try:
                folder_date = date(year, month, day)
            except ValueError:
                unmatched.append(rel)
                stats["unmatched_bad_date"] += 1
                continue
            target = self.state.tg_by_message.get(message_id)
            if target is None:
                unmatched.append(rel)
                stats["unmatched_no_message"] += 1
                continue
            v1_id, _item_id, created_raw = target
            created = _utc_ts(created_raw)
            if created is None:
                unmatched.append(rel)
                stats["unmatched_no_created_at"] += 1
                continue
            created_date = datetime.fromisoformat(created[:-1] + "+00:00").date()
            if abs(folder_date - created_date) > timedelta(days=1):
                unmatched.append(rel)
                stats["unmatched_out_of_window"] += 1
                continue
            if v1_id in self.state.tg_has_media:
                ambiguous.append(rel)
                stats["ambiguous_message_has_media"] += 1
                continue
            candidates[message_id].append((rel, folder_date))
        recovered = 0
        for message_id, found in sorted(candidates.items()):
            if len(found) > 1:
                ambiguous.extend(rel for rel, _ in found)
                stats["ambiguous_several_files"] += len(found)
                continue
            rel = found[0][0]
            v1_id, item_id, _created = self.state.tg_by_message[message_id]
            kind = self.dst.execute("SELECT kind FROM items WHERE id = ?", (item_id,)).fetchone()[0]
            self._insert_tg_media(item_id, 0, rel, rel, kind, self.state.item_collected[item_id])
            self.state.tg_has_media.add(v1_id)
            recovered += 1
        self.report.media["orphans_on_disk"] = stats["orphans"]
        self.report.media["orphans_recovered"] = recovered
        self.report.media["orphans_unmatched"] = len(unmatched)
        self.report.media["orphans_ambiguous"] = len(ambiguous)
        for key in (
            "unmatched_no_message",
            "unmatched_out_of_window",
            "unmatched_bad_date",
            "unmatched_no_created_at",
            "ambiguous_message_has_media",
            "ambiguous_several_files",
            "unreferenced_other",
            "files_on_disk",
        ):
            self.report.media[f"files_{key}" if key != "files_on_disk" else key] = stats[key]
        self.report.unmatched_files = sorted(unmatched)
        self.report.ambiguous_files = sorted(ambiguous)

    def links(self) -> None:
        """Extract links from item texts and import ``content_expanded``."""
        ftfy = _load_ftfy()
        self.report.expanded["ftfy_available"] = ftfy is not None
        if ftfy is None:
            logger.warning("ftfy is not installed; content_expanded is migrated unrepaired")
        for item_id, text in self.state.item_text.items():
            self.state.item_links[item_id] = extract_urls(text)

        stats: Counter[str] = Counter()
        fetches: list[tuple[int, str, str]] = []  # (item_id, url, text)
        legacy: list[tuple[int, str]] = []
        expanded = [*self._ig_expanded, *self._tg_expanded]
        for item_id, raw in expanded:
            stats["rows"] += 1
            if _is_url_list(raw):
                stats["url_lists"] += 1
                urls = self.state.item_links[item_id]
                for line in raw.splitlines():
                    url = line.strip()
                    if url and url not in urls:
                        urls.append(url)
                        stats["url_list_links_added"] += 1
                continue
            text = _repair(ftfy, raw)
            if text != raw:
                stats["repaired"] += 1
            if _FFFD in raw:
                stats["fffd_before"] += 1
            if _FFFD in text:
                stats["fffd_after"] += 1
            distinct: list[str] = []
            for url in self.state.item_links[item_id]:
                try:
                    normalized = normalize_url(url)
                except ValueError:
                    continue
                if normalized not in distinct:
                    distinct.append(normalized)
            if len(distinct) == 1:
                fetches.append((item_id, self.state.item_links[item_id][0], text))
            else:
                stats["legacy_multi_link" if distinct else "legacy_no_link"] += 1
                legacy.append((item_id, text))

        item_link_rows = 0
        for item_id in sorted(self.state.item_links):
            seen: set[int] = set()
            for url in self.state.item_links[item_id]:
                try:
                    link_id = self.links_repo.ensure(url)
                except ValueError:
                    stats["invalid_urls"] += 1
                    continue
                if link_id in seen:
                    continue
                self.dst.execute(
                    "INSERT INTO item_links (item_id, link_id, position) VALUES (?, ?, ?)",
                    (item_id, link_id, len(seen)),
                )
                seen.add(link_id)
                item_link_rows += 1

        fetched_texts: dict[int, str] = {}
        for item_id, url, text in fetches:
            link_id = self.links_repo.ensure(url)
            previous = fetched_texts.get(link_id)
            if previous is None:
                self.dst.execute(
                    "INSERT INTO link_fetches (link_id, fetcher, status, text, fetched_at) "
                    "VALUES (?, ?, 'ok', ?, ?)",
                    (link_id, LEGACY_FETCHER, text, self.state.item_collected[item_id]),
                )
                fetched_texts[link_id] = text
                stats["link_fetches"] += 1
            elif previous == text:
                stats["link_fetch_duplicates_skipped"] += 1
            else:
                stats["legacy_link_already_fetched"] += 1
                legacy.append((item_id, text))
        for item_id, text in legacy:
            self.dst.execute(
                "INSERT INTO legacy_expanded_text (item_id, text) VALUES (?, ?)", (item_id, text)
            )
        self.report.links["links"] = _scalar(self.dst, "SELECT count(*) FROM links")
        self.report.links["item_links"] = item_link_rows
        self.report.links["items_with_links"] = _scalar(
            self.dst, "SELECT count(DISTINCT item_id) FROM item_links"
        )
        self.report.links["invalid_urls_skipped"] = stats["invalid_urls"]
        self.report.expanded.update(
            {
                "rows": stats["rows"],
                "url_lists": stats["url_lists"],
                "url_list_links_added": stats["url_list_links_added"],
                "link_fetches_legacy": stats["link_fetches"],
                "link_fetch_duplicates_skipped": stats["link_fetch_duplicates_skipped"],
                "legacy_expanded_text": len(legacy),
                "legacy_multi_link": stats["legacy_multi_link"],
                "legacy_no_link": stats["legacy_no_link"],
                "legacy_link_already_fetched": stats["legacy_link_already_fetched"],
                "repaired": stats["repaired"],
                "fffd_items_before": stats["fffd_before"],
                "fffd_items_after": stats["fffd_after"],
            }
        )
        self.report.expanded["items_text_with_fffd"] = sum(
            1 for text in self.state.item_text.values() if text and _FFFD in text
        )

    def classifications(self) -> None:
        """Import ``content_analysis`` as legacy runs and results."""
        cls = self.report.classification
        cls.update({"taxonomies": [], "runs": []})
        if not self._has("content_analysis"):
            return
        repo = ClassificationRepo(self.dst)
        rows = self.src.execute(
            "SELECT id, content_id, content_source, classifier_name, run_id, label, confidence, "
            "reasoning, llm_metadata, llm_provider, llm_model, details_json, analyzed_at "
            "FROM content_analysis ORDER BY analyzed_at, id"
        ).fetchall()
        stats: Counter[str] = Counter()
        # run key -> item -> v1 run_id group -> rows
        grouped: dict[
            tuple[str, str | None, str | None], dict[int, dict[str, list[sqlite3.Row]]]
        ] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        run_rows: dict[tuple[str, str | None, str | None], list[sqlite3.Row]] = defaultdict(list)
        labels_seen: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            classifier = row["classifier_name"]
            if classifier not in _CLASSIFIERS:
                stats["rows_unknown_classifier"] += 1
                continue
            source = row["content_source"]
            content_id = int(row["content_id"])
            if source == "telegram" and content_id in self.state.test_tg_ids:
                stats["rows_test_dropped"] += 1
                continue
            mapping = (
                self.state.ig_items
                if source == "instagram"
                else (self.state.tg_items if source == "telegram" else {})
            )
            item_id = mapping.get(content_id)
            if item_id is None:
                stats["rows_unmapped"] += 1
                continue
            key = (classifier, row["llm_provider"], row["llm_model"])
            grouped[key][item_id][row["run_id"] or ""].append(row)
            run_rows[key].append(row)
            labels_seen[classifier].add(row["label"])

        taxonomies: dict[str, Any] = {}
        for classifier in sorted({key[0] for key in grouped}):
            name, mode, is_legacy, fallback = _CLASSIFIERS[classifier]
            label_names = sorted(set(fallback) | labels_seen[classifier])
            taxonomy = repo.ensure_taxonomy(name, mode, label_names, is_legacy=is_legacy)
            taxonomies[classifier] = taxonomy
            cls["taxonomies"].append(
                {"name": name, "mode": mode, "is_legacy": is_legacy, "labels": len(label_names)}
            )

        ordered = sorted(
            grouped,
            key=lambda k: (
                min(r["analyzed_at"] or "" for r in run_rows[k]),
                k[0],
                k[1] or "",
                k[2] or "",
            ),
        )
        for key in ordered:
            classifier, provider, model = key
            taxonomy = taxonomies[classifier]
            blobs = Counter(r["llm_metadata"] for r in run_rows[key] if r["llm_metadata"])
            params: Any = None
            if blobs:
                blob = sorted(blobs.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                try:
                    params = json.loads(blob)
                except json.JSONDecodeError:
                    params = {"raw": blob}
            times = [r["analyzed_at"] for r in run_rows[key] if r["analyzed_at"]]
            started = _utc_ts(min(times)) if times else None
            finished = _utc_ts(max(times)) if times else None
            run_id = repo.create_run(
                taxonomy.id,
                provider=provider,
                model=model,
                params=params,
                status="legacy",
                started_at=started,
            )
            n_results = n_labels = superseded = duplicates = conflicts = 0
            for item_id in sorted(grouped[key]):
                groups = grouped[key][item_id]
                chosen_key = max(
                    groups,
                    key=lambda g: (
                        max(r["analyzed_at"] or "" for r in groups[g]),
                        max(int(r["id"]) for r in groups[g]),
                    ),
                )
                superseded += sum(len(v) for g, v in groups.items() if g != chosen_key)
                chosen = sorted(
                    groups[chosen_key], key=lambda r: (r["analyzed_at"] or "", int(r["id"]))
                )
                best: dict[str, float | None] = {}
                for r in chosen:
                    conf = _confidence(r["confidence"])
                    current = best.get(r["label"])
                    if r["label"] not in best or (
                        conf is not None and (current is None or conf > current)
                    ):
                        best[r["label"]] = conf
                duplicates += len(chosen) - len(best)
                if taxonomy.mode == "single" and len(best) > 1:
                    conflicts += 1
                    top = max(best.items(), key=lambda kv: (kv[1] or 0.0, kv[0]))
                    best = {top[0]: top[1]}
                known = [c for c in best.values() if c is not None]
                confidence = max(known) if known else None
                reasoning = next((r["reasoning"] for r in chosen if r["reasoning"]), None)
                details: str | None = None
                raw_details = next((r["details_json"] for r in chosen if r["details_json"]), None)
                if raw_details is not None:
                    try:
                        details = json.dumps(json.loads(raw_details), ensure_ascii=False)
                    except json.JSONDecodeError:
                        stats["details_invalid_json"] += 1
                created = _utc_ts(chosen[-1]["analyzed_at"]) or started or utcnow_ts()
                result_id = int(
                    self.dst.execute(
                        "INSERT INTO classification_results (run_id, item_id, taxonomy_id, "
                        "status, confidence, reasoning, details, created_at) "
                        "VALUES (?, ?, ?, 'ok', ?, ?, ?, ?) RETURNING id",
                        (run_id, item_id, taxonomy.id, confidence, reasoning, details, created),
                    ).fetchone()[0]
                )
                self.dst.executemany(
                    "INSERT INTO result_labels (result_id, label, confidence) VALUES (?, ?, ?)",
                    [(result_id, label, conf) for label, conf in sorted(best.items())],
                )
                n_results += 1
                n_labels += len(best)
            finished_dt = datetime.fromisoformat(finished[:-1] + "+00:00") if finished else None
            repo.finish_run(run_id, status="legacy", finished_at=finished_dt)
            cls["runs"].append(
                {
                    "run_id": run_id,
                    "taxonomy": taxonomy.name,
                    "classifier": classifier,
                    "provider": provider,
                    "model": model,
                    "v1_rows": len(run_rows[key]),
                    "results": n_results,
                    "labels": n_labels,
                    "superseded_rows": superseded,
                    "duplicate_label_rows": duplicates,
                    "single_label_conflicts": conflicts,
                    "params_variants": len(blobs),
                }
            )
            stats["superseded"] += superseded
            stats["duplicates"] += duplicates
        cls["results"] = sum(r["results"] for r in cls["runs"])
        cls["labels"] = sum(r["labels"] for r in cls["runs"])
        cls["superseded_rows"] = stats["superseded"]
        cls["duplicate_label_rows_removed"] = stats["duplicates"]
        cls["rows_unmapped"] = stats["rows_unmapped"]
        cls["rows_unknown_classifier"] = stats["rows_unknown_classifier"]
        cls["rows_test_dropped"] = stats["rows_test_dropped"]
        cls["details_invalid_json"] = stats["details_invalid_json"]
        self.report.dropped["analysis_test_rows"] = stats["rows_test_dropped"]

    def summarize_tags(self) -> None:
        self.report.tags["tags_hashtag"] = _scalar(
            self.dst, "SELECT count(*) FROM tags WHERE kind = 'hashtag'"
        )
        self.report.tags["tags_mention"] = _scalar(
            self.dst, "SELECT count(*) FROM tags WHERE kind = 'mention'"
        )
        self.report.tags["item_tags"] = _scalar(self.dst, "SELECT count(*) FROM item_tags")
        self.report.media["media_rows"] = _scalar(self.dst, "SELECT count(*) FROM media")
        self.report.media["media_with_local_path"] = _scalar(
            self.dst, "SELECT count(*) FROM media WHERE local_path IS NOT NULL"
        )

    # -- verification --------------------------------------------------------

    def verify(self) -> None:
        """Compare the target against expected values computed from the source."""
        checks: list[dict[str, Any]] = []

        def expect(name: str, expected: Any, actual: Any, *, at_least: bool = False) -> None:
            ok = actual >= expected if at_least else actual == expected
            checks.append({"check": name, "expected": expected, "actual": actual, "ok": ok})

        src, dst = self.src, self.dst
        test_sql, test_params = self._test_clause()
        has_ig = self._has("instagram_posts")
        has_tg = self._has("telegram_messages")

        exp_ig = _scalar(src, "SELECT count(*) FROM instagram_posts") if has_ig else 0
        exp_tg = (
            _scalar(src, f"SELECT count(*) FROM telegram_messages WHERE {test_sql}", test_params)
            if has_tg
            else 0
        )
        expect(
            "items.instagram",
            exp_ig,
            _scalar(dst, "SELECT count(*) FROM items WHERE source = 'instagram'"),
        )
        expect(
            "items.telegram",
            exp_tg,
            _scalar(dst, "SELECT count(*) FROM items WHERE source = 'telegram'"),
        )
        expect(
            "detail.instagram_posts", exp_ig, _scalar(dst, "SELECT count(*) FROM instagram_posts")
        )
        expect(
            "detail.telegram_messages",
            exp_tg,
            _scalar(dst, "SELECT count(*) FROM telegram_messages"),
        )

        def ig_tag_counts(kind: str) -> tuple[int, int]:
            row = dst.execute(
                "SELECT count(*), count(DISTINCT it.tag_id) FROM item_tags AS it "
                "JOIN tags AS t ON t.id = it.tag_id JOIN items AS i ON i.id = it.item_id "
                "WHERE i.source = 'instagram' AND t.kind = ?",
                (kind,),
            ).fetchone()
            return int(row[0]), int(row[1])

        if self._has("instagram_hashtags"):
            row = src.execute(
                "SELECT count(*), count(DISTINCT h.hashtag) FROM instagram_hashtags AS h "
                "JOIN instagram_posts AS p ON p.id = h.post_id"
            ).fetchone()
            links, distinct = ig_tag_counts("hashtag")
            expect("tags.instagram_hashtag_links", int(row[0]), links)
            expect("tags.instagram_hashtags_distinct", int(row[1]), distinct)
        if self._has("instagram_mentions"):
            row = src.execute(
                "SELECT count(*), count(DISTINCT lower(m.username)) FROM instagram_mentions AS m "
                "JOIN instagram_posts AS p ON p.id = m.post_id"
            ).fetchone()
            links, distinct = ig_tag_counts("mention")
            expect("tags.instagram_mention_links", int(row[0]), links)
            expect("tags.instagram_mentions_distinct", int(row[1]), distinct)

        if has_tg:
            exp_media = _scalar(
                src,
                f"SELECT coalesce(sum(json_array_length(media_urls)), 0) FROM telegram_messages "
                f"WHERE media_urls IS NOT NULL AND json_valid(media_urls) AND {test_sql}",
                test_params,
            )
            actual_media = _scalar(
                dst,
                "SELECT count(*) FROM media AS m JOIN items AS i ON i.id = m.item_id "
                "WHERE i.source = 'telegram' AND m.local_path IS NOT NULL",
            )
            expect("media.telegram_local_path", exp_media, actual_media, at_least=True)
        missing = [
            path
            for (path,) in dst.execute(
                "SELECT local_path FROM media WHERE local_path IS NOT NULL"
            ).fetchall()
            if not (self.downloads_dir / path).is_file()
        ]
        expect("media.local_path_exists_missing", 0, len(missing))
        if has_ig:
            expect(
                "media.instagram_video_pending",
                _scalar(src, "SELECT count(*) FROM instagram_posts WHERE typename = 'GraphVideo'"),
                _scalar(
                    dst,
                    "SELECT count(*) FROM media AS m JOIN items AS i ON i.id = m.item_id "
                    "WHERE i.source = 'instagram' AND m.media_type = 'video' "
                    "AND m.transcript_status = 'pending'",
                ),
            )

        self._verify_classifications(expect)

        items = _scalar(dst, "SELECT count(*) FROM items")
        expect("search.items_fts", items, _scalar(dst, "SELECT count(*) FROM items_fts"))
        expect("search.indexed_docs", items, SearchRepo(dst).indexed_count())
        expect("search.fts_integrity", True, SearchRepo(dst).integrity_check())

        integrity = [row[0] for row in dst.execute("PRAGMA integrity_check").fetchall()]
        fk = dst.execute("PRAGMA foreign_key_check").fetchall()
        self.report.checks["integrity_check"] = "; ".join(map(str, integrity[:5]))
        self.report.checks["foreign_key_violations"] = len(fk)
        expect("db.integrity_check", "ok", self.report.checks["integrity_check"])
        expect("db.foreign_key_check", 0, len(fk))

        sample_mismatches = self._verify_samples()
        expect("samples.mismatched_fields", 0, len(sample_mismatches))
        self.report.checks["samples_compared"] = self._samples_compared

        self.report.verification = checks
        self.report.mismatches = [
            f"{c['check']}: expected {c['expected']!r}, got {c['actual']!r}"
            for c in checks
            if not c["ok"]
        ] + sample_mismatches

    def _verify_classifications(self, expect: Callable[..., None]) -> None:
        if not self._has("content_analysis"):
            return
        test_ids = sorted(self.state.test_tg_ids)
        known = sorted(_CLASSIFIERS)
        mapped = (
            "a.classifier_name IN (SELECT value FROM json_each(:known)) AND ("
            "(a.content_source = 'instagram' AND a.content_id IN (SELECT id FROM instagram_posts))"
            " OR (a.content_source = 'telegram' AND a.content_id IN "
            "(SELECT id FROM telegram_messages) "
            "AND a.content_id NOT IN (SELECT value FROM json_each(:test))))"
        )
        params = {"known": json.dumps(known), "test": json.dumps(test_ids)}
        if not self._has("instagram_posts"):
            mapped = mapped.replace("a.content_id IN (SELECT id FROM instagram_posts)", "0")
        if not self._has("telegram_messages"):
            mapped = mapped.replace("a.content_id IN (SELECT id FROM telegram_messages)", "0")
        results = {
            (r[0], r[1], r[2]): int(r[3])
            for r in self.src.execute(
                "SELECT classifier_name, llm_provider, llm_model, "
                "count(DISTINCT content_source || ':' || content_id) "
                f"FROM content_analysis AS a WHERE {mapped} GROUP BY 1, 2, 3",
                params,
            ).fetchall()
        }
        labels = {
            (r[0], r[1], r[2]): int(r[3])
            for r in self.src.execute(
                f"""
                WITH m AS (SELECT a.*, coalesce(a.run_id, '') AS rid FROM content_analysis AS a
                           WHERE {mapped}),
                g AS (SELECT classifier_name, llm_provider, llm_model, content_source,
                             content_id, rid, max(analyzed_at) AS last_at, max(id) AS last_id
                      FROM m GROUP BY 1, 2, 3, 4, 5, 6),
                r AS (SELECT *, row_number() OVER (
                          PARTITION BY classifier_name, llm_provider, llm_model,
                                       content_source, content_id
                          ORDER BY last_at DESC, last_id DESC) AS rn FROM g)
                SELECT m.classifier_name, m.llm_provider, m.llm_model,
                       count(DISTINCT m.content_source || ':' || m.content_id || ':' || m.label)
                FROM m JOIN r ON r.rn = 1
                    AND r.classifier_name = m.classifier_name
                    AND r.llm_provider IS m.llm_provider AND r.llm_model IS m.llm_model
                    AND r.content_source = m.content_source AND r.content_id = m.content_id
                    AND r.rid = m.rid
                GROUP BY 1, 2, 3
                """,
                params,
            ).fetchall()
        }
        actual_runs = {
            (run["classifier"], run["provider"], run["model"]): run["run_id"]
            for run in self.report.classification.get("runs", [])
        }
        expect("classification.runs", len(results), len(actual_runs))
        for key, expected_results in sorted(results.items(), key=lambda kv: str(kv[0])):
            run_id = actual_runs.get(key)
            label = f"{key[0]}/{key[2]}"
            actual_results = (
                _scalar(
                    self.dst,
                    "SELECT count(*) FROM classification_results WHERE run_id = ?",
                    (run_id,),
                )
                if run_id
                else 0
            )
            actual_labels = (
                _scalar(
                    self.dst,
                    "SELECT count(*) FROM result_labels AS rl "
                    "JOIN classification_results AS cr ON cr.id = rl.result_id "
                    "WHERE cr.run_id = ?",
                    (run_id,),
                )
                if run_id
                else 0
            )
            expect(f"classification.results[{label}]", expected_results, actual_results)
            expect(f"classification.labels[{label}]", labels.get(key, 0), actual_labels)
        stale = _scalar(
            self.dst,
            "SELECT count(*) FROM classification_runs AS ru JOIN taxonomies AS t "
            "ON t.id = ru.taxonomy_id WHERE ru.label_set_sha256 IS NOT t.label_set_sha256",
        )
        expect("classification.runs_on_current_label_set", 0, stale)

    def _verify_samples(self) -> list[str]:
        """Compare random items field by field with the source."""
        keys: list[tuple[str, int]] = [("instagram", k) for k in sorted(self.state.ig_items)]
        keys += [("telegram", k) for k in sorted(self.state.tg_items)]
        rng = random.Random(1)
        sample = rng.sample(keys, min(_N_SAMPLES, len(keys)))
        self._samples_compared = len(sample)
        problems: list[str] = []
        for source, v1_id in sample:
            if source == "instagram":
                row = self.src.execute(
                    "SELECT caption AS text, owner_username AS author, created_at "
                    "FROM instagram_posts WHERE id = ?",
                    (v1_id,),
                ).fetchone()
                expected_created = _convert_ig_created(row["created_at"], self.instagram_tz)
                hashtags = (
                    {
                        normalize_tag_name(r[0])
                        for r in self.src.execute(
                            "SELECT hashtag FROM instagram_hashtags WHERE post_id = ?", (v1_id,)
                        ).fetchall()
                    }
                    if self._has("instagram_hashtags")
                    else set()
                )
                mentions = (
                    {
                        normalize_tag_name(r[0])
                        for r in self.src.execute(
                            "SELECT username FROM instagram_mentions WHERE post_id = ?", (v1_id,)
                        ).fetchall()
                    }
                    if self._has("instagram_mentions")
                    else set()
                )
                item_id = self.state.ig_items[v1_id]
            else:
                row = self.src.execute(
                    "SELECT content AS text, NULL AS author, created_at "
                    "FROM telegram_messages WHERE id = ?",
                    (v1_id,),
                ).fetchone()
                expected_created = _utc_ts(row["created_at"])
                hashtags = set(extract_hashtags(row["text"]))
                mentions = set(extract_mentions(row["text"]))
                item_id = self.state.tg_items[v1_id]
            expected_tags = {("hashtag", n) for n in hashtags if n} | {
                ("mention", n) for n in mentions if n
            }
            got = self.dst.execute(
                "SELECT text, author, created_at FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            got_tags = {
                (r[0], r[1])
                for r in self.dst.execute(
                    "SELECT t.kind, t.name FROM item_tags AS it JOIN tags AS t "
                    "ON t.id = it.tag_id WHERE it.item_id = ?",
                    (item_id,),
                ).fetchall()
            }
            for name, expected, actual in (
                ("text", row["text"], got["text"]),
                ("author", row["author"], got["author"]),
                ("created_at", expected_created, got["created_at"]),
                ("tags", sorted(expected_tags), sorted(got_tags)),
            ):
                if expected != actual:
                    problems.append(f"sample {source}#{v1_id}: field {name} differs")
        return problems


def _remove_db_files(path: Path) -> None:
    """Delete a SQLite file together with its ``-wal``/``-shm``/``-journal`` siblings."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(f"{path}{suffix}")
        if candidate.exists():
            candidate.unlink()


def migrate_v1(
    source: Path,
    target: Path,
    *,
    downloads_dir: Path,
    instagram_tz: str = "Europe/Berlin",
    overwrite: bool = False,
    test_chat_ids: Sequence[int] = DEFAULT_TEST_CHAT_IDS,
) -> MigrationReport:
    """Migrate a schema v1 database file into a new schema v2 database file.

    Args:
        source: v1 database (opened read-only; never modified).
        target: v2 database to create. Built as ``<target>.tmp`` and moved into
            place only after all checks passed.
        downloads_dir: Directory that ``media.local_path`` is relative to (the
            v1 ``data/downloads`` folder).
        instagram_tz: Time zone of the naive Instagram ``created_at`` values.
        overwrite: Replace an existing ``target``.
        test_chat_ids: Telegram chats whose messages are test data and dropped.

    Returns:
        The migration report (``ok`` is True).

    Raises:
        FileNotFoundError: If ``source`` does not exist.
        FileExistsError: If ``target`` exists and ``overwrite`` is False.
        LegacyMigrationError: If the source is not a v1 database, or the
            verification failed (``exc.report`` lists the mismatches; the
            target is left untouched).
    """
    source = Path(source).expanduser().resolve()
    target = Path(target).expanduser().resolve()
    downloads_dir = Path(downloads_dir).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"v1 database not found: {source}")
    if source == target:
        raise LegacyMigrationError("source and target must be different files")
    if target.exists() and not overwrite:
        raise FileExistsError(f"Target exists: {target} (pass overwrite=True to replace it)")
    ZoneInfo(instagram_tz)  # fail early on an unknown time zone

    report = MigrationReport(str(source), str(target), str(downloads_dir))
    report.assumptions = [
        f"instagram created_at is naive local time in {instagram_tz}; converted to UTC with "
        "fold=0 (ambiguous DST hour -> first occurrence, nonexistent hour -> pre-transition "
        "offset)",
        "v1 fetched_at, saved_at and analyzed_at are naive UTC (SQLite CURRENT_TIMESTAMP)",
        "telegram created_at carries an explicit offset",
        f"telegram chats {list(test_chat_ids)} are test data and are dropped",
        "instagram media_url values are expired CDN links and are not migrated",
        "orphan files match by message_id prefix and folder date within +-1 day of created_at",
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(f"{target}.tmp")
    _remove_db_files(tmp)
    total_start = time.perf_counter()
    src = _open_readonly(source)
    try:
        tables = _tables(src)
        if "instagram_posts" not in tables and "telegram_messages" not in tables:
            raise LegacyMigrationError(f"{source} does not look like a v1 database")
        if "schema_migrations" in tables:
            raise LegacyMigrationError(f"{source} is already a schema v2 database")
        dst = connect(tmp)
        try:
            with _timed(report, "schema"):
                run_migrations(dst)
            migrator = _Migrator(
                src,
                dst,
                report,
                downloads_dir=downloads_dir,
                instagram_tz=instagram_tz,
                test_chat_ids=test_chat_ids,
            )
            migrator.source_counts()
            dst.execute("BEGIN IMMEDIATE")
            try:
                with _timed(report, "instagram"):
                    migrator.instagram()
                with _timed(report, "telegram"):
                    migrator.telegram()
                with _timed(report, "media_orphans"):
                    migrator.recover_orphans()
                with _timed(report, "links"):
                    migrator.links()
                with _timed(report, "classifications"):
                    migrator.classifications()
                migrator.summarize_tags()
                with _timed(report, "search_rebuild"):
                    report.checks["search_docs"] = SearchRepo(dst).rebuild_all()
                    SearchRepo(dst).optimize()
                dst.execute("COMMIT")
            except BaseException:
                if dst.in_transaction:
                    dst.execute("ROLLBACK")
                raise
            dst.execute("PRAGMA optimize")
            with _timed(report, "verify"):
                migrator.verify()
            dst.execute("PRAGMA journal_mode = DELETE")
            with _timed(report, "vacuum"):
                dst.execute("VACUUM")
        finally:
            dst.close()
    except BaseException:
        src.close()
        _remove_db_files(tmp)
        raise
    src.close()

    report.logical_sha256 = logical_digest(tmp)
    report.target_size_bytes = tmp.stat().st_size
    if report.mismatches:
        _remove_db_files(tmp)
        report.ok = False
        report.finished_at = utcnow_ts()
        report.timings_s["total"] = round(time.perf_counter() - total_start, 3)
        raise LegacyMigrationError(
            "v1 migration verification failed:\n  " + "\n  ".join(report.mismatches), report
        )
    if target.exists():
        for suffix in ("-wal", "-shm", "-journal"):
            sibling = Path(f"{target}{suffix}")
            if sibling.exists():
                sibling.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, target)
    report.ok = True
    report.finished_at = utcnow_ts()
    report.timings_s["total"] = round(time.perf_counter() - total_start, 3)
    logger.info(
        "Migrated v1 %s -> %s (%d instagram, %d telegram items)",
        source,
        target,
        report.items.get("instagram", 0),
        report.items.get("telegram", 0),
    )
    return report
