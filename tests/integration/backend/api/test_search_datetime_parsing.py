"""
Integration tests for datetime parsing in search endpoints.

This module tests that the search endpoints properly parse datetime strings
from database results and return valid datetime objects in responses.
"""

import pytest
from datetime import datetime
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


class TestSearchDatetimeParsing:
    """Integration tests for datetime parsing in search endpoints."""

    @pytest.mark.integration
    def test_search_posts_with_valid_datetime_strings(self, client: TestClient):
        """
        Test that search posts endpoint parses datetime strings from database.
        
        Verifies:
        - Endpoint returns 200 OK
        - Results contain parsed datetime objects
        - ISO format timestamps are correctly parsed
        """
        # Mock database to return posts with datetime strings
        mock_posts = [
            {
                "shortcode": "ABC123",
                "owner_username": "test_user",
                "caption": "Test caption",
                "is_video": False,
                "likes": 100,
                "hashtags": ["test"],
                "created_at": "2025-11-23T10:30:00Z",  # ISO format string from DB
            },
            {
                "shortcode": "XYZ789",
                "owner_username": "test_user2",
                "caption": "Another post",
                "is_video": True,
                "likes": 50,
                "hashtags": ["test"],
                "created_at": "2025-11-22T15:45:00+00:00",  # Alternative format
            }
        ]
        
        with patch("backend.postparse.api.routers.search.Depends") as mock_depends:
            # Mock database dependency
            mock_db = MagicMock()
            # Use new search_instagram_posts method that returns (results, cursor) tuple
            mock_db.search_instagram_posts.return_value = (mock_posts, None)
            mock_db.count_instagram_posts_filtered.return_value = len(mock_posts)
            
            # Setup dependency override
            from backend.postparse.api import dependencies
            original_get_db = dependencies.get_db
            
            def override_get_db():
                yield mock_db
            
            app.dependency_overrides[original_get_db] = override_get_db
            
            try:
                # Make request to search endpoint
                response = client.get("/api/v1/search/posts?limit=10")
                
                assert response.status_code == 200
                data = response.json()
                
                # Verify results exist
                assert "results" in data
                assert len(data["results"]) == 2
                
                # Verify first result has parsed datetime
                first_result = data["results"][0]
                assert first_result["shortcode"] == "ABC123"
                assert first_result["created_at"] is not None
                # Datetime should be in ISO format string after serialization
                assert "2025-11-23T10:30:00" in first_result["created_at"]
                
                # Verify second result
                second_result = data["results"][1]
                assert second_result["shortcode"] == "XYZ789"
                assert second_result["created_at"] is not None
            finally:
                app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_posts_with_invalid_datetime_strings(self, client: TestClient):
        """
        Test that search posts endpoint handles invalid datetime strings gracefully.
        
        Verifies:
        - Invalid datetime strings are converted to None
        - Endpoint doesn't crash with malformed data
        - Other fields are still correctly populated
        """
        mock_posts = [
            {
                "shortcode": "ABC123",
                "owner_username": "test_user",
                "caption": "Test caption",
                "is_video": False,
                "likes": 100,
                "hashtags": ["test"],
                "created_at": "not-a-valid-datetime",  # Invalid format
            },
            {
                "shortcode": "DEF456",
                "owner_username": "test_user2",
                "caption": "Another post",
                "is_video": False,
                "likes": 75,
                "hashtags": ["test"],
                "created_at": "",  # Empty string
            }
        ]
        
        with patch("backend.postparse.api.routers.search.Depends") as mock_depends:
            mock_db = MagicMock()
            mock_db.search_instagram_posts.return_value = (mock_posts, None)
            mock_db.count_instagram_posts_filtered.return_value = len(mock_posts)
            
            from backend.postparse.api import dependencies
            original_get_db = dependencies.get_db
            
            def override_get_db():
                yield mock_db
            
            app.dependency_overrides[original_get_db] = override_get_db
            
            try:
                response = client.get("/api/v1/search/posts?limit=10")
                
                assert response.status_code == 200
                data = response.json()
                
                # Verify results exist
                assert len(data["results"]) == 2
                
                # Both should have None for created_at due to invalid formats
                assert data["results"][0]["created_at"] is None
                assert data["results"][1]["created_at"] is None
                
                # But other fields should be populated
                assert data["results"][0]["shortcode"] == "ABC123"
                assert data["results"][1]["shortcode"] == "DEF456"
            finally:
                app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_messages_with_valid_datetime_strings(self, client: TestClient):
        """
        Test that search messages endpoint parses datetime strings from database.
        
        Verifies:
        - Endpoint returns 200 OK
        - Results contain parsed datetime objects
        - ISO format timestamps are correctly parsed
        """
        mock_messages = [
            {
                "message_id": 12345,
                "channel_username": "test_channel",
                "content": "Test message",
                "content_type": "text",
                "hashtags": ["test"],
                "created_at": "2025-11-23T08:00:00Z",
            }
        ]
        
        with patch("backend.postparse.api.routers.search.Depends") as mock_depends:
            mock_db = MagicMock()
            mock_db.search_telegram_messages.return_value = (mock_messages, None)
            mock_db.count_telegram_messages_filtered.return_value = len(mock_messages)
            
            from backend.postparse.api import dependencies
            original_get_db = dependencies.get_db
            
            def override_get_db():
                yield mock_db
            
            app.dependency_overrides[original_get_db] = override_get_db
            
            try:
                response = client.get("/api/v1/search/messages?limit=10")
                
                assert response.status_code == 200
                data = response.json()
                
                assert len(data["results"]) == 1
                assert data["results"][0]["message_id"] == 12345
                assert data["results"][0]["created_at"] is not None
                assert "2025-11-23T08:00:00" in data["results"][0]["created_at"]
            finally:
                app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_search_messages_with_none_datetime(self, client: TestClient):
        """
        Test that search messages endpoint handles None datetime values.
        
        Verifies:
        - None datetime values are preserved
        - Endpoint doesn't crash with missing timestamps
        """
        mock_messages = [
            {
                "message_id": 54321,
                "channel_username": "test_channel",
                "content": "Message without timestamp",
                "content_type": "text",
                "hashtags": [],
                "created_at": None,  # Database may return None for missing data
            }
        ]
        
        with patch("backend.postparse.api.routers.search.Depends") as mock_depends:
            mock_db = MagicMock()
            mock_db.search_telegram_messages.return_value = (mock_messages, None)
            mock_db.count_telegram_messages_filtered.return_value = len(mock_messages)
            
            from backend.postparse.api import dependencies
            original_get_db = dependencies.get_db
            
            def override_get_db():
                yield mock_db
            
            app.dependency_overrides[original_get_db] = override_get_db
            
            try:
                response = client.get("/api/v1/search/messages?limit=10")
                
                assert response.status_code == 200
                data = response.json()
                
                assert len(data["results"]) == 1
                assert data["results"][0]["created_at"] is None
                assert data["results"][0]["message_id"] == 54321
            finally:
                app.dependency_overrides.clear()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
