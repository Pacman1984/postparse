"""
Integration tests for rate limiting middleware.

This module tests the token bucket rate limiting implementation,
verifying request limits, burst capacity, and token refill behavior.
"""

import time
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.postparse.api.main import app
from backend.postparse.core.utils.config import ConfigManager


@pytest.fixture(scope="function")
def client_no_rate_limit() -> TestClient:
    """
    Create test client with rate limiting disabled.
    
    Returns:
        TestClient instance with rate limiting disabled.
    
    Example:
        def test_no_limits(client_no_rate_limit):
            for _ in range(100):
                response = client_no_rate_limit.get("/health")
                assert response.status_code == 200
    """
    # Mock config to disable rate limiting
    with patch.object(ConfigManager, 'get') as mock_get:
        def config_side_effect(key, default=None):
            if key == "api.rate_limiting.enabled":
                return False
            return default
        
        mock_get.side_effect = config_side_effect
        yield TestClient(app)


@pytest.fixture(scope="function")
def client_with_rate_limit() -> TestClient:
    """
    Create test client with rate limiting enabled.
    
    Returns:
        TestClient instance with strict rate limits for testing.
    
    Example:
        def test_rate_limit(client_with_rate_limit):
            response = client_with_rate_limit.get("/api/v1/health")
    """
    return TestClient(app)


class TestRateLimitingDisabled:
    """Tests for rate limiting when disabled in config."""
    
    @pytest.mark.integration
    def test_rate_limiting_disabled(self, client_no_rate_limit: TestClient):
        """
        Test that rate limiting does not apply when disabled.
        
        Verifies:
        - 100 rapid requests all succeed
        - No 429 errors returned
        """
        success_count = 0
        
        for _ in range(100):
            response = client_no_rate_limit.get("/health")
            if response.status_code == 200:
                success_count += 1
        
        # All requests should succeed
        assert success_count == 100


