# -*- coding: utf-8 -*-
"""cache 验收数据集：证明 scoring_memory_hash 派生正确，7月4日复用断言 cache_hit。

场景：
  r1 = plan_day(memory=None)          # 首次请求（miss）
  r2 = plan_day(memory=None)          # 同请求（命中，cache 落地后）
  r3 = plan_day(memory=dislike 天文)  # dislike 后（plan_result_cache 应失效）

今天（cache 未落地）断言：
  - scoring_memory_hash(r1) == scoring_memory_hash(r2)  → r2 与 r1 同 key，cache 应命中
  - scoring_memory_hash(r1) != scoring_memory_hash(r3)  → r3 key 不同，cache 应失效
  - r1/r2 selected_event_ids 相同（确定性）

7月4日（cache 落地后）同脚本重跑应见：
  - r1 debug.cache.cache_hit = False（miss）
  - r2 debug.cache.cache_hit = True （hit）
  - r3 debug.cache.cache_hit = False（invalidated）
  本脚本对 cache_hit 标志只记录不强制断言，避免阻塞联调。

重复运行：
  python experiments/agent_plan_runtime/cache_acceptance_dataset.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 让 runtime + agent_core 可导入
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))            # agent_plan_runtime/ → import runtime
sys.path.insert(0, str(_HERE.parent))     # experiments/        → import agent_core

from agent_core.query import Memory, ScoringMemory  # noqa: E402
from runtime import parse_now, plan_day  # noqa: E402


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


def memory_from_dict(d: dict | None) -> Memory:
    """局部 dict→Memory 转换（list→tuple）。只在数据集脚本内使用，
    不入 query.py 以免和曹昕宇的 conversion 设计冲突。"""
    d = d or {}
    return Memory(
        session_id=str(d.get("session_id", "")),
        recent_query_texts=tuple(d.get("recent_query_texts", ()) or ()),
        liked_tags=tuple(d.get("liked_tags", ()) or ()),
        disliked_tags=tuple(d.get("disliked_tags", ()) or ()),
        negative_keywords=tuple(d.get("negative_keywords", ()) or ()),
        liked_event_ids=tuple(d.get("liked_event_ids", ()) or ()),
        disliked_event_ids=tuple(d.get("disliked_event_ids", ()) or ()),
        recent_plan_event_ids=tuple(d.get("recent_plan_event_ids", ()) or ()),
    )


def scoring_memory_hash(memory_dict: dict | None) -> str:
    return ScoringMemory.from_memory(memory_from_dict(memory_dict)).cache_hash()


def cache_hit_observed(debug: dict | None) -> bool | None:
    """从 debug 读 cache_hit 标志（前向兼容，缺失返回 None）。"""
    if not isinstance(debug, dict):
        return None
    if "cache" in debug and isinstance(debug["cache"], dict):
        v = debug["cache"].get("cache_hit")
        if v is not None:
            return bool(v)
    if "cache_hit" in debug:
        return bool(debug["cache_hit"])
    return None


def summarize(result: dict) -> dict:
    data = result.get("data", {})
    debug = data.get("debug")
    return {
        "status": data.get("status"),
        "selected_event_ids": debug.get("selected_event_ids") if isinstance(debug, dict) else None,
        "summary": data.get("summary"),
        "cache_hit_observed": cache_hit_observed(debug),
    }


def main() -> int:
    now = parse_now("2026-07-09T12:00:00+08:00")
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

    r1 = plan_day(memory=None, **common)
    r2 = plan_day(memory=None, **common)
    r3 = plan_day(memory=r3_memory, **common)

    h1 = scoring_memory_hash(None)
    h2 = scoring_memory_hash(None)
    h3 = scoring_memory_hash(r3_memory)

    s1, s2, s3 = summarize(r1), summarize(r2), summarize(r3)

    # 今天可断言的 hash 派生（= cache key 派生）
    assert h1 == h2, f"同 memory 应同 hash: {h1} != {h2}"
    assert h1 != h3, f"dislike 改变后 hash 应不同: {h1} == {h3}"
    assert s1["selected_event_ids"] == s2["selected_event_ids"], "r1/r2 应确定性一致"

    # 7月4日 cache 落地后的预期（今天只记录，不强制）
    cache_expectations = {
        "r1_miss": {"expected": False, "observed": s1["cache_hit_observed"]},
        "r2_hit": {"expected": True, "observed": s2["cache_hit_observed"]},
        "r3_invalidated": {"expected": False, "observed": s3["cache_hit_observed"]},
    }
    warnings = []
    for label, ce in cache_expectations.items():
        if ce["observed"] is not None and ce["observed"] != ce["expected"]:
            warnings.append(f"{label}: expected={ce['expected']} but observed={ce['observed']}")

    fixture = {
        "scenario": "cache 验收：同请求 miss→hit，dislike 后失效",
        "pinned_now": now.isoformat(),
        "request_text": request_text,
        "date_scope": date_scope,
        "profile": profile,
        "r3_memory": r3_memory,
        "scoring_memory_hash": {"r1": h1, "r2": h2, "r3": h3},
        "hash_assertions": {"h1==h2": h1 == h2, "h1!=h3": h1 != h3},
        "results": {"r1": s1, "r2": s2, "r3": s3},
        "cache_expectations_7月4日": cache_expectations,
        "warnings": warnings,
        "note": ("cache_hit_observed 为 null 表示后端尚未写入 cache 标志（今天预期）。"
                 "7月4日曹昕宇 cache 落地后重跑本脚本，三项 observed 应分别等于 expected。"),
    }

    out_path = _HERE / "cache_acceptance_dataset.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False, indent=2)

    print(json.dumps(fixture, ensure_ascii=False, indent=2))
    print(f"\n[written] {out_path}", file=sys.stderr)
    if warnings:
        print("[warnings] " + "; ".join(warnings), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
