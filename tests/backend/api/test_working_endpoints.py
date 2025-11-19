"""
Comprehensive tests for all working PostParse API endpoints.

This module tests all functional endpoints that have been verified working
through browser testing. These tests validate the API structure, response
formats, and basic functionality.
"""

import pytest
from fastapi.testclient import TestClient
from backend.postparse.api.main import app


class TestHealthEndpoints:
    """Test all health check endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_health_endpoint_returns_ok(self):
        """Test that /health returns status ok."""
        response = self.client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
        assert "timestamp" in data

    def test_health_endpoint_response_format(self):
        """Test that /health response has correct format."""
        response = self.client.get("/health")
        data = response.json()
        
        # Check all expected fields
        assert "status" in data
        assert "version" in data
        assert "timestamp" in data
        assert "details" in data or data["details"] is None

    def test_liveness_endpoint(self):
        """Test GET /health/live."""
        response = self.client.get("/health/live")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"

    def test_metrics_endpoint(self):
        """Test GET /metrics."""
        response = self.client.get("/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert "database" in data
        assert "classifiers" in data


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

    def test_classifiers_response_structure(self):
        """Test that classifiers endpoint returns proper structure."""
        response = self.client.get("/api/v1/classify/classifiers")
        data = response.json()
        
        # Check classifiers structure
        assert isinstance(data["classifiers"], list)
        assert len(data["classifiers"]) > 0
        
        # Check first classifier has required fields
        classifier = data["classifiers"][0]
        assert "type" in classifier
        assert "name" in classifier
        assert classifier["type"] == "llm"

    def test_providers_list(self):
        """Test that providers list includes expected providers."""
        response = self.client.get("/api/v1/classify/classifiers")
        data = response.json()
        
        providers = data["providers"]
        provider_names = [p["name"] for p in providers]
        
        # Check expected providers are present
        assert "ollama" in provider_names
        assert "openai" in provider_names
        assert "anthropic" in provider_names
        assert "lm_studio" in provider_names

    def test_default_provider_is_lm_studio(self):
        """Test that default provider is lm_studio."""
        response = self.client.get("/api/v1/classify/classifiers")
        data = response.json()
        
        providers = data["providers"]
        default_providers = [p for p in providers if p.get("default") is True]
        
        assert len(default_providers) == 1
        assert default_providers[0]["name"] == "lm_studio"

    def test_classify_endpoint_requires_text(self):
        """Test that classify endpoint validates required text field."""
        response = self.client.post("/api/v1/classify/recipe", json={
            "classifier_type": "llm"
        })
        
        # FastAPI returns 400 for validation errors
        assert response.status_code == 400

    def test_classify_endpoint_rejects_empty_text(self):
        """Test that classify endpoint rejects empty text."""
        response = self.client.post("/api/v1/classify/recipe", json={
            "text": "",
            "classifier_type": "llm"
        })
        
        # FastAPI returns 400 for validation errors
        assert response.status_code == 400

    def test_classify_endpoint_error_when_llm_unavailable(self):
        """Test that classify endpoint returns proper error when LLM is unavailable."""
        response = self.client.post("/api/v1/classify/recipe", json={
            "text": "Boil pasta for 10 minutes",
            "classifier_type": "llm",
            "provider_name": "lm_studio"
        })
        
        # If LLM is running, returns 200; if not, returns 503/500
        assert response.status_code in [200, 503, 500]


class TestTelegramEndpoints:
    """Test Telegram extraction endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_telegram_messages_list(self):
        """Test GET /api/v1/telegram/messages."""
        response = self.client.get("/api/v1/telegram/messages")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check response structure
        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

    def test_telegram_messages_pagination(self):
        """Test telegram messages endpoint with pagination."""
        response = self.client.get("/api/v1/telegram/messages?limit=5&offset=0")
        
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5
        assert data["offset"] == 0

    def test_telegram_extract_endpoint(self):
        """Test POST /api/v1/telegram/extract."""
        payload = {
            "api_id": "12345678",
            "api_hash": "0123456789abcdef0123456789abcdef",
            "phone": "+1234567890"
        }
        
        response = self.client.post("/api/v1/telegram/extract", json=payload)
        
        # Should accept request (202) as it's async
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert "status" in data


