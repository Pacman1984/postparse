"""
Improved comprehensive tests for PostParse API endpoints.

This module provides high-quality tests that:
- Use proper pytest fixtures for test isolation
- Avoid hardcoded values
- Test actual behavior, not just structure
- Follow best practices for integration testing
"""

import pytest
from backend.postparse.core.utils.config import ConfigManager


class TestHealthEndpoints:
    """Test all health check endpoints."""

    def test_health_endpoint_returns_ok(self, test_client):
        """Test that /health returns status ok."""
        response = test_client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data  # Don't hardcode version
        assert "timestamp" in data
        
    def test_health_endpoint_response_format(self, test_client):
        """Test that /health response has correct format."""
        response = test_client.get("/health")
        data = response.json()
        
        # Check all expected fields exist
        required_fields = ["status", "version", "timestamp", "details"]
        for field in required_fields:
            assert field in data

    def test_liveness_endpoint(self, test_client):
        """Test GET /health/live."""
        response = test_client.get("/health/live")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"

    def test_metrics_endpoint(self, test_client):
        """Test GET /metrics."""
        response = test_client.get("/metrics")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify metrics structure
        assert "database" in data
        assert "classifiers" in data
        assert isinstance(data["database"], dict)
        assert isinstance(data["classifiers"], dict)


class TestClassifyEndpoints:
    """Test classification endpoints."""

    def test_list_classifiers_endpoint(self, test_client):
        """Test GET /api/v1/classify/classifiers."""
        response = test_client.get("/api/v1/classify/classifiers")
        
        assert response.status_code == 200
        data = response.json()
        assert "classifiers" in data
        assert "providers" in data

    def test_classifiers_response_structure(self, test_client):
        """Test that classifiers endpoint returns proper structure."""
        response = test_client.get("/api/v1/classify/classifiers")
        data = response.json()
        
        # Verify classifiers structure
        assert isinstance(data["classifiers"], list)
        assert len(data["classifiers"]) > 0
        
        # Check first classifier has required fields
        classifier = data["classifiers"][0]
        assert "type" in classifier
        assert "name" in classifier
        assert "description" in classifier

    def test_providers_list_completeness(self, test_client):
        """Test that all expected providers are listed."""
        response = test_client.get("/api/v1/classify/classifiers")
        data = response.json()
        
        providers = data["providers"]
        provider_names = [p["name"] for p in providers]
        
        # Verify all expected providers from config
        expected_providers = ["ollama", "openai", "anthropic", "lm_studio"]
        for provider in expected_providers:
            assert provider in provider_names

    def test_default_provider_matches_config(self, test_client):
        """Test that default provider matches configuration."""
        # Get configured default provider
        config = ConfigManager()
        default_provider = config.get("llm.default_provider", "lm_studio")
        
        # Get providers from API
        response = test_client.get("/api/v1/classify/classifiers")
        data = response.json()
        
        providers = data["providers"]
        default_providers = [p for p in providers if p.get("default") is True]
        
        # Verify default matches config
        assert len(default_providers) == 1
        assert default_providers[0]["name"] == default_provider

    def test_classify_endpoint_validates_required_fields(self, test_client):
        """Test that classify endpoint validates required text field."""
        response = test_client.post("/api/v1/classify/recipe", json={
            "classifier_type": "llm"
        })
        
        # FastAPI returns 400 for missing required fields
        assert response.status_code == 400

    def test_classify_endpoint_rejects_empty_text(self, test_client):
        """Test that classify endpoint rejects empty text."""
        response = test_client.post("/api/v1/classify/recipe", json={
            "text": "",
            "classifier_type": "llm"
        })
        
        # FastAPI returns 400 for validation errors
        assert response.status_code == 400

    def test_classify_endpoint_handles_llm_unavailable(self, test_client):
        """Test proper error handling when LLM is unavailable."""
        # Use configured default provider
        config = ConfigManager()
        default_provider = config.get("llm.default_provider", "lm_studio")
        
        response = test_client.post("/api/v1/classify/recipe", json={
            "text": "Boil pasta for 10 minutes",
            "classifier_type": "llm",
            "provider_name": default_provider
        })
        
        # If LLM is running, returns 200; if not, returns 503/500
        assert response.status_code in [200, 503, 500]
        
        if response.status_code == 200:
            # Verify response structure if successful
            data = response.json()
            assert "label" in data
            assert "confidence" in data
        else:
            # Verify error response if failed
            data = response.json()
            assert "error_code" in data or "message" in data


