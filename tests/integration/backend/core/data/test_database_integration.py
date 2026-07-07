"""
Integration tests for SocialMediaDatabase using real SQLite.

This module tests the database with actual SQL execution using temporary
SQLite databases, verifying real queries and data operations work correctly.
"""

from datetime import datetime, timedelta
import tempfile
from pathlib import Path

import pytest

from backend.postparse.core.data.database import SocialMediaDatabase


@pytest.fixture(scope="function")
def temp_db_path(tmp_path) -> str:
    """
    Create a temporary database file path.

    Args:
        tmp_path: Pytest's temporary directory fixture.

    Returns:
        Path to temporary database file.
    """
    return str(tmp_path / "test_social_media.db")


@pytest.fixture(scope="function")
def db(temp_db_path) -> SocialMediaDatabase:
    """
    Create a real SQLite database for integration testing.

    Args:
        temp_db_path: Path to temporary database file.

    Yields:
        SocialMediaDatabase: Real database instance.
    """
    database = SocialMediaDatabase(temp_db_path)
    yield database


class TestDatabaseInitialization:
    """Integration tests for database initialization."""

    def test_creates_tables_on_init(self, temp_db_path) -> None:
        """
        Test database creates all required tables on initialization.

        Verifies table creation happens automatically.
        """
        import sqlite3

        db = SocialMediaDatabase(temp_db_path)

        # Use separate connection to verify tables exist
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()

        # Check Instagram tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='instagram_posts'"
        )
        assert cursor.fetchone() is not None

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='instagram_hashtags'"
        )
        assert cursor.fetchone() is not None

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='instagram_mentions'"
        )
        assert cursor.fetchone() is not None

        # Check Telegram tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='telegram_messages'"
        )
        assert cursor.fetchone() is not None

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='telegram_hashtags'"
        )
        assert cursor.fetchone() is not None

        # Check content_analysis table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='content_analysis'"
        )
        assert cursor.fetchone() is not None

        conn.close()

    def test_database_file_is_created(self, temp_db_path) -> None:
        """
        Test database file is created on disk.

        Verifies file is created at specified path.
        """
        db = SocialMediaDatabase(temp_db_path)

        assert Path(temp_db_path).exists()


