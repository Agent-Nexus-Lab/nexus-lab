from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from query_rewrite import rewrite_query, _rule_based_rewrite, PROMPT_VERSION as RW_VERSION
from answer_composer import compose_answer, _rule_based_compose, PROMPT_VERSION as AC_VERSION


SAMPLE_MEMORY = "用户对天文观测类活动有持续偏好，连续两轮选择了观星和观测活动。不喜欢过于学术或商业化的活动。偏好轻松、互动、实操型的活动形式。"


class QueryRewriteTest(unittest.TestCase):
    # ============================================================
    # _rule_based_rewrite
    # ============================================================

    def test_rewrite_with_memory(self):
        result = _rule_based_rewrite(
            query="今天下午有什么活动",
            memory_summary=SAMPLE_MEMORY,
            profile={"interest_tags": ["天文"], "preferred_campuses": ["邯郸"]},
        )
        self.assertIn("今天下午有什么活动", result["enriched_query"])
        self.assertIn("天文", result["positive_terms"])
        self.assertTrue(any("路演" in t or "商业" in t for t in result["negative_terms"]))
        self.assertIn("afternoon", result["time_hint"])
        self.assertIn("偏好", result["memory_influence"])
        self.assertEqual(result["top_k"], 4)
        self.assertTrue(result["used_fallback"])
        self.assertEqual(result["prompt_version"], RW_VERSION)

    def test_rewrite_no_memory(self):
        result = _rule_based_rewrite(
            query="想看2个AI活动",
            memory_summary=None,
            profile=None,
        )
        self.assertEqual(result["positive_terms"], [])
        self.assertEqual(result["negative_terms"], [])
        self.assertEqual(result["top_k"], 2)

    def test_rewrite_evening(self):
        result = _rule_based_rewrite(
            query="晚上有没有音乐会",
            memory_summary=None,
            profile=None,
        )
        self.assertEqual(result["time_hint"], "evening")

    def test_rewrite_location_from_query(self):
        result = _rule_based_rewrite(
            query="江湾有什么讲座",
            memory_summary=None,
            profile={"preferred_campuses": ["邯郸"]},
        )
        self.assertEqual(result["location_hint"], "江湾")

    def test_rewrite_location_from_profile(self):
        result = _rule_based_rewrite(
            query="有什么活动",
            memory_summary=None,
            profile={"preferred_campuses": ["枫林"]},
        )
        self.assertEqual(result["location_hint"], "枫林")

    def test_rewrite_top_k_boundary(self):
        result = _rule_based_rewrite(query="推荐20个活动", memory_summary=None, profile=None)
        self.assertEqual(result["top_k"], 10)  # max clamped
        result = _rule_based_rewrite(query="推荐0个活动", memory_summary=None, profile=None)
        self.assertEqual(result["top_k"], 1)  # min clamped to 1

    # ============================================================
    # rewrite_query integration (rule fallback)
    # ============================================================

    def test_rewrite_query_fallback(self):
        result = rewrite_query(
            query="今天下午想看天文",
            memory_summary=SAMPLE_MEMORY,
            profile={"interest_tags": ["天文", "AI"]},
            api_key="",  # no key → fallback
        )
        self.assertTrue(result["used_fallback"])
        self.assertIn("天文", result["enriched_query"])

    # ============================================================
    # 样例：memory_summary 确实影响了输出
    # ============================================================

    def test_memory_influence_proof(self):
        """证明 memory_summary 会影响 query rewrite 输出."""
        # Without memory
        r1 = _rule_based_rewrite(query="有什么活动", memory_summary=None, profile=None)
        # With memory
        r2 = _rule_based_rewrite(query="有什么活动", memory_summary=SAMPLE_MEMORY, profile=None)

        # With memory should have more terms
        self.assertGreaterEqual(len(r2["positive_terms"]), len(r1["positive_terms"]))
        # With memory should have negative terms extracted
        self.assertTrue(len(r2["negative_terms"]) > 0)
        # Memory influence should be non-empty
        self.assertIn("偏好", r2["memory_influence"])


class AnswerComposerTest(unittest.TestCase):
    # ============================================================
    # _rule_based_compose
    # ============================================================

    def setUp(self):
        self.sample_items = [
            {"event_id": "evt_1", "title": "天文观测夜", "score": 0.92,
             "reason_text": "匹配天文偏好，校区为邯郸，规则评分 0.92", "start_time": "2026-07-10T19:00", "location": "邯郸"},
            {"event_id": "evt_2", "title": "AI讲座", "score": 0.75,
             "reason_text": "匹配AI兴趣，校区为江湾，规则评分 0.75", "start_time": "2026-07-10T15:00", "location": "江湾"},
            {"event_id": "evt_3", "title": "音乐会", "score": 0.65,
             "reason_text": "匹配娱乐偏好，校区为邯郸，规则评分 0.65", "start_time": "2026-07-10T20:00", "location": "邯郸"},
        ]

    def test_compose_with_memory(self):
        result = _rule_based_compose(
            self.sample_items,
            memory_summary=SAMPLE_MEMORY,
            request_text="今天下午有什么活动",
        )
        self.assertIn("3 个活动", result["summary"])
        self.assertIn("天文观测夜", result["summary"])
        self.assertEqual(len(result["items"]), 3)
        self.assertIn("参考", result["memory_note"])
        # Items maintain original order
        self.assertEqual(result["items"][0]["event_id"], "evt_1")
        self.assertEqual(result["items"][1]["event_id"], "evt_2")
        self.assertEqual(result["items"][2]["event_id"], "evt_3")
        self.assertTrue(result["used_fallback"])

    def test_compose_no_memory(self):
        result = _rule_based_compose(
            self.sample_items[:2],
            memory_summary=None,
            request_text="有什么活动",
        )
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["memory_note"], "")
        self.assertNotIn("参考", result["summary"])

    def test_compose_empty_items(self):
        result = compose_answer([], memory_summary=SAMPLE_MEMORY, request_text="test", api_key="")
        self.assertEqual(result["items"], [])
        self.assertIn("没有找到", result["summary"])

    def test_compose_preserves_order(self):
        """answer_composer 不重排，保持输入顺序."""
        items = [
            {"event_id": "z", "title": "Third", "score": 0.5, "reason_text": ""},
            {"event_id": "a", "title": "First", "score": 0.5, "reason_text": ""},
            {"event_id": "m", "title": "Second", "score": 0.5, "reason_text": ""},
        ]
        result = _rule_based_compose(items, None, "")
        self.assertEqual([r["event_id"] for r in result["items"]], ["z", "a", "m"])

    def test_compose_fallback_works(self):
        result = compose_answer(
            self.sample_items[:1],
            memory_summary=SAMPLE_MEMORY,
            request_text="test",
            api_key="",  # no API key
        )
        self.assertTrue(result["used_fallback"])
        self.assertEqual(len(result["items"]), 1)

    # ============================================================
    # 版本一致性
    # ============================================================

    def test_prompt_versions(self):
        self.assertEqual(RW_VERSION, "2026-07-08-v1")
        self.assertEqual(AC_VERSION, "2026-07-08-v1")


if __name__ == "__main__":
    unittest.main()