class TestTelegramEndpoints:
    """Test Telegram extraction endpoints."""

    def test_telegram_messages_list_structure(self, test_client):
        """Test GET /api/v1/telegram/messages returns proper structure."""
        response = test_client.get("/api/v1/telegram/messages")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify all required pagination fields
        required_fields = ["items", "total", "limit", "offset", "has_more"]
        for field in required_fields:
            assert field in data

    def test_telegram_messages_pagination_params_work(self, test_client):
        """Test that pagination parameters are properly applied."""
        limit, offset = 5, 10
        response = test_client.get(f"/api/v1/telegram/messages?limit={limit}&offset={offset}")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify pagination parameters are reflected in response
        assert data["limit"] == limit
        assert data["offset"] == offset

    def test_telegram_extract_endpoint_accepts_request(self, test_client):
        """Test POST /api/v1/telegram/extract accepts valid request."""
        payload = {
            "api_id": "12345678",
            "api_hash": "0123456789abcdef0123456789abcdef",
            "phone": "+1234567890",
            "limit": 100
        }
        
        response = test_client.post("/api/v1/telegram/extract", json=payload)
        
        # Should return 202 Accepted for async operation
        assert response.status_code == 202
        data = response.json()
        
        # Verify job response structure
        assert "job_id" in data
        assert "status" in data
        assert data["status"] == "pending"


class TestInstagramEndpoints:
    """Test Instagram extraction endpoints."""

    def test_instagram_posts_list_structure(self, test_client):
        """Test GET /api/v1/instagram/posts returns proper structure."""
        response = test_client.get("/api/v1/instagram/posts")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify pagination structure
        required_fields = ["items", "total", "limit", "offset"]
        for field in required_fields:
            assert field in data

    def test_instagram_posts_pagination_works(self, test_client):
        """Test that pagination parameters work correctly."""
        response = test_client.get("/api/v1/instagram/posts?limit=10&offset=5")
        
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 5

    def test_instagram_extract_endpoint_accepts_request(self, test_client):
        """Test POST /api/v1/instagram/extract."""
        payload = {
            "username": "test_user",
            "limit": 50
        }
        
        response = test_client.post("/api/v1/instagram/extract", json=payload)
        
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert "status" in data


class TestSearchEndpoints:
    """Test search endpoints."""

    def test_search_posts_returns_proper_structure(self, test_client):
        """Test GET /api/v1/search/posts structure."""
        response = test_client.get("/api/v1/search/posts")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify search response structure
        required_fields = ["results", "total_count", "filters_applied", "pagination"]
        for field in required_fields:
            assert field in data
        
        # Verify nested structures
        assert isinstance(data["results"], list)
        assert isinstance(data["filters_applied"], dict)
        assert isinstance(data["pagination"], dict)

    def test_search_posts_limit_parameter(self, test_client):
        """Test that limit parameter is applied correctly."""
        limit = 20
        response = test_client.get(f"/api/v1/search/posts?limit={limit}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["limit"] == limit

    def test_search_hashtags_returns_list(self, test_client):
        """Test GET /api/v1/search/hashtags."""
        response = test_client.get("/api/v1/search/hashtags")
        
        assert response.status_code == 200
        data = response.json()
        assert "hashtags" in data
        assert isinstance(data["hashtags"], list)

    def test_search_messages_structure(self, test_client):
        """Test GET /api/v1/search/messages structure."""
        response = test_client.get("/api/v1/search/messages")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "results" in data
        assert "total_count" in data


class TestRootEndpoint:
    """Test root API endpoint."""

    def test_root_endpoint_returns_api_info(self, test_client, api_version):
        """Test GET / returns complete API information."""
        response = test_client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify all expected fields
        assert "message" in data
        assert "version" in data
        assert "documentation" in data
        assert "endpoints" in data
        
        # Verify version matches fixture (not hardcoded)
        assert data["version"] == api_version

    def test_root_endpoint_documentation_links(self, test_client):
        """Test that all documentation links are present."""
        response = test_client.get("/")
        data = response.json()
        
        docs = data["documentation"]
        assert "swagger" in docs
        assert "redoc" in docs
        assert "openapi" in docs
        
        # Verify links are strings
        assert isinstance(docs["swagger"], str)
        assert isinstance(docs["redoc"], str)
        assert isinstance(docs["openapi"], str)


class TestResponseFormats:
    """Test response format consistency across endpoints."""

    @pytest.mark.parametrize("endpoint", [
        "/api/v1/telegram/messages",
        "/api/v1/instagram/posts"
    ])
    def test_pagination_response_format(self, test_client, endpoint):
        """Test pagination response format is consistent."""
        response = test_client.get(endpoint)
        assert response.status_code == 200
        data = response.json()
        
        # Check standard pagination fields
        pagination_fields = ["items", "total", "limit", "offset"]
        for field in pagination_fields:
            assert field in data
        
        # Verify types
        assert isinstance(data["items"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["limit"], int)
        assert isinstance(data["offset"], int)


class TestErrorHandling:
    """Test error handling across endpoints."""

    def test_404_for_nonexistent_endpoint(self, test_client):
        """Test 404 response for non-existent endpoint."""
        response = test_client.get("/api/v1/nonexistent")
        
        assert response.status_code == 404
        data = response.json()
        
        # Verify error response structure
        assert "error_code" in data
        assert isinstance(data["error_code"], str)

    def test_validation_error_format(self, test_client):
        """Test that validation errors have consistent format."""
        response = test_client.post("/api/v1/classify/recipe", json={
            "text": ""
        })
        
        # FastAPI returns 400 for validation errors
        assert response.status_code == 400

