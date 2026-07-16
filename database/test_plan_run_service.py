from __future__ import annotations

import json
import os
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from database import plan_run_service
from database.models import Event, PlanRun, User, UserProfile


REFERENCE_NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)


class FakeIntent:
    def model_dump(self):
        return {"date_scope": "today"}


class FakePlanResponse:
    def __init__(self, *, cache_hit=False):
        self.cache_hit = cache_hit

    def model_dump(self, mode="python"):
        return {
            "code": 0,
            "data": {
                "title": "Plan",
                "summary": "Summary",
                "date_scope": "today",
                "items": [{
                    "event_id": "event-1",
                    "start_time": "2026-07-15T10:00:00+00:00",
                    "end_time": "2026-07-15T11:00:00+00:00",
                    "reason_text": "Relevant",
                    "score": 0.8,
                    "score_components": {"interest_match": 0.8},
                    "display_order": 0,
                }],
                "debug": {
                    "cache": {
                        "cache_hit": self.cache_hit,
                        "cache_type": "plan_result" if self.cache_hit else "none",
                        "cache_ttl_seconds": 600 if self.cache_hit else None,
                    },
                    "timings_ms": {"search": 5},
                },
            },
            "message": "ok",
        }


class PlanRunServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(User(id="user-1", openid="demo", campus="邯郸", nickname="Demo"))
        self.db.add(UserProfile(
            user_id="user-1",
            interest_tags=["AI"],
            preferred_campuses=["邯郸"],
        ))
        self.db.add(Event(
            id="event-1",
            title="AI lecture",
            start_time=REFERENCE_NOW,
            location="Room 1",
            source_url="https://example.com/event",
            verification_status="unverified",
            is_user_visible=True,
        ))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def create_run(self):
        return plan_run_service.create_plan_run(
            db=self.db,
            user_id="user-1",
            request_text="AI events",
            date_scope="today",
            reference_now=REFERENCE_NOW,
        )

    def execute(self, run_id, *, cache_hit=False, fail=False):
        stages = []
        original_set_stage = plan_run_service._set_stage

        def record_stage(db, run, stage):
            stages.append(stage)
            original_set_stage(db, run, stage)

        parse_side_effect = RuntimeError("intent failed") if fail else FakeIntent()
        with patch.object(plan_run_service, "SessionLocal", self.Session), patch.object(
            plan_run_service, "parse_intent", side_effect=parse_side_effect if fail else None,
            return_value=None if fail else parse_side_effect,
        ), patch.object(
            plan_run_service, "read_memory", return_value={}
        ), patch.object(
            plan_run_service, "plan_day_service", return_value=FakePlanResponse(cache_hit=cache_hit)
        ), patch.object(
            plan_run_service, "should_reflect_memory_summary", return_value=False
        ), patch.object(
            plan_run_service, "_set_stage", side_effect=record_stage
        ):
            plan_run_service.execute_plan_run(run_id, REFERENCE_NOW)
        return stages

    def test_run_persists_real_stages_and_reference_clock(self):
        run = self.create_run()
        self.assertEqual(run.status, "queued")
        stages = self.execute(run.id)
        self.db.expire_all()
        stored = self.db.query(PlanRun).filter_by(id=run.id).one()
        self.assertEqual(
            stages,
            ["load_profile", "parse_intent", "read_memory", "search_events", "build_schedule", "save_plan"],
        )
        self.assertEqual(stored.status, "completed")
        self.assertEqual(stored.stage, "completed")
        self.assertEqual(stored.progress, 1.0)
        self.assertTrue(stored.evidence_eligible)
        self.assertEqual(json.loads(stored.debug)["reference_now"], REFERENCE_NOW.isoformat())

    def test_cache_hit_is_not_new_evidence(self):
        run = self.create_run()
        self.execute(run.id, cache_hit=True)
        self.db.expire_all()
        stored = self.db.query(PlanRun).filter_by(id=run.id).one()
        self.assertTrue(stored.cache_hit)
        self.assertFalse(stored.evidence_eligible)

    def test_duplicate_request_is_not_new_evidence(self):
        first = self.create_run()
        self.execute(first.id)
        second = self.create_run()
        self.execute(second.id)
        self.db.expire_all()
        self.assertTrue(self.db.query(PlanRun).filter_by(id=first.id).one().evidence_eligible)
        self.assertFalse(self.db.query(PlanRun).filter_by(id=second.id).one().evidence_eligible)

    def test_failure_persists_stage_and_reason(self):
        run = self.create_run()
        self.execute(run.id, fail=True)
        self.db.expire_all()
        stored = self.db.query(PlanRun).filter_by(id=run.id).one()
        self.assertEqual(stored.status, "failed")
        self.assertEqual(stored.stage, "parse_intent")
        self.assertIn("intent failed", stored.error_message)
        self.assertFalse(stored.evidence_eligible)


if __name__ == "__main__":
    unittest.main()
