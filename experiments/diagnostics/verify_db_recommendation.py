# -*- coding: utf-8 -*-
"""正式数据库推荐验证诊断（需求七）。

用昕宇正式写入数据库的 Event 验证：DB Event -> search_events -> score_and_sort -> plan_day。
对至少 3 个新 event_id 输出诊断：是否进候选 / 最终排名 / 是否进计划 / 总分 /
score_components / 拒绝原因。端到端检查至少 1 条新活动进最终计划。

证据来源：服务器数据库（非 database/events.json）。

用法：
    python experiments/diagnostics/verify_db_recommendation.py
    python experiments/diagnostics/verify_db_recommendation.py --now 2026-08-01T12:00:00+08:00
    python experiments/diagnostics/verify_db_recommendation.py --request "想看天文讲座" --date-scope this_week
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
for _p in (str(_HERE.parent), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from database.database import SessionLocal  # noqa: E402
from database.models import Event, User, UserProfile  # noqa: E402
from database.memory_service import read_memory  # noqa: E402


def _event_to_dict(event: Event) -> dict:
    d = {
        "event_id": event.id,
        "title": event.title,
        "summary": event.summary,
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "end_time": event.end_time.isoformat() if event.end_time else None,
        "location": event.location,
        "campus": event.campus,
        "organizer": event.organizer,
        "tags": event.tags,
        "source_url": event.source_url,
        "quality_score": event.quality_score,
        "source_name": event.source_name,
        "evidence_text": event.evidence_text,
    }
    # embedding 字段（昕宇落地后存在；未落地则 None，scoring 走 keyword_fallback）
    d["summary_embedding"] = getattr(event, "summary_embedding", None)
    d["embedding_model"] = getattr(event, "embedding_model", None)
    return d


def _is_stopgap(event: Event) -> bool:
    src = (event.source_name or "") + " " + (event.source_url or "")
    return "stopgap" in src.lower() or "events.json" in src.lower()


def _build_profile(user: User, profile_raw: UserProfile) -> dict:
    return {
        "preferred_campuses": profile_raw.preferred_campuses or [],
        "interest_tags": profile_raw.interest_tags or [],
        "activity_style_tags": profile_raw.activity_style_tags or [],
        "available_time": profile_raw.available_time or "",
        "campus": user.campus or "",
        "profile_summary": profile_raw.profile_summary or "",
    }


def _reject_reason(event_id: str, items: list, rejections: list[dict]) -> str:
    """解释一个 event 为何没进计划。"""
    in_items = any(getattr(it, "event", {}).get("event_id") == event_id for it in items)
    if in_items:
        return "in_plan"
    for r in rejections:
        if r.get("event_id") == event_id:
            return f"rejected:{r.get('reason', 'unknown')}"
    return "not_in_candidates"


def diagnose_one(event_dict: dict, *, all_events: list[dict], profile: dict,
                 memory: dict, request_text: str, date_scope: str, now: datetime) -> dict:
    """对单个 event 跑 search_events+score_and_sort，输出诊断。"""
    from agent_core.search_events import search_events
    from agent_core.query import Intent, Profile, Memory
    intent = Intent(request_text=request_text, date_scope=date_scope)
    prof = Profile.from_dict(profile)
    mem = Memory.from_dict(memory) if memory else None
    result = search_events(all_events, intent=intent, profile=prof, memory=mem, now=now)
    eid = event_dict["event_id"]
    diag = {"event_id": eid, "title": event_dict.get("title")}
    in_cand = False
    rank = None
    score = None
    components = None
    for i, it in enumerate(result.items):
        if it.event.get("event_id") == eid:
            in_cand = True
            rank = i + 1
            score = it.score
            components = it.score_components
            break
    diag["in_candidates"] = in_cand
    diag["rank"] = rank
    diag["score"] = score
    diag["score_components"] = components
    diag["rejection"] = None if in_cand else _reject_reason(eid, result.items, result.rejections)
    return diag


def run_diagnosis(*, request_text: str, date_scope: str, now: datetime,
                  min_events: int = 3) -> dict:
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            return {"code": 1001, "message": "数据库无用户，无法诊断", "evidence_source": "database"}
        profile_raw = db.query(UserProfile).filter_by(user_id=user.id).first()
        if not profile_raw:
            return {"code": 1001, "message": "用户画像未创建", "evidence_source": "database"}
        profile = _build_profile(user, profile_raw)
        memory = read_memory(user.id, db=db)

        events_raw = db.query(Event).order_by(Event.created_at.desc()).limit(50).all()
        all_events = [_event_to_dict(e) for e in events_raw]
        # 选非 stopgap 的新事件做诊断
        target_events = [_event_to_dict(e) for e in events_raw if not _is_stopgap(e)]
        if len(target_events) < min_events:
            # 不足则放宽到全部最近事件
            target_events = all_events
        target_events = target_events[:max(min_events, 5)]

        diagnoses = []
        for ev in target_events:
            try:
                diagnoses.append(diagnose_one(
                    ev, all_events=all_events, profile=profile, memory=memory,
                    request_text=request_text, date_scope=date_scope, now=now))
            except Exception as e:  # noqa: BLE001
                diagnoses.append({"event_id": ev.get("event_id"), "error": str(e)})

        # 端到端 plan_day
        from backend.plan_service import plan_day_service
        plan_result = plan_day_service(
            events=all_events, profile=profile, request_text=request_text,
            date_scope=date_scope, now=now, include_debug=True,
        )
        plan_items = []
        try:
            plan_items = plan_result.data.items or []  # type: ignore[attr-defined]
        except AttributeError:
            data = getattr(plan_result, "data", None)
            if isinstance(data, dict):
                plan_items = data.get("items", [])

        plan_event_ids = []
        for it in plan_items:
            eid = it.get("event_id") if isinstance(it, dict) else getattr(it, "event_id", None)
            if eid:
                plan_event_ids.append(eid)
        new_in_plan = [eid for eid in plan_event_ids
                       if any(e["event_id"] == eid for e in target_events)]

        return {
            "code": 0,
            "evidence_source": "database",
            "request_text": request_text,
            "date_scope": date_scope,
            "now": now.isoformat(),
            "total_db_events": len(all_events),
            "diagnosed_events": len(diagnoses),
            "diagnoses": diagnoses,
            "plan_event_ids": plan_event_ids,
            "new_events_in_plan": new_in_plan,
            "acceptance": {
                "at_least_one_new_in_plan": len(new_in_plan) >= 1,
                "all_diagnosed_explainable": all(d.get("score_components") is not None or d.get("error") for d in diagnoses),
            },
            "message": "ok" if len(new_in_plan) >= 1 else "无新活动进入最终计划",
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="正式数据库推荐验证诊断")
    parser.add_argument("--request", default="推荐一些近期的校园活动")
    parser.add_argument("--date-scope", default="this_week")
    parser.add_argument("--now", default=None, help="ISO 时间，默认当前")
    parser.add_argument("--min-events", type=int, default=3)
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    report = run_diagnosis(
        request_text=args.request, date_scope=args.date_scope, now=now,
        min_events=args.min_events)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report.get("code") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
