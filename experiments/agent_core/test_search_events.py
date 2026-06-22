"""Unit tests for agent-core retrieval layer: search_events, filters, scoring."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure agent_core is importable
_EXPERIMENTS_ROOT = Path(__file__).resolve().parents[1]
if str(_EXPERIMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXPERIMENTS_ROOT))

from agent_core.filters import (
    apply_hard_constraints,
    filter_campus,
    filter_excluded_tags,
    filter_location,
    filter_source_evidence,
    filter_start_time,
)
from agent_core.freshness import event_freshness_score, has_future_events, needs_refresh
from agent_core.query import (
    HardConstraints,
    Intent,
    MatchedEvent,
    Memory,
    Pagination,
    Profile,
    SearchQuery,
    SearchResult,
    SoftPreferences,
)
from agent_core.scoring import score_and_sort
from agent_core.search_events import query_for_plan_day, search_events

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=TZ)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_event(
    *,
    event_id: str = "evt_test",
    title: str = "测试活动",
    start_time: str | None = "2026-06-05T14:00:00+08:00",
    end_time: str | None = "2026-06-05T16:00:00+08:00",
    campus: str = "邯郸",
    location: str | None = "邯郸校区测试场地",
    organizer: str | None = "测试主办方",
    tags: list[str] | None = None,
    source_url: str | None = "http://example.com/event",
    evidence_text: str | None = "原文片段",
    source_file: str = "test.txt",
    source_name: str | None = "测试来源",
) -> dict:
    return {
        "event_id": event_id,
        "source_file": source_file,
        "source_name": source_name,
        "source_url": source_url,
        "title": title,
        "summary": title,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "campus": campus,
        "organizer": organizer,
        "tags": tags or ["讲座"],
        "evidence_text": evidence_text,
    }


def assert_event_ids(self, result: SearchResult, expected_ids: list[str]) -> None:
    """Assert the event_ids in result.items match expected."""
    got = [item.event["event_id"] for item in result.items]
    self.assertEqual(got, expected_ids)


# ---------------------------------------------------------------------------
# Filter tests
# ---------------------------------------------------------------------------


class FilterStartTimeTest(unittest.TestCase):
    def test_past_event_rejected(self) -> None:
        event = make_event(start_time="2026-05-01T14:00:00+08:00")
        c = HardConstraints(exclude_past=True)
        ok, reason = filter_start_time(event, constraint=c, now=NOW)
        self.assertFalse(ok)
        self.assertEqual(reason, "past_event")

    def test_future_event_passes(self) -> None:
        event = make_event(start_time="2026-06-10T14:00:00+08:00")
        c = HardConstraints(exclude_past=True)
        ok, reason = filter_start_time(event, constraint=c, now=NOW)
        self.assertTrue(ok)

    def test_past_event_passes_when_exclude_past_false(self) -> None:
        event = make_event(start_time="2026-05-01T14:00:00+08:00")
        c = HardConstraints(exclude_past=False)
        ok, reason = filter_start_time(event, constraint=c, now=NOW)
        self.assertTrue(ok)

    def test_missing_start_time_rejected_when_required(self) -> None:
        event = make_event(start_time=None)
        c = HardConstraints(require_start_time=True)
        ok, reason = filter_start_time(event, constraint=c, now=NOW)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_start_time")

    def test_missing_start_time_passes_when_not_required(self) -> None:
        event = make_event(start_time=None)
        c = HardConstraints(require_start_time=False)
        ok, reason = filter_start_time(event, constraint=c, now=NOW)
        self.assertTrue(ok)

    def test_outside_date_window_before(self) -> None:
        event = make_event(start_time="2026-06-01T10:00:00+08:00")
        c = HardConstraints(start_time_after=NOW, exclude_past=False)
        ok, reason = filter_start_time(event, constraint=c, now=NOW)
        self.assertFalse(ok)
        self.assertEqual(reason, "outside_date_scope")

    def test_outside_date_window_after(self) -> None:
        event = make_event(start_time="2026-06-10T14:00:00+08:00")
        c = HardConstraints(start_time_before=datetime(2026, 6, 5, tzinfo=TZ))
        ok, reason = filter_start_time(event, constraint=c, now=NOW)
        self.assertFalse(ok)
        self.assertEqual(reason, "outside_date_scope")

    def test_within_date_window(self) -> None:
        event = make_event(start_time="2026-06-03T14:00:00+08:00")
        c = HardConstraints(
            start_time_after=datetime(2026, 6, 1, tzinfo=TZ),
            start_time_before=datetime(2026, 6, 5, tzinfo=TZ),
        )
        ok, reason = filter_start_time(event, constraint=c, now=NOW)
        self.assertTrue(ok)


class FilterCampusTest(unittest.TestCase):
    def test_campus_mismatch_rejected(self) -> None:
        event = make_event(campus="邯郸")
        c = HardConstraints(campuses=("江湾",))
        ok, reason = filter_campus(event, constraint=c)
        self.assertFalse(ok)
        self.assertEqual(reason, "campus_mismatch")

    def test_campus_match_passes(self) -> None:
        event = make_event(campus="邯郸")
        c = HardConstraints(campuses=("邯郸", "江湾"))
        ok, reason = filter_campus(event, constraint=c)
        self.assertTrue(ok)

    def test_empty_campuses_allows_all(self) -> None:
        event = make_event(campus="张江")
        c = HardConstraints(campuses=())
        ok, reason = filter_campus(event, constraint=c)
        self.assertTrue(ok)


class FilterLocationTest(unittest.TestCase):
    def test_missing_location_rejected_when_required(self) -> None:
        event = make_event(location=None)
        c = HardConstraints(require_location=True)
        ok, reason = filter_location(event, constraint=c)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_location")

    def test_online_event_passes_without_location(self) -> None:
        event = make_event(location=None, tags=["线上", "讲座"])
        c = HardConstraints(require_location=True)
        ok, reason = filter_location(event, constraint=c)
        self.assertTrue(ok)


class FilterSourceEvidenceTest(unittest.TestCase):
    def test_no_evidence_rejected_when_required(self) -> None:
        event = make_event(source_url=None, evidence_text=None)
        c = HardConstraints(require_source_evidence=True)
        ok, reason = filter_source_evidence(event, constraint=c)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_source_evidence")

    def test_source_url_sufficient(self) -> None:
        event = make_event(source_url="http://example.com", evidence_text=None)
        c = HardConstraints(require_source_evidence=True)
        ok, reason = filter_source_evidence(event, constraint=c)
        self.assertTrue(ok)


class FilterExcludedTagsTest(unittest.TestCase):
    def test_excluded_tag_triggers_rejection(self) -> None:
        event = make_event(title="AI 讲座", tags=["AI"])
        c = HardConstraints(exclude_tags=("AI",))
        ok, reason = filter_excluded_tags(event, constraint=c)
        self.assertFalse(ok)
        self.assertEqual(reason, "excluded_preference")

    def test_no_excluded_tags_passes(self) -> None:
        event = make_event(title="天文讲座", tags=["天文"])
        c = HardConstraints(exclude_tags=("AI",))
        ok, reason = filter_excluded_tags(event, constraint=c)
        self.assertTrue(ok)


class ApplyHardConstraintsTest(unittest.TestCase):
    def test_all_filters_applied(self) -> None:
        events = [
            make_event(event_id="e1", start_time="2026-06-03T14:00:00+08:00", campus="邯郸"),
            make_event(event_id="e2", start_time="2025-01-01T14:00:00+08:00", campus="邯郸"),  # past
            make_event(event_id="e3", start_time="2026-06-03T14:00:00+08:00", campus="江湾"),  # wrong campus
            make_event(event_id="e4", start_time=None, campus="邯郸"),  # no start_time
        ]
        c = HardConstraints(
            exclude_past=True,
            require_start_time=True,
            campuses=("邯郸",),
        )
        rejections: list[dict[str, str]] = []
        filtered = apply_hard_constraints(events, constraint=c, now=NOW, rejections=rejections)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["event_id"], "e1")
        reasons = {r["reason"] for r in rejections}
        self.assertIn("past_event", reasons)
        self.assertIn("campus_mismatch", reasons)
        self.assertIn("missing_start_time", reasons)


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------


class ScoringTest(unittest.TestCase):
    def test_interest_match_boosts_score(self) -> None:
        events = [
            make_event(event_id="e1", title="AI 大模型讲座", tags=["AI", "讲座"]),
            make_event(event_id="e2", title="体育比赛", tags=["体育"]),
        ]
        prefs = SoftPreferences(interest_terms=("AI", "大模型"))
        results = score_and_sort(events, preferences=prefs, now=NOW)
        self.assertEqual(len(results), 2)
        self.assertGreater(results[0].score, results[1].score)
        self.assertIn("AI", results[0].matched_terms)

    def test_preferred_campus_bonus(self) -> None:
        events = [
            make_event(event_id="e1", campus="江湾"),
            make_event(event_id="e2", campus="邯郸"),
        ]
        prefs = SoftPreferences(preferred_campuses=("江湾",))
        results = score_and_sort(events, preferences=prefs, now=NOW, home_campus="邯郸")
        # 江湾 should score higher due to preferred campus match
        jiangwan = next(r for r in results if r.event["event_id"] == "e1")
        handan = next(r for r in results if r.event["event_id"] == "e2")
        self.assertGreater(jiangwan.score, handan.score)

    def test_freshness_nearer_scores_higher(self) -> None:
        events = [
            make_event(event_id="e1", start_time="2026-06-02T14:00:00+08:00"),  # 1 day away
            make_event(event_id="e2", start_time="2026-06-08T14:00:00+08:00"),  # 7 days away
        ]
        prefs = SoftPreferences()
        results = score_and_sort(events, preferences=prefs, now=NOW)
        self.assertGreater(results[0].score, results[1].score)

    def test_empty_events(self) -> None:
        results = score_and_sort([], preferences=SoftPreferences(), now=NOW)
        self.assertEqual(len(results), 0)


# ---------------------------------------------------------------------------
# search_events integration tests
# ---------------------------------------------------------------------------


class SearchEventsTest(unittest.TestCase):
    def test_empty_input(self) -> None:
        q = SearchQuery()
        r = search_events([], query=q, now=NOW)
        self.assertEqual(r.total, 0)
        self.assertEqual(r.total_before_filter, 0)

    def test_all_rejected(self) -> None:
        events = [make_event(start_time=None)]  # will be rejected
        q = SearchQuery(hard=HardConstraints(require_start_time=True), include_debug=True)
        r = search_events(events, query=q, now=NOW)
        self.assertEqual(r.total, 0)
        self.assertEqual(len(r.rejections), 1)

    def test_pagination_first_page(self) -> None:
        events = [
            make_event(event_id=f"e{i}", start_time=f"2026-06-{i+3:02d}T14:00:00+08:00")
            for i in range(5)
        ]
        q = SearchQuery(
            hard=HardConstraints(exclude_past=False),
            pagination=Pagination(page=1, page_size=2),
        )
        r = search_events(events, query=q, now=NOW)
        self.assertEqual(len(r.items), 2)
        self.assertEqual(r.total, 5)
        self.assertEqual(r.page, 1)

    def test_pagination_second_page(self) -> None:
        events = [
            make_event(event_id=f"e{i}", start_time=f"2026-06-{i+3:02d}T14:00:00+08:00")
            for i in range(5)
        ]
        q = SearchQuery(
            hard=HardConstraints(exclude_past=False),
            pagination=Pagination(page=2, page_size=2),
        )
        r = search_events(events, query=q, now=NOW)
        self.assertEqual(len(r.items), 2)  # items 2-3
        self.assertEqual(r.total, 5)

    def test_pagination_past_end(self) -> None:
        events = [make_event(event_id="e1")]
        q = SearchQuery(
            hard=HardConstraints(exclude_past=False),
            pagination=Pagination(page=5, page_size=20),
        )
        r = search_events(events, query=q, now=NOW)
        self.assertEqual(len(r.items), 0)
        self.assertEqual(r.total, 1)

    def test_is_stale_with_future_events(self) -> None:
        events = [make_event(start_time="2026-06-03T14:00:00+08:00")]  # 2 days away, within 7d buffer
        q = SearchQuery()
        r = search_events(events, query=q, now=NOW)
        self.assertFalse(r.is_stale)

    def test_is_stale_with_all_past_events(self) -> None:
        events = [make_event(start_time="2025-01-01T14:00:00+08:00")]
        q = SearchQuery(hard=HardConstraints(exclude_past=False))
        r = search_events(events, query=q, now=NOW)
        self.assertTrue(r.is_stale)

    def test_debug_mode_excludes_rejections_by_default(self) -> None:
        events = [make_event(start_time=None)]
        q = SearchQuery()
        r = search_events(events, query=q, now=NOW)
        self.assertEqual(r.rejections, [])

    def test_debug_mode_includes_rejections(self) -> None:
        events = [make_event(start_time=None)]
        q = SearchQuery(hard=HardConstraints(require_start_time=True), include_debug=True)
        r = search_events(events, query=q, now=NOW)
        self.assertEqual(len(r.rejections), 1)


# ---------------------------------------------------------------------------
# query_for_plan_day tests
# ---------------------------------------------------------------------------


class QueryForPlanDayTest(unittest.TestCase):
    def test_builds_correct_hard_constraints(self) -> None:
        profile = {"campus": "邯郸", "interest_tags": ["天文"]}
        q = query_for_plan_day(
            date_scope="tomorrow",
            now=NOW,
            profile=profile,
            request_text="想看天文活动",
        )
        self.assertTrue(q.hard.exclude_past)
        self.assertTrue(q.hard.require_start_time)

    def test_builds_correct_soft_preferences(self) -> None:
        profile = {
            "campus": "邯郸",
            "interest_tags": ["天文", "讲座"],
            "activity_style_tags": ["轻松"],
            "preferred_campuses": ["邯郸", "江湾"],
            "available_time": "晚上",
        }
        q = query_for_plan_day(
            date_scope="this_week",
            now=NOW,
            profile=profile,
            request_text="这周想看天文活动",
        )
        self.assertIn("天文", q.soft.interest_terms)
        self.assertIn("讲座", q.soft.interest_terms)
        self.assertIn("轻松", q.soft.interest_terms)
        self.assertIn("邯郸", q.soft.preferred_campuses)
        self.assertIn("晚上", q.soft.preferred_time_of_day)

    def test_campus_request_from_text(self) -> None:
        profile = {"campus": "邯郸"}
        q = query_for_plan_day(
            date_scope="this_week",
            now=NOW,
            profile=profile,
            request_text="江湾校区有什么天文活动",
        )
        self.assertIn("江湾", q.hard.campuses)


# ---------------------------------------------------------------------------
# Freshness tests
# ---------------------------------------------------------------------------


class FreshnessTest(unittest.TestCase):
    def test_event_freshness_score_now(self) -> None:
        score = event_freshness_score(NOW, NOW)
        self.assertEqual(score, 1.0)  # 0 days away = 1 - 0/7 = 1

    def test_event_freshness_score_near(self) -> None:
        start = NOW + timedelta(days=1)
        score = event_freshness_score(start, NOW)
        self.assertAlmostEqual(score, 1.0 - 1.0 / 7.0, places=2)

    def test_event_freshness_score_far(self) -> None:
        start = NOW + timedelta(days=7)
        score = event_freshness_score(start, NOW)
        self.assertEqual(score, 0.0)

    def test_event_freshness_score_null(self) -> None:
        score = event_freshness_score(None, NOW)
        self.assertEqual(score, 0.0)

    def test_has_future_events_true(self) -> None:
        events = [make_event(start_time="2026-06-03T14:00:00+08:00")]
        self.assertTrue(has_future_events(events, now=NOW))

    def test_has_future_events_false(self) -> None:
        events = [make_event(start_time="2025-01-01T14:00:00+08:00")]
        self.assertFalse(has_future_events(events, now=NOW))

    def test_has_future_events_with_none_start(self) -> None:
        events = [make_event(start_time=None)]
        self.assertFalse(has_future_events(events, now=NOW))

    def test_needs_refresh_never_fetched(self) -> None:
        events = [make_event(start_time="2026-06-03T14:00:00+08:00")]
        self.assertTrue(needs_refresh(events, last_fetched_at=None, now=NOW))

    def test_needs_refresh_ttl_expired(self) -> None:
        events = [make_event(start_time="2026-06-03T14:00:00+08:00")]
        old_fetch = NOW - timedelta(hours=25)  # 25h ago > 24h TTL
        self.assertTrue(needs_refresh(events, last_fetched_at=old_fetch, now=NOW))

    def test_needs_refresh_no_future_events(self) -> None:
        events = [make_event(start_time="2025-01-01T14:00:00+08:00")]
        recent_fetch = NOW - timedelta(hours=1)  # fetched 1h ago but all events past
        self.assertTrue(needs_refresh(events, last_fetched_at=recent_fetch, now=NOW))

    def test_needs_refresh_false_when_fresh(self) -> None:
        events = [make_event(start_time="2026-06-03T14:00:00+08:00")]
        recent_fetch = NOW - timedelta(hours=1)
        self.assertFalse(needs_refresh(events, last_fetched_at=recent_fetch, now=NOW))


# ---------------------------------------------------------------------------
# V2 API tests (intent + profile + memory)
# ---------------------------------------------------------------------------


class V2ApiTest(unittest.TestCase):
    def test_intent_profile_search(self) -> None:
        events = [
            make_event(event_id="e1", title="AI 讲座", start_time="2026-06-05T14:00:00+08:00", campus="邯郸"),
            make_event(event_id="e2", title="音乐演出", start_time="2026-06-06T19:00:00+08:00", campus="江湾"),
        ]
        intent = Intent(request_text="想看AI讲座", date_scope="this_week")
        profile = Profile(campus="邯郸", interest_tags=("AI",), preferred_campuses=("邯郸",))
        result = search_events(events, intent=intent, profile=profile, now=NOW)
        self.assertGreaterEqual(result.total, 1)
        # e1 should rank higher (matches AI interest, home campus)
        self.assertIn("e1", [item.event["event_id"] for item in result.items])

    def test_profile_from_dict(self) -> None:
        d = {
            "campus": "江湾",
            "interest_tags": ["天文", "戏剧"],
            "preferred_campuses": ["江湾", "邯郸"],
            "available_time": "晚上",
            "activity_style_tags": ["轻松"],
            "excluded_tags": ["体育"],
            "excluded_keywords": ["考试"],
        }
        p = Profile.from_dict(d)
        self.assertEqual(p.campus, "江湾")
        self.assertIn("天文", p.interest_tags)
        self.assertIn("体育", p.excluded_tags)
        self.assertIn("考试", p.excluded_keywords)

    def test_profile_from_none(self) -> None:
        p = Profile.from_dict(None)
        self.assertEqual(p.campus, "")

    def test_excluded_keywords_rejected(self) -> None:
        events = [make_event(event_id="e1", title="考试通知", tags=["考试"])]
        intent = Intent(request_text="看活动", date_scope="this_week")
        profile = Profile(excluded_keywords=("考试",))
        result = search_events(events, intent=intent, profile=profile, now=NOW, include_debug=True)
        self.assertEqual(result.total, 0)

    def test_old_query_path_still_works(self) -> None:
        """Deprecated query=SearchQuery path still functional."""
        events = [make_event(event_id="e1", start_time="2026-06-05T14:00:00+08:00")]
        from agent_core.query import SearchQuery, HardConstraints, SoftPreferences
        q = SearchQuery(hard=HardConstraints(exclude_past=False))
        result = search_events(events, query=q, now=NOW)
        self.assertEqual(result.total, 1)


# ---------------------------------------------------------------------------
# FIXED_NOW tests
# ---------------------------------------------------------------------------


class FixedNowTest(unittest.TestCase):
    def setUp(self) -> None:
        # Save original
        self._orig = os.environ.pop("AGENT_FIXED_NOW", None)

    def tearDown(self) -> None:
        if self._orig is not None:
            os.environ["AGENT_FIXED_NOW"] = self._orig

    def test_fixed_now_activates(self) -> None:
        os.environ["AGENT_FIXED_NOW"] = "2026-06-01T12:00:00+08:00"
        from agent_core.time_provider import resolve_now
        now = resolve_now()
        self.assertEqual(now, NOW)

    def test_explicit_wins_over_fixed(self) -> None:
        os.environ["AGENT_FIXED_NOW"] = "2026-01-01T00:00:00+08:00"
        from agent_core.time_provider import resolve_now
        explicit = datetime(2026, 12, 25, tzinfo=TZ)
        now = resolve_now(explicit)
        self.assertEqual(now, explicit)

    def test_search_uses_fixed_now(self) -> None:
        os.environ["AGENT_FIXED_NOW"] = "2026-06-01T12:00:00+08:00"
        events = [make_event(event_id="e1", start_time="2026-05-01T14:00:00+08:00")]  # past
        intent = Intent(date_scope="this_week")
        result = search_events(events, intent=intent)
        self.assertEqual(result.total, 0)  # excluded as past


# ---------------------------------------------------------------------------
# Memory scoring tests (memory → score_and_sort integration)
# ---------------------------------------------------------------------------


class MemoryScoringTest(unittest.TestCase):
    """Tests for Memory-based soft adjustments in scoring (nested structure)."""

    def _memory(self, m: MatchedEvent) -> dict:
        return m.score_components.get("memory", {})

    # --- repeat_penalty ---

    def test_repeat_penalty_demotes_seen_event(self) -> None:
        """Events in memory.recent_plan_event_ids get lower scores."""
        events = [
            make_event(event_id="e1", title="AI 讲座", start_time="2026-06-05T14:00:00+08:00"),
            make_event(event_id="e2", title="AI 讲座", start_time="2026-06-06T14:00:00+08:00"),
        ]
        intent = Intent(request_text="AI", date_scope="this_week")
        profile = Profile(interest_tags=("AI",))
        memory = Memory(recent_plan_event_ids=("e1",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.items[0].event["event_id"], "e2")
        e1 = next(m for m in result.items if m.event["event_id"] == "e1")
        mem = self._memory(e1)
        self.assertIn("repeat_penalty", mem)
        self.assertAlmostEqual(mem["repeat_penalty"], -0.15)

    def test_repeat_penalty_no_match(self) -> None:
        """No penalty when event_id not in recent_plan_event_ids."""
        events = [
            make_event(event_id="e1", title="AI 讲座", start_time="2026-06-05T14:00:00+08:00"),
        ]
        intent = Intent(request_text="AI", date_scope="this_week")
        profile = Profile(interest_tags=("AI",))
        memory = Memory(recent_plan_event_ids=("e_other",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        self.assertNotIn("repeat_penalty", mem)

    # --- disliked_penalty ---

    def test_disliked_tags_penalty(self) -> None:
        events = [
            make_event(event_id="e1", title="AI 讲座", tags=["AI", "讲座"]),
            make_event(event_id="e2", title="音乐演出", tags=["音乐"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(disliked_tags=("AI",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.items[0].event["event_id"], "e2")
        e1 = next(m for m in result.items if m.event["event_id"] == "e1")
        mem = self._memory(e1)
        self.assertIn("disliked_penalty", mem)
        self.assertAlmostEqual(mem["disliked_penalty"], -0.10)

    def test_disliked_tags_capped_at_two(self) -> None:
        """Disliked penalty caps at -0.20 even with 3+ matching tags."""
        events = [
            make_event(event_id="e1", title="AI 大模型 编程", tags=["AI", "大模型", "编程"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(disliked_tags=("AI", "大模型", "编程"))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        self.assertIn("disliked_penalty", mem)
        self.assertAlmostEqual(mem["disliked_penalty"], -0.20)

    # --- liked_boost ---

    def test_liked_tags_boost(self) -> None:
        events = [
            make_event(event_id="e1", title="AI 讲座", tags=["AI", "讲座"]),
            make_event(event_id="e2", title="音乐演出", tags=["音乐"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(liked_tags=("音乐",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.items[0].event["event_id"], "e2")
        e2 = next(m for m in result.items if m.event["event_id"] == "e2")
        mem = self._memory(e2)
        self.assertIn("liked_boost", mem)
        self.assertAlmostEqual(mem["liked_boost"], 0.10)

    def test_liked_tags_capped_at_two(self) -> None:
        """Liked boost caps at +0.20 even with 3+ matching tags."""
        events = [
            make_event(event_id="e1", title="AI 大模型 编程", tags=["AI", "大模型", "编程"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(liked_tags=("AI", "大模型", "编程"))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        self.assertIn("liked_boost", mem)
        self.assertAlmostEqual(mem["liked_boost"], 0.20)

    # --- keyword_penalty ---

    def test_negative_keyword_penalty(self) -> None:
        events = [
            make_event(event_id="e1", title="考试辅导讲座"),
            make_event(event_id="e2", title="天文观测活动"),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(negative_keywords=("考试",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.items[0].event["event_id"], "e2")
        e1 = next(m for m in result.items if m.event["event_id"] == "e1")
        mem = self._memory(e1)
        self.assertIn("keyword_penalty", mem)
        self.assertAlmostEqual(mem["keyword_penalty"], -0.10)

    def test_keyword_penalty_capped(self) -> None:
        """Keyword penalty caps at -0.20 with 3+ matching keywords."""
        events = [
            make_event(event_id="e1", title="考试 收费 报名 讲座"),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(negative_keywords=("考试", "收费", "报名"))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        self.assertIn("keyword_penalty", mem)
        self.assertAlmostEqual(mem["keyword_penalty"], -0.20)

    def test_keyword_case_insensitive(self) -> None:
        """Negative keyword matching is case-insensitive."""
        events = [
            make_event(event_id="e1", title="Exam 考试"),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(negative_keywords=("EXAM", "考试"))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        self.assertIn("keyword_penalty", mem)
        self.assertAlmostEqual(mem["keyword_penalty"], -0.20)

    # --- empty / default memory ---

    def test_empty_memory_has_zero_memory_delta(self) -> None:
        """Empty Memory produces memory component with total_memory_delta=0."""
        events = [make_event(event_id="e1", title="活动")]
        intent = Intent(date_scope="this_week")
        result = search_events(events, intent=intent, now=NOW)
        self.assertEqual(result.total, 1)
        e1 = result.items[0]
        self.assertIn("memory", e1.score_components)
        mem = e1.score_components["memory"]
        self.assertIsInstance(mem, dict)
        self.assertEqual(mem.get("total_memory_delta"), 0.0)
        self.assertEqual(mem.get("matched_memory_terms"), [])

    def test_memory_default_constructor(self) -> None:
        """Memory() with no args must still work."""
        m = Memory()
        self.assertEqual(m.liked_tags, ())
        self.assertEqual(m.disliked_tags, ())
        self.assertEqual(m.negative_keywords, ())
        self.assertEqual(m.liked_event_ids, ())
        self.assertEqual(m.disliked_event_ids, ())
        self.assertEqual(m.recent_plan_event_ids, ())
        self.assertEqual(m.recent_query_texts, ())
        self.assertEqual(m.session_id, "")

    # --- soft vs hard boundary ---

    def test_penalty_does_not_exclude(self) -> None:
        """Memory penalties are soft -- events still appear in results."""
        events = [
            make_event(event_id="e1", title="考试通知", tags=["考试"]),
            make_event(event_id="e2", title="音乐会", tags=["音乐"]),
        ]
        intent = Intent(date_scope="this_week", max_items=10)
        profile = Profile()
        memory = Memory(disliked_tags=("考试",), recent_plan_event_ids=("e1",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        self.assertEqual(result.total, 2)

    def test_memory_penalty_vs_profile_exclusion(self) -> None:
        """Memory.disliked_tags is soft; Profile.excluded_keywords is hard rejection."""
        events = [make_event(event_id="e1", title="考试通知", tags=["考试"])]
        intent = Intent(date_scope="this_week")
        mem_result = search_events(
            events, intent=intent,
            profile=Profile(),
            memory=Memory(disliked_tags=("考试",)),
            now=NOW,
        )
        self.assertEqual(mem_result.total, 1, "memory penalty should not reject")
        prof_result = search_events(
            events, intent=intent,
            profile=Profile(excluded_keywords=("考试",)),
            now=NOW,
        )
        self.assertEqual(prof_result.total, 0, "profile excluded_keywords should reject")

    # --- stacking and total_memory_delta cap ---

    def test_multiple_penalties_stack(self) -> None:
        """All penalties stack but total_memory_delta clamped to [-0.30, +0.20]."""
        events = [
            make_event(event_id="e1", title="考试收费", tags=["考试"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(
            recent_plan_event_ids=("e1",),
            disliked_tags=("考试",),             # matches tag "考试"
            negative_keywords=("收费",),          # different term from disliked → not deduped
        )
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        self.assertGreaterEqual(e1.score, 0.0)
        self.assertLessEqual(e1.score, 1.0)
        mem = self._memory(e1)
        self.assertIn("repeat_penalty", mem)
        self.assertIn("disliked_penalty", mem)
        self.assertIn("keyword_penalty", mem)
        self.assertGreaterEqual(mem["total_memory_delta"], -0.30)

    def test_total_memory_delta_capped_at_minus_30(self) -> None:
        """When penalties would exceed -0.30, total_memory_delta clamps."""
        events = [
            make_event(event_id="e1", title="考试 收费 AI", tags=["考试", "收费", "AI"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(
            recent_plan_event_ids=("e1",),
            disliked_tags=("考试", "收费", "AI"),
            negative_keywords=("考试", "收费", "AI"),
        )
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        self.assertGreaterEqual(mem["total_memory_delta"], -0.30)
        self.assertGreaterEqual(e1.score, 0.0)

    def test_liked_and_disliked_net(self) -> None:
        """Liked boost and disliked penalty can coexist; net may be zero."""
        events = [
            make_event(event_id="e1", title="AI 讲座", tags=["AI"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(liked_tags=("AI",), disliked_tags=("AI",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        self.assertIn("liked_boost", mem)
        self.assertIn("disliked_penalty", mem)
        self.assertAlmostEqual(mem["liked_boost"] + mem["disliked_penalty"], 0.0)
        self.assertAlmostEqual(mem["total_memory_delta"], 0.0)

    def test_score_clamped_to_one(self) -> None:
        """Score never exceeds 1.0 even with heavy boost."""
        events = [
            make_event(
                event_id="e1", title="AI 大模型",
                start_time="2026-06-05T14:00:00+08:00",
                campus="邯郸", tags=["AI", "大模型"],
                source_url="http://example.com",
                evidence_text="原文",
                source_file="test.txt",
                organizer="主办方",
            ),
        ]
        intent = Intent(request_text="AI 大模型", date_scope="this_week")
        profile = Profile(
            campus="邯郸",
            interest_tags=("AI", "大模型"),
            preferred_campuses=("邯郸",),
        )
        memory = Memory(liked_tags=("AI", "大模型"))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        self.assertLessEqual(e1.score, 1.0)

    # --- NEW: nested structure ---

    def test_memory_component_is_nested(self) -> None:
        """score_components contains a 'memory' sub-dict with required keys."""
        events = [
            make_event(event_id="e1", title="AI 讲座", tags=["AI"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(liked_tags=("AI",), disliked_tags=("考试",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        self.assertIn("memory", e1.score_components)
        mem = e1.score_components["memory"]
        self.assertIsInstance(mem, dict)
        for key in ("total_memory_delta", "matched_memory_terms", "explanation", "details"):
            self.assertIn(key, mem, f"memory component missing key: {key}")

    # --- NEW: matched_memory_terms ---

    def test_matched_memory_terms_populated(self) -> None:
        """matched_memory_terms lists all matched signals."""
        events = [
            make_event(event_id="e1", title="AI 创业讲座", tags=["AI", "创业"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(liked_tags=("AI",), disliked_tags=("创业",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        terms = mem["matched_memory_terms"]
        self.assertTrue(any("喜欢:" in t for t in terms), f"expected liked term in {terms}")
        self.assertTrue(any("排除:" in t for t in terms), f"expected disliked term in {terms}")

    # --- NEW: explanation ---

    def test_explanation_not_empty_when_memory_active(self) -> None:
        """explanation is populated when memory adjustments are active."""
        events = [
            make_event(event_id="e1", title="AI 讲座", tags=["AI"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(liked_tags=("AI",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        self.assertTrue(len(mem["explanation"]) > 0, "explanation should not be empty")

    def test_explanation_empty_when_no_memory(self) -> None:
        """explanation is empty string when memory is empty."""
        events = [make_event(event_id="e1", title="活动")]
        intent = Intent(date_scope="this_week")
        result = search_events(events, intent=intent, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        self.assertEqual(mem["explanation"], "")

    # --- NEW: details per adjustment ---

    def test_memory_details_per_adjustment(self) -> None:
        """Each memory adjustment has a corresponding detail entry."""
        events = [
            make_event(event_id="e1", title="AI 创业讲座", tags=["AI", "创业"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(
            liked_tags=("AI",),
            disliked_tags=("创业",),
            recent_plan_event_ids=("e1",),
        )
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        details = mem["details"]
        self.assertIsInstance(details, list)
        detail_types = {d["type"] for d in details}
        self.assertIn("liked_boost", detail_types)
        self.assertIn("disliked_penalty", detail_types)
        self.assertIn("repeat_penalty", detail_types)
        for d in details:
            for key in ("type", "delta", "matched", "matched_field", "source", "reason"):
                self.assertIn(key, d, f"detail missing key: {key}")

    # --- NEW: event_id similarity ---

    def test_liked_event_ids_extract_tags(self) -> None:
        """Events similar to liked_event_ids get a boost via shared tags."""
        events = [
            make_event(event_id="e1", title="科技讲座", tags=["科技"]),
            make_event(event_id="e_liked", title="科技峰会", tags=["科技", "AI"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(liked_event_ids=("e_liked",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        self.assertEqual(result.total, 2)
        e1 = next(m for m in result.items if m.event["event_id"] == "e1")
        mem = self._memory(e1)
        self.assertIn("liked_boost", mem)
        self.assertGreater(mem["liked_boost"], 0)
        liked_details = [d for d in mem["details"] if d["type"] == "liked_boost"]
        self.assertTrue(any("liked_event_ids" in d.get("source", "") for d in liked_details))

    def test_disliked_event_ids_extract_tags(self) -> None:
        """Events similar to disliked_event_ids get penalized via shared tags."""
        events = [
            make_event(event_id="e1", title="创业讲座", tags=["创业"]),
            make_event(event_id="e_disliked", title="创业峰会", tags=["创业", "商业"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(disliked_event_ids=("e_disliked",))
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        self.assertEqual(result.total, 2)
        e1 = next(m for m in result.items if m.event["event_id"] == "e1")
        mem = self._memory(e1)
        self.assertIn("disliked_penalty", mem)
        self.assertLess(mem["disliked_penalty"], 0)

    # --- NEW: timings ---

    def test_timings_in_search_result(self) -> None:
        """SearchResult includes timings_ms with key phases."""
        events = [make_event(event_id="e1", title="活动", start_time="2026-06-05T14:00:00+08:00")]
        intent = Intent(date_scope="this_week")
        result = search_events(events, intent=intent, now=NOW)
        self.assertIn("hard_constraints", result.timings_ms)
        self.assertIn("score_and_sort", result.timings_ms)
        self.assertIn("filter_and_score", result.timings_ms)
        self.assertIn("search_events_total", result.timings_ms)
        self.assertGreater(result.timings_ms["search_events_total"], 0)

    # --- NEW: dedup between disliked_penalty and keyword_penalty ---

    def test_keyword_dedup_with_disliked_tags(self) -> None:
        """Same term in disliked_tags and negative_keywords penalized only once."""
        events = [
            make_event(event_id="e1", title="创业路演大赛", tags=["创业"]),
            make_event(event_id="e2", title="天文观测", tags=["天文"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(
            disliked_tags=("创业",),
            negative_keywords=("创业",),  # same term as disliked → should be deduped
        )
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        self.assertEqual(result.total, 2)
        e1 = next(m for m in result.items if m.event["event_id"] == "e1")
        mem = self._memory(e1)
        # disliked_penalty should exist (matched via tag)
        self.assertIn("disliked_penalty", mem)
        self.assertAlmostEqual(mem["disliked_penalty"], -0.10)
        # keyword_penalty should NOT exist (deduped because "创业" already matched as disliked tag)
        self.assertNotIn("keyword_penalty", mem)
        # Only one "排除:创业" entry
        terms = mem["matched_memory_terms"]
        self.assertEqual(terms.count("排除:创业"), 1, f"expected 1 '排除:创业', got {terms}")

    def test_keyword_no_dedup_when_disliked_not_matched(self) -> None:
        """Keyword NOT in disliked_tags is penalized normally."""
        events = [
            make_event(event_id="e1", title="考试报名通知"),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(
            disliked_tags=("创业",),              # "创业" not in event
            negative_keywords=("考试",),          # "考试" IS in title
        )
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        # disliked_penalty should NOT exist (no match)
        self.assertNotIn("disliked_penalty", mem)
        # keyword_penalty should exist (normal operation, no dedup needed)
        self.assertIn("keyword_penalty", mem)
        self.assertAlmostEqual(mem["keyword_penalty"], -0.10)

    def test_keyword_dedup_case_insensitive(self) -> None:
        """Dedup between disliked and keyword is case-insensitive."""
        events = [
            make_event(event_id="e1", title="ENTREPRENEURSHIP 创业", tags=["ENTREPRENEURSHIP"]),
        ]
        intent = Intent(date_scope="this_week")
        profile = Profile()
        memory = Memory(
            disliked_tags=("entrepreneurship",),  # matches "ENTREPRENEURSHIP" in tags
            negative_keywords=("Entrepreneurship",),  # same, different case → deduped
        )
        result = search_events(events, intent=intent, profile=profile, memory=memory, now=NOW)
        e1 = result.items[0]
        mem = self._memory(e1)
        self.assertIn("disliked_penalty", mem)
        self.assertNotIn("keyword_penalty", mem, "keyword should be deduped (case-insensitive)")

    # --- NEW: ScoringMemory / DisplayMemory ---

    def test_scoring_memory_from_memory(self) -> None:
        """ScoringMemory.from_memory() extracts scoring-relevant fields."""
        from agent_core.query import ScoringMemory
        m = Memory(
            liked_tags=("AI", "展览"),
            disliked_tags=("创业",),
            negative_keywords=("收费",),
            liked_event_ids=("e1", "e2"),
            disliked_event_ids=("e3",),
            recent_plan_event_ids=("e4",),
            recent_query_texts=("test",),           # NOT in ScoringMemory
            session_id="sess-123",                  # NOT in ScoringMemory
        )
        sm = ScoringMemory.from_memory(m)
        self.assertEqual(sm.liked_tags, ("AI", "展览"))
        self.assertEqual(sm.disliked_tags, ("创业",))
        self.assertEqual(sm.negative_keywords, ("收费",))
        self.assertEqual(sm.liked_event_ids, ("e1", "e2"))
        self.assertEqual(sm.disliked_event_ids, ("e3",))
        self.assertEqual(sm.recent_plan_event_ids, ("e4",))

    def test_scoring_memory_cache_hash_stable(self) -> None:
        """Same ScoringMemory fields → same cache_hash."""
        from agent_core.query import ScoringMemory
        sm1 = ScoringMemory(liked_tags=("AI", "展览"), disliked_tags=("创业",))
        sm2 = ScoringMemory(liked_tags=("AI", "展览"), disliked_tags=("创业",))
        self.assertEqual(sm1.cache_hash(), sm2.cache_hash())

    def test_scoring_memory_cache_hash_changes(self) -> None:
        """Different ScoringMemory fields → different cache_hash."""
        from agent_core.query import ScoringMemory
        sm1 = ScoringMemory(liked_tags=("AI", "展览"), disliked_tags=("创业",))
        sm2 = ScoringMemory(liked_tags=("展览",), disliked_tags=("创业",))
        self.assertNotEqual(sm1.cache_hash(), sm2.cache_hash())

    def test_display_memory_from_memory(self) -> None:
        """DisplayMemory.from_memory() extracts display-relevant fields."""
        from agent_core.query import DisplayMemory
        m = Memory(
            recent_query_texts=("test query",),
            liked_tags=("AI", "展览"),
            disliked_tags=("创业",),
            negative_keywords=("收费",),            # NOT in DisplayMemory
            liked_event_ids=("e1",),                # NOT in DisplayMemory
        )
        dm = DisplayMemory.from_memory(m)
        self.assertEqual(dm.recent_query_texts, ("test query",))
        self.assertEqual(dm.liked_tags, ("AI", "展览"))
        self.assertEqual(dm.disliked_tags, ("创业",))

    def test_display_memory_cache_hash_stable(self) -> None:
        """Same DisplayMemory fields → same cache_hash."""
        from agent_core.query import DisplayMemory
        dm1 = DisplayMemory(
            recent_query_texts=("q1", "q2"),
            liked_tags=("AI",),
            disliked_tags=("创业",),
        )
        dm2 = DisplayMemory(
            recent_query_texts=("q1", "q2"),
            liked_tags=("AI",),
            disliked_tags=("创业",),
        )
        self.assertEqual(dm1.cache_hash(), dm2.cache_hash())

    def test_scoring_memory_default_empty(self) -> None:
        """ScoringMemory() with no args has empty fields and valid hash."""
        from agent_core.query import ScoringMemory
        sm = ScoringMemory()
        self.assertEqual(sm.liked_tags, ())
        self.assertEqual(sm.cache_hash(), ScoringMemory().cache_hash())

    def test_display_memory_default_empty(self) -> None:
        """DisplayMemory() with no args has empty fields and valid hash."""
        from agent_core.query import DisplayMemory
        dm = DisplayMemory()
        self.assertEqual(dm.recent_query_texts, ())
        self.assertEqual(dm.cache_hash(), DisplayMemory().cache_hash())


if __name__ == "__main__":
    unittest.main()
