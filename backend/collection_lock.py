"""Redis-backed collection lock with a single-process fallback."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from typing import Any

logger = logging.getLogger(__name__)

LOCK_KEY = "collection:lock"
DEFAULT_LOCK_TTL_SECONDS = 900


class CollectionLock:
    def __init__(self, redis_url: str | None = None) -> None:
        self._client: Any = None
        self._local_lock = threading.Lock()
        self._local_token: str | None = None
        if redis_url:
            try:
                import redis

                self._client = redis.Redis.from_url(redis_url, socket_connect_timeout=3)
                self._client.ping()
            except Exception as exc:
                logger.warning("Redis collection lock unavailable, using local lock: %s", exc)
                self._client = None

    @property
    def using_redis(self) -> bool:
        return self._client is not None

    def acquire(self, ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS) -> str | None:
        token = str(uuid.uuid4())
        if self._client is not None:
            try:
                acquired = self._client.set(LOCK_KEY, token, nx=True, ex=ttl_seconds)
                return token if acquired else None
            except Exception as exc:
                logger.warning("Redis lock acquire failed, using local lock: %s", exc)

        if not self._local_lock.acquire(blocking=False):
            return None
        self._local_token = token
        return token

    def release(self, token: str) -> None:
        if self._client is not None:
            script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            end
            return 0
            """
            try:
                self._client.eval(script, 1, LOCK_KEY, token)
                return
            except Exception as exc:
                logger.warning("Redis lock release failed: %s", exc)

        if self._local_token == token and self._local_lock.locked():
            self._local_token = None
            self._local_lock.release()


_lock: CollectionLock | None = None


def get_collection_lock() -> CollectionLock:
    global _lock
    if _lock is None:
        _lock = CollectionLock(os.getenv("REDIS_URL"))
    return _lock
