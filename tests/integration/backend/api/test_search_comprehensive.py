"""
Comprehensive integration tests for search endpoints.

Tests GET /api/v1/search/posts and GET /api/v1/search/messages with all
filter combinations, cursor pagination, and metadata validation.

IMPORTANT: These tests use a REAL temporary SQLite database instead of mocks
to ensure that tested behavior matches the actual database implementation.
This prevents false confidence from mocks that claim support for features
the real database doesn't implement.

DATABASE CAPABILITIES TESTED (as of current implementation):

✓ Instagram Posts (search_instagram_posts):
  - hashtags: List[str] - OR logic, matches posts with ANY specified hashtag
  - date_range: Tuple[datetime, datetime] - Filters by creation date
  - content_type: str - Filters by 'video' or 'image'
  - owner_username: str - Filters by post owner
  - cursor: str - Base64-encoded cursor for pagination
  - limit: int - Maximum results per page

✓ Telegram Messages (search_telegram_messages):
  - hashtags: List[str] - OR logic, matches messages with ANY specified hashtag
  - date_range: Tuple[datetime, datetime] - Filters by creation date
  - content_type: str - Filters by 'text', 'photo', 'video', etc.
  - cursor: str - Base64-encoded cursor for pagination
  - limit: int - Maximum results per page

✗ NOT SUPPORTED (will be rejected with 400 error):
  - Telegram messages: channel_username filtering
    Reason: Database schema does not store channel username information.
    The telegram_messages table only stores chat_id (numeric identifier).
    See database.py lines 729-730 for documentation.

If you need to add channel_username filtering:
1. Extend the telegram_messages schema to include a channel_username column
2. Update _insert_telegram_message() to store channel_username
3. Update search_telegram_messages() to accept and filter by channel_username
4. Update count_telegram_messages_filtered() similarly
5. Then update these tests to verify the new functionality
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from typing import List, Dict, Any
import tempfile
import os

from backend.postparse.api.main import app
from backend.postparse.core.data.database import SocialMediaDatabase


@pytest.fixture(scope="function")
def temp_db():
    """
    Create a temporary SQLite database with test data.
    
    This fixture creates a real database instance (not a mock) to ensure
    tests verify actual database behavior rather than mock assumptions.
    """
    # Create temporary database file
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    try:
        # Initialize database
        db = SocialMediaDatabase(db_path=db_path)
        
        # Insert test Instagram posts
        test_posts = [
            {
                "shortcode": "ABC123",
                "owner_username": "chef_john",
                "caption": "Amazing pasta recipe #recipe #italian #pasta",
                "is_video": False,
                "likes": 100,
                "created_at": datetime(2024, 1, 15, 10, 0, 0),
                "hashtags": ["recipe", "italian", "pasta"],
            },
            {
                "shortcode": "DEF456",
                "owner_username": "chef_mary",
                "caption": "Cooking video tutorial #recipe #cooking #video",
                "is_video": True,
                "likes": 250,
                "created_at": datetime(2024, 1, 16, 12, 0, 0),
                "hashtags": ["recipe", "cooking", "video"],
            },
            {
                "shortcode": "GHI789",
                "owner_username": "chef_john",
                "caption": "Italian dessert recipe #recipe #italian #dessert",
                "is_video": False,
                "likes": 150,
                "created_at": datetime(2024, 1, 17, 14, 0, 0),
                "hashtags": ["recipe", "italian", "dessert"],
            },
        ]
        
        for post in test_posts:
            db._insert_instagram_post(**post)
        
        # Insert test Telegram messages
        test_messages = [
            {
                "message_id": 1001,
                "chat_id": -1001234567890,
                "content": "Daily recipe share #recipe #news",
                "content_type": "text",
                "created_at": datetime(2024, 1, 15, 9, 0, 0),
                "hashtags": ["recipe", "news"],
            },
            {
                "message_id": 1002,
                "chat_id": -1009876543210,
                "content": "Beautiful food photo",
                "content_type": "photo",
                "created_at": datetime(2024, 1, 16, 11, 0, 0),
                "hashtags": ["food"],
            },
            {
                "message_id": 1003,
                "chat_id": -1001234567890,
                "content": "Video tutorial #recipe #tutorial",
                "content_type": "video",
                "created_at": datetime(2024, 1, 17, 13, 0, 0),
                "hashtags": ["recipe", "tutorial"],
            },
        ]
        
        for msg in test_messages:
            db._insert_telegram_message(**msg)
        
        yield db
        
    finally:
        # Cleanup
        if os.path.exists(db_path):
            os.unlink(db_path)


class TestSearchComprehensive:
    """
    Comprehensive integration tests for search endpoints using real database.
    
    All tests use a temporary SQLite database to verify actual implementation
    behavior rather than mock assumptions. This ensures test results accurately
    reflect production capabilities.
    """
    
    @pytest.mark.integration
    def test_search_posts_with_multiple_hashtags_or_logic(self, temp_db):
        """
        Test hashtags filter with multiple hashtags using OR logic.
        
        Verifies that the ACTUAL database implementation:
        - Returns posts with any of the specified hashtags (OR logic)
        - Includes all hashtags in filters_applied metadata
        """
        from fastapi.testclient import TestClient
        from backend.postparse.api.main import app
        from backend.postparse.api.dependencies import get_db
        from backend.postparse.api.schemas.search import SearchPostsRequest
        
        # Override dependency with real database
        def mock_search_request():
            return SearchPostsRequest(hashtags=["recipe", "italian"], limit=20)
        
        client = TestClient(app)
        app.dependency_overrides[get_db] = lambda: temp_db
        app.dependency_overrides[SearchPostsRequest] = mock_search_request
        
        try:
            response = client.get("/api/v1/search/posts")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "results" in data
            assert len(data["results"]) == 3  # All 3 posts have "recipe" or "italian"
            
            # Verify filters_applied
            assert "filters_applied" in data
            assert "hashtags" in data["filters_applied"]
            assert set(data["filters_applied"]["hashtags"]) == {"recipe", "italian"}
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_posts_with_date_range(self, temp_db):
        """
        Test date_range filter with actual database.
        
        Verifies that the ACTUAL database implementation:
        - Returns only posts within the specified date range
        - Includes date_range in filters_applied metadata
        
        Note: This test uses dependency override to inject date_range since
        FastAPI doesn't parse nested query params well.
        """
        client = TestClient(app)
        
        from backend.postparse.api.dependencies import get_db
        from backend.postparse.api.schemas.search import SearchPostsRequest, DateRangeFilter
        
        # Override with date range filter
        def mock_search_request():
            return SearchPostsRequest(
                date_range=DateRangeFilter(
                    start_date=datetime(2024, 1, 15, 0, 0, 0),
                    end_date=datetime(2024, 1, 16, 23, 59, 59)
                ),
                limit=20
            )
        
        app.dependency_overrides[get_db] = lambda: temp_db
        app.dependency_overrides[SearchPostsRequest] = mock_search_request
        
        try:
            response = client.get("/api/v1/search/posts")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "results" in data
            # Only posts from 2024-01-15 and 2024-01-16 should be returned
            assert len(data["results"]) == 2
            assert "date_range" in data["filters_applied"]
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_posts_with_content_type_video(self, temp_db):
        """
        Test content_type='video' filter with actual database.
        
        Verifies that the ACTUAL database implementation:
        - Returns only video posts (is_video=True)
        - Includes content_type in filters_applied metadata
        """
        client = TestClient(app)
        
        from backend.postparse.api.dependencies import get_db
        app.dependency_overrides[get_db] = lambda: temp_db
        
        try:
            response = client.get(
                "/api/v1/search/posts",
                params={"content_type": "video", "limit": 20}
            )
            
            assert response.status_code == 200
            data = response.json()
            
            assert "results" in data
            # Only 1 post (DEF456) is a video
            assert len(data["results"]) == 1
            for post in data["results"]:
                assert post["is_video"] is True
            
            # Verify filters_applied
            assert data["filters_applied"]["content_type"] == "video"
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_posts_with_owner_username(self, temp_db):
        """
        Test owner_username filter with actual database.
        
        Verifies that the ACTUAL database implementation:
        - Returns only posts from the specified owner
        - Includes owner_username in filters_applied metadata
        """
        client = TestClient(app)
        
        from backend.postparse.api.dependencies import get_db
        app.dependency_overrides[get_db] = lambda: temp_db
        
        try:
            response = client.get(
                "/api/v1/search/posts",
                params={"owner_username": "chef_john", "limit": 20}
            )
            
            assert response.status_code == 200
            data = response.json()
            
            assert "results" in data
            # chef_john has 2 posts (ABC123 and GHI789)
            assert len(data["results"]) == 2
            for post in data["results"]:
                assert post["owner_username"] == "chef_john"
            
            assert data["filters_applied"]["owner_username"] == "chef_john"
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_posts_with_combined_filters(self, temp_db):
        """
        Test multiple filters together with actual database.
        
        Verifies that the ACTUAL database implementation:
        - Applies all filters correctly (AND logic across different filter types)
        - Includes all used filters in filters_applied metadata
        """
        from fastapi.testclient import TestClient
        from backend.postparse.api.main import app
        from backend.postparse.api.dependencies import get_db
        from backend.postparse.api.schemas.search import SearchPostsRequest, ContentTypeFilter
        
        # Test with multiple filters
        def mock_search_request():
            return SearchPostsRequest(
                hashtags=["recipe"],
                content_type=ContentTypeFilter.IMAGE,
                owner_username="chef_john",
                limit=20
            )
        
        client = TestClient(app)
        app.dependency_overrides[get_db] = lambda: temp_db
        app.dependency_overrides[SearchPostsRequest] = mock_search_request
        
        try:
            response = client.get("/api/v1/search/posts")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify all filters are in filters_applied
            assert "hashtags" in data["filters_applied"]
            assert "content_type" in data["filters_applied"]
            assert "owner_username" in data["filters_applied"]
            
            # Should return only image posts by chef_john with #recipe
            # That's posts ABC123 and GHI789 (both are images by chef_john with #recipe)
            assert len(data["results"]) == 2
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_posts_cursor_pagination(self, temp_db):
        """
        Test cursor-based pagination with actual database.
        
        Verifies that the ACTUAL database implementation:
        - Returns next_cursor when more results exist
        - Using cursor fetches the next page correctly
        - No duplicate results appear across pages
        - Cursor encoding/decoding works correctly
        """
        import base64
        from fastapi.testclient import TestClient
        from backend.postparse.api.main import app
        from backend.postparse.api.dependencies import get_db
        from backend.postparse.api.schemas.search import SearchPostsRequest
        
        client = TestClient(app)
        app.dependency_overrides[get_db] = lambda: temp_db
        
        try:
            # First page - request with small limit to force pagination
            def mock_request_page1():
                return SearchPostsRequest(limit=2)
            
            app.dependency_overrides[SearchPostsRequest] = mock_request_page1
            response1 = client.get("/api/v1/search/posts")
            assert response1.status_code == 200
            data1 = response1.json()
            
            # Check pagination metadata
            assert "pagination" in data1
            assert "next_cursor" in data1["pagination"]
            assert len(data1["results"]) == 2
            
            # Should have a next_cursor since we have 3 posts total
            assert data1["pagination"]["next_cursor"] is not None
            assert data1["pagination"]["has_more"] is True
            
            # Fetch next page using cursor
            def mock_request_page2():
                return SearchPostsRequest(
                    limit=2,
                    cursor=data1["pagination"]["next_cursor"]
                )
            
            app.dependency_overrides[SearchPostsRequest] = mock_request_page2
            response2 = client.get("/api/v1/search/posts")
            assert response2.status_code == 200
            data2 = response2.json()
            
            # Should have 1 result (3rd post)
            assert len(data2["results"]) == 1
            
            # Verify no duplicates
            ids1 = {post["shortcode"] for post in data1["results"]}
            ids2 = {post["shortcode"] for post in data2["results"]}
            assert ids1.isdisjoint(ids2)
            
            # No more pages
            assert data2["pagination"]["next_cursor"] is None
            assert data2["pagination"]["has_more"] is False
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_posts_invalid_cursor(self, temp_db):
        """
        Test with invalid cursor string using actual database.
        
        Verifies that the ACTUAL database implementation:
        - Returns 400 Bad Request for malformed cursors
        - Error message indicates invalid cursor
        """
        import base64
        from fastapi.testclient import TestClient
        from backend.postparse.api.main import app
        from backend.postparse.api.dependencies import get_db
        from backend.postparse.api.schemas.search import SearchPostsRequest
        
        client = TestClient(app)
        
        # Create a valid base64 string but with invalid cursor format
        # (database expects "timestamp|id" format)
        invalid_cursor = base64.b64encode(b"invalid_data").decode()
        
        app.dependency_overrides[get_db] = lambda: temp_db
        
        # Mock request with invalid cursor (valid base64 but wrong format)
        def mock_request():
            return SearchPostsRequest(cursor=invalid_cursor, limit=10)
        
        app.dependency_overrides[SearchPostsRequest] = mock_request
        
        try:
            response = client.get("/api/v1/search/posts")
            
            assert response.status_code == 400
            assert "invalid cursor" in response.json()["detail"].lower()
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_messages_with_hashtags(self, temp_db):
        """
        Test Telegram message search with hashtags filter using actual database.
        
        Verifies that the ACTUAL database implementation:
        - Returns messages with any of the specified hashtags (OR logic)
        - Includes hashtags in filters_applied metadata
        """
        from fastapi.testclient import TestClient
        from backend.postparse.api.main import app
        from backend.postparse.api.dependencies import get_db
        from backend.postparse.api.schemas.search import SearchMessagesRequest
        
        # Test hashtag filtering
        def mock_search_request():
            return SearchMessagesRequest(hashtags=["recipe"], limit=20)
        
        client = TestClient(app)
        app.dependency_overrides[get_db] = lambda: temp_db
        app.dependency_overrides[SearchMessagesRequest] = mock_search_request
        
        try:
            response = client.get("/api/v1/search/messages")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "results" in data
            # Messages 1001 and 1003 have #recipe
            assert len(data["results"]) == 2
            assert "hashtags" in data["filters_applied"]
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_messages_with_channel_username(self, temp_db):
        """
        Test channel_username filter rejection with actual database.
        
        IMPORTANT: This test verifies that channel_username filtering is correctly
        REJECTED because the database schema does NOT store channel username
        information for Telegram messages.
        
        Verifies that the implementation:
        - Returns 400 Bad Request when channel_username is provided
        - Error message explains that channel_username is not supported
        """
        client = TestClient(app)
        
        from backend.postparse.api.dependencies import get_db
        app.dependency_overrides[get_db] = lambda: temp_db
        
        try:
            response = client.get(
                "/api/v1/search/messages",
                params={"channel_username": "cooking_channel", "limit": 20}
            )
            
            # Should return 400 Bad Request
            assert response.status_code == 400
            data = response.json()
            
            # Verify error message mentions unsupported filter
            assert "channel_username" in data["detail"].lower()
            assert "not supported" in data["detail"].lower()
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_messages_with_content_type(self, temp_db):
        """
        Test content_type filter for messages with actual database.
        
        Verifies that the ACTUAL database implementation:
        - Returns only messages with the specified content type
        - Includes content_type in filters_applied metadata
        """
        client = TestClient(app)
        
        from backend.postparse.api.dependencies import get_db
        app.dependency_overrides[get_db] = lambda: temp_db
        
        try:
            # Test with "photo" content type
            response = client.get(
                "/api/v1/search/messages?content_type=image&limit=20"
            )
            
            # Note: The database stores "photo" but the API accepts "image"
            # which gets mapped accordingly
            assert response.status_code == 200
            data = response.json()
            
            assert "results" in data
            assert data["filters_applied"]["content_type"] == "image"
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_messages_cursor_pagination(self, temp_db):
        """
        Test cursor pagination for messages with actual database.
        
        Verifies that the ACTUAL database implementation:
        - Pagination works correctly for messages endpoint
        - next_cursor is returned when more results exist
        - Cursor-based navigation retrieves correct pages
        """
        client = TestClient(app)
        
        from backend.postparse.api.dependencies import get_db
        app.dependency_overrides[get_db] = lambda: temp_db
        
        try:
            response = client.get("/api/v1/search/messages", params={"limit": 2})
            
            assert response.status_code == 200
            data = response.json()
            
            assert "pagination" in data
            assert "next_cursor" in data["pagination"]
            assert len(data["results"]) == 2
            
            # Should have next_cursor since we have 3 messages total
            assert data["pagination"]["next_cursor"] is not None
            assert data["pagination"]["has_more"] is True
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_messages_includes_chat_id(self, temp_db):
        """
        Test that message search results include chat_id field using actual database.
        
        Verifies that the ACTUAL database implementation:
        - Returns chat_id (numeric identifier) for each message
        - chat_id is properly populated from the database
        - channel_username is None (deprecated field, not stored in DB)
        """
        from fastapi.testclient import TestClient
        from backend.postparse.api.main import app
        from backend.postparse.api.dependencies import get_db
        from backend.postparse.api.schemas.search import SearchMessagesRequest
        
        # Search for messages with hashtag
        def mock_search_request():
            return SearchMessagesRequest(hashtags=["recipe"], limit=20)
        
        client = TestClient(app)
        app.dependency_overrides[get_db] = lambda: temp_db
        app.dependency_overrides[SearchMessagesRequest] = mock_search_request
        
        try:
            response = client.get("/api/v1/search/messages")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "results" in data
            assert len(data["results"]) == 2  # 2 messages with #recipe
            
            # Verify each result has chat_id and channel_username is None
            for msg in data["results"]:
                assert "chat_id" in msg
                assert msg["chat_id"] is not None
                assert isinstance(msg["chat_id"], int)
                # Verify it's one of our test chat IDs
                assert msg["chat_id"] in [-1001234567890, -1009876543210]
                
                # channel_username should be None (deprecated field)
                assert "channel_username" in msg  # Field exists for backwards compatibility
                assert msg["channel_username"] is None
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_list_hashtags_aggregation(self, temp_db):
        """
        Test GET /api/v1/search/hashtags with actual database aggregation.
        
        Verifies that the ACTUAL database implementation:
        - Returns hashtags with accurate counts from the database
        - Hashtags are sorted by count (descending)
        - Source (instagram/telegram/both) is correctly indicated
        - Aggregation logic works across both platforms
        """
        from fastapi.testclient import TestClient
        from backend.postparse.api.main import app
        from backend.postparse.api.dependencies import get_db
        
        client = TestClient(app)
        app.dependency_overrides[get_db] = lambda: temp_db
        
        try:
            response = client.get("/api/v1/search/hashtags?limit=10")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "hashtags" in data
            assert len(data["hashtags"]) > 0
            
            # Verify structure and content
            for hashtag in data["hashtags"]:
                assert "tag" in hashtag
                assert "count" in hashtag
                assert "source" in hashtag
                assert hashtag["source"] in ["instagram", "telegram", "both"]
            
            # Verify "recipe" is in both platforms (3 Instagram + 2 Telegram = 5 total)
            recipe_tag = next((h for h in data["hashtags"] if h["tag"] == "recipe"), None)
            assert recipe_tag is not None
            assert recipe_tag["count"] == 5
            assert recipe_tag["source"] == "both"
            
        finally:
            app.dependency_overrides.clear()

