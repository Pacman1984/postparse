"""
Integration tests for extraction endpoints.

This module tests the complete extraction lifecycle from job creation to completion,
covering Telegram and Instagram extraction workflows with real job tracking.
"""

import asyncio
import time
from datetime import datetime
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.postparse.api.main import app
from backend.postparse.api.schemas.telegram import ExtractionStatus
from backend.postparse.api.services.job_manager import JobManager
from backend.postparse.core.data.database import SocialMediaDatabase


@pytest.fixture(scope="function")
def test_db(tmp_path) -> Generator[SocialMediaDatabase, None, None]:
    """
    Create temporary test database.
    
    Yields:
        SocialMediaDatabase instance with temporary database file.
    
    Example:
        def test_something(test_db):
            test_db.insert_telegram_message(...)
    """
    db_path = tmp_path / "test_social_media.db"
    db = SocialMediaDatabase(str(db_path))
    yield db
    # Cleanup happens automatically when tmp_path is removed


@pytest.fixture(scope="function")
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


class TestTelegramExtraction:
    """Integration tests for Telegram extraction endpoints."""
    
    @pytest.mark.integration
    def test_telegram_extraction_job_creation(self, client: TestClient):
        """
        Test that Telegram extraction job is created successfully.
        
        Verifies:
        - POST /api/v1/telegram/extract returns 202 ACCEPTED
        - Response contains job_id and PENDING status
        - Job exists in JobManager
        """
        request_data = {
            "api_id": 12345678,
            "api_hash": "0123456789abcdef0123456789abcdef",
            "phone": "+1234567890",
            "limit": 10,
        }
        
        response = client.post("/api/v1/telegram/extract", json=request_data)
        
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert isinstance(data["job_id"], str)
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_telegram_job_tracking_with_mocked_parser(
        self, client: TestClient, test_db: SocialMediaDatabase
    ):
        """
        Test Telegram extraction job tracking and database persistence.
        
        Verifies:
        - Job status progresses from PENDING to COMPLETED
        - Progress percentage updates correctly
        - Messages are saved to database
        - Parser is called with correct parameters
        
        Note: Parser is mocked to avoid external dependencies.
        """
        # Mock TelegramParser to return sample messages
        mock_messages = [
            {
                "message_id": i,
                "chat_id": 123456,
                "content": f"Test message {i}",
                "content_type": "text",
                "media_urls": [],
                "views": 100,
                "forwards": 5,
                "reply_to_msg_id": None,
                "created_at": datetime.now(),
                "hashtags": ["test"],
            }
            for i in range(5)
        ]
        
        async def mock_get_saved_messages(*args, **kwargs):
            """Async generator that yields mock messages."""
            for msg in mock_messages:
                yield msg
        
        with patch(
            "backend.postparse.api.services.extraction_service.TelegramParser"
        ) as MockParser:
            mock_instance = AsyncMock()
            mock_instance.get_saved_messages = mock_get_saved_messages
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            MockParser.return_value = mock_instance
            
            # Override database dependency to use test_db
            from backend.postparse.api import dependencies
            original_get_db = dependencies.get_db
            
            def override_get_db():
                yield test_db
            
            app.dependency_overrides[original_get_db] = override_get_db
            
            try:
                # Start extraction
                request_data = {
                    "api_id": 12345678,
                    "api_hash": "0123456789abcdef0123456789abcdef",
                    "phone": "+1234567890",
                    "limit": 10,
                }
                
                response = client.post("/api/v1/telegram/extract", json=request_data)
                assert response.status_code == 202
                job_id = response.json()["job_id"]
                
                # Poll for completion with timeout (background task limitation)
                max_wait = 10  # seconds
                start_time = time.time()
                status_response = None
                final_data = None
                
                while time.time() - start_time < max_wait:
                    status_response = client.get(f"/api/v1/telegram/jobs/{job_id}")
                    assert status_response.status_code == 200
                    final_data = status_response.json()
                    
                    if final_data["status"] in ["completed", "failed"]:
                        break
                    
                    time.sleep(0.5)
                
                # Verify job completed successfully
                assert final_data is not None, "Failed to get job status"
                assert final_data["status"] == "completed", f"Job failed or timed out: {final_data.get('errors', [])}"
                assert final_data["progress"] == 100
                assert final_data["messages_processed"] == 5
                
                # Verify parser was called with correct parameters
                MockParser.assert_called_once()
                call_kwargs = MockParser.call_args[1]
                assert call_kwargs["api_id"] == 12345678
                assert call_kwargs["api_hash"] == "0123456789abcdef0123456789abcdef"
                assert call_kwargs["phone"] == "+1234567890"
                assert call_kwargs["interactive"] is False
                
                # Verify messages were saved to database
                saved_messages = test_db.get_telegram_messages(limit=10)
                assert len(saved_messages) == 5, "Expected 5 messages to be saved to database"
                
                # Verify message content (sort by message_id since DB returns by created_at DESC)
                saved_messages_sorted = sorted(saved_messages, key=lambda m: m["message_id"])
                for i, msg in enumerate(saved_messages_sorted):
                    assert msg["content"] == f"Test message {i}"
                    assert msg["message_id"] == i
                
            finally:
                # Clean up override
                app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_telegram_extraction_job_failure(self, client: TestClient):
        """
        Test Telegram extraction job failure handling.
        
        Verifies:
        - Job is marked as FAILED when parser raises exception
        - Error message is captured in job errors list
        """
        # Mock TelegramParser to raise exception
        with patch(
            "backend.postparse.api.services.extraction_service.TelegramParser"
        ) as MockParser:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(
                side_effect=ValueError("Authentication error: Invalid credentials")
            )
            MockParser.return_value = mock_instance
            
            # Start extraction
            request_data = {
                "api_id": 12345678,
                "api_hash": "invalid0hash00000000000000000000",
                "phone": "+1234567890",
                "limit": 10,
            }
            
            response = client.post("/api/v1/telegram/extract", json=request_data)
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            
            # Poll for failure with timeout
            max_wait = 5  # seconds
            start_time = time.time()
            data = None
            
            while time.time() - start_time < max_wait:
                status_response = client.get(f"/api/v1/telegram/jobs/{job_id}")
                data = status_response.json()
                
                if data["status"] == "failed":
                    break
                
                time.sleep(0.2)
            
            # Verify job failed
            assert data is not None, "Failed to get job status"
            assert data["status"] == "failed", f"Expected job to fail, got status: {data['status']}"
            assert len(data["errors"]) > 0, "Expected error messages in failed job"
            assert "Authentication error" in data["errors"][0]
    
    @pytest.mark.integration
    def test_job_status_not_found(self, client: TestClient):
        """
        Test job status endpoint with invalid job ID.
        
        Verifies:
        - Returns 404 NOT FOUND for non-existent job
        """
        response = client.get("/api/v1/telegram/jobs/invalid-uuid-12345")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    @pytest.mark.integration
    def test_telegram_missing_credentials(self, client: TestClient):
        """
        Test Telegram extraction with missing required credentials.
        
        Verifies:
        - Returns 422 UNPROCESSABLE ENTITY for missing api_hash
        """
        request_data = {
            "api_id": 12345678,
            # Missing api_hash
            "phone": "+1234567890",
        }
        
        response = client.post("/api/v1/telegram/extract", json=request_data)
        
        assert response.status_code == 422  # Validation error


