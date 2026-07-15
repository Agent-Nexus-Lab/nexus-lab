from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.collection_lock import CollectionLock
from database import Base
from database import collection_service
from database.models import CollectionRun


class FakeLock:
    def __init__(self, token="lock-token"):
        self.token = token
        self.released = []

    def acquire(self):
        return self.token

    def release(self, token):
        self.released.append(token)


class CollectionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_create_finish_and_list_collection_run(self):
        run = collection_service.create_collection_run(
            db=self.db,
            trigger_method="manual",
            sources=["source-1"],
        )
        collection_service.finish_collection_run(
            run.batch_id,
            db=self.db,
            counts={"fetched_count": 4, "imported_count": 2},
            duration_ms=123,
        )
        stored = collection_service.get_collection_runs(
            db=self.db, batch_id=run.batch_id, limit=1
        )[0]
        self.assertEqual(stored.status, "completed")
        self.assertEqual(stored.fetched_count, 4)
        self.assertEqual(stored.imported_count, 2)
        self.assertEqual(stored.duration_ms, 123)

    def test_execute_records_real_counts(self):
        run = collection_service.create_collection_run(
            db=self.db, trigger_method="manual"
        )
        lock = FakeLock()
        collector_result = {
            "scanned_account_ids": ["a1", "a2"],
            "commit_summary": {
                "fetched_count": 5,
                "extracted_count": 3,
                "imported_count": 2,
                "updated_count": 1,
                "skipped_count": 0,
                "failed_count": 0,
                "errors": [],
            },
        }
        with patch.object(collection_service, "SessionLocal", self.Session), patch.object(
            collection_service, "get_collection_lock", return_value=lock
        ), patch(
            "experiments.scrapers.auto_collector.run", return_value=collector_result
        ) as collector:
            collection_service.execute_collection_run(run.batch_id, limit=7)

        stored = self.db.query(CollectionRun).filter_by(batch_id=run.batch_id).one()
        self.db.refresh(stored)
        self.assertEqual(stored.status, "completed")
        self.assertEqual(stored.sources, ["a1", "a2"])
        self.assertEqual(stored.imported_count, 2)
        self.assertEqual(stored.updated_count, 1)
        self.assertEqual(lock.released, ["lock-token"])
        collector.assert_called_once_with(
            dry_run=False, commit=True, limit=7, source_ids=None
        )

    def test_execute_records_skipped_when_lock_is_busy(self):
        run = collection_service.create_collection_run(
            db=self.db, trigger_method="cron"
        )
        with patch.object(collection_service, "SessionLocal", self.Session), patch.object(
            collection_service, "get_collection_lock", return_value=FakeLock(token=None)
        ):
            collection_service.execute_collection_run(run.batch_id)

        stored = self.db.query(CollectionRun).filter_by(batch_id=run.batch_id).one()
        self.db.refresh(stored)
        self.assertEqual(stored.status, "skipped")
        self.assertEqual(stored.failure_reason, "collection_already_running")

    def test_local_lock_prevents_overlap(self):
        lock = CollectionLock()
        first = lock.acquire()
        second = lock.acquire()
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        lock.release(first)
        self.assertIsNotNone(lock.acquire())


if __name__ == "__main__":
    unittest.main()
