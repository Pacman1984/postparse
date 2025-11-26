"""Database module for social media data storage.

This module handles all database operations for storing and retrieving social media posts.
"""
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import json
from datetime import datetime
import base64


class SocialMediaDatabase:
    """Handles all database operations for social media data."""
    
    INSTAGRAM_BASE_URL = "https://instagram.com/p/"
    
    def __init__(self, db_path: str = "social_media.db"):
        """Initialize database connection and create tables if they don't exist.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self._db_path = Path(db_path)
        self._conn = None
        self._cursor = None
        self.__initialize_database()
    
    def __enter__(self):
        """Context manager entry."""
        self._conn = sqlite3.connect(self._db_path)
        self._cursor = self._conn.cursor()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self._conn:
            self._conn.close()
    
    def __initialize_database(self):
        """Initialize database and ensure all tables exist.
        
        Uses CREATE TABLE IF NOT EXISTS for all tables, so existing data is preserved
        and missing tables are created automatically.
        """
        with self as db:
            db.__create_tables()
    
    def __create_tables(self):
        """Create necessary database tables if they don't exist."""
        # Create Instagram posts table
        self._cursor.execute("""
            CREATE TABLE IF NOT EXISTS instagram_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shortcode TEXT NOT NULL UNIQUE,
                post_url TEXT NOT NULL,  -- Full URL to post
                owner_username TEXT,
                owner_id INTEGER,
                caption TEXT,
                is_video BOOLEAN,
                media_url TEXT,  -- URL to media content
                typename TEXT,  -- Type of post (GraphImage, GraphVideo, etc)
                likes INTEGER,
                comments INTEGER,
                is_saved BOOLEAN NOT NULL DEFAULT 0,  -- Whether this is a saved post
                source TEXT NOT NULL DEFAULT 'saved',  -- Where this post was found (saved, profile, hashtag, etc)
                created_at TIMESTAMP,  -- When the post was created on Instagram
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- When we fetched the post
            )
        """)
        
        # Create Instagram hashtags table
        self._cursor.execute("""
            CREATE TABLE IF NOT EXISTS instagram_hashtags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER,
                hashtag TEXT NOT NULL,
                FOREIGN KEY(post_id) REFERENCES instagram_posts(id),
                UNIQUE(post_id, hashtag)
            )
        """)
        
        # Create Instagram mentions table
        self._cursor.execute("""
            CREATE TABLE IF NOT EXISTS instagram_mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER,
                username TEXT NOT NULL,
                FOREIGN KEY(post_id) REFERENCES instagram_posts(id),
                UNIQUE(post_id, username)
            )
        """)
        
        # Create Telegram messages table
        self._cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL UNIQUE,
                chat_id INTEGER,
                content TEXT,
                content_type TEXT NOT NULL,
                media_urls TEXT,
                views INTEGER,
                forwards INTEGER,
                reply_to_msg_id INTEGER,
                created_at TIMESTAMP,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create Telegram hashtags table
        self._cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_hashtags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                hashtag TEXT NOT NULL,
                FOREIGN KEY(message_id) REFERENCES telegram_messages(id),
                UNIQUE(message_id, hashtag)
            )
        """)
        
        # Create content analysis table for classification results
        self._cursor.execute("""
            CREATE TABLE IF NOT EXISTS content_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id INTEGER NOT NULL,
                content_source TEXT NOT NULL,
                classifier_name TEXT NOT NULL,
                classification_type TEXT NOT NULL DEFAULT 'single',
                run_id TEXT,
                label TEXT NOT NULL,
                confidence REAL NOT NULL,
                reasoning TEXT,
                llm_metadata TEXT,
                llm_provider TEXT,
                llm_model TEXT,
                details_json TEXT,
                analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Ensure columns exist for older databases
        self.__add_column_if_not_exists('content_analysis', 'llm_provider', 'TEXT')
        self.__add_column_if_not_exists('content_analysis', 'llm_model', 'TEXT')
        self.__add_column_if_not_exists('content_analysis', 'details_json', 'TEXT')
        
        self._conn.commit()
    
    def __add_column_if_not_exists(self, table: str, column: str, col_type: str) -> None:
        """Add a column to a table if it doesn't already exist.
        
        Args:
            table: Name of the table.
            column: Name of the column to add.
            col_type: SQL type for the column.
        """
        try:
            self._cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        except sqlite3.OperationalError:
            # Column already exists, ignore
            pass
    
    def _insert_instagram_post(self, shortcode: str, owner_username: str = None,
                             owner_id: int = None, caption: str = None,
                             is_video: bool = False, media_url: str = None,
                             typename: str = None, likes: int = None,
                             comments: int = None, created_at: datetime = None,
                             hashtags: List[str] = None, mentions: List[str] = None,
                             is_saved: bool = True, source: str = 'saved') -> int:
        """Insert a new Instagram post into the database.
        
        Args:
            shortcode: Instagram post shortcode
            owner_username: Username of post owner
            owner_id: User ID of post owner
            caption: Post caption text
            is_video: Whether post is a video
            media_url: URL to media content
            typename: Type of post (GraphImage, GraphVideo, etc)
            likes: Number of likes
            comments: Number of comments
            created_at: Post creation timestamp
            hashtags: List of hashtags in caption
            mentions: List of @mentions in caption
            is_saved: Whether this is a saved post
            source: Where this post was found (saved, profile, hashtag, etc)
            
        Returns:
            int: ID of the inserted post
        """
        with self as db:
            try:
                post_url = f"{self.INSTAGRAM_BASE_URL}{shortcode}"
                db._cursor.execute("""
                    INSERT INTO instagram_posts (
                        shortcode, post_url, owner_username, owner_id, caption,
                        is_video, media_url, typename, likes, comments,
                        created_at, is_saved, source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    shortcode, post_url, owner_username, owner_id, caption,
                    is_video, media_url, typename, likes, comments,
                    created_at.isoformat() if created_at else None,
                    is_saved, source
                ))
                post_id = db._cursor.lastrowid
                
                # Add hashtags
                if hashtags:
                    for hashtag in hashtags:
                        try:
                            db._cursor.execute("""
                                INSERT INTO instagram_hashtags (post_id, hashtag)
                                VALUES (?, ?)
                            """, (post_id, hashtag))
                        except sqlite3.IntegrityError:
                            continue
                
                # Add mentions
                if mentions:
                    for username in mentions:
                        try:
                            db._cursor.execute("""
                                INSERT INTO instagram_mentions (post_id, username)
                                VALUES (?, ?)
                            """, (post_id, username))
                        except sqlite3.IntegrityError:
                            continue
                
                db._conn.commit()
                return post_id
            except sqlite3.IntegrityError:
                return None
    
    def _insert_telegram_message(self, message_id: int, chat_id: int = None,
                               content: str = None, content_type: str = "text",
                               media_urls: List[str] = None, views: int = None,
                               forwards: int = None, reply_to_msg_id: int = None,
                               created_at: datetime = None,
                               hashtags: List[str] = None) -> int:
        """Insert a new Telegram message into the database.
        
        Args:
            message_id: Telegram message ID
            chat_id: Chat ID where message was posted
            content: Message text content
            content_type: Type of content (text, image, video, etc.)
            media_urls: List of media URLs
            views: Number of views
            forwards: Number of forwards
            reply_to_msg_id: ID of message being replied to
            created_at: Message creation timestamp
            hashtags: List of hashtags in message
            
        Returns:
            int: ID of the inserted message
        """
        with self as db:
            try:
                db._cursor.execute("""
                    INSERT INTO telegram_messages (
                        message_id, chat_id, content, content_type,
                        media_urls, views, forwards, reply_to_msg_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    message_id, chat_id, content, content_type,
                    json.dumps(media_urls) if media_urls else None,
                    views, forwards, reply_to_msg_id,
                    created_at.isoformat() if created_at else None
                ))
                msg_id = db._cursor.lastrowid
                
                # Add hashtags
                if hashtags:
                    for hashtag in hashtags:
                        try:
                            db._cursor.execute("""
                                INSERT INTO telegram_hashtags (message_id, hashtag)
                                VALUES (?, ?)
                            """, (msg_id, hashtag))
                        except sqlite3.IntegrityError:
                            continue
                
                db._conn.commit()
                return msg_id
            except sqlite3.IntegrityError:
                return None
    
    def get_instagram_post(self, shortcode: str) -> Dict[str, Any]:
        """Retrieve an Instagram post by its shortcode.
        
        Args:
            shortcode: Instagram post shortcode
            
        Returns:
            Dict containing post data or None if not found
        """
        with self as db:
            db._cursor.execute("""
                SELECT * FROM instagram_posts WHERE shortcode = ?
            """, (shortcode,))
            post = db._cursor.fetchone()
            
            if post:
                columns = [description[0] for description in db._cursor.description]
                post_dict = dict(zip(columns, post))
                
                # Get hashtags
                db._cursor.execute("""
                    SELECT hashtag FROM instagram_hashtags WHERE post_id = ?
                """, (post_dict['id'],))
                post_dict['hashtags'] = [row[0] for row in db._cursor.fetchall()]
                
                # Get mentions
                db._cursor.execute("""
                    SELECT username FROM instagram_mentions WHERE post_id = ?
                """, (post_dict['id'],))
                post_dict['mentions'] = [row[0] for row in db._cursor.fetchall()]
                
                return post_dict
            return None
    
    def get_telegram_message(self, message_id: int) -> Dict[str, Any]:
        """Retrieve a Telegram message by its ID.
        
        Args:
            message_id: Telegram message ID
            
        Returns:
            Dict containing message data or None if not found
        """
        with self as db:
            db._cursor.execute("""
                SELECT * FROM telegram_messages WHERE message_id = ?
            """, (message_id,))
            message = db._cursor.fetchone()
            
            if message:
                columns = [description[0] for description in db._cursor.description]
                msg_dict = dict(zip(columns, message))
                
                # Get hashtags
                db._cursor.execute("""
                    SELECT hashtag FROM telegram_hashtags WHERE message_id = ?
                """, (msg_dict['id'],))
                msg_dict['hashtags'] = [row[0] for row in db._cursor.fetchall()]
                
                return msg_dict
            return None
    
    def post_exists(self, shortcode: str) -> bool:
        """Check if a post already exists in the database.
        
        Args:
            shortcode: Instagram post shortcode
            
        Returns:
            bool: True if post exists, False otherwise
        """
        with self as db:
            db._cursor.execute("""
                SELECT COUNT(*) FROM instagram_posts WHERE shortcode = ?
            """, (shortcode,))
            count = db._cursor.fetchone()[0]
            return count > 0
    
    def message_exists(self, message_id: int) -> bool:
        """Check if a Telegram message already exists in the database.
        
        Args:
            message_id: Telegram message ID
            
        Returns:
            bool: True if message exists, False otherwise
        """
        with self as db:
            db._cursor.execute("""
                SELECT COUNT(*) FROM telegram_messages WHERE message_id = ?
            """, (message_id,))
            count = db._cursor.fetchone()[0]
            return count > 0

    def get_posts_by_hashtag(self, hashtag: str) -> List[Dict[str, Any]]:
        """Get Instagram posts by hashtag.
        
        Args:
            hashtag: Hashtag to search for
            
        Returns:
            List of post dictionaries
        """
        with self as db:
            db._cursor.execute("""
                SELECT p.* FROM instagram_posts p
                JOIN instagram_hashtags h ON p.id = h.post_id
                WHERE h.hashtag = ?
            """, (hashtag,))
            
            posts = []
            for row in db._cursor.fetchall():
                columns = [description[0] for description in db._cursor.description]
                post_dict = dict(zip(columns, row))
                posts.append(post_dict)
            return posts
    
    def get_posts_by_date_range(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Get Instagram posts within a date range.
        
        Args:
            start_date: Start date for the range
            end_date: End date for the range
            
        Returns:
            List of post dictionaries
        """
        with self as db:
            db._cursor.execute("""
                SELECT * FROM instagram_posts 
                WHERE created_at BETWEEN ? AND ?
                ORDER BY created_at DESC
            """, (start_date.isoformat(), end_date.isoformat()))
            
            posts = []
            for row in db._cursor.fetchall():
                columns = [description[0] for description in db._cursor.description]
                post_dict = dict(zip(columns, row))
                posts.append(post_dict)
            return posts
    
    def get_instagram_posts(self, limit: int = None) -> List[Dict[str, Any]]:
        """Get all Instagram posts.
        
        Args:
            limit: Maximum number of posts to return
            
        Returns:
            List of post dictionaries
        """
        with self as db:
            sql = "SELECT * FROM instagram_posts ORDER BY created_at DESC"
            if limit:
                sql += f" LIMIT {limit}"
                
            db._cursor.execute(sql)
            
            posts = []
            for row in db._cursor.fetchall():
                columns = [description[0] for description in db._cursor.description]
                post_dict = dict(zip(columns, row))
                posts.append(post_dict)
            return posts
    
    def get_telegram_messages(self, limit: int = None) -> List[Dict[str, Any]]:
        """Get all Telegram messages.
        
        Args:
            limit: Maximum number of messages to return
            
        Returns:
            List of message dictionaries
        """
        with self as db:
            sql = "SELECT * FROM telegram_messages ORDER BY created_at DESC"
            if limit:
                sql += f" LIMIT {limit}"
                
            db._cursor.execute(sql)
            
            messages = []
            for row in db._cursor.fetchall():
                columns = [description[0] for description in db._cursor.description]
                msg_dict = dict(zip(columns, row))
                messages.append(msg_dict)
            return messages
    
    def count_instagram_posts(self) -> int:
        """Get the total count of Instagram posts in the database.
        
        This method is used for pagination metadata to provide clients with
        the total number of posts available across all pages.
        
        Returns:
            int: Total number of Instagram posts in the database.
            
        Example:
            >>> db = SocialMediaDatabase()
            >>> total = db.count_instagram_posts()
            >>> print(f"Total posts: {total}")
            Total posts: 1250
        """
        with self as db:
            db._cursor.execute("SELECT COUNT(*) FROM instagram_posts")
            count = db._cursor.fetchone()[0]
            return count
    
    def count_instagram_posts_by_hashtag(self, hashtag: str) -> int:
        """Get the total count of Instagram posts matching a specific hashtag.
        
        This method is used for paginated search results to provide clients
        with the total number of posts matching the hashtag filter.
        
        Args:
            hashtag: The hashtag to count posts for (without # symbol).
            
        Returns:
            int: Total number of Instagram posts with the specified hashtag.
            
        Example:
            >>> db = SocialMediaDatabase()
            >>> recipe_count = db.count_instagram_posts_by_hashtag("recipe")
            >>> print(f"Recipe posts: {recipe_count}")
            Recipe posts: 125
        """
        with self as db:
            db._cursor.execute("""
                SELECT COUNT(DISTINCT p.id) 
                FROM instagram_posts p
                JOIN instagram_hashtags h ON p.id = h.post_id
                WHERE h.hashtag = ?
            """, (hashtag,))
            count = db._cursor.fetchone()[0]
            return count
    
    def count_telegram_messages(self) -> int:
        """Get the total count of Telegram messages in the database.
        
        This method is used for pagination metadata to provide clients with
        the total number of messages available across all pages.
        
        Returns:
            int: Total number of Telegram messages in the database.
            
        Example:
            >>> db = SocialMediaDatabase()
            >>> total = db.count_telegram_messages()
            >>> print(f"Total messages: {total}")
            Total messages: 3420
        """
        with self as db:
            db._cursor.execute("SELECT COUNT(*) FROM telegram_messages")
            count = db._cursor.fetchone()[0]
            return count
    
    def _encode_cursor(self, created_at: str, record_id: int) -> str:
        """Encode cursor from created_at and record_id.
        
        Args:
            created_at: ISO format timestamp string
            record_id: Database record ID
            
        Returns:
            Base64-encoded cursor string
            
        Example:
            >>> cursor = db._encode_cursor("2024-01-15T10:30:00", 123)
            >>> print(cursor)
            MjAyNC0wMS0xNVQxMDozMDowMHwxMjM=
        """
        cursor_str = f"{created_at}|{record_id}"
        return base64.b64encode(cursor_str.encode()).decode()
    
    def _decode_cursor(self, cursor: str) -> Tuple[str, int]:
        """Decode cursor to get created_at and record_id.
        
        Args:
            cursor: Base64-encoded cursor string
            
        Returns:
            Tuple of (created_at, record_id)
            
        Raises:
            ValueError: If cursor format is invalid
            
        Example:
            >>> created_at, record_id = db._decode_cursor("MjAyNC0wMS0xNVQxMDozMDowMHwxMjM=")
            >>> print(f"{created_at}, {record_id}")
            2024-01-15T10:30:00, 123
        """
        try:
            decoded = base64.b64decode(cursor.encode()).decode()
            created_at, record_id = decoded.split("|")
            return created_at, int(record_id)
        except (ValueError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid cursor format: {e}")
    
    def search_instagram_posts(
        self,
        hashtags: Optional[List[str]] = None,
        date_range: Optional[Tuple[datetime, datetime]] = None,
        content_type: Optional[str] = None,
        owner_username: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Search Instagram posts with multiple filter criteria and cursor pagination.
        
        Args:
            hashtags: List of hashtags to filter by (OR logic - matches any)
            date_range: Tuple of (start_date, end_date) for filtering
            content_type: Content type filter ('video' or 'image')
            owner_username: Filter by post owner username
            limit: Maximum number of results to return
            cursor: Pagination cursor (base64-encoded)
            
        Returns:
            Tuple of (list of post dictionaries, next_cursor string or None)
            
        Example:
            >>> db = SocialMediaDatabase()
            >>> posts, next_cursor = db.search_instagram_posts(
            ...     hashtags=["recipe", "cooking"],
            ...     content_type="video",
            ...     limit=20
            ... )
            >>> print(f"Found {len(posts)} posts")
            Found 20 posts
            >>> # Get next page
            >>> more_posts, cursor = db.search_instagram_posts(
            ...     hashtags=["recipe", "cooking"],
            ...     content_type="video",
            ...     limit=20,
            ...     cursor=next_cursor
            ... )
        """
        with self as db:
            # Build WHERE clauses
            where_clauses = []
            params = []
            
            # Cursor pagination
            if cursor:
                cursor_created_at, cursor_id = self._decode_cursor(cursor)
                where_clauses.append("(p.created_at < ? OR (p.created_at = ? AND p.id < ?))")
                params.extend([cursor_created_at, cursor_created_at, cursor_id])
            
            # Hashtags filter (OR logic)
            if hashtags:
                placeholders = ",".join(["?" for _ in hashtags])
                where_clauses.append(f"p.id IN (SELECT post_id FROM instagram_hashtags WHERE hashtag IN ({placeholders}))")
                params.extend(hashtags)
            
            # Date range filter
            if date_range:
                start_date, end_date = date_range
                start_str = start_date.isoformat() if isinstance(start_date, datetime) else start_date
                end_str = end_date.isoformat() if isinstance(end_date, datetime) else end_date
                where_clauses.append("p.created_at BETWEEN ? AND ?")
                params.extend([start_str, end_str])
            
            # Content type filter
            if content_type:
                if content_type.lower() == "video":
                    where_clauses.append("p.is_video = 1")
                elif content_type.lower() == "image":
                    where_clauses.append("p.is_video = 0")
            
            # Owner username filter
            if owner_username:
                where_clauses.append("p.owner_username = ?")
                params.append(owner_username)
            
            # Build final query
            sql = "SELECT DISTINCT p.* FROM instagram_posts p"
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)
            sql += " ORDER BY p.created_at DESC, p.id DESC LIMIT ?"
            params.append(limit + 1)  # Fetch one extra to check if there are more results
            
            db._cursor.execute(sql, params)
            rows = db._cursor.fetchall()
            
            # Check if there are more results
            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]
            
            # Convert to dictionaries
            posts = []
            columns = [description[0] for description in db._cursor.description]
            for row in rows:
                post_dict = dict(zip(columns, row))
                
                # Get hashtags for this post
                db._cursor.execute("""
                    SELECT hashtag FROM instagram_hashtags WHERE post_id = ?
                """, (post_dict['id'],))
                post_dict['hashtags'] = [r[0] for r in db._cursor.fetchall()]
                
                # Get mentions for this post
                db._cursor.execute("""
                    SELECT username FROM instagram_mentions WHERE post_id = ?
                """, (post_dict['id'],))
                post_dict['mentions'] = [r[0] for r in db._cursor.fetchall()]
                
                posts.append(post_dict)
            
            # Generate next cursor
            next_cursor = None
            if has_more and posts:
                last_post = posts[-1]
                next_cursor = self._encode_cursor(last_post['created_at'], last_post['id'])
            
            return posts, next_cursor
    
    def search_telegram_messages(
        self,
        hashtags: Optional[List[str]] = None,
        date_range: Optional[Tuple[datetime, datetime]] = None,
        content_type: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Search Telegram messages with multiple filter criteria and cursor pagination.
        
        Note: Channel-based filtering is NOT supported as the telegram_messages table
        does not store channel username information.
        
        Args:
            hashtags: List of hashtags to filter by (OR logic - matches any)
            date_range: Tuple of (start_date, end_date) for filtering
            content_type: Content type filter (text/photo/video)
            limit: Maximum number of results to return
            cursor: Pagination cursor (base64-encoded)
            
        Returns:
            Tuple of (list of message dictionaries, next_cursor string or None)
            
        Example:
            >>> db = SocialMediaDatabase()
            >>> messages, next_cursor = db.search_telegram_messages(
            ...     hashtags=["news"],
            ...     content_type="photo",
            ...     limit=20
            ... )
            >>> print(f"Found {len(messages)} messages")
            Found 20 messages
        """
        with self as db:
            # Build WHERE clauses
            where_clauses = []
            params = []
            
            # Cursor pagination
            if cursor:
                cursor_created_at, cursor_id = self._decode_cursor(cursor)
                where_clauses.append("(m.created_at < ? OR (m.created_at = ? AND m.id < ?))")
                params.extend([cursor_created_at, cursor_created_at, cursor_id])
            
            # Hashtags filter (OR logic)
            if hashtags:
                placeholders = ",".join(["?" for _ in hashtags])
                where_clauses.append(f"m.id IN (SELECT message_id FROM telegram_hashtags WHERE hashtag IN ({placeholders}))")
                params.extend(hashtags)
            
            # Date range filter
            if date_range:
                start_date, end_date = date_range
                start_str = start_date.isoformat() if isinstance(start_date, datetime) else start_date
                end_str = end_date.isoformat() if isinstance(end_date, datetime) else end_date
                where_clauses.append("m.created_at BETWEEN ? AND ?")
                params.extend([start_str, end_str])
            
            # Content type filter
            if content_type:
                where_clauses.append("m.content_type = ?")
                params.append(content_type.lower())
            
            # Build final query
            sql = "SELECT DISTINCT m.* FROM telegram_messages m"
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)
            sql += " ORDER BY m.created_at DESC, m.id DESC LIMIT ?"
            params.append(limit + 1)  # Fetch one extra to check if there are more results
            
            db._cursor.execute(sql, params)
            rows = db._cursor.fetchall()
            
            # Check if there are more results
            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]
            
            # Convert to dictionaries
            messages = []
            columns = [description[0] for description in db._cursor.description]
            for row in rows:
                msg_dict = dict(zip(columns, row))
                
                # Get hashtags for this message
                db._cursor.execute("""
                    SELECT hashtag FROM telegram_hashtags WHERE message_id = ?
                """, (msg_dict['id'],))
                msg_dict['hashtags'] = [r[0] for r in db._cursor.fetchall()]
                
                # Parse media_urls from JSON
                if msg_dict.get('media_urls'):
                    try:
                        msg_dict['media_urls'] = json.loads(msg_dict['media_urls'])
                    except json.JSONDecodeError:
                        msg_dict['media_urls'] = []
                
                messages.append(msg_dict)
            
            # Generate next cursor
            next_cursor = None
            if has_more and messages:
                last_msg = messages[-1]
                next_cursor = self._encode_cursor(last_msg['created_at'], last_msg['id'])
            
            return messages, next_cursor
    
    def count_instagram_posts_filtered(
        self,
        hashtags: Optional[List[str]] = None,
        date_range: Optional[Tuple[datetime, datetime]] = None,
        content_type: Optional[str] = None,
        owner_username: Optional[str] = None
    ) -> int:
        """Count Instagram posts matching filter criteria.
        
        Args:
            hashtags: List of hashtags to filter by (OR logic - matches any)
            date_range: Tuple of (start_date, end_date) for filtering
            content_type: Content type filter ('video' or 'image')
            owner_username: Filter by post owner username
            
        Returns:
            Total count of posts matching filters
            
        Example:
            >>> db = SocialMediaDatabase()
            >>> count = db.count_instagram_posts_filtered(
            ...     hashtags=["recipe"],
            ...     content_type="video"
            ... )
            >>> print(f"Total: {count}")
            Total: 150
        """
        with self as db:
            # Build WHERE clauses
            where_clauses = []
            params = []
            
            # Hashtags filter (OR logic)
            if hashtags:
                placeholders = ",".join(["?" for _ in hashtags])
                where_clauses.append(f"p.id IN (SELECT post_id FROM instagram_hashtags WHERE hashtag IN ({placeholders}))")
                params.extend(hashtags)
            
            # Date range filter
            if date_range:
                start_date, end_date = date_range
                start_str = start_date.isoformat() if isinstance(start_date, datetime) else start_date
                end_str = end_date.isoformat() if isinstance(end_date, datetime) else end_date
                where_clauses.append("p.created_at BETWEEN ? AND ?")
                params.extend([start_str, end_str])
            
            # Content type filter
            if content_type:
                if content_type.lower() == "video":
                    where_clauses.append("p.is_video = 1")
                elif content_type.lower() == "image":
                    where_clauses.append("p.is_video = 0")
            
            # Owner username filter
            if owner_username:
                where_clauses.append("p.owner_username = ?")
                params.append(owner_username)
            
            # Build final query
            sql = "SELECT COUNT(DISTINCT p.id) FROM instagram_posts p"
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)
            
            db._cursor.execute(sql, params)
            count = db._cursor.fetchone()[0]
            return count
    
    def count_telegram_messages_filtered(
        self,
        hashtags: Optional[List[str]] = None,
        date_range: Optional[Tuple[datetime, datetime]] = None,
        content_type: Optional[str] = None
    ) -> int:
        """Count Telegram messages matching filter criteria.
        
        Note: Channel-based filtering is NOT supported as the telegram_messages table
        does not store channel username information.
        
        Args:
            hashtags: List of hashtags to filter by (OR logic - matches any)
            date_range: Tuple of (start_date, end_date) for filtering
            content_type: Content type filter (text/photo/video)
            
        Returns:
            Total count of messages matching filters
            
        Example:
            >>> db = SocialMediaDatabase()
            >>> count = db.count_telegram_messages_filtered(
            ...     hashtags=["news"],
            ...     content_type="photo"
            ... )
            >>> print(f"Total: {count}")
            Total: 89
        """
        with self as db:
            # Build WHERE clauses
            where_clauses = []
            params = []
            
            # Hashtags filter (OR logic)
            if hashtags:
                placeholders = ",".join(["?" for _ in hashtags])
                where_clauses.append(f"m.id IN (SELECT message_id FROM telegram_hashtags WHERE hashtag IN ({placeholders}))")
                params.extend(hashtags)
            
            # Date range filter
            if date_range:
                start_date, end_date = date_range
                start_str = start_date.isoformat() if isinstance(start_date, datetime) else start_date
                end_str = end_date.isoformat() if isinstance(end_date, datetime) else end_date
                where_clauses.append("m.created_at BETWEEN ? AND ?")
                params.extend([start_str, end_str])
            
            # Content type filter
            if content_type:
                where_clauses.append("m.content_type = ?")
                params.append(content_type.lower())
            
            # Build final query
            sql = "SELECT COUNT(DISTINCT m.id) FROM telegram_messages m"
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)
            
            db._cursor.execute(sql, params)
            count = db._cursor.fetchone()[0]
            return count
    
    def get_all_hashtags(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all unique hashtags with usage counts from both platforms.
        
        Aggregates hashtags from both Instagram posts and Telegram messages,
        counts their occurrences, and returns them sorted by total count (descending).
        
        Args:
            limit: Maximum number of hashtags to return (default: 100).
            
        Returns:
            List of hashtag dictionaries with count information.
            Each dict contains:
            - tag: Hashtag string
            - count: Total usage count across both platforms
            - instagram_count: Usage count in Instagram posts
            - telegram_count: Usage count in Telegram messages
            - source: Platform source ("instagram", "telegram", or "both")
            
        Example:
            >>> db = SocialMediaDatabase()
            >>> hashtags = db.get_all_hashtags(limit=50)
            >>> for tag in hashtags[:3]:
            ...     print(f"{tag['tag']}: {tag['count']} uses ({tag['source']})")
            recipe: 125 uses (both)
            cooking: 89 uses (instagram)
            italian: 67 uses (telegram)
        """
        with self as db:
            # Query Instagram hashtags
            db._cursor.execute("""
                SELECT hashtag, COUNT(*) as count
                FROM instagram_hashtags
                GROUP BY hashtag
                ORDER BY count DESC
            """)
            instagram_hashtags = {row[0]: row[1] for row in db._cursor.fetchall()}
            
            # Query Telegram hashtags
            db._cursor.execute("""
                SELECT hashtag, COUNT(*) as count
                FROM telegram_hashtags
                GROUP BY hashtag
                ORDER BY count DESC
            """)
            telegram_hashtags = {row[0]: row[1] for row in db._cursor.fetchall()}
            
            # Merge and aggregate
            all_hashtags = {}
            for tag, count in instagram_hashtags.items():
                all_hashtags[tag] = {
                    "tag": tag,
                    "count": count,
                    "instagram_count": count,
                    "telegram_count": 0,
                    "source": "instagram"
                }
            
            for tag, count in telegram_hashtags.items():
                if tag in all_hashtags:
                    all_hashtags[tag]["count"] += count
                    all_hashtags[tag]["telegram_count"] = count
                    all_hashtags[tag]["source"] = "both"
                else:
                    all_hashtags[tag] = {
                        "tag": tag,
                        "count": count,
                        "instagram_count": 0,
                        "telegram_count": count,
                        "source": "telegram"
                    }
            
            # Sort by total count and limit
            sorted_hashtags = sorted(
                all_hashtags.values(),
                key=lambda x: x["count"],
                reverse=True
            )[:limit]
            
            return sorted_hashtags

    # ==================== Classification Methods ====================

    def save_classification_result(
        self,
        content_id: int,
        content_source: str,
        classifier_name: str,
        label: str,
        confidence: float,
        details: Optional[Dict[str, Any]] = None,
        classification_type: str = "single",
        run_id: Optional[str] = None,
        reasoning: Optional[str] = None,
        llm_metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Save a classification result to the database.

        Args:
            content_id: ID of the analyzed content (instagram post or telegram message).
            content_source: Source of the content ('instagram' or 'telegram').
            classifier_name: Name of the classifier used (e.g., 'recipe_llm', 'multi_class').
            label: Classification label (e.g., 'recipe', 'non_recipe', 'tech_news').
            confidence: Confidence score between 0.0 and 1.0.
            details: Optional dictionary of additional classification details.
            classification_type: Type of classification ('single' or 'multi_label').
            run_id: Optional UUID to group multi-label results from the same run.
            reasoning: Optional reasoning explanation from the classifier.
            llm_metadata: Optional dictionary of LLM configuration used for classification.
                Example: {'provider': 'openai', 'model': 'gpt-4o-mini', 'temperature': 0.7}

        Returns:
            The ID of the inserted content_analysis record.

        Example:
            >>> db = SocialMediaDatabase()
            >>> # Single-label classification with LLM metadata
            >>> analysis_id = db.save_classification_result(
            ...     content_id=42,
            ...     content_source='instagram',
            ...     classifier_name='recipe_llm',
            ...     label='recipe',
            ...     confidence=0.95,
            ...     details={'cuisine_type': 'italian', 'difficulty': 'easy'},
            ...     reasoning='Contains cooking instructions and ingredient list',
            ...     llm_metadata={
            ...         'provider': 'lm_studio',
            ...         'model': 'qwen/qwen3-vl-8b',
            ...         'temperature': 0.7,
            ...         'max_tokens': 1000
            ...     }
            ... )
            >>> # Multi-label classification (multiple labels per content)
            >>> import uuid
            >>> run_id = str(uuid.uuid4())
            >>> llm_meta = {'provider': 'openai', 'model': 'gpt-4o-mini', 'temperature': 0.5}
            >>> db.save_classification_result(
            ...     content_id=42, content_source='instagram',
            ...     classifier_name='multi_label_llm', label='recipe',
            ...     confidence=0.95, classification_type='multi_label',
            ...     run_id=run_id, reasoning='Post discusses cooking techniques',
            ...     llm_metadata=llm_meta
            ... )
        """
        # Serialize to JSON
        llm_metadata_json = json.dumps(llm_metadata) if llm_metadata else None
        details_json = json.dumps(details) if details else None
        
        # Extract provider and model from llm_metadata for dedicated columns
        llm_provider = llm_metadata.get('provider') if llm_metadata else None
        llm_model = llm_metadata.get('model') if llm_metadata else None

        with self as db:
            db._cursor.execute(
                """
                INSERT INTO content_analysis (
                    content_id, content_source, classifier_name,
                    classification_type, run_id, label, confidence, reasoning,
                    llm_metadata, llm_provider, llm_model, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content_id, content_source, classifier_name,
                    classification_type, run_id, label, confidence, reasoning,
                    llm_metadata_json, llm_provider, llm_model, details_json
                )
            )
            db._conn.commit()
            return db._cursor.lastrowid

    def get_classification_results(
        self,
        content_id: int,
        content_source: str,
        classifier_name: Optional[str] = None,
        run_id: Optional[str] = None,
        llm_model: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve classification results for content.

        Args:
            content_id: ID of the content.
            content_source: Source of the content ('instagram' or 'telegram').
            classifier_name: Optional filter by classifier name.
            run_id: Optional filter by run_id (for multi-label grouping).
            llm_model: Optional filter by LLM model name.

        Returns:
            List of classification result dictionaries with details.

        Example:
            >>> db = SocialMediaDatabase()
            >>> results = db.get_classification_results(42, 'instagram')
            >>> for r in results:
            ...     print(f"{r['label']} ({r['confidence']:.2%})")
            >>> # Get multi-label results by run_id
            >>> results = db.get_classification_results(42, 'instagram', run_id='abc-123')
            >>> # Get results from specific model
            >>> results = db.get_classification_results(42, 'instagram', llm_model='gpt-4o')
        """
        with self as db:
            query = """
                SELECT 
                    id, classifier_name, classification_type,
                    run_id, label, confidence, reasoning,
                    llm_metadata, analyzed_at, llm_provider, llm_model,
                    details_json
                FROM content_analysis
                WHERE content_id = ? AND content_source = ?
            """
            params: List[Any] = [content_id, content_source]

            if classifier_name:
                query += " AND classifier_name = ?"
                params.append(classifier_name)

            if run_id:
                query += " AND run_id = ?"
                params.append(run_id)

            if llm_model:
                query += " AND llm_model = ?"
                params.append(llm_model)

            db._cursor.execute(query, params)
            rows = db._cursor.fetchall()

            results = []
            for row in rows:
                # Parse JSON fields
                llm_metadata = json.loads(row[7]) if row[7] else None
                details = json.loads(row[11]) if row[11] else {}

                results.append({
                    "id": row[0],
                    "classifier_name": row[1],
                    "classification_type": row[2],
                    "run_id": row[3],
                    "label": row[4],
                    "confidence": row[5],
                    "reasoning": row[6],
                    "llm_metadata": llm_metadata,
                    "analyzed_at": row[8],
                    "llm_provider": row[9],
                    "llm_model": row[10],
                    "details": details
                })

            return results

    def has_classification(
        self,
        content_id: int,
        content_source: str,
        classifier_name: str,
        llm_model: Optional[str] = None
    ) -> bool:
        """Check if content has already been classified by a specific classifier.

        Args:
            content_id: ID of the content.
            content_source: Source of the content ('instagram' or 'telegram').
            classifier_name: Name of the classifier.
            llm_model: Optional LLM model name. If provided, checks for classification
                with that specific model. If None, checks for any classification.

        Returns:
            True if classification exists, False otherwise.

        Example:
            >>> db = SocialMediaDatabase()
            >>> # Check for any classification by recipe_llm
            >>> if not db.has_classification(42, 'instagram', 'recipe_llm'):
            ...     pass
            >>> # Check for classification with specific model
            >>> if not db.has_classification(42, 'instagram', 'recipe_llm', 'gpt-4o-mini'):
            ...     pass
        """
        with self as db:
            if llm_model:
                db._cursor.execute(
                    """
                    SELECT 1 FROM content_analysis
                    WHERE content_id = ? AND content_source = ? 
                    AND classifier_name = ? AND llm_model = ?
                    LIMIT 1
                    """,
                    (content_id, content_source, classifier_name, llm_model)
                )
            else:
                db._cursor.execute(
                    """
                    SELECT 1 FROM content_analysis
                    WHERE content_id = ? AND content_source = ? AND classifier_name = ?
                    LIMIT 1
                    """,
                    (content_id, content_source, classifier_name)
                )
            return db._cursor.fetchone() is not None

    def get_classification_id(
        self,
        content_id: int,
        content_source: str,
        classifier_name: str,
        llm_model: Optional[str] = None
    ) -> Optional[int]:
        """Get the ID of an existing classification record.

        Args:
            content_id: ID of the content.
            content_source: Source of the content ('instagram' or 'telegram').
            classifier_name: Name of the classifier.
            llm_model: Optional LLM model name. If provided, looks for classification
                with that specific model.

        Returns:
            The analysis ID if found, None otherwise.

        Example:
            >>> db = SocialMediaDatabase()
            >>> analysis_id = db.get_classification_id(42, 'instagram', 'recipe_llm', 'gpt-4o')
            >>> if analysis_id:
            ...     db.update_classification(analysis_id, ...)
        """
        with self as db:
            if llm_model:
                db._cursor.execute(
                    """
                    SELECT id FROM content_analysis
                    WHERE content_id = ? AND content_source = ? 
                    AND classifier_name = ? AND llm_model = ?
                    ORDER BY analyzed_at DESC, id DESC
                    LIMIT 1
                    """,
                    (content_id, content_source, classifier_name, llm_model)
                )
            else:
                db._cursor.execute(
                    """
                    SELECT id FROM content_analysis
                    WHERE content_id = ? AND content_source = ? AND classifier_name = ?
                    ORDER BY analyzed_at DESC, id DESC
                    LIMIT 1
                    """,
                    (content_id, content_source, classifier_name)
                )
            row = db._cursor.fetchone()
            return row[0] if row else None

    def update_classification(
        self,
        analysis_id: int,
        label: str,
        confidence: float,
        reasoning: Optional[str] = None,
        llm_metadata: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Update an existing classification record.

        Args:
            analysis_id: ID of the content_analysis record to update.
            label: New classification label.
            confidence: New confidence score between 0.0 and 1.0.
            reasoning: Optional new reasoning explanation.
            llm_metadata: Optional new LLM metadata dictionary.
            details: Optional new details dictionary (replaces existing details).

        Example:
            >>> db = SocialMediaDatabase()
            >>> db.update_classification(
            ...     analysis_id=123,
            ...     label='recipe',
            ...     confidence=0.95,
            ...     reasoning='Updated classification',
            ...     llm_metadata={'provider': 'openai', 'model': 'gpt-4o'}
            ... )
        """
        # Serialize to JSON
        llm_metadata_json = json.dumps(llm_metadata) if llm_metadata else None
        details_json = json.dumps(details) if details else None
        
        # Extract provider and model from llm_metadata for dedicated columns
        llm_provider = llm_metadata.get('provider') if llm_metadata else None
        llm_model = llm_metadata.get('model') if llm_metadata else None

        with self as db:
            db._cursor.execute(
                """
                UPDATE content_analysis
                SET label = ?, confidence = ?, reasoning = ?,
                    llm_metadata = ?, llm_provider = ?, llm_model = ?,
                    details_json = ?, analyzed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (label, confidence, reasoning, llm_metadata_json,
                 llm_provider, llm_model, details_json, analysis_id)
            )
            db._conn.commit()