class TestInstagramPostOperations:
    """Integration tests for Instagram post operations."""

    def test_insert_and_retrieve_instagram_post(self, db) -> None:
        """
        Test inserting and retrieving an Instagram post.

        Verifies roundtrip data integrity.
        """
        created_at = datetime(2024, 1, 15, 10, 30, 0)

        db._insert_instagram_post(
            shortcode="ABC123",
            owner_username="test_user",
            owner_id="12345",
            caption="Test caption #recipe #food @friend",
            is_video=False,
            media_url="https://example.com/image.jpg",
            typename="GraphImage",
            likes=150,
            comments=25,
            created_at=created_at,
            hashtags=["recipe", "food"],
            mentions=["friend"],
        )

        posts = db.get_instagram_posts(limit=10)

        assert len(posts) == 1
        post = posts[0]
        assert post["shortcode"] == "ABC123"
        assert post["owner_username"] == "test_user"
        assert post["caption"] == "Test caption #recipe #food @friend"
        assert post["is_video"] == False
        assert post["likes"] == 150
        assert post["comments"] == 25

    def test_insert_video_post(self, db) -> None:
        """
        Test inserting a video post sets is_video correctly.

        Verifies boolean field handling.
        """
        db._insert_instagram_post(
            shortcode="VIDEO123",
            owner_username="video_user",
            caption="Video post",
            is_video=True,
            typename="GraphVideo",
            likes=500,
            comments=100,
            created_at=datetime.now(),
        )

        posts = db.get_instagram_posts()
        assert len(posts) == 1
        assert posts[0]["is_video"] == True

    def test_update_existing_post(self, db) -> None:
        """
        Test updating an existing post with same shortcode.

        Verifies upsert behavior.
        """
        # Insert initial post
        db._insert_instagram_post(
            shortcode="UPDATE123",
            owner_username="user1",
            caption="Original caption",
            is_video=False,
            likes=100,
            created_at=datetime.now(),
        )

        # Insert same shortcode with different data
        db._insert_instagram_post(
            shortcode="UPDATE123",
            owner_username="user1",
            caption="Updated caption",
            is_video=False,
            likes=200,  # Updated likes
            created_at=datetime.now(),
        )

        posts = db.get_instagram_posts()
        # Should still have 1 post (no duplicates)
        assert len(posts) == 1
        # Note: behavior depends on implementation (update vs ignore)

    def test_hashtag_insertion(self, db, temp_db_path) -> None:
        """
        Test hashtags are stored in separate table.

        Verifies hashtag relationship.
        """
        import sqlite3

        db._insert_instagram_post(
            shortcode="HASHTAG123",
            owner_username="hashtag_user",
            caption="Test #cooking #recipe #italian",
            is_video=False,
            likes=50,
            created_at=datetime.now(),
            hashtags=["cooking", "recipe", "italian"],
        )

        # Query hashtags directly using separate connection
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT h.hashtag FROM instagram_hashtags h
            JOIN instagram_posts p ON h.post_id = p.id
            WHERE p.shortcode = ?
            """,
            ("HASHTAG123",),
        )
        hashtags = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "cooking" in hashtags
        assert "recipe" in hashtags
        assert "italian" in hashtags

    def test_mention_insertion(self, db, temp_db_path) -> None:
        """
        Test mentions are stored in separate table.

        Verifies mention relationship.
        """
        import sqlite3

        db._insert_instagram_post(
            shortcode="MENTION123",
            owner_username="mention_user",
            caption="Thanks @friend1 and @friend2!",
            is_video=False,
            likes=50,
            created_at=datetime.now(),
            mentions=["friend1", "friend2"],
        )

        # Query mentions directly using separate connection
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT m.username FROM instagram_mentions m
            JOIN instagram_posts p ON m.post_id = p.id
            WHERE p.shortcode = ?
            """,
            ("MENTION123",),
        )
        mentions = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "friend1" in mentions
        assert "friend2" in mentions


