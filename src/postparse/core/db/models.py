"""Row and input dataclasses for the schema v2 database.

Row classes (``Item``, ``Media``, ...) mirror table rows; timestamps are aware
UTC ``datetime`` objects. Input classes (``ItemUpsert``, ``MediaInput``, ...)
describe writes; their timestamps may be aware datetimes or ISO strings with
an offset (naive values are rejected, see :func:`postparse.core.timeutil.to_db_ts`).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from postparse.core.timeutil import from_db_ts

__all__ = [
    "ClassificationResult",
    "ClassificationRun",
    "CurrentClassification",
    "InstagramDetail",
    "Item",
    "ItemFilter",
    "ItemUpsert",
    "LabelFilter",
    "Link",
    "LinkFetch",
    "Media",
    "MediaInput",
    "Summary",
    "Tag",
    "TagCount",
    "Taxonomy",
    "TaxonomyLabel",
    "TelegramDetail",
    "Transcript",
]

Source = Literal["instagram", "telegram"]
ItemKind = Literal["text", "image", "video", "carousel", "document", "audio", "other"]
MediaType = Literal["image", "video", "audio", "document", "other"]
TranscriptStatus = Literal["none", "pending", "transcribed", "no_audio", "failed", "skipped"]
TagKind = Literal["hashtag", "mention"]
TaxonomyMode = Literal["single", "multi"]
RunStatus = Literal["running", "done", "failed", "legacy"]
ResultStatus = Literal["ok", "no_labels", "error"]
FetchStatus = Literal["ok", "error", "skipped"]
PendingScope = Literal["default", "backfill", "reprocess"]

TimestampValue = datetime | str


def _ts(value: str | None) -> datetime | None:
    """Parse an optional canonical timestamp column."""
    return from_db_ts(value) if value is not None else None


def _json(value: str | None) -> Any:
    """Decode an optional JSON column."""
    return json.loads(value) if value is not None else None


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstagramDetail:
    """Instagram-specific fields of an item (``instagram_posts`` row)."""

    shortcode: str
    owner_id: int | None = None
    typename: str | None = None
    likes: int | None = None
    comments: int | None = None
    saved_feed_rank: int | None = None


@dataclass(frozen=True, slots=True)
class TelegramDetail:
    """Telegram-specific fields of an item (``telegram_messages`` row)."""

    chat_id: int
    message_id: int
    views: int | None = None
    forwards: int | None = None
    reply_to_msg_id: int | None = None
    fwd_from_name: str | None = None
    fwd_from_id: int | None = None
    fwd_from_post_id: int | None = None


@dataclass(frozen=True, slots=True)
class MediaInput:
    """One media attachment to upsert, identified by ``(item, position)``.

    Attributes:
        position: 0-based position within the item.
        media_type: Media type.
        local_path: POSIX path relative to ``Settings.downloads_dir``.
        remote_url: CDN URL (may expire; see ``remote_url_seen_at``).
        transcript_status: Initial status for new rows. ``None`` means
            ``pending`` for video/audio and ``none`` otherwise. Never applied
            to existing rows (transcript state is owned by the transcriber).
    """

    position: int
    media_type: MediaType
    local_path: str | None = None
    remote_url: str | None = None
    mime: str | None = None
    size_bytes: int | None = None
    duration_s: float | None = None
    sha256: str | None = None
    transcript_status: TranscriptStatus | None = None


@dataclass(frozen=True, slots=True)
class ItemUpsert:
    """Full description of a collected item for :meth:`ItemsRepo.upsert`.

    Collection fields set to ``None`` leave the stored data untouched; an
    empty tuple clears it.

    Attributes:
        source: ``instagram`` or ``telegram``.
        external_id: Stable id within the source (convention: shortcode for
            Instagram, ``"<chat_id>:<message_id>"`` for Telegram).
        kind: Item kind.
        text: Caption / message text. ``None`` keeps the stored text.
        author: Author handle or name. ``None`` keeps the stored value.
        url: Permalink. ``None`` keeps the stored value.
        created_at: Publication time at the source, if known.
        collected_at: First collection time (default: now). Only used on insert.
        detail: Per-source detail row.
        hashtags: Replaces the item's hashtags when not ``None``.
        mentions: Replaces the item's mentions when not ``None``.
        media: Media to upsert by position when not ``None`` (other positions
            are kept).
        links: Replaces the item's links when not ``None``; ``None`` derives
            links from ``text`` when text is given.
    """

    source: Source
    external_id: str
    kind: ItemKind
    text: str | None = None
    author: str | None = None
    url: str | None = None
    created_at: TimestampValue | None = None
    collected_at: TimestampValue | None = None
    detail: InstagramDetail | TelegramDetail | None = None
    hashtags: tuple[str, ...] | None = None
    mentions: tuple[str, ...] | None = None
    media: tuple[MediaInput, ...] | None = None
    links: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class TaxonomyLabel:
    """A label of a taxonomy."""

    name: str
    description: str = ""


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Item:
    """An ``items`` row."""

    id: int
    source: Source
    external_id: str
    kind: ItemKind
    text: str | None
    author: str | None
    url: str | None
    created_at: datetime | None
    collected_at: datetime
    updated_at: datetime
    sort_at: datetime

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Item:
        """Build from a row selecting all ``items`` columns including ``sort_at``."""
        return cls(
            id=row["id"],
            source=row["source"],
            external_id=row["external_id"],
            kind=row["kind"],
            text=row["text"],
            author=row["author"],
            url=row["url"],
            created_at=_ts(row["created_at"]),
            collected_at=from_db_ts(row["collected_at"]),
            updated_at=from_db_ts(row["updated_at"]),
            sort_at=from_db_ts(row["sort_at"]),
        )


@dataclass(frozen=True, slots=True)
class Tag:
    """A hashtag or mention."""

    id: int
    kind: TagKind
    name: str

    @property
    def display(self) -> str:
        """Name with ``#`` or ``@`` prefix."""
        return ("#" if self.kind == "hashtag" else "@") + self.name


