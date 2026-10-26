"""Full-text search documents (``search_docs`` -> ``items_fts``).

``search_docs`` holds one denormalized document per item; triggers keep the
external-content FTS5 index ``items_fts`` in sync. The repositories that change
searchable content call :meth:`SearchRepo.refresh` for the affected items in
the caller's transaction:

* ``ItemsRepo.upsert`` / ``ItemsRepo.set_legacy_expanded_text`` (text, tags, links),
* ``TranscriptsRepo.add`` (transcripts),
* ``SummariesRepo.add`` (summaries),
* ``LinksRepo.add_fetch`` / ``LinksRepo.set_item_links`` (fetched link texts).

Direct SQL writes to those tables must call :meth:`refresh` themselves (or run
``postparse db reindex``).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

__all__ = ["SearchRepo"]

_DOC_SELECT = """
SELECT
    i.id,
    i.text,
    nullif(concat_ws(char(10),
        (SELECT group_concat(t.text, char(10) ORDER BY m.position)
           FROM media AS m
           JOIN transcripts AS t ON t.id = (
                SELECT t2.id FROM transcripts AS t2 WHERE t2.media_id = m.id
                ORDER BY t2.created_at DESC, t2.id DESC LIMIT 1)
          WHERE m.item_id = i.id),
        (SELECT s.text FROM summaries AS s WHERE s.item_id = i.id
          ORDER BY s.id DESC LIMIT 1),
        (SELECT group_concat(concat_ws(char(10), lf.title, lf.text), char(10)
                             ORDER BY il.position)
           FROM item_links AS il
           JOIN link_fetches AS lf ON lf.id = (
                SELECT lf2.id FROM link_fetches AS lf2
                WHERE lf2.link_id = il.link_id AND lf2.status = 'ok'
                ORDER BY lf2.fetched_at DESC, lf2.id DESC LIMIT 1)
          WHERE il.item_id = i.id),
        (SELECT le.text FROM legacy_expanded_text AS le WHERE le.item_id = i.id)
    ), ''),
    (SELECT group_concat(tg.name, ' ' ORDER BY tg.kind, tg.name)
       FROM item_tags AS it JOIN tags AS tg ON tg.id = it.tag_id
      WHERE it.item_id = i.id)
FROM items AS i
"""

_UPSERT_TAIL = """
ON CONFLICT (item_id) DO UPDATE SET
    body = excluded.body,
    extra = excluded.extra,
    tags = excluded.tags
WHERE search_docs.body IS NOT excluded.body
   OR search_docs.extra IS NOT excluded.extra
   OR search_docs.tags IS NOT excluded.tags
"""


class SearchRepo:
    """Maintenance of the full-text search documents.

    Args:
        conn: Open connection; the caller controls the transaction.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def refresh(self, item_ids: Iterable[int]) -> None:
        """Rebuild the search documents of the given items.

        Unchanged documents are not rewritten (no FTS churn); ids of deleted
        items are ignored (their documents are removed by cascade).

        Args:
            item_ids: Items whose searchable content changed.
        """
        ids = sorted(set(item_ids))
        if not ids:
            return
        self.conn.execute(
            "INSERT INTO search_docs (item_id, body, extra, tags) "
            + _DOC_SELECT
            + " WHERE i.id IN (SELECT value FROM json_each(?)) "
            + _UPSERT_TAIL,
            (json.dumps(ids),),
        )

    def rebuild_all(self) -> int:
        """Rebuild every search document and the FTS index from scratch.

        Returns:
            Number of items indexed.
        """
        self.conn.execute("DELETE FROM search_docs WHERE item_id NOT IN (SELECT id FROM items)")
        self.conn.execute(
            "INSERT INTO search_docs (item_id, body, extra, tags) "
            + _DOC_SELECT
            + " WHERE true "
            + _UPSERT_TAIL
        )
        self.conn.execute("INSERT INTO items_fts (items_fts) VALUES ('rebuild')")
        return int(self.conn.execute("SELECT count(*) FROM search_docs").fetchone()[0])

    def optimize(self) -> None:
        """Merge FTS index segments (run outside hot paths)."""
        self.conn.execute("INSERT INTO items_fts (items_fts) VALUES ('optimize')")

    def integrity_check(self) -> bool:
        """Return True if the FTS index matches ``search_docs``."""
        try:
            self.conn.execute(
                "INSERT INTO items_fts (items_fts, rank) VALUES ('integrity-check', 1)"
            )
        except sqlite3.DatabaseError:
            return False
        return True

    def indexed_count(self) -> int:
        """Return the number of documents in the FTS index."""
        return int(self.conn.execute("SELECT count(*) FROM items_fts_docsize").fetchone()[0])
