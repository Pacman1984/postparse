"""Tests for the database module."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import sqlite3
import json

from backend.postparse.core.data.database import SocialMediaDatabase


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

    @pytest.mark.skip(reason="Brittle test comparing exact SQL strings. Integration tests cover real DB behavior.")
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
        
        # Verify that the main message insertion happened
        # Check that at least one call contains the main INSERT for telegram_messages
        message_insert_found = False
        hashtag_insert_found = False
        
        for call in cursor.execute.call_args_list:
            if len(call[0]) > 0:
                sql = call[0][0].strip()
                if "INSERT INTO telegram_messages" in sql:
                    message_insert_found = True
                    # Verify the arguments match what we expect
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
                    assert call[0][1] == expected_args, f"Message insert args mismatch: {call[0][1]} != {expected_args}"
                
                elif "INSERT INTO telegram_hashtags" in sql:
                    hashtag_insert_found = True
                    # Should have message_id and hashtag
                    assert len(call[0][1]) == 2, f"Hashtag insert should have 2 args: {call[0][1]}"
                    assert call[0][1][1] == 'test', f"Expected hashtag 'test', got {call[0][1][1]}"
        
        assert message_insert_found, "Message insertion SQL not found"
        assert hashtag_insert_found, "Hashtag insertion SQL not found"

    def test_hashtag_handling(self, mock_db, sample_instagram_post):
        """Test hashtag insertion and querying."""
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (1,)  # Return post ID for existence check
        
        # Test hashtag insertion
        mock_db._insert_instagram_post(**sample_instagram_post)
        
        # Verify hashtag SQL execution (using actual table name)
        cursor.execute.assert_any_call(
            """
                                INSERT INTO instagram_hashtags (post_id, hashtag)
                                VALUES (?, ?)
                            """,
            (cursor.lastrowid, 'test')
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
        
        # Verify mention SQL execution (using actual table name)
        cursor.execute.assert_any_call(
            """
                                INSERT INTO instagram_mentions (post_id, username)
                                VALUES (?, ?)
                            """,
            (cursor.lastrowid, 'mention')
        )

    def test_media_url_handling(self, mock_db, sample_instagram_post):
        """Test media URL storage in posts table."""
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (1,)  # Return post ID for existence check
        
        # Test with single media URL (stored directly in posts table)
        sample_instagram_post['media_url'] = 'test_url.jpg'
        
        # Test media URL insertion
        mock_db._insert_instagram_post(**sample_instagram_post)
        
        # Verify the post insertion includes the media URL
        # This should be part of the main INSERT into instagram_posts
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
                sample_instagram_post['media_url'],  # This is the media URL
                sample_instagram_post['typename'],
                sample_instagram_post['likes'],
                sample_instagram_post['comments'],
                sample_instagram_post['created_at'].isoformat() if sample_instagram_post['created_at'] else None,
                True,  # is_saved default
                'saved'  # source default
            )
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


class TestCursorEncodingDecoding:
    """Tests for cursor encoding and decoding methods."""

    def test_encode_cursor_returns_base64_string(self, mock_db) -> None:
        """
        Test _encode_cursor returns a base64-encoded string.

        Verifies cursor format is correct.
        """
        cursor = mock_db._encode_cursor("2024-01-15T10:30:00", 123)

        assert isinstance(cursor, str)
        # Base64 string should be decodable
        import base64
        try:
            decoded = base64.b64decode(cursor)
            assert b"|" in decoded
        except Exception:
            pytest.fail("Cursor is not valid base64")

    def test_encode_cursor_includes_timestamp_and_id(self, mock_db) -> None:
        """
        Test _encode_cursor includes both timestamp and id.

        Verifies all components are encoded.
        """
        cursor = mock_db._encode_cursor("2024-01-15T10:30:00", 456)

        import base64
        decoded = base64.b64decode(cursor).decode()
        assert "2024-01-15T10:30:00" in decoded
        assert "456" in decoded

    def test_decode_cursor_returns_tuple(self, mock_db) -> None:
        """
        Test _decode_cursor returns (timestamp, id) tuple.

        Verifies cursor can be decoded.
        """
        import base64
        cursor = base64.b64encode(b"2024-01-15T10:30:00|789").decode()

        created_at, record_id = mock_db._decode_cursor(cursor)

        assert created_at == "2024-01-15T10:30:00"
        assert record_id == 789

    def test_encode_decode_roundtrip(self, mock_db) -> None:
        """
        Test that encode/decode is reversible.

        Verifies roundtrip produces original values.
        """
        original_timestamp = "2024-01-20T14:25:00"
        original_id = 9999

        cursor = mock_db._encode_cursor(original_timestamp, original_id)
        decoded_timestamp, decoded_id = mock_db._decode_cursor(cursor)

        assert decoded_timestamp == original_timestamp
        assert decoded_id == original_id

    def test_decode_cursor_raises_for_invalid_format(self, mock_db) -> None:
        """
        Test _decode_cursor raises ValueError for invalid cursor.

        Verifies error handling for malformed cursors.
        """
        import base64
        # Invalid format (no pipe separator)
        invalid_cursor = base64.b64encode(b"invalidformat").decode()

        with pytest.raises(ValueError, match="Invalid cursor format"):
            mock_db._decode_cursor(invalid_cursor)

    def test_decode_cursor_raises_for_non_base64(self, mock_db) -> None:
        """
        Test _decode_cursor raises ValueError for non-base64 string.

        Verifies error handling for corrupted cursors.
        """
        with pytest.raises(ValueError):
            mock_db._decode_cursor("not-valid-base64!!!")


class TestCountInstagramPostsFiltered:
    """Tests for count_instagram_posts_filtered method."""

    def test_count_with_no_filters(self, mock_db) -> None:
        """
        Test count returns total when no filters applied.

        Verifies basic count functionality.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (150,)

        count = mock_db.count_instagram_posts_filtered()

        assert count == 150

    def test_count_with_hashtags_filter(self, mock_db) -> None:
        """
        Test count with hashtag filter builds correct SQL.

        Verifies hashtag filtering in count query.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (42,)

        count = mock_db.count_instagram_posts_filtered(hashtags=["recipe", "cooking"])

        assert count == 42
        # Verify SQL contains hashtag filter
        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        assert "instagram_hashtags" in sql
        assert "IN" in sql

    def test_count_with_content_type_video(self, mock_db) -> None:
        """
        Test count with video content type filter.

        Verifies video filtering.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (25,)

        count = mock_db.count_instagram_posts_filtered(content_type="video")

        assert count == 25
        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        assert "is_video = 1" in sql

    def test_count_with_content_type_image(self, mock_db) -> None:
        """
        Test count with image content type filter.

        Verifies image filtering.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (75,)

        count = mock_db.count_instagram_posts_filtered(content_type="image")

        assert count == 75
        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        assert "is_video = 0" in sql

    def test_count_with_owner_username(self, mock_db) -> None:
        """
        Test count with owner_username filter.

        Verifies username filtering.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (10,)

        count = mock_db.count_instagram_posts_filtered(owner_username="chef_alice")

        assert count == 10
        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        assert "owner_username" in sql

    def test_count_with_date_range(self, mock_db) -> None:
        """
        Test count with date_range filter.

        Verifies date filtering.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (30,)

        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 31)
        count = mock_db.count_instagram_posts_filtered(date_range=(start, end))

        assert count == 30
        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        assert "BETWEEN" in sql

    def test_count_with_multiple_filters(self, mock_db) -> None:
        """
        Test count with multiple filters combined.

        Verifies AND logic for multiple filters.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (5,)

        count = mock_db.count_instagram_posts_filtered(
            hashtags=["recipe"],
            content_type="video",
            owner_username="chef_bob"
        )

        assert count == 5
        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        # All filters should be in the SQL
        assert "instagram_hashtags" in sql
        assert "is_video = 1" in sql
        assert "owner_username" in sql


