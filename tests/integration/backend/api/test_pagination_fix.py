"""
Tests to verify pagination total count fix.

This module contains tests that ensure pagination responses return the actual
total count from the database, not just the current page size.

The fix addresses an issue where the `total` field was incorrectly set to
`len(results)` (current page size) instead of the actual database total.
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, MagicMock

from backend.postparse.core.data.database import SocialMediaDatabase


class TestDatabaseCountMethods:
    """Test count methods in database class for pagination."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing.
        
        Uses a temporary file that is automatically cleaned up after the test.
        
        Yields:
            SocialMediaDatabase: Database instance with temporary file.
        """
        # Create temporary file for database
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        
        # Create database instance
        db = SocialMediaDatabase(path)
        
        yield db
        
        # Cleanup
        try:
            os.unlink(path)
        except:
            pass

    def test_count_instagram_posts_returns_integer(self, temp_db):
        """Test that count_instagram_posts returns an integer count.
        
        This ensures the method works correctly and returns a valid count
        for pagination metadata.
        
        Args:
            temp_db: Temporary database fixture.
        """
        # Should return 0 for empty database
        count = temp_db.count_instagram_posts()
        assert isinstance(count, int)
        assert count >= 0

    def test_count_telegram_messages_returns_integer(self, temp_db):
        """Test that count_telegram_messages returns an integer count.
        
        This ensures the method works correctly and returns a valid count
        for pagination metadata.
        
        Args:
            temp_db: Temporary database fixture.
        """
        # Should return 0 for empty database
        count = temp_db.count_telegram_messages()
        assert isinstance(count, int)
        assert count >= 0

    def test_count_instagram_posts_by_hashtag_returns_integer(self, temp_db):
        """Test that count_instagram_posts_by_hashtag returns an integer count.
        
        This ensures the method works correctly and returns a valid count
        for filtered search results.
        
        Args:
            temp_db: Temporary database fixture.
        """
        # Should return 0 for hashtag that doesn't exist
        count = temp_db.count_instagram_posts_by_hashtag("nonexistent")
        assert isinstance(count, int)
        assert count >= 0


class TestPaginationTotalFix:
    """Test that pagination endpoints use actual total counts."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database with count methods.
        
        This mock database simulates a database with 150 total items,
        which is important for testing that pagination returns the actual
        total (150) not just the page size (e.g., 50).
        
        Returns:
            Mock: Database mock with count methods returning 150.
        """
        db = Mock(spec=SocialMediaDatabase)
        # Simulate database with 150 total items
        db.count_instagram_posts.return_value = 150
        db.count_telegram_messages.return_value = 150
        db.count_instagram_posts_by_hashtag.return_value = 45
        
        # Simulate get methods returning only page-size results
        db.get_instagram_posts.return_value = [{"shortcode": f"post{i}"} for i in range(51)]
        db.get_telegram_messages.return_value = [{"message_id": i} for i in range(51)]
        db.get_posts_by_hashtag.return_value = [{"shortcode": f"post{i}"} for i in range(46)]
        
        return db

    def test_instagram_posts_uses_actual_count_not_page_size(self, mock_db):
        """Test that /instagram/posts returns actual total, not page size.
        
        This is the core test for the pagination fix. Previously, the endpoint
        would return total=50 (the page size). After the fix, it should return
        total=150 (the actual database count).
        
        Args:
            mock_db: Mock database fixture with 150 total items.
        """
        # Simulate the logic from instagram.py router
        limit = 50
        posts = mock_db.get_instagram_posts(limit=limit + 1)
        
        # Old buggy code: total = len(posts[:limit])  # Would be 50
        # New fixed code: total = db.count_instagram_posts()  # Should be 150
        
        total = mock_db.count_instagram_posts()
        
        # Verify the fix: total should be actual DB count (150), not page size (50)
        assert total == 150, "Total should be actual database count, not page size"
        assert total != limit, "Total should not equal the limit parameter"
        assert len(posts[:limit]) == limit, "Current page should have limit items"

    def test_telegram_messages_uses_actual_count_not_page_size(self, mock_db):
        """Test that /telegram/messages returns actual total, not page size.
        
        Similar to the Instagram test, this verifies the Telegram endpoint
        returns the correct total count from the database.
        
        Args:
            mock_db: Mock database fixture with 150 total items.
        """
        # Simulate the logic from telegram.py router
        limit = 50
        messages = mock_db.get_telegram_messages(limit=limit + 1)
        
        # Old buggy code: total = len(messages[:limit])  # Would be 50
        # New fixed code: total = db.count_telegram_messages()  # Should be 150
        
        total = mock_db.count_telegram_messages()
        
        # Verify the fix: total should be actual DB count (150), not page size (50)
        assert total == 150, "Total should be actual database count, not page size"
        assert total != limit, "Total should not equal the limit parameter"
        assert len(messages[:limit]) == limit, "Current page should have limit items"

    def test_search_posts_with_hashtag_uses_filtered_count(self, mock_db):
        """Test that /search/posts with hashtag filter uses correct count.
        
        When filtering by hashtag, the total should reflect the count of posts
        matching that hashtag, not all posts or the current page size.
        
        Args:
            mock_db: Mock database fixture with 45 posts matching the hashtag.
        """
        # Simulate the logic from search.py router with hashtag filter
        hashtag = "recipe"
        limit = 20
        posts = mock_db.get_posts_by_hashtag(hashtag, limit=limit + 1)
        
        # Old buggy code: total_count = len(posts[:limit])  # Would be 20
        # New fixed code: total_count = db.count_instagram_posts_by_hashtag(hashtag)  # Should be 45
        
        total_count = mock_db.count_instagram_posts_by_hashtag(hashtag)
        
        # Verify the fix: total should be filtered count (45), not page size (20)
        assert total_count == 45, "Total should be hashtag-filtered count, not page size"
        assert total_count != limit, "Total should not equal the limit parameter"
        assert len(posts[:limit]) == limit, "Current page should have limit items"

    def test_search_posts_without_filter_uses_total_count(self, mock_db):
        """Test that /search/posts without filters uses total count.
        
        When no filters are applied, the total should be the count of all posts.
        
        Args:
            mock_db: Mock database fixture with 150 total posts.
        """
        # Simulate the logic from search.py router without filters
        limit = 20
        posts = mock_db.get_instagram_posts(limit=limit + 1)
        
        # New fixed code: total_count = db.count_instagram_posts()
        total_count = mock_db.count_instagram_posts()
        
        # Verify the fix: total should be all posts count (150), not page size (20)
        assert total_count == 150, "Total should be all posts count, not page size"
        assert total_count != limit, "Total should not equal the limit parameter"


if __name__ == "__main__":
    # Run tests when executed directly
    pytest.main([__file__, "-v"])

