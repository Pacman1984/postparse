"""
Integration tests for the FastAPI application.

This module tests the complete API integration including middleware,
exception handlers, and endpoint interactions.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch

from backend.postparse.api.main import app


class TestAPIIntegration:
    """Test API integration."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_cors_headers(self):
        """Test that CORS headers are properly set."""
        # Use GET instead of OPTIONS since the endpoint may not support OPTIONS
        response = self.client.get(
            "/api/v1/telegram/messages",
            headers={"Origin": "http://localhost:3000"}
        )
        
        assert response.status_code == 200
        # CORS headers should be present
        assert "access-control-allow-origin" in response.headers

    def test_request_logging_headers(self):
        """Test that request logging adds headers."""
        response = self.client.get("/health")
        
        assert response.status_code == 200
        # Request ID header should be present
        assert "x-request-id" in response.headers
        assert "x-processing-time" in response.headers

    def test_validation_error_handler(self):
        """Test validation error handler."""
        response = self.client.post("/api/v1/classify/recipe", json={
            "text": "",  # Invalid (empty)
            "classifier_type": "llm"
        })
        
        # FastAPI returns 400 for validation errors
        assert response.status_code == 400

    def test_404_error_handler(self):
        """Test 404 error handling."""
        response = self.client.get("/api/v1/nonexistent")
        
        assert response.status_code == 404
        data = response.json()
        assert "error_code" in data

    def test_openapi_schema_generation(self):
        """Test that OpenAPI schema is generated."""
        response = self.client.get("/openapi.json")
        
        assert response.status_code == 200
        schema = response.json()
        assert "openapi" in schema
        assert "info" in schema
        assert "paths" in schema


class TestEndpointAccessibility:
    """Test that all endpoints are accessible."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_telegram_endpoints_exist(self):
        """Test that Telegram endpoints exist."""
        # Extract endpoint
        response = self.client.post("/api/v1/telegram/extract", json={
            "api_id": "test",
            "api_hash": "0123456789abcdef0123456789abcdef"
        })
        # Should not be 404
        assert response.status_code != 404

    def test_instagram_endpoints_exist(self):
        """Test that Instagram endpoints exist."""
        response = self.client.post("/api/v1/instagram/extract", json={
            "username": "test"
        })
        assert response.status_code != 404

    def test_classify_endpoints_exist(self):
        """Test that classify endpoints exist."""
        response = self.client.get("/api/v1/classify/classifiers")
        assert response.status_code == 200

    def test_search_endpoints_exist(self):
        """Test that search endpoints exist."""
        response = self.client.get("/api/v1/search/posts")
        assert response.status_code == 200


class TestAuthenticationMiddleware:
    """Test authentication middleware."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_public_endpoints_no_auth(self):
        """Test that public endpoints don't require auth."""
        # Health endpoint should be accessible
        response = self.client.get("/health")
        assert response.status_code == 200
        
        # Docs endpoint should be accessible
        response = self.client.get("/docs")
        assert response.status_code == 200

    def test_api_endpoints_when_auth_disabled(self):
        """Test that API endpoints work when auth is disabled (default)."""
        # Auth is disabled by default in development
        response = self.client.get("/api/v1/telegram/messages")
        # Should not be 401 (unauthorized)
        assert response.status_code != 401


class TestPaginationBehavior:
    """Test pagination behavior across endpoints."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_telegram_messages_pagination(self):
        """Test pagination for Telegram messages."""
        response = self.client.get("/api/v1/telegram/messages?limit=5&offset=0")
        
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5
        assert data["offset"] == 0

    def test_instagram_posts_pagination(self):
        """Test pagination for Instagram posts."""
        response = self.client.get("/api/v1/instagram/posts?limit=10&offset=5")
        
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 5

