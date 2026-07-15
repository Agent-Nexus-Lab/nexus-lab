"""Rewrite cache — caches LLM-generated summary and reasons for reuse."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from backend.cache_backend import CacheBackend, InMemoryCache

CACHE_VERSION = "v1"


def _hash_str(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()[:12]


class RewriteCache:
    """Caches LLM rewrite output.

    Key = plan_items_hash + display_memory_hash + prompt_version + model_name
    Value = {"summary": str, "reasons": [{"event_id": str, "reason_text": str}]}
    """

    def __init__(self, backend: Optional[CacheBackend] = None) -> None:
        self._backend = backend or InMemoryCache()

    @property
    def backend(self) -> CacheBackend:
        return self._backend

    def build_key(
        self,
        *,
        user_id: str,
        query_hash: str,
        date_scope: str,
        plan_items_hash: str,
        display_memory_hash: str,
        prompt_version: str,
        model_name: str,
    ) -> str:
        raw = json.dumps(
            {
                "v": CACHE_VERSION,
                "uid": user_id,
                "qh": query_hash,
                "ds": date_scope,
                "pih": plan_items_hash,
                "dmh": display_memory_hash,
                "pv": prompt_version,
                "mn": model_name,
            },
            sort_keys=True,
        )
        return f"rewrite:{_hash_str(raw)}"

    def get(self, key: str) -> Optional[dict[str, Any]]:
        return self._backend.get(key)

    def set(self, key: str, value: dict[str, Any], ttl_seconds: int = 3600) -> None:
        self._backend.set(key, value, ttl_seconds)

    def delete(self, key: str) -> None:
        self._backend.delete(key)

    @staticmethod
    def compute_plan_items_hash(items: list[dict[str, Any]]) -> str:
        """Hash of plan items (event_ids + order) to detect when items change."""
        payload = json.dumps(
            [{"eid": it.get("event_id", ""), "do": it.get("display_order", 0)} for it in items],
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.md5(payload.encode()).hexdigest()[:12]
