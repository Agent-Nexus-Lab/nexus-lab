from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import uuid
from schemas import PlanDayRequest, PlanDayResponseData, RunItem, RunStatusData
from models import User, PlanRun, Plan, PlanItem, Event, UserProfile
from datetime import datetime
import time
from typing import Any
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
from backend.plan_service import plan_day_service as plan_day_funct
from experiments.agent_plan_runtime.runtime import parse_now, DEFAULT_TIMEZONE
from dotenv import load_dotenv
import os
import json

_parent_dir = str(Path(__file__).parent.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
from memory_service import read_memory

load_dotenv()
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", 30.0))

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/plan-day")
def plan_day(req: PlanDayRequest, db: Session = Depends(get_db)):    
    t_start = time.perf_counter()
    user = db.query(User).first()
    if not user:
        return {"code": 1001, "data": None, "message": "用户画像未创建"}
    runid = str(uuid.uuid4())
    run = PlanRun(
        id=runid,
        user_id=user.id,
        status="running",
        request_text=req.request_text,
        ended_at=None,
        error_message=None,
        date_scope=None,
        intent_json=None,
        stage="load_profile",
        debug=None,
        client_context=None,
    )
    db.add(run)
    db.flush()
    
    profile_raw = db.query(UserProfile).filter_by(user_id=user.id).first()
    if not profile_raw:
        return {"code": 1001, "data": None, "message": "用户画像未创建"}
    profile = {
        "preferred_campuses": profile_raw.preferred_campuses or [],
        "interest_tags": profile_raw.interest_tags or [],
        "activity_style_tags": profile_raw.activity_style_tags or [],
        "available_time": profile_raw.available_time or "",
        "campus": user.campus or "",
        "profile_summary": profile_raw.profile_summary or "",
    }
    t_load_profile = time.perf_counter()  

    run.stage = "parse_intent"
    intent = parse_intent(
        query=req.request_text,
        profile=profile,
        use_llm=True,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        time_out=LLM_TIMEOUT,
    )
    run.intent_json = intent
    run.stage = "read_memory"
    t_before_memory = time.perf_counter()
    memory_context: dict[str, Any] = {}
    try:
        memory_context = read_memory(user.id, db=db)
    except Exception:
        pass
    t_after_memory = time.perf_counter()

    run.stage = "search_events"
    events_raw = db.query(Event).all()
    events = []
    for event in events_raw:
        events.append({
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
        })
    run.stage = "build_schedule"
    try:
        result = plan_day_funct(
            events=events,
            profile=profile,
            request_text=req.request_text,
            date_scope=req.date_scope,
            now=parse_now("2026-05-14T12:00:00+08:00"),
            include_debug=True,
            enable_llm_rewrite=True,
            llm_base_url=LLM_BASE_URL,
            llm_model=LLM_MODEL,
            llm_timeout=LLM_TIMEOUT,
            memory=memory_context,
        )
    except Exception as e:
        run.status = "failed"
        run.error_message = str(e)
        run.ended_at = datetime.now(DEFAULT_TIMEZONE)
        run.debug = None
        db.commit()
        return {"code": 500, "data": None, "message": f"生成失败：{str(e)}"}
    run.stage = "save_plan"
    data = result.model_dump()
    inner = data.get("data") or {}
    plan_id = inner.get("plan_id") or str(uuid.uuid4())

    plan = Plan(
        id=plan_id,
        run_id=runid,
        user_id=user.id,
        title=inner.get("title"),
        date_scope=inner.get("date_scope"),
        summary=inner.get("summary"),
    )
    db.add(plan)
    db.flush()

    items = inner.get("items") or []
    for item_raw in items:
        item = PlanItem(
            id=str(uuid.uuid4()),
            plan_id=plan_id,
            event_id=item_raw.get("event_id"),
            start_time=datetime.fromisoformat(item_raw["start_time"]),
            end_time=datetime.fromisoformat(item_raw["end_time"]) if item_raw.get("end_time") else None,
            reason_text=item_raw.get("reason_text", ""),
            score=item_raw.get("score"),
            score_components=item_raw.get("score_components"),
            matched_terms=,
            matched_reasons=,
            display_order=item_raw.get("display_order", 0),
        )
        db.add(item)

    t_end = time.perf_counter()
    debug_raw = inner.get("debug") or {}
    if not isinstance(debug_raw, dict):
        debug_raw = {}

    timings_ms = {
        "load_profile": round((t_load_profile - t_start) * 1000),
        "read_memory": round((t_after_memory - t_before_memory) * 1000),
    }
    if isinstance(debug_raw, dict) and "timings_ms" in debug_raw:
        timings_ms.update(debug_raw.pop("timings_ms"))
    timings_ms["total"] = round((t_end - t_start) * 1000)
    debug_raw["timings_ms"] = timings_ms

    debug_raw["memory_used"] = {
        "enabled": bool(memory_context),
        "liked_tags": memory_context.get("liked_tags", []),
        "disliked_tags": memory_context.get("disliked_tags", []),
        "negative_keywords": memory_context.get("negative_keywords", []),
        "recent_plan_event_ids": memory_context.get("recent_plan_event_ids", []),
        "memory_item_count": len(memory_context.get("memory_items", [])),
    }
    run.stage = "completed"
    run.status = "completed"
    run.ended_at = datetime.now(DEFAULT_TIMEZONE)
    run.debug = json.dumps(debug_raw, ensure_ascii=False)

    db.commit()
    db.refresh(run)

    return {
        "code": 0,
        "data": PlanDayResponseData(run_id=run.id, status=run.status, stage =run.stage, poll_after_ms=1000).model_dump(mode="json"),
        "message": "ok",
    }


@router.get("/runs/{run_id}")
def get_run_status(run_id: str, db: Session = Depends(get_db)):
    run = db.query(PlanRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(404, "运行记录不存在")

    if run.status == "running":
        return {
            "code": 0,
            "data": {
                "run_id": run_id,
                "status": "running",
                "plan_id": None,
                "title": None,
                "summary": None,
                "items": None,
                "started_at": run.started_at.isoformat() + "+08:00",
                "error_message": None,
                "debug": None,
                "memory_used": None,
                "stage": "loading",
                "stage_message": "正在生成日程...",
                "progress": 0.3,
                "cache_hit": None,
            },
            "message": "ok",
        }

    plan = db.query(Plan).filter_by(run_id=run.id).first()
    items = []
    memory_used = None
    cache_hit = None

    if plan:
        plan_items = (
            db.query(PlanItem)
            .filter_by(plan_id=plan.id)
            .order_by(PlanItem.display_order)
            .all()
        )
        for pi in plan_items:
            event = db.query(Event).filter_by(id=pi.event_id).first() if pi.event_id else None
            items.append(RunItem(
                plan_item_id=pi.id,
                event_id=pi.event_id or "",
                title=event.title if event else "",
                summary=event.summary if event else None,
                start_time=pi.start_time,
                end_time=pi.end_time,
                location=event.location if event else None,
                campus=event.campus if event else None,
                organizer=event.organizer if event else None,
                tags=event.tags if event else None,
                source_url=event.source_url if event else None,
                source_name=event.source_name if event else None,
                reason_text=pi.reason_text,
                score=pi.score,
                score_components=pi.score_components,
                display_order=pi.display_order or 0,
                quality_score=event.quality_score if event else None,
            ))

        if run.debug:
            try:
                debug_data = json.loads(run.debug) if isinstance(run.debug, str) else run.debug
                memory_used = debug_data.get("memory_used")
                cache_info = debug_data.get("cache")
                if isinstance(cache_info, dict):
                    cache_hit = cache_info.get("cache_hit", False)
                else:
                    cache_hit = None
            except (json.JSONDecodeError, TypeError):
                pass

    stage = "completed" if run.status == "completed" else run.status
    stage_message_map = {
        "running": "正在生成日程...",
        "completed": "日程已生成",
        "failed": run.error_message or "生成失败",
    }

    return {
        "code": 0,
        "data": RunStatusData(
            run_id=run.id,
            status=run.status,
            stage = run.stage,
            plan_id=plan.id if plan else None,
            title=plan.title if plan else None,
            summary=plan.summary if plan else None,
            date_scope=plan.date_scope if plan else None,
            request_text=run.request_text,
            memory_used=memory_used,
            items=items if items else None,
            started_at=run.started_at,
            ended_at=run.ended_at,
            error_message=run.error_message,
            debug=run.debug,
            cache_hit=cache_hit,
        ).model_dump(mode="json"),
        "message": "ok",
    }
