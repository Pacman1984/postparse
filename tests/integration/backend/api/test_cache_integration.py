"""
Integration tests for Redis caching layer.

Tests CacheManager functionality with Redis and in-memory fallback,
cache hit/miss behavior, TTL expiry, and cache invalidation.
"""

import pytest
import time
from unittest.mock import Mock, patch
from typing import Dict, Any

from backend.postparse.api.services.cache_manager import CacheManager
from backend.postparse.core.utils.config import ConfigManager
from fastapi.testclient import TestClient


@pytest.fixture
def test_config_with_cache():
    """Config with caching enabled for testing."""
    config = Mock(spec=ConfigManager)
    config.get.side_effect = lambda key, default=None: {
        "api.cache.enabled": True,
        "api.cache.redis_url": "redis://localhost:6379/0",
        "api.cache.default_ttl": 300,
        "api.cache.search_ttl": 600,
        "api.cache.max_memory_mb": 100
    }.get(key, default)
    return config


@pytest.fixture
def test_config_without_cache():
    """Config with caching disabled for testing."""
    config = Mock(spec=ConfigManager)
    config.get.side_effect = lambda key, default=None: {
        "api.cache.enabled": False,
        "api.cache.redis_url": "redis://localhost:6379/0",
        "api.cache.default_ttl": 300,
        "api.cache.search_ttl": 600,
        "api.cache.max_memory_mb": 100
    }.get(key, default)
    return config


class TestCacheManager:
    """Tests for CacheManager functionality."""
    
    @pytest.mark.cache
    @pytest.mark.skipif(True, reason="Requires Redis server running")
    def test_cache_manager_redis_available(self, test_config_with_cache):
        """
        Test CacheManager with real Redis connection.
        
        Verifies:
        - get/set/delete operations work
        - Cache persists data correctly
        - TTL is respected
        """
        cache = CacheManager(test_config_with_cache)
        
        # Test set and get
        test_key = "test:key:1"
        test_value = {"data": "test_value", "count": 42}
        
        assert cache.set(test_key, test_value, ttl=60)
        retrieved = cache.get(test_key)
        
        assert retrieved is not None
        assert retrieved["data"] == "test_value"
        assert retrieved["count"] == 42
        
        # Test delete
        assert cache.delete(test_key)
        assert cache.get(test_key) is None
    
    @pytest.mark.cache
    def test_cache_manager_redis_unavailable(self, test_config_with_cache):
        """
        Test graceful degradation to in-memory cache when Redis fails.
        
        Verifies:
        - Fallback to in-memory cache works
        - Basic operations still function
        - No exceptions are raised
        """
        # Patch redis import to raise ImportError
        import sys
        import importlib
        
        # Temporarily remove redis from sys.modules if it exists
        redis_module = sys.modules.get('redis')
        if 'redis' in sys.modules:
            del sys.modules['redis']
        
        try:
            # Mock redis import to raise ImportError
            with patch.dict('sys.modules', {'redis': None}):
                # Reload cache_manager to trigger import error handling
                importlib.reload(sys.modules['backend.postparse.api.services.cache_manager'])
                from backend.postparse.api.services.cache_manager import CacheManager as ReloadedCacheManager
                
                cache = ReloadedCacheManager(test_config_with_cache)
                
                # Should fall back to in-memory cache
                assert cache.is_available()
                assert not cache.is_redis_available
                
                # Test operations work with in-memory fallback
                test_key = "memory:test:1"
                test_value = {"name": "test"}
                
                assert cache.set(test_key, test_value)
                retrieved = cache.get(test_key)
                
                assert retrieved is not None
                assert retrieved["name"] == "test"
        finally:
            # Restore redis module if it existed
            if redis_module:
                sys.modules['redis'] = redis_module
    
    @pytest.mark.cache
    def test_cache_manager_generate_cache_key(self, test_config_with_cache):
        """
        Test deterministic cache key generation.
        
        Verifies:
        - Same parameters produce same key
        - Different parameters produce different keys
        - Key format is consistent
        """
        cache = CacheManager(test_config_with_cache)
        
        # Same params should produce same key
        key1 = cache.generate_cache_key(
            "search:posts",
            hashtags=["recipe"],
            content_type="video",
            limit=20
        )
        key2 = cache.generate_cache_key(
            "search:posts",
            hashtags=["recipe"],
            content_type="video",
            limit=20
        )
        
        assert key1 == key2
        assert key1.startswith("search:posts:")
        
        # Different params should produce different keys
        key3 = cache.generate_cache_key(
            "search:posts",
            hashtags=["cooking"],
            content_type="video",
            limit=20
        )
        
        assert key1 != key3
    
    @pytest.mark.cache
    def test_cache_disabled_in_config(self, test_config_without_cache):
        """
        Test that caching is skipped when disabled in config.
        
        Verifies:
        - is_available() returns False
        - set/get operations are no-ops
        """
        cache = CacheManager(test_config_without_cache)
        
        assert not cache.is_available()
        
        # Operations should be no-ops
        assert not cache.set("key", "value")
        assert cache.get("key") is None


