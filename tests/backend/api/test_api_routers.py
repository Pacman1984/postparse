"""
Tests for API routers.

This module tests the FastAPI endpoints for Telegram, Instagram, classification,
search, and health.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock

from backend.postparse.api.main import app


class TestHealthEndpoints:
    """Test health check endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_health_endpoint(self):
        """Test basic health check."""
        response = self.client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
        assert "timestamp" in data

    def test_liveness_endpoint(self):
        """Test liveness probe."""
        response = self.client.get("/health/live")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"

    def test_metrics_endpoint(self):
        """Test metrics endpoint."""
        response = self.client.get("/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert "database" in data
        assert "classifiers" in data


class TestTelegramEndpoints:
    """Test Telegram extraction endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_telegram_extract_endpoint(self):
        """Test POST /api/v1/telegram/extract."""
        payload = {
            "api_id": "12345678",
            "api_hash": "0123456789abcdef0123456789abcdef",
            "phone": "+1234567890",
            "limit": 100
        }
        
        response = self.client.post("/api/v1/telegram/extract", json=payload)
        
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"

    def test_telegram_messages_endpoint(self):
        """Test GET /api/v1/telegram/messages."""
        response = self.client.get("/api/v1/telegram/messages?limit=10")
        
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)


class TestInstagramEndpoints:
    """Test Instagram extraction endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_instagram_extract_endpoint(self):
        """Test POST /api/v1/instagram/extract."""
        payload = {
            "username": "test_user",
            "password": "test_password",
            "limit": 50,
            "use_api": False
        }
        
        response = self.client.post("/api/v1/instagram/extract", json=payload)
        
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"

    def test_instagram_posts_endpoint(self):
        """Test GET /api/v1/instagram/posts."""
        response = self.client.get("/api/v1/instagram/posts?limit=10")
        
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data


class TestSearchEndpoints:
    """Test search endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_search_posts_endpoint(self):
        """Test GET /api/v1/search/posts."""
        response = self.client.get("/api/v1/search/posts?limit=10")
        
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "total_count" in data

    def test_search_hashtags_endpoint(self):
        """Test GET /api/v1/search/hashtags."""
        response = self.client.get("/api/v1/search/hashtags?limit=50")
        
        assert response.status_code == 200
        data = response.json()
        assert "hashtags" in data
        assert isinstance(data["hashtags"], list)


class TestClassifyEndpoints:
    """Test classification endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_list_classifiers_endpoint(self):
        """Test GET /api/v1/classify/classifiers."""
        response = self.client.get("/api/v1/classify/classifiers")
        
        assert response.status_code == 200
        data = response.json()
        assert "classifiers" in data
        assert "providers" in data

    @patch('backend.postparse.api.routers.classify.get_recipe_llm_classifier')
    def test_classify_recipe_endpoint_validation(self, mock_classifier):
        """Test classify endpoint request validation."""
        # Invalid request (empty text)
        response = self.client.post("/api/v1/classify/recipe", json={
            "text": "",
            "classifier_type": "llm"
        })
        
        # FastAPI returns 400 for validation errors
        assert response.status_code == 400


class TestRootEndpoint:
    """Test root endpoint."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_root_endpoint(self):
        """Test GET /."""
        response = self.client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data
        assert "documentation" in data
        assert "endpoints" in data

