# -*- coding: utf-8 -*-
"""验证新入库活动可推荐：events.json → search_events → plan-day。

停gap 方式（--commit-json 写 events.json）导入的活动，用此脚本验证：
  1. 能被 search_events 找到
  2. 能在 scoring 中得到合理解释
  3. 能在 plan-day schedule 中出现

Usage:
    python experiments/scrapers/verify_recommendable.py
    python experiments/scrapers/verify_recommendable.py --source-file auto_collector_stopgap  # 只看停gap
    python experiments/scrapers/verify_recommendable.py --event-id <event_id>  # 单条诊断
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
EVENTS_JSON = _REPO_ROOT / "database" / "events.json"

for _p in (str(_HERE.parent), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agent_core.query import Intent, Memory, Profile, SoftPreferences
from agent_core.search_events import search_events
from agent_core.scoring import score_and_sort, score_interest_match
from agent_core._runtime_compat import event_text


def load_events(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("events", []) if isinstance(data, dict) else []


def guess_intent(event: dict) -> str:
    """从 event 的 title+summary 猜测能命中的 query。"""
    title = event.get("title", "")
    summary = event.get("summary") or ""
    # 提取前几组关键词
    words = (title + " " + summary).replace("——", " ").replace("—", " ").split()
    key_terms = [w for w in words[:6] if len(w) >= 2 and w not in
                 ("活动", "时间", "地点", "主题", "咨询", "问题", "以及", "|", "-")]
    return " ".join(key_terms[:4]) or title


def diagnose_event(event: dict, now: datetime) -> dict:
    """逐维诊断单个 event 为什么（不）被推荐。

    Returns dict with keys: event_id, title, query, in_candidates, in_schedule,
    score, score_components, diagnosis.
    """
    query_text = guess_intent(event)
    all_events = load_events(EVENTS_JSON)
    event_id = event.get("event_id", "")
    source_url = event.get("source_url", "")

    intent = Intent(request_text=query_text, date_scope="this_week", max_items=8)
    profile = Profile(interest_tags=tuple(), campus=None,
                      preferred_campuses=tuple(), activity_style_tags=tuple())
    memory = Memory()

    try:
        result = search_events(all_events, intent=intent, profile=profile,
                               memory=memory, now=now, include_debug=True)
    except Exception as e:  # noqa: BLE001
        return {"event_id": event_id, "title": event.get("title"),
                "query": query_text, "error": str(e),
                "in_results": False, "diagnoses": [f"search_events 异常: {e}"]}

    # 查找新 event 是否在结果中
    found = None
    for item in result.items:
        eid = str(item.event.get("event_id", ""))
        if eid == event_id:
            found = item
            break
    if found is None and source_url:
        for item in result.items:
            if item.event.get("source_url") == source_url:
                found = item
                break

    diagnoses: list[str] = []
    if found:
        diagnoses.append("✓ 新活动进入 search_events 候选")
    else:
        # 逐维诊断：是什么挡住了？
        start_time = event.get("start_time")
        if not start_time:
            diagnoses.append("✗ 缺少 start_time，无法确定在时间范围内")
        elif isinstance(start_time, str) and "2026" in start_time:
            # 样例活动日期是 2026-06，now 需要与之匹配
            if now.month not in (5, 6, 7):
                diagnoses.append(
                    f"✗ 活动时间 {start_time}，但 now={now.isoformat()} 不在附近，"
                    f"time_filter 可能排除。传 --now 2026-06-15 试试")
            else:
                diagnoses.append(f"? start_time={start_time}，time_filter 应通过")
        diagnoses.append(f"? 候选集大小: {len(result.items)}/{result.total} "
                         f"(total_before_filter={result.total_before_filter})")
        if result.rejections:
            for rej in result.rejections[:5]:
                diagnoses.append(f"  rejection: {rej.get('reason')}: {rej.get('detail')}")

    # 如果在结果中，逐维打分
    if found:
        sc = found.score_components
        diagnoses.append(f"总分: {found.score:.3f}")
        diagnoses.append(f"  interest_match: {_fmt_component(sc.get('interest_match'))}")
        diagnoses.append(f"  time_fit: {_fmt_component(sc.get('time_fit'))}")
        diagnoses.append(f"  campus_fit: {_fmt_component(sc.get('campus_fit'))}")
        diagnoses.append(f"  source_reliability: {_fmt_component(sc.get('source_reliability'))}")
        diagnoses.append(f"  freshness: {_fmt_component(sc.get('freshness'))}")
        memory = sc.get("memory")
        if isinstance(memory, dict) and memory.get("total_memory_delta"):
            diagnoses.append(f"  memory_delta: {memory['total_memory_delta']:.3f}")
        rank = next((i + 1 for i, item in enumerate(result.items)
                     if item.event.get("event_id") == event_id), -1)
        diagnoses.append(f"排名: {rank}/{len(result.items)}")
    else:
        diagnoses.append("✗ 新活动未进入候选集")

    return {
        "event_id": event_id,
        "title": event.get("title", ""),
        "source_url": source_url,
        "query": query_text,
        "in_results": found is not None,
        "score": found.score if found else None,
        "score_components": found.score_components if found else None,
        "rank": rank if found else None,
        "result_count": len(result.items),
        "total_before_filter": result.total_before_filter,
        "diagnoses": diagnoses,
    }


def _fmt_component(c: object) -> str:
    if isinstance(c, dict):
        sc = c.get("score")
        method = c.get("method", "")
        return f"{sc:.3f} [{method}]" if sc is not None and method else f"{c}"
    if isinstance(c, (int, float)):
        return f"{c:.3f}"
    return str(c)


# ---------------------------------------------------------------------------
# plan-day 模拟：search_events → 简单贪婪构建 schedule（不依赖 runtime.py）
# ---------------------------------------------------------------------------

def simulate_plan_day(request_text: str, now: datetime,
                      campus: str = "邯郸") -> list[dict]:
    """用 search_events + 评分结果模拟一次 plan-day 推荐。"""
    all_events = load_events(EVENTS_JSON)
    intent = Intent(request_text=request_text, date_scope="this_week", max_items=8)
    profile = Profile(interest_tags=tuple(), campus=campus,
                      preferred_campuses=tuple(), activity_style_tags=tuple())
    memory = Memory()

    result = search_events(all_events, intent=intent, profile=profile,
                           memory=memory, now=now, include_debug=True)
    # 简单的 top-4 贪婪（无冲突检查，等同于 schedule 候选）
    schedule: list[dict] = []
    for item in result.items[:4]:
        schedule.append({
            "event_id": item.event.get("event_id"),
            "title": item.event.get("title"),
            "score": item.score,
            "start_time": item.event.get("start_time"),
            "location": item.event.get("location"),
        })
    return schedule


def main() -> int:
    parser = argparse.ArgumentParser(description="验证新入库活动可推荐")
    parser.add_argument("--source-file", default="auto_collector_stopgap",
                        help="只看特定 source_file 的活动")
    parser.add_argument("--event-id", help="单条 event 诊断")
    parser.add_argument("--now", help="参考时间 ISO 8601，默认 2026-06-15T12:00:00+08:00 "
                        "(样例活动在 6 月)")
    parser.add_argument("--request-text", default="AI 讲座展览 毕业季",
                        help="模拟用户 query")
    parser.add_argument("--campus", default="邯郸",
                        help="模拟用户校区")
    args = parser.parse_args()

    now = (datetime.fromisoformat(args.now)
           if args.now
           else datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone(timedelta(hours=8))))

    events = load_events(EVENTS_JSON)
    if not events:
        print("events.json 为空或无合法 events", file=sys.stderr)
        return 1

    # 筛选停gap 活动
    target = [e for e in events
              if e.get("source_file") == args.source_file]
    if args.event_id:
        target = [e for e in events if e.get("event_id") == args.event_id]
        if not target:
            print(f"未找到 event_id={args.event_id}", file=sys.stderr)
            return 1

    if not target:
        print(f"未找到 source_file={args.source_file} 的活动", file=sys.stderr)
        return 1

    print(f"= 诊断 {len(target)} 条目标活动 (source_file={args.source_file}) =")
    print(f"  now={now.isoformat()}")
    ok = 0
    for evt in target:
        diag = diagnose_event(evt, now)
        print(f"\n── {diag.get('title','?')[:60]} "
              f"({'✓ 可见' if diag.get('in_results') else '✗ 不可见'}) "
              f"[{diag.get('event_id','')[:8]}]")
        for d in diag["diagnoses"]:
            print(f"  {d}")
        if diag.get("in_results"):
            ok += 1

    print(f"\n= 可见性: {ok}/{len(target)} =")

    # plan-day 模拟
    print(f"\n= plan-day 模拟 (query='{args.request_text}', campus={args.campus}) =")
    schedule = simulate_plan_day(args.request_text, now, campus=args.campus)
    stopgap_ids = {e.get("event_id") for e in target}
    in_schedule = [s for s in schedule if s["event_id"] in stopgap_ids]
    print(f"schedule top-4: {len(schedule)} 条")
    for s in schedule:
        marker = "← STOPGAP" if s["event_id"] in stopgap_ids else ""
        print(f"  [score={s['score']:.3f}] {s['title'][:50]} {marker}")
    print(f"\n停gap 活动进入 schedule: {len(in_schedule)}/{len(schedule)}")
    if not in_schedule and ok > 0:
        print("(可能被其他更高分活动挤出 top-4，调整 query 试试)")
    elif not in_schedule:
        print("(活动未进入候选集，见上方诊断)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
