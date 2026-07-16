from __future__ import annotations

import unittest
import importlib
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from experiments.agent_plan_runtime.runtime import _search_and_score

EXPERIMENTS_ROOT = str(Path(__file__).resolve().parents[1])
if EXPERIMENTS_ROOT not in sys.path:
    sys.path.insert(0, EXPERIMENTS_ROOT)


class EmbeddingWiringTest(unittest.TestCase):
    def test_generated_embedding_is_attached_to_frozen_intent(self):
        captured = {}

        class SearchResult:
            items = []
            rejections = []

        def fake_search(events, *, intent, profile, memory, now, include_debug=False):
            captured["intent"] = intent
            return SearchResult()

        embedding_module = importlib.import_module("agent_core.embedding")
        search_module = importlib.import_module("agent_core.search_events")
        with patch.object(
            embedding_module,
            "generate_query_embedding",
            return_value=([0.1, 0.2], "embedding-test"),
        ), patch.object(search_module, "search_events", side_effect=fake_search):
            now = datetime(2026, 7, 15, tzinfo=timezone.utc)
            _search_and_score(
                events=[],
                profile={},
                request_text="AI lecture",
                date_scope="today",
                now=now,
                window_start=now,
                window_end=now + timedelta(days=1),
                memory=None,
                rejections=[],
            )

        intent = captured["intent"]
        self.assertEqual(intent.query_embedding, (0.1, 0.2))
        self.assertEqual(intent.embedding_model, "embedding-test")


if __name__ == "__main__":
    unittest.main()