@dataclass(frozen=True, slots=True)
class TagCount:
    """A tag with the number of items carrying it."""

    kind: TagKind
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class Media:
    """A ``media`` row."""

    id: int
    item_id: int
    position: int
    media_type: MediaType
    local_path: str | None
    remote_url: str | None
    remote_url_seen_at: datetime | None
    mime: str | None
    size_bytes: int | None
    duration_s: float | None
    sha256: str | None
    transcript_status: TranscriptStatus
    attempts: int
    last_error: str | None
    next_attempt_at: datetime | None
    updated_at: datetime

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Media:
        """Build from a ``SELECT * FROM media`` row."""
        return cls(
            id=row["id"],
            item_id=row["item_id"],
            position=row["position"],
            media_type=row["media_type"],
            local_path=row["local_path"],
            remote_url=row["remote_url"],
            remote_url_seen_at=_ts(row["remote_url_seen_at"]),
            mime=row["mime"],
            size_bytes=row["size_bytes"],
            duration_s=row["duration_s"],
            sha256=row["sha256"],
            transcript_status=row["transcript_status"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            next_attempt_at=_ts(row["next_attempt_at"]),
            updated_at=from_db_ts(row["updated_at"]),
        )


@dataclass(frozen=True, slots=True)
class Transcript:
    """A ``transcripts`` row (``segments`` decoded from JSON)."""

    id: int
    media_id: int
    backend: str
    model: str
    language: str | None
    text: str
    segments: Any
    duration_s: float | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Transcript:
        """Build from a ``SELECT * FROM transcripts`` row."""
        return cls(
            id=row["id"],
            media_id=row["media_id"],
            backend=row["backend"],
            model=row["model"],
            language=row["language"],
            text=row["text"],
            segments=_json(row["segments"]),
            duration_s=row["duration_s"],
            created_at=from_db_ts(row["created_at"]),
        )


@dataclass(frozen=True, slots=True)
class Summary:
    """A ``summaries`` row."""

    id: int
    item_id: int
    provider: str | None
    model: str | None
    prompt_sha256: str | None
    text: str
    created_at: datetime

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Summary:
        """Build from a ``SELECT * FROM summaries`` row."""
        return cls(
            id=row["id"],
            item_id=row["item_id"],
            provider=row["provider"],
            model=row["model"],
            prompt_sha256=row["prompt_sha256"],
            text=row["text"],
            created_at=from_db_ts(row["created_at"]),
        )


@dataclass(frozen=True, slots=True)
class Link:
    """A ``links`` row (normalized URL)."""

    id: int
    url: str
    domain: str


@dataclass(frozen=True, slots=True)
class LinkFetch:
    """A ``link_fetches`` row (``metadata`` decoded from JSON)."""

    id: int
    link_id: int
    fetcher: str
    status: FetchStatus
    http_status: int | None
    title: str | None
    text: str | None
    metadata: Any
    error: str | None
    fetched_at: datetime

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> LinkFetch:
        """Build from a ``SELECT * FROM link_fetches`` row."""
        return cls(
            id=row["id"],
            link_id=row["link_id"],
            fetcher=row["fetcher"],
            status=row["status"],
            http_status=row["http_status"],
            title=row["title"],
            text=row["text"],
            metadata=_json(row["metadata"]),
            error=row["error"],
            fetched_at=from_db_ts(row["fetched_at"]),
        )


@dataclass(frozen=True, slots=True)
class Taxonomy:
    """A ``taxonomies`` row (``labels`` decoded)."""

    id: int
    name: str
    mode: TaxonomyMode
    version: int
    labels: tuple[TaxonomyLabel, ...]
    label_set_sha256: str
    is_legacy: bool
    created_at: datetime
    updated_at: datetime

    @property
    def label_names(self) -> tuple[str, ...]:
        """Label names in stored order."""
        return tuple(label.name for label in self.labels)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Taxonomy:
        """Build from a ``SELECT * FROM taxonomies`` row."""
        labels = tuple(
            TaxonomyLabel(entry["name"], entry.get("description", ""))
            for entry in json.loads(row["labels"])
        )
        return cls(
            id=row["id"],
            name=row["name"],
            mode=row["mode"],
            version=row["version"],
            labels=labels,
            label_set_sha256=row["label_set_sha256"],
            is_legacy=bool(row["is_legacy"]),
            created_at=from_db_ts(row["created_at"]),
            updated_at=from_db_ts(row["updated_at"]),
        )


@dataclass(frozen=True, slots=True)
class ClassificationRun:
    """A ``classification_runs`` row."""

    id: int
    taxonomy_id: int
    provider: str | None
    model: str | None
    label_set_sha256: str | None
    prompt_sha256: str | None
    params: Any
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    n_ok: int
    n_failed: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> ClassificationRun:
        """Build from a ``SELECT * FROM classification_runs`` row."""
        return cls(
            id=row["id"],
            taxonomy_id=row["taxonomy_id"],
            provider=row["provider"],
            model=row["model"],
            label_set_sha256=row["label_set_sha256"],
            prompt_sha256=row["prompt_sha256"],
            params=_json(row["params"]),
            status=row["status"],
            started_at=from_db_ts(row["started_at"]),
            finished_at=_ts(row["finished_at"]),
            n_ok=row["n_ok"],
            n_failed=row["n_failed"],
        )


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """A ``classification_results`` row with its labels."""

    id: int
    run_id: int
    item_id: int
    taxonomy_id: int
    status: ResultStatus
    labels: tuple[tuple[str, float | None], ...]
    confidence: float | None
    reasoning: str | None
    details: Any
    error: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CurrentClassification:
    """The current (newest ok/no_labels) classification of an item in a taxonomy."""

    item_id: int
    taxonomy_id: int
    taxonomy: str
    result_id: int
    run_id: int
    status: ResultStatus
    labels: tuple[str, ...]
    confidence: float | None
    reasoning: str | None
    provider: str | None
    model: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LabelFilter:
    """Match items whose current classification in ``taxonomy`` has any of ``labels``.

    An empty ``labels`` tuple matches items with any current ``ok`` result.
    """

    taxonomy: str
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ItemFilter:
    """Item selection criteria; all given criteria must match (AND).

    Attributes:
        source: Restrict to one source.
        kinds: Any of these kinds.
        tags: Any of these tags. ``#name`` matches hashtags, ``@name`` mentions,
            a bare name either kind (case-insensitive).
        authors: Any of these authors (exact match).
        date_from: ``sort_at >= date_from``. Naive datetimes are taken as UTC.
        date_to: ``sort_at <= date_to``; a plain ``date`` includes that whole day.
        labels: Current classification filter.
        q: Full-text query; plain words (AND), ``"quoted phrases"`` and a
            trailing ``*`` for prefixes are supported, everything else is
            treated literally.
        has_transcript: ``True``/``False`` to require items with/without a
            transcript on any media.
    """

    source: Source | None = None
    kinds: tuple[ItemKind, ...] = ()
    tags: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    date_from: datetime | date | str | None = None
    date_to: datetime | date | str | None = None
    labels: LabelFilter | None = None
    q: str | None = None
    has_transcript: bool | None = None