class TestTelegramMessageOperations:
    """Integration tests for Telegram message operations."""

    def test_insert_and_retrieve_telegram_message(self, db) -> None:
        """
        Test inserting and retrieving a Telegram message.

        Verifies roundtrip data integrity.
        """
        created_at = datetime(2024, 1, 20, 14, 0, 0)

        db._insert_telegram_message(
            message_id=9001,
            chat_id=-1001234567890,
            content="Hello from Telegram #test #message",
            content_type="text",
            views=500,
            forwards=50,
            created_at=created_at,
            hashtags=["test", "message"],
        )

        messages = db.get_telegram_messages(limit=10)

        assert len(messages) == 1
        msg = messages[0]
        assert msg["message_id"] == 9001
        assert msg["content"] == "Hello from Telegram #test #message"
        assert msg["content_type"] == "text"
        assert msg["views"] == 500

    def test_insert_photo_message(self, db) -> None:
        """
        Test inserting a photo message with media_urls.

        Verifies media storage.
        """
        db._insert_telegram_message(
            message_id=9002,
            chat_id=-1001234567890,
            content="Beautiful photo",
            content_type="photo",
            media_urls=["https://example.com/photo1.jpg"],
            views=100,
            created_at=datetime.now(),
        )

        messages = db.get_telegram_messages()
        assert len(messages) == 1
        assert messages[0]["content_type"] == "photo"

    def test_telegram_hashtag_insertion(self, db, temp_db_path) -> None:
        """
        Test Telegram hashtags are stored in separate table.

        Verifies hashtag relationship.
        """
        import sqlite3

        db._insert_telegram_message(
            message_id=9003,
            chat_id=-1001234567890,
            content="News #tech #AI #future",
            content_type="text",
            created_at=datetime.now(),
            hashtags=["tech", "AI", "future"],
        )

        # Query hashtags directly using separate connection
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT h.hashtag FROM telegram_hashtags h
            JOIN telegram_messages m ON h.message_id = m.id
            WHERE m.message_id = ?
            """,
            (9003,),
        )
        hashtags = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "tech" in hashtags
        assert "AI" in hashtags
        assert "future" in hashtags


class TestSearchOperations:
    """Integration tests for search functionality."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, db):
        """Set up test data for search tests."""
        # Insert Instagram posts
        db._insert_instagram_post(
            shortcode="SEARCH001",
            owner_username="chef_alice",
            caption="Pasta recipe #recipe #italian",
            is_video=False,
            likes=100,
            created_at=datetime(2024, 1, 10, 10, 0, 0),
            hashtags=["recipe", "italian"],
        )
        db._insert_instagram_post(
            shortcode="SEARCH002",
            owner_username="chef_bob",
            caption="Video cooking tutorial #recipe #cooking",
            is_video=True,
            likes=200,
            created_at=datetime(2024, 1, 15, 12, 0, 0),
            hashtags=["recipe", "cooking"],
        )
        db._insert_instagram_post(
            shortcode="SEARCH003",
            owner_username="traveler",
            caption="Beach sunset #travel #nature",
            is_video=False,
            likes=300,
            created_at=datetime(2024, 1, 20, 18, 0, 0),
            hashtags=["travel", "nature"],
        )

        # Insert Telegram messages
        db._insert_telegram_message(
            message_id=8001,
            chat_id=-1001234567890,
            content="Daily recipe #recipe #daily",
            content_type="text",
            views=50,
            created_at=datetime(2024, 1, 12, 9, 0, 0),
            hashtags=["recipe", "daily"],
        )
        db._insert_telegram_message(
            message_id=8002,
            chat_id=-1001234567890,
            content="Tech news #tech #news",
            content_type="text",
            views=100,
            created_at=datetime(2024, 1, 18, 11, 0, 0),
            hashtags=["tech", "news"],
        )

        yield

    def test_search_instagram_by_hashtag(self, db) -> None:
        """
        Test searching Instagram posts by hashtag.

        Verifies hashtag filtering works.
        """
        posts, cursor = db.search_instagram_posts(hashtags=["recipe"])

        assert len(posts) == 2
        shortcodes = [p["shortcode"] for p in posts]
        assert "SEARCH001" in shortcodes
        assert "SEARCH002" in shortcodes

    def test_search_instagram_by_content_type_video(self, db) -> None:
        """
        Test filtering Instagram posts by video type.

        Verifies content type filtering.
        """
        posts, cursor = db.search_instagram_posts(content_type="video")

        assert len(posts) == 1
        assert posts[0]["shortcode"] == "SEARCH002"

    def test_search_instagram_by_content_type_image(self, db) -> None:
        """
        Test filtering Instagram posts by image type.

        Verifies image filtering.
        """
        posts, cursor = db.search_instagram_posts(content_type="image")

        assert len(posts) == 2  # SEARCH001 and SEARCH003

    def test_search_instagram_by_owner_username(self, db) -> None:
        """
        Test filtering Instagram posts by owner username.

        Verifies owner filtering.
        """
        posts, cursor = db.search_instagram_posts(owner_username="chef_alice")

        assert len(posts) == 1
        assert posts[0]["shortcode"] == "SEARCH001"

    def test_search_instagram_by_date_range(self, db) -> None:
        """
        Test filtering Instagram posts by date range.

        Verifies date filtering.
        """
        start = datetime(2024, 1, 14, 0, 0, 0)
        end = datetime(2024, 1, 16, 23, 59, 59)

        posts, cursor = db.search_instagram_posts(date_range=(start, end))

        assert len(posts) == 1
        assert posts[0]["shortcode"] == "SEARCH002"

    def test_search_telegram_by_hashtag(self, db) -> None:
        """
        Test searching Telegram messages by hashtag.

        Verifies hashtag filtering works.
        """
        messages, cursor = db.search_telegram_messages(hashtags=["recipe"])

        assert len(messages) == 1
        assert messages[0]["message_id"] == 8001

    def test_search_telegram_by_content_type(self, db) -> None:
        """
        Test filtering Telegram messages by content type.

        Verifies content type filtering.
        """
        messages, cursor = db.search_telegram_messages(content_type="text")

        assert len(messages) == 2