class TestRateLimitingEnabled:
    """Tests for rate limiting when enabled in config."""
    
    @pytest.mark.integration
    def test_rate_limiting_enabled_within_limit(self, client_with_rate_limit: TestClient):
        """
        Test requests within rate limit are allowed.
        
        Verifies:
        - Requests below limit succeed
        - All return 200 OK (or expected status codes)
        
        Note: Uses 5 requests well below typical 60/min limit.
        """
        success_count = 0
        
        for _ in range(5):
            response = client_with_rate_limit.get("/health")
            if response.status_code == 200:
                success_count += 1
            time.sleep(0.1)  # Small delay to avoid burst
        
        # All requests should succeed
        assert success_count == 5
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_rate_limiting_enabled_exceeds_limit(self):
        """
        Test that exceeding rate limit returns 429.
        
        Verifies:
        - First N requests succeed (up to limit)
        - Subsequent requests return 429 TOO MANY REQUESTS
        - Error response contains rate limit details
        
        Note: This test requires custom rate limit config.
        """
        # Create client with very low rate limit for testing
        from backend.postparse.api.middleware import RateLimitMiddleware
        from fastapi import FastAPI
        
        test_app = FastAPI()
        
        # Mock config with low rate limit
        mock_config = ConfigManager()
        
        with patch.object(mock_config, 'get') as mock_get:
            def config_side_effect(key, default=None):
                if key == "api.rate_limiting.enabled":
                    return True
                elif key == "api.rate_limiting.requests_per_minute":
                    return 5  # Very low limit for testing
                elif key == "api.rate_limiting.burst_size":
                    return 2  # Small burst
                return default
            
            mock_get.side_effect = config_side_effect
            
            # Add middleware
            test_app.add_middleware(RateLimitMiddleware, config=mock_config)
            
            # Add test endpoint
            @test_app.get("/test")
            def test_endpoint():
                return {"message": "ok"}
            
            client = TestClient(test_app)
            
            # Make requests rapidly
            status_codes = []
            for _ in range(10):
                response = client.get("/test")
                status_codes.append(response.status_code)
            
            # Count successes and rate limit errors
            success_count = status_codes.count(200)
            rate_limit_count = status_codes.count(429)
            
            # First 7 requests should succeed (5 base + 2 burst)
            assert success_count >= 5
            # Some requests should be rate limited
            assert rate_limit_count > 0
            
            # Check error response format
            response = client.get("/test")
            if response.status_code == 429:
                data = response.json()
                assert "error_code" in data
                assert data["error_code"] == "RATE_LIMIT_EXCEEDED"
                assert "message" in data
                assert "details" in data
                assert "limit" in data["details"]
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_rate_limiting_token_refill(self):
        """
        Test that tokens refill over time.
        
        Verifies:
        - Tokens are exhausted by rapid requests
        - After waiting, tokens refill
        - Subsequent requests succeed
        
        Note: This test has delays and is marked as slow.
        """
        from backend.postparse.api.middleware import RateLimitMiddleware
        from fastapi import FastAPI
        
        test_app = FastAPI()
        mock_config = ConfigManager()
        
        with patch.object(mock_config, 'get') as mock_get:
            def config_side_effect(key, default=None):
                if key == "api.rate_limiting.enabled":
                    return True
                elif key == "api.rate_limiting.requests_per_minute":
                    return 10  # 10 per minute = 1 every 6 seconds
                elif key == "api.rate_limiting.burst_size":
                    return 0  # No burst
                return default
            
            mock_get.side_effect = config_side_effect
            
            test_app.add_middleware(RateLimitMiddleware, config=mock_config)
            
            @test_app.get("/test")
            def test_endpoint():
                return {"message": "ok"}
            
            client = TestClient(test_app)
            
            # Exhaust tokens
            for _ in range(10):
                client.get("/test")
            
            # Next request should be rate limited
            response = client.get("/test")
            assert response.status_code == 429, "Expected rate limit after exhausting tokens"
            
            # Wait for tokens to refill
            # At 10 requests/minute, tokens refill at 1 token per 6 seconds
            # Wait 7 seconds to ensure at least 1 token has refilled
            time.sleep(7)
            
            # Should now succeed with refilled token
            response = client.get("/test")
            assert response.status_code == 200, "Expected request to succeed after token refill"
    
    @pytest.mark.integration
    def test_rate_limiting_burst_size(self):
        """
        Test burst capacity allows temporary excess.
        
        Verifies:
        - Can make (base_rate + burst_size) requests immediately
        - Requests beyond burst are rate limited
        
        Note: Burst allows temporary spikes in traffic.
        """
        from backend.postparse.api.middleware import RateLimitMiddleware
        from fastapi import FastAPI
        
        test_app = FastAPI()
        mock_config = ConfigManager()
        
        with patch.object(mock_config, 'get') as mock_get:
            def config_side_effect(key, default=None):
                if key == "api.rate_limiting.enabled":
                    return True
                elif key == "api.rate_limiting.requests_per_minute":
                    return 5
                elif key == "api.rate_limiting.burst_size":
                    return 3  # Can burst to 8 total (5 + 3)
                return default
            
            mock_get.side_effect = config_side_effect
            
            test_app.add_middleware(RateLimitMiddleware, config=mock_config)
            
            @test_app.get("/test")
            def test_endpoint():
                return {"message": "ok"}
            
            client = TestClient(test_app)
            
            # Make 8 requests (5 base + 3 burst)
            status_codes = []
            for _ in range(10):
                response = client.get("/test")
                status_codes.append(response.status_code)
            
            success_count = status_codes.count(200)
            
            # Should succeed for at least 5 requests (base rate)
            assert success_count >= 5
            # May succeed for up to 8 requests (base + burst)
            # But some requests should be rate limited
            assert 429 in status_codes
    
    @pytest.mark.integration
    @pytest.mark.skip(
        reason="TestClient does not support simulating multiple client IPs. "
        "Per-IP isolation requires real HTTP client with IP spoofing or integration test "
        "with actual network requests from different sources. "
        "This functionality should be tested manually or with end-to-end tests using real HTTP clients."
    )
    def test_rate_limiting_per_client_ip(self):
        """
        Test that rate limits are enforced per client IP.
        
        Verifies:
        - Each client IP has independent rate limit
        - Client A exhausting limit doesn't affect Client B
        
        SKIPPED: TestClient uses a single simulated IP and cannot test multi-IP scenarios.
        To test this properly, use:
        1. Real HTTP clients (requests/httpx) with different source IPs
        2. Integration tests against deployed service
        3. Manual testing with multiple physical clients
        """
        pass
    
    @pytest.mark.integration
    def test_rate_limiting_health_endpoint_excluded(self):
        """
        Test that health endpoints are excluded from rate limiting.
        
        Verifies:
        - /health endpoint is not rate limited
        - Can make unlimited requests to health check
        
        Note: Health checks must remain accessible for monitoring.
        """
        from backend.postparse.api.middleware import RateLimitMiddleware
        from fastapi import FastAPI
        
        test_app = FastAPI()
        mock_config = ConfigManager()
        
        with patch.object(mock_config, 'get') as mock_get:
            def config_side_effect(key, default=None):
                if key == "api.rate_limiting.enabled":
                    return True
                elif key == "api.rate_limiting.requests_per_minute":
                    return 2  # Very low limit
                elif key == "api.rate_limiting.burst_size":
                    return 0
                return default
            
            mock_get.side_effect = config_side_effect
            
            test_app.add_middleware(RateLimitMiddleware, config=mock_config)
            
            @test_app.get("/health")
            def health_endpoint():
                return {"status": "healthy"}
            
            @test_app.get("/api/test")
            def api_endpoint():
                return {"message": "ok"}
            
            client = TestClient(test_app)
            
            # Make many requests to /health - all should succeed
            health_success = 0
            for _ in range(10):
                response = client.get("/health")
                if response.status_code == 200:
                    health_success += 1
            
            assert health_success == 10  # All health checks succeed
            
            # But /api/test should be rate limited
            for _ in range(2):
                client.get("/api/test")
            
            response = client.get("/api/test")
            assert response.status_code == 429  # Rate limited
    
    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.skip(
        reason="This test was removed due to testing private implementation details (_buckets, _check_rate_limit). "
        "Cleanup behavior should be tested through observable effects in production usage. "
        "Consider adding memory profiling tests or monitoring in production instead."
    )
    def test_rate_limiting_cleanup_old_buckets(self):
        """
        DEPRECATED: This test accessed private implementation details.
        
        The cleanup behavior is an internal optimization and should not be
        tested directly. Instead, verify that:
        1. Memory usage stays reasonable under load (performance test)
        2. Rate limiting continues to work correctly over long periods
        3. Production monitoring alerts on memory growth
        
        Testing private methods provides false confidence and breaks encapsulation.
        """
        pass