class TestCountTelegramMessagesFiltered:
    """Tests for count_telegram_messages_filtered method."""

    def test_count_with_no_filters(self, mock_db) -> None:
        """
        Test count returns total when no filters applied.

        Verifies basic count functionality.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (200,)

        count = mock_db.count_telegram_messages_filtered()

        assert count == 200

    def test_count_with_hashtags_filter(self, mock_db) -> None:
        """
        Test count with hashtag filter.

        Verifies hashtag filtering in count query.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (50,)

        count = mock_db.count_telegram_messages_filtered(hashtags=["news", "tech"])

        assert count == 50
        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        assert "telegram_hashtags" in sql

    def test_count_with_content_type(self, mock_db) -> None:
        """
        Test count with content_type filter.

        Verifies content type filtering.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (35,)

        count = mock_db.count_telegram_messages_filtered(content_type="photo")

        assert count == 35
        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        assert "content_type" in sql

    def test_count_with_date_range(self, mock_db) -> None:
        """
        Test count with date_range filter.

        Verifies date filtering.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchone.return_value = (80,)

        start = datetime(2024, 2, 1)
        end = datetime(2024, 2, 28)
        count = mock_db.count_telegram_messages_filtered(date_range=(start, end))

        assert count == 80
        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        assert "BETWEEN" in sql