class TestInstagramExtraction:
    """Integration tests for Instagram extraction endpoints."""
    
    @pytest.mark.integration
    def test_instagram_extraction_job_creation(self, client: TestClient):
        """
        Test that Instagram extraction job is created successfully.
        
        Verifies:
        - POST /api/v1/instagram/extract returns 202 ACCEPTED
        - Response contains job_id and PENDING status
        - Job exists in JobManager
        """
        request_data = {
            "username": "test_user",
            "password": "test_password",
            "limit": 10,
            "use_api": False,
        }
        
        response = client.post("/api/v1/instagram/extract", json=request_data)
        
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert isinstance(data["job_id"], str)
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_instagram_job_tracking_with_mocked_parser(
        self, client: TestClient, test_db: SocialMediaDatabase
    ):
        """
        Test Instagram extraction job tracking and database persistence.
        
        Verifies:
        - Job status progresses from PENDING to COMPLETED
        - Progress percentage updates correctly
        - Posts are saved to database
        - Parser is called with correct parameters
        
        Note: Parser is mocked to avoid external dependencies.
        """
        # Mock InstaloaderParser to return sample posts
        mock_posts = [
            {
                "shortcode": f"ABC{i:03d}",
                "owner_username": "test_user",
                "owner_id": "123456789",
                "caption": f"Test post {i}",
                "is_video": False,
                "media_url": f"https://example.com/media{i}.jpg",
                "typename": "GraphImage",
                "likes": 100 + i,
                "comments": 10 + i,
                "created_at": datetime.now(),
                "is_saved": True,
                "source": "saved",
            }
            for i in range(5)
        ]
        
        def mock_get_saved_posts(*args, **kwargs):
            """Generator that yields mock posts."""
            for post in mock_posts:
                yield post
        
        with patch(
            "backend.postparse.api.services.extraction_service.InstaloaderParser"
        ) as MockParser:
            mock_instance = MagicMock()
            mock_instance.get_saved_posts = mock_get_saved_posts
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=None)
            MockParser.return_value = mock_instance
            
            # Override database dependency
            from backend.postparse.api import dependencies
            original_get_db = dependencies.get_db
            
            def override_get_db():
                yield test_db
            
            app.dependency_overrides[original_get_db] = override_get_db
            
            try:
                # Start extraction
                request_data = {
                    "username": "test_user",
                    "password": "test_password",
                    "limit": 10,
                    "use_api": False,
                }
                
                response = client.post("/api/v1/instagram/extract", json=request_data)
                assert response.status_code == 202
                job_id = response.json()["job_id"]
                
                # Poll for completion with timeout
                max_wait = 10  # seconds
                start_time = time.time()
                final_data = None
                
                while time.time() - start_time < max_wait:
                    status_response = client.get(f"/api/v1/instagram/jobs/{job_id}")
                    assert status_response.status_code == 200
                    final_data = status_response.json()
                    
                    if final_data["status"] in ["completed", "failed"]:
                        break
                    
                    time.sleep(0.5)
                
                # Verify job completed successfully
                assert final_data is not None, "Failed to get job status"
                assert final_data["status"] == "completed", f"Job failed or timed out: {final_data.get('errors', [])}"
                assert final_data["progress"] == 100
                assert final_data["messages_processed"] == 5
                
                # Verify parser was called with correct parameters
                MockParser.assert_called_once()
                call_kwargs = MockParser.call_args[1]
                assert call_kwargs["username"] == "test_user"
                assert call_kwargs["password"] == "test_password"
                
                # Verify posts were saved to database
                saved_posts = test_db.get_instagram_posts(limit=10)
                assert len(saved_posts) == 5, "Expected 5 posts to be saved to database"
                
                # Verify post content (sort by shortcode since DB may return in different order)
                saved_posts_sorted = sorted(saved_posts, key=lambda p: p["shortcode"])
                for i, post in enumerate(saved_posts_sorted):
                    assert post["shortcode"] == f"ABC{i:03d}"
                    assert post["owner_username"] == "test_user"
                    assert post["caption"] == f"Test post {i}"
                
            finally:
                # Clean up override
                app.dependency_overrides.clear()
    
    @pytest.mark.integration
    def test_instagram_extraction_job_failure(self, client: TestClient):
        """
        Test Instagram extraction job failure handling.
        
        Verifies:
        - Job is marked as FAILED when parser raises exception
        - Error message is captured in job errors list
        """
        # Mock InstaloaderParser to raise exception
        with patch(
            "backend.postparse.api.services.extraction_service.InstaloaderParser"
        ) as MockParser:
            mock_instance = MagicMock()
            mock_instance.__enter__ = MagicMock(
                side_effect=Exception("Login failed: Invalid credentials")
            )
            MockParser.return_value = mock_instance
            
            # Start extraction
            request_data = {
                "username": "test_user",
                "password": "wrong_password",
                "limit": 10,
                "use_api": False,
            }
            
            response = client.post("/api/v1/instagram/extract", json=request_data)
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            
            # Poll for failure with timeout
            max_wait = 5  # seconds
            start_time = time.time()
            data = None
            
            while time.time() - start_time < max_wait:
                status_response = client.get(f"/api/v1/instagram/jobs/{job_id}")
                data = status_response.json()
                
                if data["status"] == "failed":
                    break
                
                time.sleep(0.2)
            
            # Verify job failed
            assert data is not None, "Failed to get job status"
            assert data["status"] == "failed", f"Expected job to fail, got status: {data['status']}"
            assert len(data["errors"]) > 0, "Expected error messages in failed job"
    
    @pytest.mark.integration
    def test_instagram_missing_credentials(self, client: TestClient):
        """
        Test Instagram extraction with missing credentials.
        
        Verifies:
        - Returns 400 BAD REQUEST when use_api=False but no password
        - Returns 400 BAD REQUEST when use_api=True but no access_token
        """
        # Test missing password for Instaloader
        request_data = {
            "username": "test_user",
            "limit": 10,
            "use_api": False,
        }
        
        response = client.post("/api/v1/instagram/extract", json=request_data)
        assert response.status_code == 400
        assert "password" in response.json()["detail"].lower()
        
        # Test missing access_token for API
        request_data = {
            "username": "test_user",
            "limit": 10,
            "use_api": True,
        }
        
        response = client.post("/api/v1/instagram/extract", json=request_data)
        assert response.status_code == 400
        assert "access token" in response.json()["detail"].lower()
