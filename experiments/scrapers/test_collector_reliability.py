from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from experiments.scrapers import auto_collector


class FakeDb:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeArticleState:
    def __init__(self, previous):
        self.previous = previous
        self.processing = []
        self.completed = []
        self.failed = []

    def is_article_processed(self, db, source_url, content_hash):
        return self.previous

    def mark_article_processing(self, db, source_url, **kwargs):
        self.processing.append((source_url, kwargs))
        return "raw-1"

    def mark_article_completed(self, db, raw_document_id):
        self.completed.append(raw_document_id)

    def mark_article_failed(self, db, raw_document_id, **kwargs):
        self.failed.append((raw_document_id, kwargs))


class CollectorReliabilityTest(unittest.TestCase):
    def article(self, digest):
        return {
            "title": "Article",
            "source_url": "https://example.com/article",
            "source_name": "Source",
            "source_id": "source-1",
            "digest": digest,
        }

    def test_terminal_article_skips_only_when_content_is_unchanged(self):
        digest = "活动信息" * 60
        content_hash = auto_collector._content_hash(digest)
        state = FakeArticleState({
            "status": "skipped_no_activity",
            "content_hash": content_hash,
            "retry_count": 0,
        })
        with patch.object(auto_collector, "extract_article_to_events") as extract:
            drafts, ok, reason, info = auto_collector.extract_and_map(
                self.article(digest), cn8n_mod=None, warnings=[],
                db=FakeDb(), article_state=state,
            )
        self.assertEqual(drafts, [])
        self.assertFalse(ok)
        self.assertEqual(reason, "no_activity")
        self.assertEqual(info["dedup"], "skipped_no_activity")
        extract.assert_not_called()

    def test_terminal_article_reprocesses_when_content_changes(self):
        old_hash = auto_collector._content_hash("旧内容" * 60)
        state = FakeArticleState({
            "status": "skipped_no_activity",
            "content_hash": old_hash,
            "retry_count": 0,
        })
        event = {
            "title": "New event",
            "summary": "Details",
            "start_time": "2026-08-01T10:00:00+08:00",
            "end_time": "2026-08-01T11:00:00+08:00",
            "location": "Room 1",
        }
        draft = {**event, "source_url": "https://example.com/article"}
        with patch.object(auto_collector, "extract_article_to_events", return_value={
            "status": "ok", "events": [event], "warnings": [], "error": None,
            "used_fallback": False,
        }) as extract, patch.object(
            auto_collector, "map_wechat_article_to_drafts", return_value=([draft], [])
        ):
            drafts, ok, reason, _ = auto_collector.extract_and_map(
                self.article("更新后的活动正文" * 60), cn8n_mod=None, warnings=[],
                db=FakeDb(), article_state=state,
            )
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertEqual(len(drafts), 1)
        self.assertEqual(len(state.processing), 1)
        self.assertEqual(state.completed, ["raw-1"])
        extract.assert_called_once()

    def test_no_text_is_persisted_as_terminal_status(self):
        state = FakeArticleState(None)
        drafts, ok, reason, _ = auto_collector.extract_and_map(
            self.article(""), cn8n_mod=None, warnings=[],
            db=FakeDb(), article_state=state,
        )
        self.assertEqual(drafts, [])
        self.assertFalse(ok)
        self.assertEqual(reason, "no_text")
        self.assertEqual(len(state.processing), 1)
        self.assertEqual(state.failed[0][1]["error"], "no_text")
        self.assertTrue(state.failed[0][1]["is_terminal"])

    def test_account_cursor_rotates_across_runs(self):
        accounts = {
            "accounts": [
                {"id": "a1", "name": "One", "enabled": True},
                {"id": "a2", "name": "Two", "enabled": True},
                {"id": "a3", "name": "Three", "enabled": True},
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            accounts_path = root / "accounts.json"
            cursor_path = root / "cursor.json"
            accounts_path.write_text(json.dumps(accounts), encoding="utf-8")
            first, _, next_cursor = auto_collector.load_enabled_accounts_rotating(
                accounts_path, limit=1, cursor_path=cursor_path
            )
            auto_collector._write_cursor(cursor_path, next_cursor)
            second, _, _ = auto_collector.load_enabled_accounts_rotating(
                accounts_path, limit=1, cursor_path=cursor_path
            )
        self.assertEqual(first[0]["id"], "a1")
        self.assertEqual(second[0]["id"], "a2")


if __name__ == "__main__":
    unittest.main()
