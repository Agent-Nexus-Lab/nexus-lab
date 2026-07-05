"""Cache storage backends — abstract interface + in-memory + Redis."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CacheBackend(ABC):
    """Abstract cache backend interface."""

    @abstractmethod
    def get(self, key: str) -> Optional[dict[str, Any]]:
        """Return cached value or None on miss."""
        ...

    @abstractmethod
    def set(self, key: str, value: dict[str, Any], ttl_seconds: int = 3600) -> None:
        """Store a value with TTL."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove a key."""
        ...

    @abstractmethod
    def available(self) -> bool:
        """Whether the backend is healthy."""
        ...


class InMemoryCache(CacheBackend):
    """Simple dict-based cache for local development / fallback."""

    def __init__(self) -> None:
        import time
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}
        self._time = time

    def get(self, key: str) -> Optional[dict[str, Any]]:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: dict[str, Any], ttl_seconds: int = 3600) -> None:
        self._store[key] = (self._time.monotonic() + ttl_seconds, value)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def available(self) -> bool:
        return True


class RedisCache(CacheBackend):
    """Redis-backed cache. Falls back to InMemoryCache if unavailable."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Any = None
        self._fallback = InMemoryCache()
        self._redis_available = False
        self._init_error: Optional[str] = None
        self._try_connect()

    def _try_connect(self) -> None:
        try:
            import redis
            self._client = redis.Redis.from_url(self._redis_url, socket_connect_timeout=3)
            self._client.ping()
            self._redis_available = True
            logger.info("Redis cache connected: %s", self._redis_url)
        except Exception as exc:
            self._redis_available = False
            self._init_error = str(exc)
            logger.warning("Redis unavailable (%s), falling back to InMemoryCache", exc)

    def get(self, key: str) -> Optional[dict[str, Any]]:
        if self._redis_available and self._client:
            try:
                raw = self._client.get(key)
                if raw is None:
                    return None
                return json.loads(raw)
            except Exception:
                pass
        return self._fallback.get(key)

    def set(self, key: str, value: dict[str, Any], ttl_seconds: int = 3600) -> None:
        if self._redis_available and self._client:
            try:
                self._client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))
                return
            except Exception:
                pass
        self._fallback.set(key, value, ttl_seconds)

    def delete(self, key: str) -> None:
        if self._redis_available and self._client:
            try:
                self._client.delete(key)
                return
            except Exception:
                pass
        self._fallback.delete(key)

    def available(self) -> bool:
        return self._redis_available or self._fallback.available()

    @property
    def using_fallback(self) -> bool:
        return not self._redis_available

    @property
    def init_error(self) -> Optional[str]:
        return self._init_error
