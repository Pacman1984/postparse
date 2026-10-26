"""Items and their per-source detail rows."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from postparse.core.db.models import (
    InstagramDetail,
    Item,
    ItemUpsert,
    Source,
    TelegramDetail,
)
from postparse.core.db.repos.links import LinksRepo
from postparse.core.db.repos.media import MediaRepo
from postparse.core.db.repos.search import SearchRepo
from postparse.core.db.repos.tags import TagsRepo
from postparse.core.timeutil import to_db_ts, utcnow_ts
from postparse.core.urls import extract_urls

__all__ = ["ItemsRepo"]

_ITEM_COLUMNS = (
    "id, source, external_id, kind, text, author, url, created_at, collected_at, "
    "updated_at, sort_at"
)


class ItemsRepo:
    """Access to ``items``, ``instagram_posts``, ``telegram_messages`` and
    ``legacy_expanded_text``.

    Args:
        conn: Open connection; the caller controls the transaction.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, item: ItemUpsert) -> tuple[int, bool]:
        """Insert or update an item with tags, media, links and detail row.

        On conflict ``(source, external_id)`` the mutable fields are updated
        (``None`` inputs keep stored values), ``updated_at`` is bumped and
        ``collected_at`` is preserved. The search document is refreshed.

        Args:
            item: Item description.

        Returns:
            ``(item_id, created)``.

        Raises:
            ValueError: If the detail type does not match ``item.source`` or a
                timestamp is naive.
        """
        if isinstance(item.detail, InstagramDetail) and item.source != "instagram":
            raise ValueError("InstagramDetail requires source 'instagram'")
        if isinstance(item.detail, TelegramDetail) and item.source != "telegram":
            raise ValueError("TelegramDetail requires source 'telegram'")

        now = utcnow_ts()
        created_at = to_db_ts(item.created_at) if item.created_at is not None else None
        collected_at = to_db_ts(item.collected_at) if item.collected_at is not None else now
        existing = self.conn.execute(
            "SELECT id FROM items WHERE source = ? AND external_id = ?",
            (item.source, item.external_id),
        ).fetchone()
        row = self.conn.execute(
            """
            INSERT INTO items (source, external_id, kind, text, author, url, created_at,
                               collected_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, external_id) DO UPDATE SET
                kind = excluded.kind,
                text = coalesce(excluded.text, items.text),
                author = coalesce(excluded.author, items.author),
                url = coalesce(excluded.url, items.url),
                created_at = coalesce(excluded.created_at, items.created_at),
                updated_at = excluded.updated_at
            RETURNING id
            """,
            (
                item.source,
                item.external_id,
                item.kind,
                item.text,
                item.author,
                item.url,
                created_at,
                collected_at,
                now,
            ),
        ).fetchone()
        item_id = int(row[0])

        if isinstance(item.detail, InstagramDetail):
            self._upsert_instagram(item_id, item.detail)
        elif isinstance(item.detail, TelegramDetail):
            self._upsert_telegram(item_id, item.detail)

        if item.hashtags is not None or item.mentions is not None:
            TagsRepo(self.conn).set_item_tags(
                item_id, hashtags=item.hashtags, mentions=item.mentions
            )
        if item.media is not None:
            media_repo = MediaRepo(self.conn)
            for media in item.media:
                media_repo.upsert(item_id, media)
        links = item.links
        if links is None and item.text is not None:
            links = tuple(extract_urls(item.text))
        if links is not None:
            LinksRepo(self.conn).set_item_links(item_id, links, refresh=False)

        SearchRepo(self.conn).refresh([item_id])
        return item_id, existing is None

    def _upsert_instagram(self, item_id: int, d: InstagramDetail) -> None:
        """Write the ``instagram_posts`` row (``None`` keeps stored values)."""
        self.conn.execute(
            """
            INSERT INTO instagram_posts (item_id, shortcode, owner_id, typename, likes,
                                         comments, saved_feed_rank)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (item_id) DO UPDATE SET
                shortcode = excluded.shortcode,
                owner_id = coalesce(excluded.owner_id, instagram_posts.owner_id),
                typename = coalesce(excluded.typename, instagram_posts.typename),
                likes = coalesce(excluded.likes, instagram_posts.likes),
                comments = coalesce(excluded.comments, instagram_posts.comments),
                saved_feed_rank = coalesce(excluded.saved_feed_rank,
                                           instagram_posts.saved_feed_rank)
            """,
            (item_id, d.shortcode, d.owner_id, d.typename, d.likes, d.comments,
             d.saved_feed_rank),
        )

    def _upsert_telegram(self, item_id: int, d: TelegramDetail) -> None:
        """Write the ``telegram_messages`` row (``None`` keeps stored values)."""
        self.conn.execute(
            """
            INSERT INTO telegram_messages (item_id, chat_id, message_id, views, forwards,
                                           reply_to_msg_id, fwd_from_name, fwd_from_id,
                                           fwd_from_post_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (item_id) DO UPDATE SET
                chat_id = excluded.chat_id,
                message_id = excluded.message_id,
                views = coalesce(excluded.views, telegram_messages.views),
                forwards = coalesce(excluded.forwards, telegram_messages.forwards),
                reply_to_msg_id = coalesce(excluded.reply_to_msg_id,
                                           telegram_messages.reply_to_msg_id),
                fwd_from_name = coalesce(excluded.fwd_from_name, telegram_messages.fwd_from_name),
                fwd_from_id = coalesce(excluded.fwd_from_id, telegram_messages.fwd_from_id),
                fwd_from_post_id = coalesce(excluded.fwd_from_post_id,
                                            telegram_messages.fwd_from_post_id)
            """,
            (item_id, d.chat_id, d.message_id, d.views, d.forwards, d.reply_to_msg_id,
             d.fwd_from_name, d.fwd_from_id, d.fwd_from_post_id),
        )

    def get(self, item_id: int) -> Item | None:
        """Return an item by id."""
        row = self.conn.execute(
            f"SELECT {_ITEM_COLUMNS} FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return Item.from_row(row) if row else None

    def get_by_external(self, source: Source, external_id: str) -> Item | None:
        """Return an item by ``(source, external_id)``."""
        row = self.conn.execute(
            f"SELECT {_ITEM_COLUMNS} FROM items WHERE source = ? AND external_id = ?",
            (source, external_id),
        ).fetchone()
        return Item.from_row(row) if row else None

    def exists(self, source: Source, external_id: str) -> bool:
        """Return True if the item is stored."""
        return (
            self.conn.execute(
                "SELECT 1 FROM items WHERE source = ? AND external_id = ?",
                (source, external_id),
            ).fetchone()
            is not None
        )

    def delete(self, item_id: int) -> bool:
        """Delete an item and (by cascade) everything attached to it."""
        cursor = self.conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return cursor.rowcount > 0

    def instagram_detail(self, item_id: int) -> InstagramDetail | None:
        """Return the Instagram detail row of an item."""
        row = self.conn.execute(
            "SELECT shortcode, owner_id, typename, likes, comments, saved_feed_rank "
            "FROM instagram_posts WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        return InstagramDetail(*row) if row else None

    def telegram_detail(self, item_id: int) -> TelegramDetail | None:
        """Return the Telegram detail row of an item."""
        row = self.conn.execute(
            "SELECT chat_id, message_id, views, forwards, reply_to_msg_id, fwd_from_name, "
            "fwd_from_id, fwd_from_post_id FROM telegram_messages WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        return TelegramDetail(*row) if row else None

    def max_telegram_message_id(self, chat_id: int | None = None) -> int | None:
        """Return the highest stored Telegram message id (optionally per chat)."""
        if chat_id is None:
            row = self.conn.execute("SELECT max(message_id) FROM telegram_messages").fetchone()
        else:
            row = self.conn.execute(
                "SELECT max(message_id) FROM telegram_messages WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return int(row[0]) if row[0] is not None else None

    def known_instagram_shortcodes(self, shortcodes: Iterable[str]) -> set[str]:
        """Return the subset of ``shortcodes`` already stored."""
        codes = list(dict.fromkeys(shortcodes))
        if not codes:
            return set()
        rows = self.conn.execute(
            "SELECT shortcode FROM instagram_posts "
            "WHERE shortcode IN (SELECT value FROM json_each(?))",
            (json.dumps(codes),),
        ).fetchall()
        return {row[0] for row in rows}

    def set_legacy_expanded_text(self, item_id: int, text: str | None) -> None:
        """Store (or clear with ``None``) the v1 expanded text and refresh search."""
        if text is None:
            self.conn.execute("DELETE FROM legacy_expanded_text WHERE item_id = ?", (item_id,))
        else:
            self.conn.execute(
                "INSERT INTO legacy_expanded_text (item_id, text) VALUES (?, ?) "
                "ON CONFLICT (item_id) DO UPDATE SET text = excluded.text",
                (item_id, text),
            )
        SearchRepo(self.conn).refresh([item_id])
