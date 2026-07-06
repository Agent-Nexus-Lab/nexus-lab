from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from intent_parser import parse_intent, to_agent_intent, to_agent_intent_extended
from schemas import IntentParseOutput


EVAL_PATH = _SCRIPT_DIR / "eval.json"


class IntentParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(EVAL_PATH, encoding="utf-8") as f:
            cls.eval_cases = json.load(f)

    def test_eval_dataset_not_empty(self):
        self.assertGreaterEqual(len(self.eval_cases), 17, "评测集至少需要 17 条用例")

    def test_001_clear_time_interest_style_campus(self):
        case = self._get_case("eval_001")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertEqual(result.explicit_campuses, exp["explicit_campuses"])
        self.assertTrue(result.time_preference.afternoon)
        for tag in exp["interest_tag_includes"]:
            self.assertIn(tag, result.interest_tags)
        for tag in exp["style_tag_includes"]:
            self.assertIn(tag, result.style_tags)

    def test_002_ai_evening_exclude_lecture(self):
        case = self._get_case("eval_002")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertTrue(result.time_preference.evening)
        self.assertIn("AI", result.interest_tags)

        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values,
                          f"expected hard constraint '{exp['hard_constraint_contains']}' in {values}")

        self.assertGreaterEqual(len(result.soft_constraints), exp["min_soft_constraints"])

    def test_003_weekend_multi_interest_multi_campus(self):
        case = self._get_case("eval_003")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertTrue(result.time_preference.weekend)
        for tag in exp["interest_tag_includes"]:
            self.assertIn(tag, result.interest_tags)
        for campus in exp["explicit_campuses"]:
            self.assertIn(campus, result.explicit_campuses)

    def test_004_specific_campus_multi_interest_exclude(self):
        case = self._get_case("eval_004")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        for tag in exp["interest_tag_includes"]:
            self.assertIn(tag, result.interest_tags)
        self.assertIn("邯郸", result.explicit_campuses)

        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values)

    def test_005_tomorrow_evening_love_astronomy(self):
        case = self._get_case("eval_005")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertTrue(result.time_preference.evening)
        self.assertIn("天文", result.interest_tags)
        self.assertIn("互动", result.style_tags)

        self.assertGreaterEqual(len(result.soft_constraints), exp["min_soft_constraints"])
        if exp.get("soft_weight_ge_1_5"):
            weights = [s.weight for s in result.soft_constraints]
            self.assertTrue(any(w >= 1.5 for w in weights),
                            f"expected soft constraint with weight >= 1.5, got {weights}")

    def test_006_vague_query(self):
        case = self._get_case("eval_006")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertEqual(result.explicit_campuses, [])
        self.assertEqual(result.interest_tags, [])
        self.assertEqual(result.style_tags, [])
        self.assertEqual(result.hard_constraints, [])
        self.assertEqual(result.soft_constraints, [])
        self.assertTrue(result.parsed_successfully)

    def test_007_multi_interest_style_count(self):
        case = self._get_case("eval_007")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertTrue(result.time_preference.afternoon)
        interest_set = set(result.interest_tags)
        for tag in exp["interest_tag_includes"]:
            self.assertIn(tag, interest_set)
        self.assertIn("轻松", result.style_tags)
        self.assertEqual(result.max_items, exp["max_items"])

    # --- 第二阶段新增测试 (eval_008 ~ eval_015) ---

    def test_008_switch_and_exclude_repeat(self):
        case = self._get_case("eval_008")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertEqual(result.explicit_campuses, exp["explicit_campuses"])
        self.assertEqual(result.interest_tags, exp["interest_tag_includes"])
        self.assertEqual(result.style_tags, exp["style_tag_includes"])
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])

    def test_009_no_hard_and_easy_style(self):
        case = self._get_case("eval_009")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertIn("轻松", result.style_tags)
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values)
        self.assertGreaterEqual(len(result.soft_constraints), exp["min_soft_constraints"])

    def test_010_prefer_ai_exclude_lecture(self):
        case = self._get_case("eval_010")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertIn("AI", result.interest_tags)
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values)
        self.assertGreaterEqual(len(result.soft_constraints), exp["min_soft_constraints"])
        if exp.get("soft_weight_ge_1_5"):
            weights = [s.weight for s in result.soft_constraints]
            self.assertTrue(any(w >= 1.5 for w in weights),
                            f"expected soft constraint with weight >= 1.5, got {weights}")

    def test_011_exclude_graduation_season(self):
        case = self._get_case("eval_011")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values)

    def test_012_switch_different_and_feedback(self):
        case = self._get_case("eval_012")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertEqual(result.interest_tags, exp["interest_tag_includes"])
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values)

    def test_013_exclude_sports_prefer_workshop_easy(self):
        case = self._get_case("eval_013")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertIn("工作坊", result.interest_tags)
        self.assertIn("轻松", result.style_tags)
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values)
        self.assertGreaterEqual(len(result.soft_constraints), exp["min_soft_constraints"])

    def test_014_stop_push_lecture_multi_interest(self):
        case = self._get_case("eval_014")
        result = parse_intent(case["query"])
        exp = case["expected"]
        interest_set = set(result.interest_tags)
        for tag in exp["interest_tag_includes"]:
            self.assertIn(tag, interest_set)
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        self.assertGreaterEqual(len(result.soft_constraints), exp["min_soft_constraints"])

    def test_015_want_fresh_avoid_repeat(self):
        case = self._get_case("eval_015")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values)
        self.assertGreaterEqual(len(result.soft_constraints), exp["min_soft_constraints"])

    # --- 第二阶段补充：反馈语义用例 (eval_016 ~ eval_020) ---

    def test_016_exclude_startup_roadshow(self):
        case = self._get_case("eval_016")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertIn("创业", result.interest_tags)
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values)
        self.assertGreaterEqual(len(result.soft_constraints), exp["min_soft_constraints"])

    def test_017_exclude_too_commercial(self):
        case = self._get_case("eval_017")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertEqual(result.interest_tags, exp["interest_tag_includes"])
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values)
        # 核心断言："不想XX"中的XX不应进入软偏好
        self.assertEqual(len(result.soft_constraints), 0)

    def test_018_prefer_ai_exhibition(self):
        case = self._get_case("eval_018")
        result = parse_intent(case["query"])
        exp = case["expected"]
        interest_set = set(result.interest_tags)
        for tag in exp["interest_tag_includes"]:
            self.assertIn(tag, interest_set)
        self.assertEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        self.assertGreaterEqual(len(result.soft_constraints), exp["min_soft_constraints"])
        if exp.get("soft_weight_ge_1_5"):
            weights = [s.weight for s in result.soft_constraints]
            self.assertTrue(any(w >= 1.5 for w in weights),
                            f"expected soft constraint with weight >= 1.5, got {weights}")

    def test_019_exclude_too_far_afternoon(self):
        case = self._get_case("eval_019")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertTrue(result.time_preference.afternoon)
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values)

    def test_020_exclude_repeat_feedback_semantics(self):
        case = self._get_case("eval_020")
        result = parse_intent(case["query"])
        exp = case["expected"]
        self.assertEqual(result.date_scope, exp["date_scope"])
        self.assertGreaterEqual(len(result.hard_constraints), exp["min_hard_constraints"])
        if "hard_constraint_contains" in exp:
            values = [c.value for c in result.hard_constraints]
            self.assertIn(exp["hard_constraint_contains"], values)
        self.assertEqual(len(result.soft_constraints), exp["min_soft_constraints"])

    def test_empty_query(self):
        result = parse_intent("")
        self.assertFalse(result.parsed_successfully)
        self.assertIn("query 为空", result.parse_warnings)

    def test_all_eval_cases_parse_successfully(self):
        for case in self.eval_cases:
            with self.subTest(case_id=case["id"]):
                result = parse_intent(case["query"])
                self.assertTrue(result.parsed_successfully, f"{case['id']}: {result.parse_warnings}")
                self.assertIsInstance(result.date_scope, str)
                self.assertIsInstance(result.explicit_campuses, list)
                self.assertIsInstance(result.hard_constraints, list)
                self.assertIsInstance(result.soft_constraints, list)

    def test_to_agent_intent_output_format(self):
        result = parse_intent("今天下午在江湾有没有天文活动")
        agent_intent = to_agent_intent(result)
        self.assertEqual(agent_intent["request_text"], "今天下午在江湾有没有天文活动")
        self.assertEqual(agent_intent["date_scope"], "today")
        self.assertIsInstance(agent_intent["explicit_campuses"], tuple)
        self.assertIn("江湾", agent_intent["explicit_campuses"])
        self.assertEqual(agent_intent["max_items"], 4)

    def test_to_agent_intent_extended_includes_hard_soft(self):
        result = parse_intent("今晚想看AI但不要讲座的活动")
        extended = to_agent_intent_extended(result)
        self.assertIn("hard_constraints", extended)
        self.assertIn("soft_constraints", extended)
        self.assertGreaterEqual(len(extended["hard_constraints"]), 1)

    def test_fuzzy_query_returns_empty_arrays(self):
        result = parse_intent("最近有什么活动")
        self.assertEqual(result.interest_tags, [])
        self.assertEqual(result.style_tags, [])
        self.assertEqual(result.explicit_campuses, [])
        self.assertEqual(result.hard_constraints, [])
        self.assertEqual(result.soft_constraints, [])

    def test_max_items_parsing(self):
        result = parse_intent("推荐3个活动")
        self.assertEqual(result.max_items, 3)
        result = parse_intent("想看5个AI活动")
        self.assertEqual(result.max_items, 5)
        result = parse_intent("推荐20个活动")
        self.assertEqual(result.max_items, 10)

    def test_hard_constraints_exclude_keywords(self):
        result = parse_intent("不要讲座，别去讨论会，不想运动")
        values = {c.value for c in result.hard_constraints if c.field == "excluded_keywords"}
        self.assertIn("讲座", values)
        self.assertIn("讨论会", values)
        self.assertIn("运动", values)

    def test_soft_constraints_weight_levels(self):
        result = parse_intent("特别喜欢天文，喜欢AI，不太喜欢体育")
        weights = {c.value: c.weight for c in result.soft_constraints}
        self.assertGreaterEqual(weights.get("天文", 0), 1.5)
        self.assertGreaterEqual(weights.get("AI", 0), 1.0)
        self.assertGreaterEqual(weights.get("体育", 0), 0.5)

    def test_hard_constraints_empty_on_plain_query(self):
        result = parse_intent("今天下午有什么活动")
        self.assertEqual(result.hard_constraints, [])
        self.assertEqual(result.soft_constraints, [])

    def _get_case(self, case_id: str) -> dict:
        for case in self.eval_cases:
            if case["id"] == case_id:
                return case
        raise KeyError(f"eval case not found: {case_id}")


if __name__ == "__main__":
    unittest.main()
