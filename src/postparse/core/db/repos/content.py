"""Derived content: transcripts and summaries."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from typing import Any

from postparse.core.db.models import Summary, Transcript
from postparse.core.db.repos.search import SearchRepo

__all__ = ["SummariesRepo", "TranscriptsRepo"]


class TranscriptsRepo:
    """Access to ``transcripts``.

    Args:
        conn: Open connection; the caller controls the transaction.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(
        self,
        media_id: int,
        *,
        backend: str,
        model: str,
        text: str,
        language: str | None = None,
        segments: Any = None,
        duration_s: float | None = None,
    ) -> int:
        """Store a transcript; replaces an earlier one of the same backend/model.

        Also refreshes the item's search document. Media status is not changed;
        call :meth:`MediaRepo.mark_transcribed` in the same transaction.

        Returns:
            Transcript id.
        """
        row = self.conn.execute(
            """
            INSERT INTO transcripts (media_id, backend, model, language, text, segments,
                                     duration_s)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (media_id, backend, model) DO UPDATE SET
                language = excluded.language,
                text = excluded.text,
                segments = excluded.segments,
                duration_s = excluded.duration_s,
                created_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            RETURNING id
            """,
            (
                media_id,
                backend,
                model,
                language,
                text,
                json.dumps(segments, ensure_ascii=False) if segments is not None else None,
                duration_s,
            ),
        ).fetchone()
        item_row = self.conn.execute(
            "SELECT item_id FROM media WHERE id = ?", (media_id,)
        ).fetchone()
        SearchRepo(self.conn).refresh([item_row[0]])
        return int(row[0])

    def current_for_media(self, media_id: int) -> Transcript | None:
        """Return the newest transcript of a media item."""
        row = self.conn.execute(
            "SELECT * FROM transcripts WHERE media_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (media_id,),
        ).fetchone()
        return Transcript.from_row(row) if row else None

    def current_for_items(self, item_ids: Sequence[int]) -> dict[int, list[Transcript]]:
        """Return the newest transcript per media for several items.

        Returns:
            ``{item_id: [Transcript, ...]}`` ordered by media position.
        """
        result: dict[int, list[Transcript]] = {}
        if not item_ids:
            return result
        rows = self.conn.execute(
            """
            SELECT m.item_id AS owner_item_id, t.* FROM media AS m
            JOIN transcripts AS t ON t.id = (
                SELECT t2.id FROM transcripts AS t2 WHERE t2.media_id = m.id
                ORDER BY t2.created_at DESC, t2.id DESC LIMIT 1)
            WHERE m.item_id IN (SELECT value FROM json_each(?))
            ORDER BY m.item_id, m.position
            """,
            (json.dumps(list(item_ids)),),
        ).fetchall()
        for row in rows:
            result.setdefault(row["owner_item_id"], []).append(Transcript.from_row(row))
        return result


class SummariesRepo:
    """Access to ``summaries`` (append-only; the newest row is current).

    Args:
        conn: Open connection; the caller controls the transaction.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(
        self,
        item_id: int,
        text: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        prompt_sha256: str | None = None,
    ) -> int:
        """Append a summary and refresh the item's search document.

        Returns:
            Summary id.
        """
        row = self.conn.execute(
            "INSERT INTO summaries (item_id, provider, model, prompt_sha256, text) "
            "VALUES (?, ?, ?, ?, ?) RETURNING id",
            (item_id, provider, model, prompt_sha256, text),
        ).fetchone()
        SearchRepo(self.conn).refresh([item_id])
        return int(row[0])

    def latest(self, item_id: int) -> Summary | None:
        """Return the newest summary of an item."""
        return self.latest_for_items([item_id]).get(item_id)

    def latest_for_items(self, item_ids: Sequence[int]) -> dict[int, Summary]:
        """Return the newest summary per item for several items."""
        if not item_ids:
            return {}
        rows = self.conn.execute(
            "SELECT s.* FROM summaries AS s WHERE s.id IN ("
            " SELECT max(id) FROM summaries"
            " WHERE item_id IN (SELECT value FROM json_each(?)) GROUP BY item_id)",
            (json.dumps(list(item_ids)),),
        ).fetchall()
        return {row["item_id"]: Summary.from_row(row) for row in rows}

    def items_needing_summary(
        self,
        *,
        limit: int | None = None,
        force: bool = False,
        item_ids: Sequence[int] | None = None,
    ) -> list[int]:
        """Return items with a transcript and no summary newer than their newest transcript.

        Args:
            limit: Maximum items.
            force: Ignore existing summaries (every item with a transcript).
            item_ids: Restrict to these items.

        Returns:
            Item ids, oldest first.
        """
        sql = (
            "SELECT m.item_id, max(t.created_at) AS newest FROM media AS m "
            "JOIN transcripts AS t ON t.media_id = m.id "
        )
        params: list[object] = []
        if item_ids is not None:
            sql += "WHERE m.item_id IN (SELECT value FROM json_each(?)) "
            params.append(json.dumps(list(item_ids)))
        sql += "GROUP BY m.item_id"
        outer = f"SELECT x.item_id FROM ({sql}) AS x "
        if not force:
            outer += (
                "WHERE NOT EXISTS (SELECT 1 FROM summaries AS s WHERE s.item_id = x.item_id "
                "AND s.created_at >= x.newest) "
            )
        outer += "ORDER BY x.item_id"
        if limit is not None:
            outer += " LIMIT ?"
            params.append(limit)
        return [int(row[0]) for row in self.conn.execute(outer, params).fetchall()]
