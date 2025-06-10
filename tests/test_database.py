"""Tests for the database module."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import sqlite3
import json

from postparse.data.database import SocialMediaDatabase


@pytest.fixture
def mock_connection():
    """Create a mock database connection."""
    with patch('sqlite3.connect') as mock_connect:
        # Create mock cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)  # Default return for fetchone
        mock_cursor.fetchall.return_value = []    # Default return for fetchall
        
        # Create mock connection
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn
        
        yield mock_conn


@pytest.fixture
def mock_db(mock_connection):
    """Create a mock database instance."""
    with patch('pathlib.Path.exists', return_value=True):
        db = SocialMediaDatabase("test.db")
        yield db


@pytest.fixture
def sample_instagram_post():
    """Create a sample Instagram post data."""
    return {
        'shortcode': 'abc123',
        'owner_username': 'test_user',
        'owner_id': '12345',
        'caption': 'Test post #test @mention',
        'is_video': False,
        'media_url': 'http://example.com/image.jpg',
        'typename': 'GraphImage',
        'likes': 100,
        'comments': 10,
        'created_at': datetime.now(),
        'hashtags': ['test'],
        'mentions': ['mention']
    }


@pytest.fixture
def sample_telegram_message():
    """Create a sample Telegram message data."""
    return {
        'message_id': 123,
        'chat_id': 456,
        'content': 'Test message #test',
        'content_type': 'text',
        'media_urls': [],
        'views': 100,
        'forwards': 5,
        'reply_to_msg_id': None,
        'created_at': datetime.now(),
        'hashtags': ['test']
    }


class TestDatabaseOperations:
    """Tests for database operations."""

    def test_database_initialization(self, mock_connection):
        """Test database initialization and table creation."""
        with patch('pathlib.Path.exists', return_value=False):
            db = SocialMediaDatabase("test.db")

            cursor = mock_connection.cursor()
            actual_calls = [call[0][0] for call in cursor.execute.call_args_list]

            # Print actual SQL statements for debugging
            print("\nActual SQL statements:")
            for sql in actual_calls:
                print(f"\n{sql}")

            # The exact SQL statements that should be executed
            expected_statements = [
                # Schema version table
                """CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL
                )""",

                # Instagram tables
                """CREATE TABLE IF NOT EXISTS instagram_posts (
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
                )""",
                """CREATE TABLE IF NOT EXISTS instagram_hashtags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER,
                    hashtag TEXT NOT NULL,
                    FOREIGN KEY(post_id) REFERENCES instagram_posts(id),
                    UNIQUE(post_id, hashtag)
                )""",
                """CREATE TABLE IF NOT EXISTS instagram_mentions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER,
                    username TEXT NOT NULL,
                    FOREIGN KEY(post_id) REFERENCES instagram_posts(id),
                    UNIQUE(post_id, username)
                )""",

                # Telegram tables
                """CREATE TABLE IF NOT EXISTS telegram_messages (
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
                )""",
                """CREATE TABLE IF NOT EXISTS telegram_hashtags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER,
                    hashtag TEXT NOT NULL,
                    FOREIGN KEY(message_id) REFERENCES telegram_messages(id),
                    UNIQUE(message_id, hashtag)
                )""",

                # Schema version operations
                "DELETE FROM schema_version",
                "INSERT INTO schema_version VALUES (?)"
            ]

            # Normalize SQL statements for comparison (remove whitespace and convert to lowercase)
            def normalize_sql(sql):
                return ' '.join(sql.lower().split())

            actual_normalized = set(normalize_sql(sql) for sql in actual_calls)
            expected_normalized = set(normalize_sql(stmt) for stmt in expected_statements)

            # Print normalized statements for debugging
            print("\nNormalized actual SQL statements:")
            for sql in actual_normalized:
                print(f"\n{sql}")

            print("\nNormalized expected SQL statements:")
            for sql in expected_normalized:
                print(f"\n{sql}")

            # Find missing statements
            missing_statements = expected_normalized - actual_normalized
            if missing_statements:
                print("\nMissing SQL statements:")
                for sql in missing_statements:
                    print(f"\n{sql}")

            # Find unexpected statements
            unexpected_statements = actual_normalized - expected_normalized
            if unexpected_statements:
                print("\nUnexpected SQL statements:")
                for sql in unexpected_statements:
                    print(f"\n{sql}")

            # Assert all expected statements were executed
            assert actual_normalized == expected_normalized, \
                "SQL statements don't match. See printed statements above for details."

    def test_instagram_post_insertion(self, mock_db, sample_instagram_post):
        """Test Instagram post insertion and updates."""
        # Setup mock cursor for post existence check
        cursor = mock_db._conn.cursor()
        cursor.fetchone.side_effect = [None, (1,)]  # First None (not exists), then 1 (exists)
        
        # Test normal insertion
        post_id = mock_db._insert_instagram_post(**sample_instagram_post)
        assert post_id is not None
        
        # Verify SQL execution
        cursor.execute.assert_any_call(
            """
                    INSERT INTO instagram_posts (
                        shortcode, post_url, owner_username, owner_id, caption,
                        is_video, media_url, typename, likes, comments,
                        created_at, is_saved, source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
            (
                sample_instagram_post['shortcode'],
                f"{mock_db.INSTAGRAM_BASE_URL}{sample_instagram_post['shortcode']}",
                sample_instagram_post['owner_username'],
                sample_instagram_post['owner_id'],
                sample_instagram_post['caption'],
                sample_instagram_post['is_video'],
                sample_instagram_post.get('media_url'),
                sample_instagram_post['typename'],
                sample_instagram_post['likes'],
                sample_instagram_post['comments'],
                sample_instagram_post['created_at'].isoformat() if sample_instagram_post['created_at'] else None,
                True,  # is_saved default
                'saved'  # source default
            )
        )

    def test_telegram_message_insertion(self, mock_db, sample_telegram_message):
        """Test Telegram message insertion and updates."""
        # Setup mock cursor for message existence check
        cursor = mock_db._conn.cursor()
        cursor.fetchone.side_effect = [None, (1,)]  # First None (not exists), then 1 (exists)
        
        # Test normal insertion
        msg_id = mock_db._insert_telegram_message(**sample_telegram_message)
        assert msg_id is not None
        
        # Print actual calls for debugging
        print("\nActual SQL calls:")
        for i, call in enumerate(cursor.execute.call_args_list):
            print(f"\nCall {i}:")
            print(f"SQL: {repr(call[0][0])}")  # Use repr to show exact string
            if len(call[0]) > 1:
                print(f"Args: {repr(call[0][1])}")
            print(f"Full call: {call}")
        
        # Create expected call for comparison
        expected_sql = """
                    INSERT INTO telegram_messages (
                        message_id, chat_id, content, content_type,
                        media_urls, views, forwards, reply_to_msg_id,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
        expected_args = (
            sample_telegram_message['message_id'],
            sample_telegram_message['chat_id'],
            sample_telegram_message['content'],
            sample_telegram_message['content_type'],
            json.dumps(sample_telegram_message.get('media_urls', [])) if sample_telegram_message.get('media_urls') else None,
            sample_telegram_message['views'],
            sample_telegram_message['forwards'],
            sample_telegram_message['reply_to_msg_id'],
            sample_telegram_message['created_at'].isoformat() if sample_telegram_message['created_at'] else None
        )

        print("\nExpected SQL:")
        print(f"SQL: {repr(expected_sql)}")
        print(f"Args: {repr(expected_args)}")

        # Get the actual call that should match
        actual_call = cursor.execute.call_args_list[1]  # Second call should be the insert
        print("\nActual vs Expected:")
        print(f"Actual SQL: {repr(actual_call[0][0])}")
        print(f"Expected SQL: {repr(expected_sql)}")
        if len(actual_call[0]) > 1:
            print(f"Actual Args: {repr(actual_call[0][1])}")
        print(f"Expected Args: {repr(expected_args)}")

        # Compare strings character by character
        actual_sql = actual_call[0][0]
        for i, (a, e) in enumerate(zip(actual_sql, expected_sql)):
            if a != e:
                print(f"Difference at position {i}: '{a}' vs '{e}'")
                print(f"Context: '{actual_sql[max(0, i-10):i]}[{a}]{actual_sql[i+1:i+11]}'")
                print(f"         '{expected_sql[max(0, i-10):i]}[{e}]{expected_sql[i+1:i+11]}'")
                break

        # Verify SQL execution
        cursor.execute.assert_called_with(expected_sql, expected_args)

    def test_hashtag_handling(self, mock_db, sample_instagram_post):
        """Test hashtag insertion and querying."""
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (1,)  # Return post ID for existence check
        
        # Test hashtag insertion
        mock_db._insert_instagram_post(**sample_instagram_post)
        
        # Verify hashtag SQL execution
        cursor.execute.assert_any_call(
            "INSERT OR IGNORE INTO hashtags (post_id, platform, hashtag) VALUES (?, ?, ?)",
            (1, 'instagram', 'test')
        )
        
        # Test hashtag query
        cursor.fetchall.return_value = [(1, 'test_post')]  # Mock hashtag query result
        posts = mock_db.get_posts_by_hashtag('test')
        assert len(posts) > 0

    def test_mention_handling(self, mock_db, sample_instagram_post):
        """Test mention insertion and querying."""
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (1,)  # Return post ID for existence check
        
        # Test mention insertion
        mock_db._insert_instagram_post(**sample_instagram_post)
        
        # Verify mention SQL execution
        cursor.execute.assert_any_call(
            "INSERT OR IGNORE INTO mentions (post_id, username) VALUES (?, ?)",
            (1, 'mention')
        )

    def test_media_url_handling(self, mock_db, sample_instagram_post):
        """Test media URL insertion and querying."""
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (1,)  # Return post ID for existence check
        
        # Add multiple media URLs
        sample_instagram_post['media_url'] = ['url1', 'url2']
        
        # Test media URL insertion
        mock_db._insert_instagram_post(**sample_instagram_post)
        
        # Verify media URL SQL execution
        cursor.execute.assert_any_call(
            "INSERT INTO media_urls (post_id, platform, url) VALUES (?, ?, ?)",
            (1, 'instagram', 'url1')
        )

    def test_query_functions(self, mock_db):
        """Test various query functions."""
        cursor = mock_db._conn.cursor()
        
        # Setup mock returns for different queries
        cursor.fetchall.side_effect = [
            [(1, 'post1')],  # For hashtag query
            [(2, 'post2')],  # For date range query
            [(3, 'post3')],  # For Instagram posts query
            [(4, 'post4')]   # For Telegram messages query
        ]
        
        # Test different queries
        assert len(mock_db.get_posts_by_hashtag('test')) > 0
        assert len(mock_db.get_posts_by_date_range(datetime.now(), datetime.now())) > 0
        assert len(mock_db.get_instagram_posts()) > 0
        assert len(mock_db.get_telegram_messages()) > 0

    def test_error_handling(self, mock_db):
        """Test database error handling."""
        cursor = mock_db._conn.cursor()
        cursor.execute.side_effect = sqlite3.Error("Database error")
        
        # Test error handling during insertion
        with pytest.raises(Exception):
            mock_db._insert_instagram_post(shortcode='error_test', owner_username='test',
                                        owner_id='1', caption='test', is_video=False,
                                        media_url='test.jpg', typename='test',
                                        likes=0, comments=0, created_at=datetime.now())