# -*- coding: utf-8 -*-
"""生成 score_components.memory 的 debug JSON 样例，供验收文档复制。

场景：用户喜欢 AI、不喜欢"创业"、且 e1 刚被推荐过。e1 同时命中 liked_boost /
disliked_penalty / repeat_penalty，total_memory_delta 为负，details 与 explanation 非空。

重复运行可刷新样例：
    python experiments/agent_core/generate_memory_debug_sample.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 让 agent_core 可导入（与 test_search_events.py 一致的 shim）
_EXPERIMENTS_ROOT = Path(__file__).resolve().parents[1]
if str(_EXPERIMENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXPERIMENTS_ROOT))

from agent_core.query import Intent, Memory, Profile  # noqa: E402
from agent_core.search_events import search_events  # noqa: E402

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=TZ)


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


def main() -> None:
    events = [
        make_event(event_id="e1", title="AI 创业讲座", tags=["AI", "创业"],
                   start_time="2026-06-05T14:00:00+08:00"),
        make_event(event_id="e2", title="AI 学术报告", tags=["AI", "学术"],
                   start_time="2026-06-06T14:00:00+08:00"),
    ]
    intent = Intent(request_text="AI", date_scope="this_week")
    profile = Profile(interest_tags=("AI",))
    memory = Memory(
        liked_tags=("AI",),
        disliked_tags=("创业",),
        recent_plan_event_ids=("e1",),
    )

    result = search_events(
        events, intent=intent, profile=profile, memory=memory,
        now=NOW, include_debug=True,
    )

    target = next(m for m in result.items if m.event["event_id"] == "e1")
    memory_component = target.score_components["memory"]

    sample = {
        "scenario": "用户喜欢 AI、不喜欢创业、e1 刚被推荐过（命中 liked+disliked+repeat）",
        "now": NOW.isoformat(),
        "ranking": [m.event["event_id"] for m in result.items],
        "event_id": "e1",
        "base_score": round(target.score - memory_component["total_memory_delta"], 4),
        "final_score": target.score,
        "score_components.memory": memory_component,
    }

    out_path = Path(__file__).resolve().parent / "sample_memory_debug.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sample, f, ensure_ascii=False, indent=2)

    print(json.dumps(sample, ensure_ascii=False, indent=2))
    print(f"\n[written] {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
