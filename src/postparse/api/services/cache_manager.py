"""Response cache for read endpoints (optional Redis, in-memory fallback).

Keys are namespaced ``postparse:v2:{resource}:{hash}`` where ``hash`` is a
SHA-256 over the normalized request parameters, so different schema versions
or resources never collide. :meth:`CacheManager.invalidate` deletes every key
below a prefix; the job runner calls it after jobs and the classify endpoints
after persisting results.

The client is synchronous. Endpoints that use the cache are plain ``def``
handlers (FastAPI runs them in the threadpool); async callers wrap calls in
``anyio.to_thread.run_sync``.

Configuration (``[api.cache]``)::

    enabled = false                       # off: every call is a no-op
    redis_url = "redis://localhost:6379/0"
    default_ttl = 300                     # seconds
    search_ttl = 600                      # seconds for search/list endpoints
    max_entries = 1000                    # in-memory fallback size

Example:
    >>> cache = CacheManager(enabled=True)          # Redis unavailable -> memory
    >>> key = cache.key("items", q="pasta", limit=20)
    >>> cache.set(key, {"items": []})
    >>> cache.invalidate("items")
    1
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from datetime import date, datetime
from enum import Enum
from typing import Any

__all__ = ["KEY_NAMESPACE", "CacheManager"]

logger = logging.getLogger(__name__)

#: Prefix of every cache key written by this module.
KEY_NAMESPACE = "postparse:v2:"


def _normalize(value: Any) -> Any:
    """Return a JSON-stable representation of a parameter value."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_normalize(v) for v in value]
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items())}
    return value


class CacheManager:
    """Small key/value cache with TTLs and prefix invalidation.

    Args:
        enabled: ``False`` turns every operation into a no-op.
        redis_url: Redis server; ignored when ``client`` is given.
        default_ttl: TTL in seconds when :meth:`set` gets none.
        search_ttl: TTL used by search/list endpoints.
        max_entries: Size of the in-memory fallback (oldest entries evicted).
        client: Ready Redis-compatible client (tests pass ``fakeredis``).
        clock: Monotonic clock for the in-memory TTLs.
    """

    def __init__(
        self,
        enabled: bool = False,
        *,
        redis_url: str = "redis://localhost:6379/0",
        default_ttl: int = 300,
        search_ttl: int = 600,
        max_entries: int = 1000,
        client: Any = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.enabled = bool(enabled)
        self.default_ttl = int(default_ttl)
        self.search_ttl = int(search_ttl)
        self.max_entries = max(1, int(max_entries))
        self._clock = clock
        self._lock = threading.Lock()
        self._memory: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self.redis_client: Any = None
        if not self.enabled:
            return
        if client is not None:
            self.redis_client = client
            return
        try:
            import redis

            candidate = redis.from_url(
                redis_url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True
            )
            candidate.ping()
            self.redis_client = candidate
            logger.info("Redis cache connected")
        except Exception as exc:
            logger.warning("Redis unavailable (%s); using the in-memory cache", exc)

    @classmethod
    def from_config(cls, config: Any, *, client: Any = None) -> CacheManager:
        """Create a cache from ``[api.cache]`` of a ``ConfigManager`` (``None``: disabled)."""
        if config is None:
            return cls(False)
        return cls(
            bool(config.get("api.cache.enabled", default=False)),
            redis_url=config.get("api.cache.redis_url", default="redis://localhost:6379/0"),
            default_ttl=int(config.get("api.cache.default_ttl", default=300)),
            search_ttl=int(config.get("api.cache.search_ttl", default=600)),
            max_entries=int(config.get("api.cache.max_entries", default=1000)),
            client=client,
        )

    # -- info --------------------------------------------------------------------

    @property
    def backend(self) -> str:
        """``redis``, ``memory`` or ``disabled``."""
        if not self.enabled:
            return "disabled"
        return "redis" if self.redis_client is not None else "memory"

    def is_available(self) -> bool:
        """True when caching is enabled (Redis or memory)."""
        return self.enabled

    # -- keys --------------------------------------------------------------------

    @staticmethod
    def key(resource: str, **params: Any) -> str:
        """Build ``postparse:v2:{resource}:{hash}`` for request parameters.

        ``None`` values are dropped, so absent and explicitly empty optional
        parameters share a key.
        """
        payload = {k: _normalize(v) for k, v in sorted(params.items()) if v is not None}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()[:32]
        return f"{KEY_NAMESPACE}{resource}:{digest}"

    # -- operations --------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        """Return the cached value, or ``None`` on a miss / when disabled."""
        if not self.enabled:
            return None
        try:
            if self.redis_client is not None:
                raw = self.redis_client.get(key)
            else:
                raw = self._memory_get(key)
        except Exception as exc:
            logger.warning("Cache get failed: %s", exc)
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Store a JSON-serializable value; returns ``True`` when stored."""
        if not self.enabled:
            return False
        ttl = int(ttl if ttl is not None else self.default_ttl)
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        try:
            if self.redis_client is not None:
                self.redis_client.set(key, serialized, ex=ttl)
            else:
                self._memory_set(key, serialized, ttl)
        except Exception as exc:
            logger.warning("Cache set failed: %s", exc)
            return False
        return True

    def invalidate(self, prefix: str = "") -> int:
        """Delete every key below ``postparse:v2:{prefix}``.

        Args:
            prefix: Resource prefix (``""``: the whole namespace).

        Returns:
            Number of deleted keys.
        """
        if not self.enabled:
            return 0
        pattern = KEY_NAMESPACE + prefix
        try:
            if self.redis_client is not None:
                keys = list(self.redis_client.scan_iter(match=pattern + "*", count=500))
                deleted = int(self.redis_client.delete(*keys)) if keys else 0
            else:
                with self._lock:
                    keys = [k for k in self._memory if k.startswith(pattern)]
                    for k in keys:
                        del self._memory[k]
                deleted = len(keys)
        except Exception as exc:
            logger.warning("Cache invalidation failed: %s", exc)
            return 0
        if deleted:
            logger.debug("Invalidated %d cache keys below %s", deleted, pattern)
        return deleted

    # -- in-memory fallback ------------------------------------------------------

    def _memory_get(self, key: str) -> str | None:
        with self._lock:
            entry = self._memory.get(key)
            if entry is None:
                return None
            expires, value = entry
            if expires <= self._clock():
                del self._memory[key]
                return None
            self._memory.move_to_end(key)
            return value

    def _memory_set(self, key: str, value: str, ttl: int) -> None:
        with self._lock:
            self._memory[key] = (self._clock() + ttl, value)
            self._memory.move_to_end(key)
            while len(self._memory) > self.max_entries:
                self._memory.popitem(last=False)
