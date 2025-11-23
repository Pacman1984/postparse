"""Database module for social media data storage.

This module handles all database operations for storing and retrieving social media posts.
"""
import sqlite3
from pathlib import Path
from typing import Dict, Any, List
import json
from datetime import datetime


class SocialMediaDatabase:
    """Handles all database operations for social media data."""
    
    INSTAGRAM_BASE_URL = "https://instagram.com/p/"
    CURRENT_VERSION = 1  # Increment this when schema changes
    
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
        """Initialize database and handle migrations."""
        # Check if database exists
        is_new_db = not self._db_path.exists()
        
        with self as db:
            if is_new_db:
                db.__create_tables()
                db.__set_version(self.CURRENT_VERSION)
            else:
                # Check version and migrate if necessary
                current_version = db.__get_version()
                if current_version < self.CURRENT_VERSION:
                    db.__migrate_database(current_version)
    
    def __get_version(self) -> int:
        """Get current database version."""
        try:
            self._cursor.execute("SELECT version FROM schema_version")
            return self._cursor.fetchone()[0]
        except sqlite3.OperationalError:
            return 0
    
    def __set_version(self, version: int):
        """Set database version."""
        self._cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            )
        """)
        self._cursor.execute("DELETE FROM schema_version")
        self._cursor.execute("INSERT INTO schema_version VALUES (?)", (version,))
        self._conn.commit()
    
    def __migrate_database(self, current_version: int):
        """Migrate database to latest version."""
        print(f"Migrating database from version {current_version} to {self.CURRENT_VERSION}")
        
        # Backup tables
        self._cursor.execute("BEGIN TRANSACTION")
        try:
            # Drop existing tables
            self._cursor.execute("DROP TABLE IF EXISTS instagram_posts")
            self._cursor.execute("DROP TABLE IF EXISTS instagram_hashtags")
            self._cursor.execute("DROP TABLE IF EXISTS instagram_mentions")
            
            # Create new tables
            self.__create_tables()
            
            # Update version
            self.__set_version(self.CURRENT_VERSION)
            
            self._conn.commit()
            print("Migration completed successfully")
        except Exception as e:
            self._conn.rollback()
            print(f"Migration failed: {str(e)}")
            raise
    
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
        
        self._conn.commit()
    
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