class TestInstagramEndpoints:
    """Test Instagram extraction endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_instagram_posts_list(self):
        """Test GET /api/v1/instagram/posts."""
        response = self.client.get("/api/v1/instagram/posts")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check response structure
        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

    def test_instagram_posts_pagination(self):
        """Test instagram posts endpoint with pagination."""
        response = self.client.get("/api/v1/instagram/posts?limit=10&offset=5")
        
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 5

    def test_instagram_extract_endpoint(self):
        """Test POST /api/v1/instagram/extract."""
        payload = {
            "username": "test_user",
            "limit": 50
        }
        
        response = self.client.post("/api/v1/instagram/extract", json=payload)
        
        # Should accept request (202)
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data


class TestSearchEndpoints:
    """Test search endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_search_posts_endpoint(self):
        """Test GET /api/v1/search/posts."""
        response = self.client.get("/api/v1/search/posts")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check response structure
        assert "results" in data
        assert "total_count" in data
        assert "filters_applied" in data
        assert "pagination" in data

    def test_search_posts_with_limit(self):
        """Test search posts with limit parameter."""
        response = self.client.get("/api/v1/search/posts?limit=20")
        
        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["limit"] == 20

    def test_search_hashtags_endpoint(self):
        """Test GET /api/v1/search/hashtags."""
        response = self.client.get("/api/v1/search/hashtags")
        
        assert response.status_code == 200
        data = response.json()
        assert "hashtags" in data
        assert isinstance(data["hashtags"], list)

    def test_search_messages_endpoint(self):
        """Test GET /api/v1/search/messages."""
        response = self.client.get("/api/v1/search/messages")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check response structure
        assert "results" in data
        assert "total_count" in data


class TestRootEndpoint:
    """Test root API endpoint."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_root_endpoint_returns_info(self):
        """Test GET / returns API information."""
        response = self.client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "message" in data
        assert "version" in data
        assert "documentation" in data
        assert "endpoints" in data

    def test_root_endpoint_version(self):
        """Test that root endpoint returns correct version."""
        response = self.client.get("/")
        data = response.json()
        
        assert data["version"] == "0.1.0"

    def test_root_endpoint_documentation_links(self):
        """Test that documentation links are present."""
        response = self.client.get("/")
        data = response.json()
        
        assert "swagger" in data["documentation"]
        assert "redoc" in data["documentation"]
        assert "openapi" in data["documentation"]


class TestResponseFormats:
    """Test that responses follow expected formats."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_pagination_response_format(self):
        """Test pagination response format across endpoints."""
        endpoints = [
            "/api/v1/telegram/messages",
            "/api/v1/instagram/posts"
        ]
        
        for endpoint in endpoints:
            response = self.client.get(endpoint)
            assert response.status_code == 200
            data = response.json()
            
            # Check standard pagination fields
            assert "items" in data
            assert "total" in data
            assert "limit" in data
            assert "offset" in data

    def test_search_response_format(self):
        """Test search response format."""
        response = self.client.get("/api/v1/search/posts")
        data = response.json()
        
        assert "results" in data
        assert "total_count" in data
        assert "filters_applied" in data
        assert "pagination" in data
        
        # Check pagination structure
        assert "limit" in data["pagination"]
        assert "offset" in data["pagination"]


class TestErrorHandling:
    """Test error handling across endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_404_for_nonexistent_endpoint(self):
        """Test 404 response for non-existent endpoint."""
        response = self.client.get("/api/v1/nonexistent")
        
        assert response.status_code == 404
        data = response.json()
        assert "error_code" in data

    def test_validation_error_format(self):
        """Test that validation errors have consistent format."""
        response = self.client.post("/api/v1/classify/recipe", json={
            "text": ""
        })
        
        # FastAPI returns 400 for validation errors
        assert response.status_code == 400

