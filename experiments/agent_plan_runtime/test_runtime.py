from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime import commute_minutes, load_events, load_profile, normalize_campus, parse_now, plan_day


ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = ROOT / "experiments" / "agent_maas_cli" / "outputs" / "events.json"
PROFILE_PATH = ROOT / "experiments" / "agent_plan_runtime" / "profile.sample.json"


def sample_event(
    event_id: str,
    *,
    title: str,
    start_time: str,
    end_time: str | None,
    campus: str,
    tags: list[str] | None = None,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "source_file": "unit.txt",
        "source_name": "unit",
        "source_url": None,
        "title": title,
        "summary": title,
        "start_time": start_time,
        "end_time": end_time,
        "location": f"{campus}测试地点",
        "campus": campus,
        "organizer": "unit",
        "tags": tags or ["天文"],
        "evidence_text": title,
    }


class RuntimeTest(unittest.TestCase):
    def test_real_events_use_campus_enum(self) -> None:
        events = load_events(EVENTS_PATH)
        self.assertGreater(len(events), 0)
        self.assertFalse([event for event in events if not event.get("campus")])
        allowed_campuses = {"邯郸", "江湾", "枫林", "张江", "其他"}
        self.assertFalse([event for event in events if event.get("campus") not in allowed_campuses])

    def test_campus_normalization_and_commute_matrix(self) -> None:
        self.assertEqual(normalize_campus("江湾校区"), "江湾")
        self.assertEqual(normalize_campus("邯郸校区"), "邯郸")
        self.assertEqual(commute_minutes("邯郸校区", "江湾"), 30)
        self.assertEqual(commute_minutes("邯郸", "枫林校区"), 60)
        self.assertEqual(commute_minutes("江湾", "江湾校区"), 15)
        self.assertEqual(commute_minutes("江湾", "张江"), 60)

    def test_real_now_returns_no_future_sample_events(self) -> None:
        result = plan_day(
            events=load_events(EVENTS_PATH),
            profile=load_profile(PROFILE_PATH),
            request_text="想看天文活动",
            date_scope="this_week",
            now=parse_now("2026-06-25T00:00:00+08:00"),
            include_debug=True,
        )
        self.assertEqual(result["data"]["status"], "failed")
        self.assertIn("past_event", result["data"]["debug"]["rejection_counts"])

    def test_sample_data_recommends_tianwen_with_reference_now(self) -> None:
        result = plan_day(
            events=load_events(EVENTS_PATH),
            profile=load_profile(PROFILE_PATH),
            request_text="这周想看天文活动，最好轻松一点",
            date_scope="this_week",
            now=parse_now("2026-06-15T12:00:00+08:00"),
        )
        self.assertEqual(result["data"]["status"], "completed")
        items = result["data"]["items"]
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(any("天文" in item["title"] or "天文" in item["tags"] for item in items))

    def test_cross_campus_requires_thirty_minute_buffer(self) -> None:
        profile = {"campus": "邯郸", "interest_tags": ["天文"], "preferred_campuses": ["邯郸", "江湾"]}
        events = [
            sample_event(
                "evt_h",
                title="邯郸天文活动",
                start_time="2026-05-10T10:00:00+08:00",
                end_time="2026-05-10T10:30:00+08:00",
                campus="邯郸校区",
            ),
            sample_event(
                "evt_j",
                title="江湾天文活动",
                start_time="2026-05-10T10:50:00+08:00",
                end_time="2026-05-10T11:30:00+08:00",
                campus="江湾校区",
            ),
        ]
        result = plan_day(
            events=events,
            profile=profile,
            request_text="想看天文活动",
            date_scope="this_week",
            now=parse_now("2026-05-09T12:00:00+08:00"),
            include_debug=True,
        )
        self.assertEqual(len(result["data"]["items"]), 1)
        self.assertIn("required_30min", result["data"]["debug"]["schedule_skips"][0]["reason"])

        events[1]["start_time"] = "2026-05-10T11:00:00+08:00"
        result = plan_day(
            events=events,
            profile=profile,
            request_text="想看天文活动",
            date_scope="this_week",
            now=parse_now("2026-05-09T12:00:00+08:00"),
        )
        self.assertEqual(len(result["data"]["items"]), 2)

    def test_unknown_cross_campus_commute_defaults_to_sixty_minutes(self) -> None:
        profile = {"campus": "邯郸", "interest_tags": ["天文"], "preferred_campuses": ["邯郸", "张江"]}
        events = [
            sample_event(
                "evt_h",
                title="邯郸天文活动",
                start_time="2026-05-10T10:00:00+08:00",
                end_time="2026-05-10T10:30:00+08:00",
                campus="邯郸校区",
            ),
            sample_event(
                "evt_z",
                title="张江天文活动",
                start_time="2026-05-10T11:00:00+08:00",
                end_time="2026-05-10T11:30:00+08:00",
                campus="张江校区",
            ),
        ]
        result = plan_day(
            events=events,
            profile=profile,
            request_text="想看天文活动",
            date_scope="this_week",
            now=parse_now("2026-05-09T12:00:00+08:00"),
            include_debug=True,
        )
        self.assertEqual(len(result["data"]["items"]), 1)
        self.assertIn("required_60min", result["data"]["debug"]["schedule_skips"][0]["reason"])

    def test_llm_unknown_event_id_is_ignored(self) -> None:
        events = [
            sample_event(
                "evt_h",
                title="邯郸天文活动",
                start_time="2026-05-10T10:00:00+08:00",
                end_time="2026-05-10T10:30:00+08:00",
                campus="邯郸校区",
            )
        ]

        def bad_rewriter(_result):
            return {
                "summary": "改写后的摘要",
                "reasons": [{"event_id": "missing", "reason_text": "不应该写入"}],
            }

        result = plan_day(
            events=events,
            profile={"campus": "邯郸", "interest_tags": ["天文"], "preferred_campuses": ["邯郸"]},
            request_text="想看天文活动",
            date_scope="this_week",
            now=parse_now("2026-05-09T12:00:00+08:00"),
            include_debug=True,
            rewriter=bad_rewriter,
        )
        self.assertEqual(result["data"]["summary"], "改写后的摘要")
        self.assertNotEqual(result["data"]["items"][0]["reason_text"], "不应该写入")
        self.assertEqual(result["data"]["debug"]["llm_invalid_event_ids"], ["missing"])

    def test_rewrite_fallback_on_timeout(self) -> None:
        """LLM rewrite exception → used_fallback=true, plan_day still completed."""
        events = [
            sample_event(
                "evt_h",
                title="邯郸天文活动",
                start_time="2026-05-10T10:00:00+08:00",
                end_time="2026-05-10T10:30:00+08:00",
                campus="邯郸校区",
            )
        ]

        def failing_rewriter(_result):
            raise RuntimeError("simulated timeout")

        result = plan_day(
            events=events,
            profile={"campus": "邯郸", "interest_tags": ["天文"], "preferred_campuses": ["邯郸"]},
            request_text="想看天文活动",
            date_scope="this_week",
            now=parse_now("2026-05-09T12:00:00+08:00"),
            include_debug=True,
            rewriter=failing_rewriter,
        )
        self.assertEqual(result["data"]["status"], "completed")
        self.assertTrue(result["data"]["debug"]["used_fallback"])
        self.assertIn("simulated timeout", result["data"]["debug"]["llm_error"])
        # 模板 summary 仍然存在
        self.assertIsInstance(result["data"]["summary"], str)
        self.assertGreater(len(result["data"]["summary"]), 0)

    def test_rewrite_disabled_has_readable_summary(self) -> None:
        """rewriter=None → 模板 summary/reason fallback 可读."""
        events = [
            sample_event(
                "evt_h",
                title="邯郸天文活动",
                start_time="2026-05-10T10:00:00+08:00",
                end_time="2026-05-10T10:30:00+08:00",
                campus="邯郸校区",
            )
        ]
        result = plan_day(
            events=events,
            profile={"campus": "邯郸", "interest_tags": ["天文"], "preferred_campuses": ["邯郸"]},
            request_text="想看天文活动",
            date_scope="this_week",
            now=parse_now("2026-05-09T12:00:00+08:00"),
            rewriter=None,
        )
        self.assertEqual(result["data"]["status"], "completed")
        summary = result["data"]["summary"]
        self.assertIsInstance(summary, str)
        self.assertIn("活动", summary)
        self.assertIn("天文", summary)
        # reason_text 来自模板
        reason = result["data"]["items"][0]["reason_text"]
        self.assertIn("邯郸", reason)
        self.assertIn("评分", reason)


if __name__ == "__main__":
    unittest.main()
