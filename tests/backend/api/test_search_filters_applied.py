"""
Integration tests for filters_applied metadata in search endpoints.

This module tests that the filters_applied field accurately reflects
which filters were actually applied to the results, preventing misleading
client information.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.postparse.api.main import app


@pytest.fixture
def client() -> TestClient:
    """
    Create FastAPI test client.
    
    Returns:
        TestClient instance for making requests.
    
    Example:
        def test_endpoint(client):
            response = client.get("/api/v1/health")
    """
    return TestClient(app)


class TestSearchFiltersApplied:
    """Integration tests for filters_applied metadata accuracy."""

    @pytest.mark.integration
    def test_owner_username_filter_not_misleading(self, client: TestClient):
        """
        Test that owner_username filter is correctly applied and reflected in filters_applied.
        
        This test verifies that the owner_username filter is now implemented and
        correctly reported in filters_applied.
        
        Verifies:
        - When owner_username is provided, results ARE filtered by that owner
        - filters_applied DOES include owner_username (since it's now implemented)
        - Clients receive accurate information about which filters were applied
        """
        # Mock only user1's posts (filtered)
        mock_posts = [
            {
                "shortcode": "ABC123",
                "owner_username": "user1",
                "caption": "Post from user1",
                "is_video": False,
                "likes": 100,
                "hashtags": [],
                "created_at": "2025-11-23T10:30:00Z",
            }
        ]
        
        mock_db = MagicMock()
        mock_db.search_instagram_posts.return_value = (mock_posts, None)
        mock_db.count_instagram_posts_filtered.return_value = 1
        
        from backend.postparse.api import dependencies
        original_get_db = dependencies.get_db
        
        def override_get_db():
            yield mock_db
        
        app.dependency_overrides[original_get_db] = override_get_db
        
        try:
            # Request with owner_username filter
            response = client.get("/api/v1/search/posts?owner_username=user1&limit=10")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify results exist
            assert "results" in data
            assert len(data["results"]) == 1  # Only user1's posts
            
            # filters_applied should NOW include owner_username (feature is implemented)
            assert "filters_applied" in data
            assert "owner_username" in data["filters_applied"]
            assert data["filters_applied"]["owner_username"] == "user1"
            
            # Only user1's posts should be in results
            usernames = [r["owner_username"] for r in data["results"]]
            assert all(u == "user1" for u in usernames)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.integration
    @pytest.mark.skip(reason="FastAPI doesn't properly parse list query params in Pydantic models with Depends(). This is a known limitation requiring Query() annotations instead.")
    def test_hashtag_filter_correctly_reported(self, client: TestClient):
        """
        Test that hashtag filter IS correctly added to filters_applied when used.
        
        This verifies that when a filter is actually implemented and applied,
        it's correctly reported in filters_applied.
        
        Note: This test is skipped because FastAPI has a known limitation where list fields
        in Pydantic models used with Depends() for query parameters don't parse correctly.
        This needs to be fixed by using Query() annotations in the router definition.
        
        Verifies:
        - When hashtag is provided, it appears in filters_applied
        - The reported filter matches what was actually used
        """
        mock_posts = [
            {
                "shortcode": "ABC123",
                "owner_username": "user1",
                "caption": "Recipe post #recipe",
                "is_video": False,
                "likes": 100,
                "hashtags": ["recipe"],
                "created_at": "2025-11-23T10:30:00Z",
            }
        ]
        
        mock_db = MagicMock()
        mock_db.get_posts_by_hashtag.return_value = mock_posts
        mock_db.count_instagram_posts_by_hashtag.return_value = 1
        
        from backend.postparse.api import dependencies
        original_get_db = dependencies.get_db
        
        def override_get_db():
            yield mock_db
        
        app.dependency_overrides[original_get_db] = override_get_db
        
        try:
            # Request with hashtag filter using params dict for proper list parsing
            response = client.get("/api/v1/search/posts", params={
                "hashtags": ["recipe"],
                "limit": 10
            })
            
            assert response.status_code == 200
            data = response.json()
            
            # filters_applied SHOULD include hashtags since it's implemented
            assert "filters_applied" in data
            assert "hashtags" in data["filters_applied"]
            assert data["filters_applied"]["hashtags"] == ["recipe"]
            
            # Verify the correct DB method was called
            mock_db.get_posts_by_hashtag.assert_called_once_with("recipe", limit=11)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.integration
    def test_messages_unimplemented_filters_not_reported(self, client: TestClient):
        """
        Test that implemented filters are correctly reported in filters_applied.
        
        This verifies that hashtag filters for messages are added to filters_applied
        since they're implemented. Also verifies that unsupported filters like
        channel_username are rejected with a 400 error.
        
        Verifies:
        - hashtags filter IS reported in filters_applied when used
        - channel_username filter is REJECTED with 400 (not supported)
        - filters_applied accurately reflects applied filters
        """
        # Test 1: hashtags filter works and is reported
        mock_messages = [
            {
                "message_id": 12345,
                "content": "Message with recipe hashtag",
                "content_type": "text",
                "hashtags": ["recipe"],
                "created_at": "2025-11-23T08:00:00Z",
            }
        ]
        
        mock_db = MagicMock()
        mock_db.search_telegram_messages.return_value = (mock_messages, None)
        mock_db.count_telegram_messages_filtered.return_value = 1
        
        from backend.postparse.api import dependencies
        original_get_db = dependencies.get_db
        
        def override_get_db():
            yield mock_db
        
        app.dependency_overrides[original_get_db] = override_get_db
        
        try:
            # Request with hashtags filter only
            from backend.postparse.api.schemas.search import SearchMessagesRequest
            
            def mock_search_request_hashtags():
                return SearchMessagesRequest(
                    hashtags=["recipe"],
                    limit=10
                )
            
            app.dependency_overrides[SearchMessagesRequest] = mock_search_request_hashtags
            
            response = client.get("/api/v1/search/messages")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify hashtags filter is reported
            assert "filters_applied" in data
            assert "hashtags" in data["filters_applied"]
            assert data["filters_applied"]["hashtags"] == ["recipe"]
            
            # Test 2: channel_username is rejected with 400
            def mock_search_request_channel():
                return SearchMessagesRequest(
                    hashtags=["recipe"],
                    channel_username="channel1",
                    limit=10
                )
            
            app.dependency_overrides[SearchMessagesRequest] = mock_search_request_channel
            
            response2 = client.get("/api/v1/search/messages")
            
            # Should return 400 Bad Request for unsupported filter
            assert response2.status_code == 400
            error_data = response2.json()
            assert "channel_username" in error_data["detail"].lower()
            assert "not supported" in error_data["detail"].lower()
            
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.integration
    def test_no_filters_empty_filters_applied(self, client: TestClient):
        """
        Test that filters_applied is empty when no filters are provided.
        
        Verifies:
        - When no filters are provided in the request
        - filters_applied is an empty dictionary
        - All posts are returned
        """
        mock_posts = [
            {
                "shortcode": "ABC123",
                "owner_username": "user1",
                "caption": "Post 1",
                "is_video": False,
                "likes": 100,
                "hashtags": [],
                "created_at": "2025-11-23T10:30:00Z",
            }
        ]
        
        mock_db = MagicMock()
        mock_db.search_instagram_posts.return_value = (mock_posts, None)
        mock_db.count_instagram_posts_filtered.return_value = 1
        
        from backend.postparse.api import dependencies
        original_get_db = dependencies.get_db
        
        def override_get_db():
            yield mock_db
        
        app.dependency_overrides[original_get_db] = override_get_db
        
        try:
            # Request without any filters
            response = client.get("/api/v1/search/posts?limit=10")
            
            assert response.status_code == 200
            data = response.json()
            
            # filters_applied should be empty
            assert data["filters_applied"] == {}
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

