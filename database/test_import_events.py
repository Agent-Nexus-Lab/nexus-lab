from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from database.import_events import import_many, import_many_standalone
from database.models import Event


REFERENCE_NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


class EventImportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def draft(self, **overrides):
        data = {
            "title": "AI workshop",
            "summary": "first summary",
            "start_time": "2026-08-01T10:00:00+00:00",
            "end_time": "2026-08-01T11:00:00+00:00",
            "location": "Room 101",
            "source_url": "https://example.com/article",
        }
        data.update(overrides)
        return data

    def import_and_commit(self, drafts):
        result = import_many(drafts, db=self.db, reference_now=REFERENCE_NOW)
        self.db.commit()
        return result

    def test_duplicate_import_is_skipped_without_datetime_type_error(self):
        first = self.import_and_commit([self.draft()])
        second = self.import_and_commit([self.draft()])
        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(second["failed"], 0)
        self.assertEqual(self.db.query(Event).count(), 1)

    def test_same_article_allows_multiple_events_with_same_title(self):
        result = self.import_and_commit([
            self.draft(),
            self.draft(
                start_time="2026-08-02T10:00:00+00:00",
                end_time="2026-08-02T11:00:00+00:00",
            ),
        ])
        self.assertEqual(result["imported"], 2)
        self.assertEqual(len(result["event_ids"]), 2)

    def test_summary_change_updates_existing_event(self):
        self.import_and_commit([self.draft()])
        result = self.import_and_commit([self.draft(summary="updated summary")])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(self.db.query(Event).one().summary, "updated summary")

    def test_missing_start_is_pending_and_hidden(self):
        result = self.import_and_commit([self.draft(start_time=None, end_time=None)])
        event = self.db.query(Event).one()
        self.assertEqual(result["imported"], 1)
        self.assertEqual(event.verification_status, "pending")
        self.assertFalse(event.is_user_visible)

    def test_invalid_url_and_time_range_fail(self):
        result = self.import_and_commit([
            self.draft(title="bad url", source_url="ftp://example.com/a"),
            self.draft(
                title="bad range",
                start_time="2026-08-02T12:00:00+00:00",
                end_time="2026-08-02T11:00:00+00:00",
            ),
        ])
        self.assertEqual(result["failed"], 2)
        self.assertEqual(self.db.query(Event).count(), 0)

    def test_one_failure_does_not_affect_other_rows(self):
        result = self.import_and_commit([
            self.draft(title="valid before", source_url="https://example.com/1"),
            self.draft(title="invalid", start_time="not-a-time"),
            self.draft(title="valid after", source_url="https://example.com/2"),
        ])
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(self.db.query(Event).count(), 2)

    def test_expired_event_is_hidden(self):
        self.import_and_commit([
            self.draft(
                start_time="2026-06-01T10:00:00+00:00",
                end_time="2026-06-01T11:00:00+00:00",
            )
        ])
        self.assertFalse(self.db.query(Event).one().is_user_visible)

    def test_standalone_rolls_back_when_commit_fails(self):
        class BrokenSession:
            rolled_back = False
            closed = False

            def begin_nested(self):
                raise RuntimeError("unexpected nested call")

            def commit(self):
                raise RuntimeError("commit failed")

            def rollback(self):
                self.rolled_back = True

            def close(self):
                self.closed = True

        broken = BrokenSession()
        import database.database as database_module

        original = database_module.SessionLocal
        database_module.SessionLocal = lambda: broken
        try:
            with self.assertRaises(RuntimeError):
                import_many_standalone([], reference_now=REFERENCE_NOW)
        finally:
            database_module.SessionLocal = original
        self.assertTrue(broken.rolled_back)
        self.assertTrue(broken.closed)


if __name__ == "__main__":
    unittest.main()