class TestGetAllHashtags:
    """Tests for get_all_hashtags method."""

    def test_returns_empty_list_when_no_hashtags(self, mock_db) -> None:
        """
        Test returns empty list when no hashtags exist.

        Verifies empty result handling.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchall.return_value = []

        hashtags = mock_db.get_all_hashtags()

        assert hashtags == []

    def test_returns_instagram_hashtags(self, mock_db) -> None:
        """
        Test returns Instagram hashtags with counts.

        Verifies Instagram hashtag aggregation.
        """
        cursor = mock_db._conn.cursor()
        # First call for Instagram, second for Telegram
        cursor.fetchall.side_effect = [
            [("recipe", 50), ("cooking", 30)],  # Instagram
            [],  # Telegram
        ]

        hashtags = mock_db.get_all_hashtags()

        assert len(hashtags) == 2
        # Should be sorted by count descending
        assert hashtags[0]["tag"] == "recipe"
        assert hashtags[0]["count"] == 50
        assert hashtags[0]["instagram_count"] == 50
        assert hashtags[0]["telegram_count"] == 0
        assert hashtags[0]["source"] == "instagram"

    def test_returns_telegram_hashtags(self, mock_db) -> None:
        """
        Test returns Telegram hashtags with counts.

        Verifies Telegram hashtag aggregation.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchall.side_effect = [
            [],  # Instagram
            [("news", 100), ("tech", 75)],  # Telegram
        ]

        hashtags = mock_db.get_all_hashtags()

        assert len(hashtags) == 2
        assert hashtags[0]["tag"] == "news"
        assert hashtags[0]["telegram_count"] == 100
        assert hashtags[0]["instagram_count"] == 0
        assert hashtags[0]["source"] == "telegram"

    def test_merges_instagram_and_telegram(self, mock_db) -> None:
        """
        Test merges hashtags from both platforms.

        Verifies cross-platform aggregation.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchall.side_effect = [
            [("recipe", 50)],  # Instagram
            [("recipe", 30), ("news", 20)],  # Telegram
        ]

        hashtags = mock_db.get_all_hashtags()

        # "recipe" should be merged
        recipe_tag = next(h for h in hashtags if h["tag"] == "recipe")
        assert recipe_tag["count"] == 80  # 50 + 30
        assert recipe_tag["instagram_count"] == 50
        assert recipe_tag["telegram_count"] == 30
        assert recipe_tag["source"] == "both"

        # "news" should be telegram only
        news_tag = next(h for h in hashtags if h["tag"] == "news")
        assert news_tag["count"] == 20
        assert news_tag["source"] == "telegram"

    def test_respects_limit_parameter(self, mock_db) -> None:
        """
        Test respects limit parameter.

        Verifies limit is applied to results.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchall.side_effect = [
            [(f"tag{i}", i * 10) for i in range(10, 0, -1)],  # 10 Instagram tags
            [],
        ]

        hashtags = mock_db.get_all_hashtags(limit=5)

        assert len(hashtags) == 5
        # Should be top 5 by count
        assert hashtags[0]["tag"] == "tag10"

    def test_sorts_by_total_count_descending(self, mock_db) -> None:
        """
        Test results are sorted by total count descending.

        Verifies sorting order.
        """
        cursor = mock_db._conn.cursor()
        cursor.fetchall.side_effect = [
            [("small", 10), ("large", 100), ("medium", 50)],
            [],
        ]

        hashtags = mock_db.get_all_hashtags()

        assert hashtags[0]["tag"] == "large"
        assert hashtags[1]["tag"] == "medium"
        assert hashtags[2]["tag"] == "small"