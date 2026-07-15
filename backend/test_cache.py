from __future__ import annotations

import unittest

from backend.cache_backend import CacheBackend, NoOpCache, RedisCache
from backend.plan_cache import PlanResultCache
from backend.rewrite_cache import RewriteCache


class RecordingBackend(CacheBackend):
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ttl_seconds=3600):
        self.values[key] = value
        self.ttls[key] = ttl_seconds

    def delete(self, key):
        self.values.pop(key, None)

    def available(self):
        return True


class CacheContractTest(unittest.TestCase):
    def test_plan_key_includes_user_and_memory(self):
        cache = PlanResultCache(RecordingBackend())
        base = dict(
            profile_id="profile",
            query_hash="query",
            date_scope="today",
            scoring_memory_hash="memory-a",
            event_snapshot_hash="events",
        )
        first = cache.build_key(user_id="user-a", **base)
        second = cache.build_key(user_id="user-b", **base)
        third = cache.build_key(
            user_id="user-a", **{**base, "scoring_memory_hash": "memory-b"}
        )
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)

    def test_rewrite_key_includes_request_date_and_user(self):
        cache = RewriteCache(RecordingBackend())
        base = dict(
            plan_items_hash="items",
            display_memory_hash="memory",
            prompt_version="prompt-v1",
            model_name="model",
        )
        first = cache.build_key(
            user_id="user-a", query_hash="q1", date_scope="today", **base
        )
        second = cache.build_key(
            user_id="user-a", query_hash="q2", date_scope="today", **base
        )
        third = cache.build_key(
            user_id="user-b", query_hash="q1", date_scope="today", **base
        )
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)

    def test_cache_ttls_remain_distinct(self):
        backend = RecordingBackend()
        plan = PlanResultCache(backend)
        rewrite = RewriteCache(backend)
        plan.set("plan:key", {"ok": True})
        rewrite.set("rewrite:key", {"ok": True})
        self.assertEqual(backend.ttls["plan:key"], 600)
        self.assertEqual(backend.ttls["rewrite:key"], 3600)

    def test_redis_unavailable_is_not_reported_as_available(self):
        cache = RedisCache("redis://127.0.0.1:1/0")
        self.assertFalse(cache.available())
        self.assertTrue(cache.using_fallback)

    def test_noop_cache_never_stores(self):
        cache = NoOpCache()
        cache.set("key", {"value": 1})
        self.assertIsNone(cache.get("key"))


if __name__ == "__main__":
    unittest.main()
