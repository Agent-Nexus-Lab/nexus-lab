"""Plan result cache — caches the full plan_day output keyed by immutable inputs."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from backend.cache_backend import CacheBackend, InMemoryCache

CACHE_VERSION = "v1"


def _hash_str(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()[:12]


def _events_snapshot_hash(events: list[dict[str, Any]]) -> str:
    """Stable hash of the event corpus — any event change busts the cache."""
    payload = json.dumps(
        [{"id": e.get("event_id", ""), "t": e.get("title", ""), "st": e.get("start_time", "")}
         for e in events],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.md5(payload.encode()).hexdigest()[:12]


class PlanResultCache:
    """Caches complete plan_day results.

    Key = profile_id + query_hash + date_scope + scoring_memory_hash
          + event_snapshot_hash + cache_version
    Value = full plan result dict (the data portion of the response).
    """

    def __init__(self, backend: Optional[CacheBackend] = None) -> None:
        self._backend = backend or InMemoryCache()

    @property
    def backend(self) -> CacheBackend:
        return self._backend

    def build_key(
        self,
        *,
        profile_id: str,
        query_hash: str,
        date_scope: str,
        scoring_memory_hash: str,
        event_snapshot_hash: str,
    ) -> str:
        raw = json.dumps(
            {
                "v": CACHE_VERSION,
                "pid": profile_id,
                "qh": query_hash,
                "ds": date_scope,
                "smh": scoring_memory_hash,
                "esh": event_snapshot_hash,
            },
            sort_keys=True,
        )
        return f"plan:{_hash_str(raw)}"

    def get(self, key: str) -> Optional[dict[str, Any]]:
        return self._backend.get(key)

    def set(self, key: str, value: dict[str, Any], ttl_seconds: int = 600) -> None:
        self._backend.set(key, value, ttl_seconds)

    def delete(self, key: str) -> None:
        self._backend.delete(key)

    @staticmethod
    def compute_query_hash(request_text: str) -> str:
        return _hash_str(request_text.strip())

    @staticmethod
    def compute_event_snapshot_hash(events: list[dict[str, Any]]) -> str:
        return _events_snapshot_hash(events)
