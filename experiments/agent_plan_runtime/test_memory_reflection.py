from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from memory_reflection import (
    _rule_based_reflection,
    _normalize_reflection,
    _empty_reflection,
    decay_memory_strength,
    is_memory_expired,
    suppress_memory,
    reflect_on_memory,
    PROMPT_VERSION,
    MEMORY_STRENGTH_DECAY,
)
from memory_reflection_samples import (
    SAMPLE_3_ROUNDS,
    SAMPLE_3_ROUNDS_NO_FEEDBACK,
    SAMPLE_MEMORY_FOR_DECAY,
    DECAY_1_ROUND_EXPECTED,
    DECAY_ROUNDS_UNTIL_EXPIRED,
)


# 契约必需字段（memory_reflection）
MEMORY_REFLECTION_CONTRACT_FIELDS = {
    "memory_summary", "source_refs", "expires_after_turns", "cleanup_reason",
    "status", "prompt_version", "model", "used_fallback", "error",
    "duration_ms", "retry_count",
}


class MemoryReflectionTest(unittest.TestCase):
    # ============================================================
    # reflect_on_memory — rule-based fallback
    # ============================================================

    def test_rule_based_reflection_with_feedback(self):
        result = _rule_based_reflection(SAMPLE_3_ROUNDS)
        self.assertIsInstance(result["memory_summary"], str)
        self.assertGreater(len(result["memory_summary"]), 10)
        self.assertIn("天文", result["memory_summary"])
        # 规则模式下 liked[:3] 切片可能不包含所有项，只验证核心内容
        self.assertGreater(len(result["source_refs"]), 0)
        self.assertEqual(result["memory_strength"], 0.85)
        self.assertEqual(result["expires_after_turns"], 6)
        self.assertTrue(result["used_fallback"])
        self.assertIsNone(result["cleanup_reason"])
        self.assertEqual(result["status"], "active")

    def test_rule_based_reflection_no_feedback(self):
        result = _rule_based_reflection(SAMPLE_3_ROUNDS_NO_FEEDBACK)
        self.assertIn("未表达明确偏好", result["memory_summary"])
        self.assertEqual(result["memory_strength"], 0.30)
        self.assertEqual(result["expires_after_turns"], 3)
        self.assertEqual(result["status"], "insufficient_evidence")

    def test_rule_based_reflection_single_feedback(self):
        context = {
            "rounds": [
                {
                    "round": 1,
                    "run_id": "run_1",
                    "request_text": "test",
                    "recommended_event_titles": ["活动A"],
                    "feedback": {"liked": ["活动A"], "disliked": []},
                }
            ]
        }
        result = _rule_based_reflection(context)
        self.assertEqual(result["memory_strength"], 0.60)  # 1 feedback → 0.60

    def test_rule_based_reflection_empty_rounds(self):
        result = _rule_based_reflection({"rounds": []})
        self.assertIn("未表达", result["memory_summary"])
        self.assertEqual(result["memory_strength"], 0.30)

    def test_rule_based_reflection_non_dict_rounds(self):
        result = _rule_based_reflection({"rounds": ["not_a_dict", None, 123]})
        self.assertEqual(result["memory_strength"], 0.30)

    # ============================================================
    # 新输入字段：recommended_event_ids / liked_event_ids / disliked_event_ids
    # ============================================================

    def test_new_input_event_ids(self):
        """新契约输入：使用 recommended_event_ids / liked_event_ids / disliked_event_ids。"""
        context = {
            "rounds": [
                {
                    "round": 1,
                    "run_id": "run_new_1",
                    "request_text": "想看天文",
                    "recommended_event_ids": ["evt_001", "evt_002"],
                    "recommended_event_titles": ["观星", "讲座"],
                    "liked_event_ids": ["evt_001"],
                    "disliked_event_ids": ["evt_002"],
                }
            ]
        }
        result = _rule_based_reflection(context)
        self.assertEqual(result["status"], "active")
        # title_map 将 event_id 解析为标题
        self.assertIn("观星", result["memory_summary"])
        self.assertIn("讲座", result["memory_summary"])
        self.assertIn("run_new_1", result["source_refs"])

    def test_insufficient_evidence_keeps_old_summary(self):
        """证据不足时保留旧 summary（existing_memory_summary）。"""
        old_summary = "用户之前偏好天文观测活动。"
        context = {
            "rounds": [
                {
                    "round": 1,
                    "run_id": "run_x",
                    "request_text": "随便看看",
                    "recommended_event_ids": ["evt_1"],
                    "liked_event_ids": [],
                    "disliked_event_ids": [],
                }
            ],
            "existing_memory_summary": old_summary,
        }
        result = _rule_based_reflection(context)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["memory_summary"], old_summary)

    # ============================================================
    # _normalize_reflection
    # ============================================================

    def test_normalize_reflection_valid(self):
        parsed = {
            "memory_summary": "用户偏好天文和摄影",
            "source_refs": ["r1", "r2"],
            "memory_strength": 0.85,
            "expires_after_turns": 6,
            "cleanup_reason": None,
            "status": "active",
        }
        result = _normalize_reflection(parsed, {})
        self.assertEqual(result["memory_summary"], "用户偏好天文和摄影")
        self.assertEqual(result["memory_strength"], 0.85)
        self.assertEqual(result["expires_after_turns"], 6)
        self.assertFalse(result["used_fallback"])
        self.assertEqual(result["prompt_version"], PROMPT_VERSION)
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["model"], "deepseek-v4-pro")
        self.assertIsInstance(result["duration_ms"], int)
        self.assertIsInstance(result["retry_count"], int)

    def test_normalize_clamps_high_strength(self):
        result = _normalize_reflection({"memory_summary": "x", "memory_strength": 2.5}, {})
        self.assertEqual(result["memory_strength"], 1.0)

    def test_normalize_clamps_low_strength(self):
        result = _normalize_reflection({"memory_summary": "x", "memory_strength": -0.5}, {})
        self.assertEqual(result["memory_strength"], 0.0)

    def test_normalize_bad_types(self):
        result = _normalize_reflection(
            {"memory_summary": "x", "memory_strength": "not_a_number", "expires_after_turns": "bad", "source_refs": 123},
            {},
        )
        self.assertEqual(result["memory_strength"], 0.85)  # default
        self.assertEqual(result["expires_after_turns"], 6)   # default
        self.assertEqual(result["source_refs"], [])           # fallback to []

    def test_normalize_invalid_status_defaults_active(self):
        result = _normalize_reflection({"memory_summary": "x", "status": "bogus"}, {})
        self.assertEqual(result["status"], "active")

    def test_normalize_insufficient_evidence_with_rounds(self):
        """有 rounds 但无反馈时，active → insufficient_evidence。"""
        rounds = [{"run_id": "r1", "liked_event_ids": [], "disliked_event_ids": []}]
        result = _normalize_reflection(
            {"memory_summary": "x", "status": "active"}, {}, rounds=rounds
        )
        self.assertEqual(result["status"], "insufficient_evidence")

    # ============================================================
    # _empty_reflection
    # ============================================================

    def test_empty_reflection(self):
        result = _empty_reflection("no_context", "no rounds")
        self.assertEqual(result["memory_summary"], "")
        self.assertEqual(result["memory_strength"], 0.0)
        self.assertTrue(result["used_fallback"])
        self.assertEqual(result["cleanup_reason"], "no_context")
        self.assertEqual(result["status"], "no_context")

    # ============================================================
    # decay_memory_strength
    # ============================================================

    def test_decay_single_round(self):
        result = decay_memory_strength(SAMPLE_MEMORY_FOR_DECAY)
        self.assertAlmostEqual(result["memory_strength"], DECAY_1_ROUND_EXPECTED, places=2)
        self.assertIsNone(result["cleanup_reason"])  # still above threshold
        self.assertEqual(result["status"], "active")  # 未过期保持 active

    def test_decay_until_expired(self):
        mem = dict(SAMPLE_MEMORY_FOR_DECAY)
        expired = False
        for _ in range(DECAY_ROUNDS_UNTIL_EXPIRED + 5):
            mem = decay_memory_strength(mem)
            if mem.get("cleanup_reason") == "expired_below_threshold":
                expired = True
                self.assertEqual(mem["status"], "expired")
                break
        self.assertTrue(expired, "memory should eventually expire below threshold")

    def test_decay_preserves_other_fields(self):
        result = decay_memory_strength(SAMPLE_MEMORY_FOR_DECAY)
        self.assertEqual(result["memory_summary"], "测试记忆")
        self.assertEqual(result["expires_after_turns"], 6)
        self.assertEqual(result["prompt_version"], PROMPT_VERSION)

    # ============================================================
    # is_memory_expired
    # ============================================================

    def test_is_expired_below_threshold(self):
        mem = {"memory_summary": "x", "memory_strength": 0.10, "cleanup_reason": None}
        self.assertTrue(is_memory_expired(mem))

    def test_is_expired_with_reason(self):
        mem = {"memory_summary": "x", "memory_strength": 0.80, "cleanup_reason": "expired_below_threshold"}
        self.assertTrue(is_memory_expired(mem))

    def test_is_not_expired(self):
        mem = {"memory_summary": "x", "memory_strength": 0.85, "cleanup_reason": None}
        self.assertFalse(is_memory_expired(mem))

    def test_user_suppressed_is_not_auto_expired(self):
        # user_requested is a special case — frontend handles, not auto-expired
        mem = {"memory_summary": "x", "memory_strength": 0.0, "cleanup_reason": "user_requested"}
        result = is_memory_expired(mem)
        # User-requested cleanup returns False for is_memory_expired
        # because it's suppressed, not expired
        self.assertFalse(result, "user_requested mem should not be treated as auto-expired")

    # ============================================================
    # suppress_memory
    # ============================================================

    def test_suppress_memory(self):
        result = suppress_memory(SAMPLE_MEMORY_FOR_DECAY)
        self.assertEqual(result["cleanup_reason"], "user_requested")
        self.assertEqual(result["memory_strength"], 0.0)
        self.assertEqual(result["status"], "suppressed")

    # ============================================================
    # reflect_on_memory — integration (rule fallback, no API key)
    # ============================================================

    def test_reflect_on_memory_rule_fallback(self):
        result = reflect_on_memory(SAMPLE_3_ROUNDS, api_key="")
        self.assertTrue(result["used_fallback"])
        self.assertIn("天文", result["memory_summary"])
        self.assertEqual(result["prompt_version"], PROMPT_VERSION)
        self.assertEqual(result["status"], "active")

    def test_reflect_on_memory_api_key(self):
        result = reflect_on_memory(SAMPLE_3_ROUNDS, api_key="test-key")
        # 有 API key 会尝试调 LLM，这里网络不通会 fallback
        self.assertTrue(result.get("used_fallback") or not result.get("error"))

    # ============================================================
    # 契约字段完整性
    # ============================================================

    def test_reflection_contract_fields(self):
        result = reflect_on_memory(SAMPLE_3_ROUNDS, api_key="")
        missing = MEMORY_REFLECTION_CONTRACT_FIELDS - set(result.keys())
        self.assertEqual(missing, set(), f"memory_reflection 缺少契约字段: {missing}")

    # ============================================================
    # Meta
    # ============================================================

    def test_prompt_version_defined(self):
        self.assertEqual(PROMPT_VERSION, "2026-07-08-v1")

    def test_decay_constant(self):
        self.assertAlmostEqual(MEMORY_STRENGTH_DECAY, 0.85)


if __name__ == "__main__":
    unittest.main()
