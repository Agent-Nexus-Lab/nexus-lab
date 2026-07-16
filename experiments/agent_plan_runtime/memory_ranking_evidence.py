# -*- coding: utf-8 -*-
"""Memory ranking API 级证据：feedback 前后排序对比 + 下降归因。

通过 plan_day_service 跑两次：
  before = memory=None
  after  = memory={disliked_tags:["创业"], disliked_event_ids:[e_cy],
                   recent_plan_event_ids:[e_tw]}

从 debug.score_details 提取每 event 的 score 与 components.memory，标出哪个 event 因
disliked_penalty / repeat_penalty 下降，保留前后排序列表。

重复运行：
  python experiments/agent_plan_runtime/memory_ranking_evidence.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_REPO_ROOT))

from backend.plan_service import plan_day_service  # noqa: E402

TZ = timezone(timedelta(hours=8))


def sample_event(event_id, *, title, start_time, end_time, tags):
    return {
        "event_id": event_id,
        "source_file": "unit.txt",
        "source_name": "unit",
        "source_url": f"http://unit/{event_id}",
        "title": title,
        "summary": title,
        "start_time": start_time,
        "end_time": end_time,
        "location": "邯郸测试地点",
        "campus": "邯郸",
        "organizer": "unit",
        "tags": tags,
        "evidence_text": title,
    }


def ranking_and_components(resp) -> tuple[list[str], dict[str, dict]]:
    """返回 (按 score 降序的 event_id 列表, {event_id: {score, base, memory_delta, details}})。"""
    details = resp.data.debug.score_details
    comps: dict[str, dict] = {}
    for c in details:
        mem = c.components.get("memory") if isinstance(c.components, dict) else None
        mem_delta = mem.get("total_memory_delta") if isinstance(mem, dict) else None
        mem_details = mem.get("details", []) if isinstance(mem, dict) else []
        comps[c.event_id] = {
            "score": round(c.score, 4),
            "memory_delta": mem_delta,
            "memory_details": mem_details,
        }
    # score_details 已按 score 降序；保留该顺序作为 ranking
    ranking = [c.event_id for c in details]
    return ranking, comps


def attribute_drops(comps: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """从 components.memory.details 收集 disliked_penalty / repeat_penalty 条目。"""
    disliked: list[dict] = []
    repeat: list[dict] = []
    for eid, info in comps.items():
        for d in info.get("memory_details", []):
            t = d.get("type")
            if t == "disliked_penalty":
                disliked.append({
                    "event_id": eid,
                    "matched": d.get("matched"),
                    "delta": d.get("delta"),
                    "reason": d.get("reason"),
                })
            elif t == "repeat_penalty":
                repeat.append({
                    "event_id": eid,
                    "matched": d.get("matched"),
                    "delta": d.get("delta"),
                    "reason": d.get("reason"),
                })
    return disliked, repeat


def main() -> int:
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=TZ)
    events = [
        sample_event("evt_tianwen", title="周末天文观测活动",
                     start_time="2026-07-10T19:00:00+08:00",
                     end_time="2026-07-10T21:00:00+08:00", tags=["天文"]),
        sample_event("evt_drama", title="校园戏剧节展演",
                     start_time="2026-07-11T19:00:00+08:00",
                     end_time="2026-07-11T21:00:00+08:00", tags=["戏剧"]),
        sample_event("evt_ai", title="AI 大模型前沿讲座",
                     start_time="2026-07-12T14:00:00+08:00",
                     end_time="2026-07-12T16:00:00+08:00", tags=["AI"]),
        sample_event("evt_chuangye", title="创业路演沙龙",
                     start_time="2026-07-11T14:00:00+08:00",
                     end_time="2026-07-11T17:00:00+08:00", tags=["创业"]),
    ]
    profile = {
        "campus": "邯郸",
        "interest_tags": ["天文", "戏剧", "AI", "创业"],
        "preferred_campuses": ["邯郸"],
    }
    common = dict(events=events, profile=profile, request_text="这周末有什么活动",
                  date_scope="this_week", now=now, include_debug=True)

    before = plan_day_service(memory=None, **common)
    after_memory = {
        "disliked_tags": ["创业"],
        "disliked_event_ids": ["evt_chuangye"],
        "recent_plan_event_ids": ["evt_tianwen"],
    }
    after = plan_day_service(memory=after_memory, **common)

    before_ranking, before_comps = ranking_and_components(before)
    after_ranking, after_comps = ranking_and_components(after)

    disliked_drops, repeat_drops = attribute_drops(after_comps)

    # 断言：feedback 后排序真的变化
    failures: list[str] = []
    if before_ranking == after_ranking:
        failures.append("before_ranking == after_ranking，memory 未影响排序")
    if not disliked_drops:
        failures.append("未观察到 disliked_penalty 下降条目")
    if not repeat_drops:
        failures.append("未观察到 repeat_penalty 下降条目")
    # dislike 的 event 在 after 中位次应下降（或被剔除）
    if "evt_chuangye" in before_ranking and "evt_chuangye" in after_ranking:
        if after_ranking.index("evt_chuangye") < before_ranking.index("evt_chuangye"):
            failures.append("evt_chuangye 在 after 中位次未下降")

    fixture = {
        "scenario": "Memory ranking API 级证据：dislike 创业 + 天文刚推荐过",
        "pinned_now": now.isoformat(),
        "after_memory": after_memory,
        "before_ranking": before_ranking,
        "after_ranking": after_ranking,
        "ranking_changed": before_ranking != after_ranking,
        "dropped_due_to_disliked_penalty": disliked_drops,
        "dropped_due_to_repeat_penalty": repeat_drops,
        "score_components_before": before_comps,
        "score_components_after": after_comps,
        "summary_before": before.data.summary,
        "summary_after": after.data.summary,
        "failures": failures,
    }

    out_path = _HERE / "memory_ranking_evidence.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False, indent=2)

    print(json.dumps(fixture, ensure_ascii=False, indent=2))
    print(f"\n[written] {out_path}", file=sys.stderr)
    if failures:
        print("[FAIL] " + "; ".join(failures), file=sys.stderr)
        return 1
    print("[OK] ranking 变化 + 下降归因证据已生成", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