class TestCountFiltered:
    """Integration tests for count filtered methods."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, db):
        """Set up test data for count tests."""
        # Insert Instagram posts
        for i in range(5):
            db._insert_instagram_post(
                shortcode=f"COUNT{i:03d}",
                owner_username="user" if i < 3 else "other",
                caption=f"Post {i}",
                is_video=(i % 2 == 0),
                likes=i * 10,
                created_at=datetime(2024, 1, i + 1, 12, 0, 0),
                hashtags=["tag1"] if i < 3 else ["tag2"],
            )

        # Insert Telegram messages
        for i in range(4):
            db._insert_telegram_message(
                message_id=7000 + i,
                chat_id=-1001234567890,
                content=f"Message {i}",
                content_type="text" if i < 2 else "photo",
                views=i * 50,
                created_at=datetime(2024, 1, i + 1, 10, 0, 0),
                hashtags=["tech"] if i < 2 else ["other"],
            )

        yield

    def test_count_instagram_posts_total(self, db) -> None:
        """
        Test counting all Instagram posts.

        Verifies total count.
        """
        count = db.count_instagram_posts_filtered()
        assert count == 5

    def test_count_instagram_posts_by_hashtag(self, db) -> None:
        """
        Test counting Instagram posts by hashtag.

        Verifies hashtag filter count.
        """
        count = db.count_instagram_posts_filtered(hashtags=["tag1"])
        assert count == 3

    def test_count_instagram_posts_by_video(self, db) -> None:
        """
        Test counting Instagram video posts.

        Verifies video filter count.
        """
        count = db.count_instagram_posts_filtered(content_type="video")
        assert count == 3  # Posts 0, 2, 4 are videos

    def test_count_instagram_posts_by_owner(self, db) -> None:
        """
        Test counting Instagram posts by owner.

        Verifies owner filter count.
        """
        count = db.count_instagram_posts_filtered(owner_username="user")
        assert count == 3

    def test_count_telegram_messages_total(self, db) -> None:
        """
        Test counting all Telegram messages.

        Verifies total count.
        """
        count = db.count_telegram_messages_filtered()
        assert count == 4

    def test_count_telegram_messages_by_hashtag(self, db) -> None:
        """
        Test counting Telegram messages by hashtag.

        Verifies hashtag filter count.
        """
        count = db.count_telegram_messages_filtered(hashtags=["tech"])
        assert count == 2

    def test_count_telegram_messages_by_content_type(self, db) -> None:
        """
        Test counting Telegram messages by content type.

        Verifies content type filter count.
        """
        count = db.count_telegram_messages_filtered(content_type="photo")
        assert count == 2


class TestGetAllHashtags:
    """Integration tests for get_all_hashtags method."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, db):
        """Set up test data for hashtag tests."""
        # Instagram posts with hashtags
        db._insert_instagram_post(
            shortcode="TAG001",
            caption="#recipe #italian",
            is_video=False,
            likes=100,
            created_at=datetime.now(),
            hashtags=["recipe", "italian"],
        )
        db._insert_instagram_post(
            shortcode="TAG002",
            caption="#recipe #cooking",
            is_video=False,
            likes=100,
            created_at=datetime.now(),
            hashtags=["recipe", "cooking"],
        )

        # Telegram messages with hashtags
        db._insert_telegram_message(
            message_id=6001,
            chat_id=-1001234567890,
            content="#recipe #daily",
            content_type="text",
            created_at=datetime.now(),
            hashtags=["recipe", "daily"],
        )
        db._insert_telegram_message(
            message_id=6002,
            chat_id=-1001234567890,
            content="#tech #news",
            content_type="text",
            created_at=datetime.now(),
            hashtags=["tech", "news"],
        )

        yield

    def test_get_all_hashtags_includes_both_platforms(self, db) -> None:
        """
        Test get_all_hashtags includes hashtags from both platforms.

        Verifies cross-platform aggregation.
        """
        hashtags = db.get_all_hashtags()

        tags = [h["tag"] for h in hashtags]

        # Instagram tags
        assert "italian" in tags
        assert "cooking" in tags

        # Telegram tags
        assert "tech" in tags
        assert "news" in tags

        # Shared tag
        assert "recipe" in tags

    def test_get_all_hashtags_merges_counts(self, db) -> None:
        """
        Test get_all_hashtags merges counts from both platforms.

        Verifies count aggregation for shared tags.
        """
        hashtags = db.get_all_hashtags()

        recipe_tag = next(h for h in hashtags if h["tag"] == "recipe")

        # "recipe" appears 2 times on Instagram and 1 time on Telegram
        assert recipe_tag["instagram_count"] == 2
        assert recipe_tag["telegram_count"] == 1
        assert recipe_tag["count"] == 3
        assert recipe_tag["source"] == "both"

    def test_get_all_hashtags_sorted_by_count(self, db) -> None:
        """
        Test get_all_hashtags returns results sorted by count.

        Verifies sorting order.
        """
        hashtags = db.get_all_hashtags()

        # First hashtag should have highest count
        assert hashtags[0]["tag"] == "recipe"
        assert hashtags[0]["count"] == 3

    def test_get_all_hashtags_respects_limit(self, db) -> None:
        """
        Test get_all_hashtags respects limit parameter.

        Verifies limit is applied.
        """
        hashtags = db.get_all_hashtags(limit=3)

        assert len(hashtags) == 3


