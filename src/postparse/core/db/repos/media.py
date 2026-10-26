"""Media attachments and the transcription work queue."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath, PureWindowsPath

from postparse.core.db.models import Media, MediaInput, Source
from postparse.core.timeutil import to_db_ts, utcnow_ts

__all__ = ["MediaRepo", "normalize_local_path"]

_TRANSCRIBABLE = ("video", "audio")


def normalize_local_path(path: str) -> str:
    """Return ``path`` as a POSIX path relative to the downloads directory.

    Backslashes are converted to ``/``.

    Raises:
        ValueError: If the path is absolute, empty or escapes upwards (``..``).
    """
    if PureWindowsPath(path).is_absolute() or PureWindowsPath(path).drive:
        raise ValueError(f"media.local_path must be relative to downloads_dir: {path!r}")
    posix = PurePosixPath(path.replace("\\", "/"))
    if posix.is_absolute() or ".." in posix.parts or str(posix) in ("", "."):
        raise ValueError(f"media.local_path must be relative to downloads_dir: {path!r}")
    return posix.as_posix()


class MediaRepo:
    """Access to ``media``.

    Args:
        conn: Open connection; the caller controls the transaction.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, item_id: int, media: MediaInput) -> int:
        """Insert or update the media at ``(item_id, position)``.

        Descriptive fields are updated (``NULL`` inputs keep stored values).
        Transcript state (status, attempts, errors, schedule) is never reset;
        the only transition applied is ``none`` -> ``pending`` when a row turns
        into video/audio.

        Returns:
            Media id.
        """
        status = media.transcript_status or (
            "pending" if media.media_type in _TRANSCRIBABLE else "none"
        )
        local_path = normalize_local_path(media.local_path) if media.local_path else None
        seen_at = utcnow_ts() if media.remote_url else None
        row = self.conn.execute(
            """
            INSERT INTO media (item_id, position, media_type, local_path, remote_url,
                               remote_url_seen_at, mime, size_bytes, duration_s, sha256,
                               transcript_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (item_id, position) DO UPDATE SET
                media_type = excluded.media_type,
                local_path = coalesce(excluded.local_path, media.local_path),
                remote_url = coalesce(excluded.remote_url, media.remote_url),
                remote_url_seen_at = coalesce(excluded.remote_url_seen_at,
                                              media.remote_url_seen_at),
                mime = coalesce(excluded.mime, media.mime),
                size_bytes = coalesce(excluded.size_bytes, media.size_bytes),
                duration_s = coalesce(excluded.duration_s, media.duration_s),
                sha256 = coalesce(excluded.sha256, media.sha256),
                transcript_status = CASE
                    WHEN media.transcript_status = 'none'
                         AND excluded.transcript_status = 'pending' THEN 'pending'
                    ELSE media.transcript_status END,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            RETURNING id
            """,
            (
                item_id,
                media.position,
                media.media_type,
                local_path,
                media.remote_url,
                seen_at,
                media.mime,
                media.size_bytes,
                media.duration_s,
                media.sha256,
                status,
            ),
        ).fetchone()
        return int(row[0])

    def get(self, media_id: int) -> Media | None:
        """Return one media row or ``None``."""
        row = self.conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        return Media.from_row(row) if row else None

    def for_item(self, item_id: int) -> list[Media]:
        """Return an item's media ordered by position."""
        return self.for_items([item_id]).get(item_id, [])

    def for_items(self, item_ids: Sequence[int]) -> dict[int, list[Media]]:
        """Return media of several items in one query."""
        result: dict[int, list[Media]] = {}
        if not item_ids:
            return result
        rows = self.conn.execute(
            "SELECT * FROM media WHERE item_id IN (SELECT value FROM json_each(?)) "
            "ORDER BY item_id, position",
            (json.dumps(list(item_ids)),),
        ).fetchall()
        for row in rows:
            result.setdefault(row["item_id"], []).append(Media.from_row(row))
        return result

    def pending_transcriptions(
        self,
        source: Source | None = None,
        limit: int = 50,
        now: datetime | None = None,
        *,
        max_attempts: int = 5,
    ) -> list[Media]:
        """Return media due for transcription.

        Due means status ``pending`` or ``failed``, ``next_attempt_at`` unset or
        in the past, and fewer than ``max_attempts`` attempts.

        Args:
            source: Restrict to items of one source.
            limit: Maximum rows.
            now: Reference time (default: current time).
            max_attempts: Media with this many failed attempts are not retried.

        Returns:
            Media ordered by fewest attempts, then oldest id.
        """
        now_ts = to_db_ts(now) if now is not None else utcnow_ts()
        sql = (
            "SELECT m.* FROM media AS m JOIN items AS i ON i.id = m.item_id "
            "WHERE m.transcript_status IN ('pending', 'failed') "
            "AND (m.next_attempt_at IS NULL OR m.next_attempt_at <= ?) "
            "AND m.attempts < ?"
        )
        params: list[object] = [now_ts, max_attempts]
        if source is not None:
            sql += " AND i.source = ?"
            params.append(source)
        sql += " ORDER BY m.attempts, m.id LIMIT ?"
        params.append(limit)
        return [Media.from_row(row) for row in self.conn.execute(sql, params).fetchall()]

    def mark_transcribed(self, media_id: int, status: str = "transcribed") -> None:
        """Mark media as finished.

        Args:
            media_id: Media id.
            status: ``transcribed``, ``no_audio`` or ``skipped``.

        Raises:
            ValueError: For any other status.
        """
        if status not in ("transcribed", "no_audio", "skipped"):
            raise ValueError(f"Not a terminal transcript status: {status!r}")
        self.conn.execute(
            "UPDATE media SET transcript_status = ?, last_error = NULL, next_attempt_at = NULL, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (status, media_id),
        )

    def mark_failed(
        self,
        media_id: int,
        error: str,
        *,
        backoff: timedelta = timedelta(minutes=10),
        max_backoff: timedelta = timedelta(days=1),
        now: datetime | None = None,
    ) -> datetime:
        """Record a failed attempt and schedule the next one with exponential backoff.

        The delay is ``backoff * 2 ** (attempts - 1)`` capped at ``max_backoff``,
        where ``attempts`` includes this failure.

        Args:
            media_id: Media id.
            error: Error description.
            backoff: Delay after the first failure.
            max_backoff: Upper bound for the delay.
            now: Reference time (default: current time).

        Returns:
            The scheduled ``next_attempt_at``.

        Raises:
            KeyError: If the media does not exist.
        """
        row = self.conn.execute("SELECT attempts FROM media WHERE id = ?", (media_id,)).fetchone()
        if row is None:
            raise KeyError(media_id)
        attempts = int(row[0]) + 1
        delay = min(backoff * (2 ** (attempts - 1)), max_backoff)
        next_at = (now or datetime.now(UTC)) + delay
        self.conn.execute(
            "UPDATE media SET transcript_status = 'failed', attempts = ?, last_error = ?, "
            "next_attempt_at = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "WHERE id = ?",
            (attempts, error, to_db_ts(next_at), media_id),
        )
        return next_at

    def set_remote_url(
        self, media_id: int, url: str, seen_at: datetime | None = None
    ) -> None:
        """Store a (fresh) remote URL and when it was observed."""
        seen = to_db_ts(seen_at) if seen_at is not None else utcnow_ts()
        self.conn.execute(
            "UPDATE media SET remote_url = ?, remote_url_seen_at = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (url, seen, media_id),
        )
