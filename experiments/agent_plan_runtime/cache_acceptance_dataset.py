# -*- coding: utf-8 -*-
"""cache 验收数据集（真实断言）：通过 plan_day_service 验证 miss → hit → 失效。

场景：
  r1 = plan_day_service(memory=None)          # 首次请求（miss）
  r2 = plan_day_service(memory=None)          # 同请求（应命中 plan_result_cache）
  r3 = plan_day_service(memory=dislike 天文)  # scoring_memory_hash 变（应 miss）

断言（真实 cache_hit 标志，不再占位 null）：
  - r1.debug.cache.cache_hit == False
  - r2.debug.cache.cache_hit == True 且 cache_type == "plan_result"
  - r3.debug.cache.cache_hit == False
  - r1/r2 selected_event_ids 相同（cache 命中返回同一结果）

依赖：backend/plan_service.py 的 plan_day_service（曹昕宇 7月4日落地）。
重复运行：
  python experiments/agent_plan_runtime/cache_acceptance_dataset.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 让 runtime + agent_core + backend 可导入
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_HERE))            # agent_plan_runtime/ → import runtime
sys.path.insert(0, str(_HERE.parent))     # experiments/        → import agent_core
sys.path.insert(0, str(_REPO_ROOT))       # repo root           → import backend

from agent_core.query import Memory, ScoringMemory  # noqa: E402
from backend.plan_service import (  # noqa: E402
    _compute_scoring_memory_hash,
    plan_day_service,
)

TZ = timezone(timedelta(hours=8))


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


def summarize(resp) -> dict:
    """从 PlanDayResponse 提取验收字段。"""
    data = resp.data
    debug = data.debug
    cache = debug.cache
    return {
        "status": data.status,
        "selected_event_ids": debug.selected_event_ids,
        "summary": data.summary,
        "cache_hit": cache.cache_hit,
        "cache_type": cache.cache_type,
        "plan_result_cache_hit": cache.plan_result_cache_hit,
        "redis_available": cache.redis_available,
        "using_fallback": cache.using_fallback,
    }


def main() -> int:
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=TZ)
    events = [
        sample_event("evt_tianwen", title="周末天文观测活动",
                     start_time="2026-07-10T19:00:00+08:00",
                     end_time="2026-07-10T21:00:00+08:00", campus="邯郸", tags=["天文"]),
        sample_event("evt_drama", title="校园戏剧节展演",
                     start_time="2026-07-11T19:00:00+08:00",
                     end_time="2026-07-11T21:00:00+08:00", campus="邯郸", tags=["戏剧"]),
        sample_event("evt_ai", title="AI 大模型前沿讲座",
                     start_time="2026-07-12T14:00:00+08:00",
                     end_time="2026-07-12T16:00:00+08:00", campus="邯郸", tags=["AI"]),
    ]
    profile = {
        "campus": "邯郸",
        "interest_tags": ["天文", "戏剧", "AI"],
        "preferred_campuses": ["邯郸"],
    }
    request_text = "这周末想看天文或戏剧活动"
    date_scope = "this_week"
    common = dict(events=events, profile=profile, request_text=request_text,
                  date_scope=date_scope, now=now, include_debug=True)

    r3_memory = {"disliked_tags": ["天文"], "disliked_event_ids": ["evt_tianwen"]}

    r1 = plan_day_service(memory=None, **common)
    r2 = plan_day_service(memory=None, **common)
    r3 = plan_day_service(memory=r3_memory, **common)

    h1 = _compute_scoring_memory_hash(None)
    h2 = _compute_scoring_memory_hash(None)
    h3 = _compute_scoring_memory_hash(r3_memory)

    s1, s2, s3 = summarize(r1), summarize(r2), summarize(r3)

    # --- 真实断言（不再只记录）---
    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            failures.append(msg)

    # hash 派生（cache key 同源）
    check(h1 == h2, f"同 memory 应同 scoring_memory_hash: {h1} != {h2}")
    check(h1 != h3, f"dislike 改变后 scoring_memory_hash 应不同: {h1} == {h3}")

    # cache 命中标志
    check(s1["cache_hit"] is False, f"r1 应 miss, got cache_hit={s1['cache_hit']}")
    check(s2["cache_hit"] is True, f"r2 应 hit, got cache_hit={s2['cache_hit']}")
    check(s2["cache_type"] == "plan_result",
          f"r2 cache_type 应 plan_result, got {s2['cache_type']}")
    check(s3["cache_hit"] is False,
          f"r3 应 miss（memory 变化失效 cache）, got cache_hit={s3['cache_hit']}")

    # 确定性：r1/r2 命中应返回同一 selected_event_ids
    check(s1["selected_event_ids"] == s2["selected_event_ids"],
          f"r1/r2 selected_event_ids 应一致: {s1['selected_event_ids']} vs {s2['selected_event_ids']}")

    fixture = {
        "scenario": "cache 验收：同请求 miss→hit，dislike 后失效（真实断言）",
        "pinned_now": now.isoformat(),
        "request_text": request_text,
        "date_scope": date_scope,
        "profile": profile,
        "r3_memory": r3_memory,
        "scoring_memory_hash": {"r1": h1, "r2": h2, "r3": h3},
        "hash_assertions": {"h1==h2": h1 == h2, "h1!=h3": h1 != h3},
        "results": {"r1": s1, "r2": s2, "r3": s3},
        "assertions": {
            "r1_miss": s1["cache_hit"] is False,
            "r2_hit_plan_result": s2["cache_hit"] is True and s2["cache_type"] == "plan_result",
            "r3_invalidated": s3["cache_hit"] is False,
            "r1_r2_same_selection": s1["selected_event_ids"] == s2["selected_event_ids"],
        },
        "failures": failures,
    }

    out_path = _HERE / "cache_acceptance_dataset.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False, indent=2)

    print(json.dumps(fixture, ensure_ascii=False, indent=2))
    print(f"\n[written] {out_path}", file=sys.stderr)
    if failures:
        print("[FAIL] " + "; ".join(failures), file=sys.stderr)
        return 1
    print("[OK] 所有 cache 断言通过", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
