"""
Cache management service for API responses.

This module provides Redis-based caching with graceful fallback to in-memory
cache when Redis is unavailable.
"""

import json
import hashlib
import logging
from typing import Any, Optional, Dict
from functools import lru_cache

from backend.postparse.core.utils.config import ConfigManager

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Manages caching operations with Redis or in-memory fallback.
    
    This class provides a unified interface for caching API responses
    with automatic fallback to in-memory storage if Redis is unavailable.
    
    Attributes:
        config: ConfigManager instance for accessing configuration.
        redis_client: Redis client instance (None if unavailable).
        memory_cache: In-memory cache dict (used as fallback).
        is_redis_available: Boolean indicating Redis connection status.
        
    Example:
        >>> from backend.postparse.core.utils.config import ConfigManager
        >>> config = ConfigManager()
        >>> cache = CacheManager(config)
        >>> cache.set("key1", {"data": "value"}, ttl=300)
        >>> result = cache.get("key1")
        >>> print(result)
        {'data': 'value'}
    """
    
    def __init__(self, config: ConfigManager):
        """
        Initialize cache manager with configuration.
        
        Args:
            config: ConfigManager instance for accessing cache settings.
            
        Example:
            >>> config = ConfigManager()
            >>> cache = CacheManager(config)
            >>> print(cache.is_available())
            True
        """
        self.config = config
        self.redis_client: Optional[Any] = None
        self.memory_cache: Dict[str, Any] = {}
        self.is_redis_available = False
        
        # Check if caching is enabled
        cache_enabled = config.get("api.cache.enabled", default=False)
        if not cache_enabled:
            logger.info("Caching is disabled in configuration")
            return
        
        # Try to initialize Redis
        try:
            import redis
            redis_url = config.get("api.cache.redis_url", default="redis://localhost:6379/0")
            self.redis_client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2
            )
            # Test connection
            self.redis_client.ping()
            self.is_redis_available = True
            logger.info(f"Redis cache connected successfully: {redis_url}")
        except ImportError:
            logger.warning("Redis package not installed, using in-memory cache")
        except Exception as e:
            logger.warning(f"Redis connection failed, using in-memory cache: {e}")
    
    def is_available(self) -> bool:
        """
        Check if caching is available (Redis or in-memory).
        
        Returns:
            True if caching is enabled, False otherwise.
            
        Example:
            >>> cache = CacheManager(config)
            >>> if cache.is_available():
            ...     cache.set("key", "value")
        """
        return self.config.get("api.cache.enabled", default=False)
    
    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve cached value by key.
        
        Args:
            key: Cache key to retrieve.
            
        Returns:
            Cached value (deserialized from JSON) or None if not found.
            
        Example:
            >>> cache.set("user:123", {"name": "John"})
            >>> user = cache.get("user:123")
            >>> print(user)
            {'name': 'John'}
        """
        if not self.is_available():
            return None
        
        try:
            if self.is_redis_available and self.redis_client:
                value = self.redis_client.get(key)
                if value:
                    logger.debug(f"Cache hit (Redis): {key}")
                    return json.loads(value)
                logger.debug(f"Cache miss (Redis): {key}")
                return None
            else:
                value = self.memory_cache.get(key)
                if value:
                    logger.debug(f"Cache hit (memory): {key}")
                    return value
                logger.debug(f"Cache miss (memory): {key}")
                return None
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Cache a value with optional TTL.
        
        Args:
            key: Cache key to store.
            value: Value to cache (will be JSON serialized).
            ttl: Time-to-live in seconds (uses default_ttl from config if None).
            
        Returns:
            True if successful, False otherwise.
            
        Example:
            >>> cache.set("posts:all", [{"id": 1}, {"id": 2}], ttl=600)
            True
        """
        if not self.is_available():
            return False
        
        if ttl is None:
            ttl = self.config.get("api.cache.default_ttl", default=300)
        
        try:
            if self.is_redis_available and self.redis_client:
                serialized = json.dumps(value)
                self.redis_client.setex(key, ttl, serialized)
                logger.debug(f"Cache set (Redis): {key} (TTL: {ttl}s)")
                return True
            else:
                # In-memory cache doesn't support TTL natively, store value only
                self.memory_cache[key] = value
                logger.debug(f"Cache set (memory): {key}")
                # Limit memory cache size
                max_size = self.config.get("api.cache.max_memory_mb", default=100) * 10
                if len(self.memory_cache) > max_size:
                    # Remove oldest entry (FIFO)
                    self.memory_cache.pop(next(iter(self.memory_cache)))
                return True
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """
        Remove a cached value.
        
        Args:
            key: Cache key to remove.
            
        Returns:
            True if successful, False otherwise.
            
        Example:
            >>> cache.delete("user:123")
            True
        """
        if not self.is_available():
            return False
        
        try:
            if self.is_redis_available and self.redis_client:
                self.redis_client.delete(key)
                logger.debug(f"Cache delete (Redis): {key}")
                return True
            else:
                if key in self.memory_cache:
                    del self.memory_cache[key]
                    logger.debug(f"Cache delete (memory): {key}")
                return True
        except Exception as e:
            logger.error(f"Cache delete error for key {key}: {e}")
            return False
    
    def clear_pattern(self, pattern: str) -> int:
        """
        Clear all keys matching a pattern.
        
        Args:
            pattern: Pattern to match (e.g., 'search:posts:*').
            
        Returns:
            Number of keys deleted.
            
        Example:
            >>> cache.clear_pattern("search:*")
            15
        """
        if not self.is_available():
            return 0
        
        try:
            if self.is_redis_available and self.redis_client:
                keys = self.redis_client.keys(pattern)
                if keys:
                    deleted = self.redis_client.delete(*keys)
                    logger.info(f"Cache pattern clear (Redis): {pattern} ({deleted} keys)")
                    return deleted
                return 0
            else:
                # Simple pattern matching for in-memory cache
                # Convert glob pattern to prefix matching
                prefix = pattern.replace("*", "")
                keys_to_delete = [k for k in self.memory_cache.keys() if k.startswith(prefix)]
                for key in keys_to_delete:
                    del self.memory_cache[key]
                logger.info(f"Cache pattern clear (memory): {pattern} ({len(keys_to_delete)} keys)")
                return len(keys_to_delete)
        except Exception as e:
            logger.error(f"Cache pattern clear error for pattern {pattern}: {e}")
            return 0
    
    def generate_cache_key(self, prefix: str, **params) -> str:
        """
        Generate deterministic cache key from parameters.
        
        Args:
            prefix: Key prefix (e.g., 'search:posts').
            **params: Filter parameters to include in key.
            
        Returns:
            Generated cache key string.
            
        Example:
            >>> key = cache.generate_cache_key(
            ...     "search:posts",
            ...     hashtags=["recipe"],
            ...     content_type="video",
            ...     limit=20
            ... )
            >>> print(key)
            search:posts:a3f5b9c1e2d4...
        """
        from datetime import datetime
        
        # Normalize params for JSON serialization
        def normalize_value(value):
            """Convert non-JSON-serializable types to serializable forms."""
            if isinstance(value, datetime):
                return value.isoformat()
            elif isinstance(value, tuple):
                return [normalize_value(v) for v in value]
            elif isinstance(value, list):
                return [normalize_value(v) for v in value]
            elif isinstance(value, dict):
                return {k: normalize_value(v) for k, v in value.items()}
            return value
        
        # Normalize all params
        normalized_params = {k: normalize_value(v) for k, v in params.items()}
        
        # Sort params for deterministic key generation
        sorted_params = sorted(normalized_params.items())
        params_str = json.dumps(sorted_params, sort_keys=True)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()[:16]
        return f"{prefix}:{params_hash}"

