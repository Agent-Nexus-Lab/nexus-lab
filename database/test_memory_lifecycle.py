from __future__ import annotations

import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from database.memory_service import (
    is_memory_suppressed,
    read_memory,
    reflect_and_store_memory_summary,
    should_reflect_memory_summary,
    suppress_memory_summary,
)
from database.models import Event, MemoryItem, Plan, PlanItem, PlanRun, User


class MemoryLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(User(id="user-1", openid="demo", campus="邯郸", nickname="Demo"))
        for index in range(3):
            event_id = f"event-{index}"
            run_id = f"run-{index}"
            plan_id = f"plan-{index}"
            self.db.add(Event(
                id=event_id,
                title=f"Event {index}",
                start_time=datetime(2026, 8, 1 + index, tzinfo=timezone.utc),
                location="Room",
                source_url=f"https://example.com/{index}",
                is_user_visible=True,
                verification_status="unverified",
            ))
            self.db.add(PlanRun(
                id=run_id,
                user_id="user-1",
                status="completed",
                request_text=f"request {index}",
                date_scope="today",
                evidence_eligible=True,
                cache_hit=False,
                started_at=datetime(2026, 7, 1, tzinfo=timezone.utc) + timedelta(days=index),
            ))
            self.db.add(Plan(
                id=plan_id,
                run_id=run_id,
                user_id="user-1",
                title="Plan",
            ))
            self.db.add(PlanItem(
                id=str(uuid.uuid4()),
                plan_id=plan_id,
                event_id=event_id,
                start_time=datetime(2026, 8, 1 + index, tzinfo=timezone.utc),
                display_order=0,
            ))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_three_eligible_runs_reflect_once(self):
        self.assertTrue(should_reflect_memory_summary("user-1", db=self.db))
        with patch("database.memory_service.reflect_on_memory", return_value={
            "memory_summary": "Prefers practical events",
            "expires_after_turns": 6,
            "cleanup_reason": None,
            "prompt_version": "test",
            "used_fallback": False,
        }):
            result = reflect_and_store_memory_summary("user-1", db=self.db)
        self.assertTrue(result["reflected"])
        summary = self.db.query(MemoryItem).filter_by(memory_type="memory_summary").one()
        self.assertEqual(summary.structured_content["evidence_run_ids"], ["run-0", "run-1", "run-2"])
        self.assertNotIn("memory_strength", summary.structured_content)
        self.assertFalse(should_reflect_memory_summary("user-1", db=self.db))

    def test_suppressed_memory_cannot_be_read_or_rebuilt_from_same_refs(self):
        with patch("database.memory_service.reflect_on_memory", return_value={
            "memory_summary": "Summary",
            "expires_after_turns": 6,
            "cleanup_reason": None,
            "prompt_version": "test",
            "used_fallback": False,
        }):
            result = reflect_and_store_memory_summary("user-1", db=self.db)
        suppress_memory_summary(result["memory_id"], db=self.db)
        memory = read_memory("user-1", db=self.db)
        self.assertIsNone(memory["memory_summary"])
        self.assertTrue(is_memory_suppressed(
            ["run-0", "run-1", "run-2"], user_id="user-1", db=self.db
        ))
        second = reflect_and_store_memory_summary("user-1", db=self.db)
        self.assertFalse(second["reflected"])


if __name__ == "__main__":
    unittest.main()