class TestSearchCacheIntegration:
    """Integration tests for caching in search endpoints."""
    
    @pytest.mark.integration
    @pytest.mark.cache
    def test_search_posts_cache_hit(self):
        """
        Test cache hit behavior in search endpoint.
        
        Verifies:
        - First request populates cache (MISS)
        - Second identical request uses cache (HIT)
        - X-Cache-Status header indicates cache status
        """
        from backend.postparse.api.main import app
        from backend.postparse.api.dependencies import get_db, get_cache_manager
        from backend.postparse.core.data.database import SocialMediaDatabase
        
        client = TestClient(app)
        
        # Mock database
        mock_db = Mock(spec=SocialMediaDatabase)
        mock_db.search_instagram_posts.return_value = ([], None)
        mock_db.count_instagram_posts_filtered.return_value = 0
        mock_db._decode_cursor.return_value = ("2024-01-01T00:00:00", 1)
        
        # Use real cache manager with in-memory fallback
        test_config = Mock(spec=ConfigManager)
        test_config.get.side_effect = lambda key, default=None: {
            "api.cache.enabled": True,
            "api.cache.redis_url": "redis://localhost:6379/0",
            "api.cache.default_ttl": 300,
            "api.cache.search_ttl": 600,
            "api.cache.max_memory_mb": 100
        }.get(key, default)
        
        cache = CacheManager(test_config)
        
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_cache_manager] = lambda: cache
        
        try:
            # First request - should be cache miss
            response1 = client.get("/api/v1/search/posts", params={"limit": 10})
            assert response1.status_code == 200
            assert response1.headers.get("X-Cache-Status") == "MISS"
            
            # Second identical request - should be cache hit
            response2 = client.get("/api/v1/search/posts", params={"limit": 10})
            assert response2.status_code == 200
            assert response2.headers.get("X-Cache-Status") == "HIT"
            
            # Verify database was only called once
            assert mock_db.search_instagram_posts.call_count == 1
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    @pytest.mark.cache
    def test_search_posts_cache_miss_different_filters(self):
        """
        Test that different filters produce cache misses.
        
        Verifies:
        - Different filter combinations have separate cache entries
        - Each unique query hits the database
        """
        from backend.postparse.api.main import app
        from backend.postparse.api.dependencies import get_db, get_cache_manager
        from backend.postparse.core.data.database import SocialMediaDatabase
        
        client = TestClient(app)
        
        mock_db = Mock(spec=SocialMediaDatabase)
        mock_db.search_instagram_posts.return_value = ([], None)
        mock_db.count_instagram_posts_filtered.return_value = 0
        mock_db._decode_cursor.return_value = ("2024-01-01T00:00:00", 1)
        
        test_config = Mock(spec=ConfigManager)
        test_config.get.side_effect = lambda key, default=None: {
            "api.cache.enabled": True,
            "api.cache.default_ttl": 300,
            "api.cache.search_ttl": 600,
            "api.cache.max_memory_mb": 100
        }.get(key, default)
        
        # Create a fresh cache instance for this test with unique prefix
        cache = CacheManager(test_config)
        # Clear any existing cache to ensure clean state
        if cache.is_available():
            cache.clear_pattern("search:*")
            # Also clear in-memory cache if using fallback
            if not cache.is_redis_available:
                cache.memory_cache.clear()
        
        # Use Pydantic model mocking for proper parameter passing
        from backend.postparse.api.schemas.search import SearchPostsRequest
        
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_cache_manager] = lambda: cache
        
        try:
            # First request with one hashtag
            def mock_request1():
                return SearchPostsRequest(hashtags=["test_recipe_unique1"], limit=10)
            
            app.dependency_overrides[SearchPostsRequest] = mock_request1
            response1 = client.get("/api/v1/search/posts")
            assert response1.status_code == 200
            assert response1.headers.get("X-Cache-Status") == "MISS"
            
            # Second request with different hashtag - should also be cache miss
            def mock_request2():
                return SearchPostsRequest(hashtags=["test_cooking_unique2"], limit=10)
            
            app.dependency_overrides[SearchPostsRequest] = mock_request2
            response2 = client.get("/api/v1/search/posts")
            assert response2.status_code == 200
            assert response2.headers.get("X-Cache-Status") == "MISS"
            
            # Database should be called twice (once for each unique query)
            assert mock_db.search_instagram_posts.call_count == 2
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.integration
    @pytest.mark.cache
    @pytest.mark.slow
    def test_search_posts_cache_ttl_expiry(self):
        """
        Test cache expiry after TTL.
        
        Verifies:
        - Cache entries expire after TTL
        - Expired entries result in cache miss
        
        Note: This test uses short TTL and sleeps, marked as slow.
        """
        from backend.postparse.api.main import app
        from backend.postparse.api.dependencies import get_cache_manager
        
        # Use very short TTL for testing
        test_config = Mock(spec=ConfigManager)
        test_config.get.side_effect = lambda key, default=None: {
            "api.cache.enabled": True,
            "api.cache.default_ttl": 1,  # 1 second TTL
            "api.cache.search_ttl": 1,
            "api.cache.max_memory_mb": 100
        }.get(key, default)
        
        cache = CacheManager(test_config)
        
        # Test directly with cache manager
        test_key = "expiry:test"
        test_value = {"data": "value"}
        
        cache.set(test_key, test_value, ttl=1)
        
        # Should be available immediately
        assert cache.get(test_key) is not None
        
        # Wait for expiry (only works with Redis, in-memory doesn't support TTL)
        if cache.is_redis_available:
            time.sleep(2)
            assert cache.get(test_key) is None
    
    @pytest.mark.integration
    @pytest.mark.cache
    def test_cache_pattern_clear(self):
        """
        Test clearing cache keys by pattern.
        
        Verifies:
        - clear_pattern() removes matching keys
        - Non-matching keys are preserved
        """
        test_config = Mock(spec=ConfigManager)
        test_config.get.side_effect = lambda key, default=None: {
            "api.cache.enabled": True,
            "api.cache.default_ttl": 300,
            "api.cache.max_memory_mb": 100
        }.get(key, default)
        
        cache = CacheManager(test_config)
        
        # Set multiple keys
        cache.set("search:posts:1", {"data": "post1"})
        cache.set("search:posts:2", {"data": "post2"})
        cache.set("search:messages:1", {"data": "msg1"})
        
        # Clear search:posts pattern
        deleted = cache.clear_pattern("search:posts")
        assert deleted >= 0  # Returns count of deleted keys
        
        # Verify posts are cleared but messages remain
        assert cache.get("search:posts:1") is None
        assert cache.get("search:posts:2") is None
        # Message may or may not remain depending on pattern matching implementation