class TestCursorPagination:
    """Integration tests for cursor-based pagination."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, db):
        """Set up test data for pagination tests."""
        # Insert 20 Instagram posts with sequential timestamps
        for i in range(20):
            db._insert_instagram_post(
                shortcode=f"PAGE{i:03d}",
                caption=f"Post {i}",
                is_video=False,
                likes=i * 10,
                created_at=datetime(2024, 1, i + 1, 12, 0, 0),
                hashtags=["pagination"],
            )

        yield

    def test_first_page_returns_limit(self, db) -> None:
        """
        Test first page returns requested limit.

        Verifies initial page size.
        """
        posts, cursor = db.search_instagram_posts(limit=5)

        assert len(posts) == 5

    def test_cursor_pagination_returns_next_page(self, db) -> None:
        """
        Test cursor allows fetching next page.

        Verifies pagination continuity.
        """
        # Get first page
        posts1, cursor1 = db.search_instagram_posts(limit=5)
        assert len(posts1) == 5
        assert cursor1 is not None

        # Get second page using cursor
        posts2, cursor2 = db.search_instagram_posts(limit=5, cursor=cursor1)
        assert len(posts2) == 5

        # Ensure no overlap
        shortcodes1 = {p["shortcode"] for p in posts1}
        shortcodes2 = {p["shortcode"] for p in posts2}
        assert len(shortcodes1.intersection(shortcodes2)) == 0

    def test_last_page_returns_none_cursor(self, db) -> None:
        """
        Test last page returns None cursor.

        Verifies end of pagination.
        """
        # Get all posts with large limit
        posts, cursor = db.search_instagram_posts(limit=100)

        assert len(posts) == 20
        assert cursor is None

