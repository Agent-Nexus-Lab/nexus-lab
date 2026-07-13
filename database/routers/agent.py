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
import hashlib
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
from backend.plan_service import plan_day_service as plan_day_funct
from experiments.agent_plan_runtime.runtime import parse_now, DEFAULT_TIMEZONE
from dotenv import load_dotenv
import os
import json
from experiments.agent_intent_parser.intent_parser import parse_intent
_parent_dir = str(Path(__file__).parent.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
from memory_service import read_memory, decay_memory_summary, reflect_and_store_memory_summary

load_dotenv()
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", 30.0))

router = APIRouter(prefix="/api/agent", tags=["agent"])

# Simple in-memory plan-day cache: key = (user_id, request_text, date_scope) hash
# TTL = 5 minutes; stores the previous result for cache-hit detection
_plan_cache: dict[str, dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _cache_key(user_id: str, request_text: str, date_scope: str) -> str:
    raw = f"{user_id}::{request_text}::{date_scope}"
    return hashlib.sha256(raw.encode()).hexdigest()


@router.post("/plan-day")
def plan_day(req: PlanDayRequest, db: Session = Depends(get_db)):
    t_start = time.perf_counter()
    user = db.query(User).first()
    if not user:
        return {"code": 1001, "data": None, "message": "用户画像未创建"}

    # ---- Cache check ----
    cache_key = _cache_key(user.id, req.request_text, req.date_scope)
    cached = _plan_cache.get(cache_key)
    cache_hit = False
    cache_type: str | None = None
    if cached:
        elapsed = time.time() - cached["cached_at"]
        if elapsed < _CACHE_TTL_SECONDS:
            cache_hit = True
            cache_type = "plan_result"
        else:
            del _plan_cache[cache_key]

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

    # If cache hit, short-circuit with cached result
    if cache_hit and cached:
        t_profile = time.perf_counter()
        run.stage = "completed"
        run.status = "completed"
        run.ended_at = datetime.now(DEFAULT_TIMEZONE)

        # Replay plan + items from cached data so GET /runs/{run_id} resolves correctly
        cached_inner = cached.get("inner") or {}
        plan_id = str(uuid.uuid4())
        plan = Plan(
            id=plan_id,
            run_id=runid,
            user_id=user.id,
            title=cached_inner.get("title"),
            date_scope=cached_inner.get("date_scope"),
            summary=cached_inner.get("summary"),
        )
        db.add(plan)
        db.flush()

        for item_raw in (cached_inner.get("items") or []):
            item = PlanItem(
                id=str(uuid.uuid4()),
                plan_id=plan_id,
                event_id=item_raw.get("event_id"),
                start_time=datetime.fromisoformat(item_raw["start_time"]),
                end_time=datetime.fromisoformat(item_raw["end_time"]) if item_raw.get("end_time") else None,
                reason_text=item_raw.get("reason_text", ""),
                score=item_raw.get("score"),
                score_components=item_raw.get("score_components"),
                display_order=item_raw.get("display_order", 0),
            )
            db.add(item)

        cached_debug = dict(cached.get("debug_raw") or {})
        cached_debug["cache"] = {
            "cache_hit": True,
            "cache_type": "plan_result",
            "cached_from_run_id": cached.get("run_id"),
            "cache_key": cache_key,
            "cache_age_seconds": round(time.time() - cached["cached_at"], 1),
        }
        cached_debug["timings_ms"] = {
            "load_profile": round((t_profile - t_start) * 1000),
            "cache_hit": True,
        }
        run.debug = json.dumps(cached_debug, ensure_ascii=False)
        db.commit()
        db.refresh(run)

        return {
            "code": 0,
            "data": PlanDayResponseData(
                run_id=run.id, status=run.status, stage=run.stage, poll_after_ms=500,
            ).model_dump(mode="json"),
            "message": "ok (cached)",
        }

    # ---- Normal flow ----
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
    db.flush()
    intent = parse_intent(
        query=req.request_text,
        profile=profile,
        use_llm=True,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        timeout=LLM_TIMEOUT,
    )
    run.intent_json = intent.model_dump()
    run.stage = "read_memory"
    db.flush()
    t_before_memory = time.perf_counter()
    memory_context: dict[str, Any] = {}
    try:
        memory_context = read_memory(user.id, db=db)
    except Exception:
        pass
    t_after_memory = time.perf_counter()

    run.stage = "search_events"
    db.flush()
    # 切到 search_events_db：过滤可见 + 未拒绝，含 embedding 字段（采集可靠性契约四）
    from database.search_events_db import search_events_db
    events = search_events_db(db, limit=200)
    run.stage = "build_schedule"
    db.flush()
    try:
        result = plan_day_funct(
            events=events,
            profile=profile,
            request_text=req.request_text,
            date_scope=req.date_scope,
            now=parse_now("2026-06-08T12:00:00+08:00"),
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
    db.flush()
    data = result.model_dump()
    inner = data.get("data") or {}
    plan_id = str(uuid.uuid4())

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
    old_timings = debug_raw.pop("timings_ms", None)
    if isinstance(old_timings, dict):
        timings_ms.update(old_timings)
    debug_raw["timings_ms"] = timings_ms

    debug_raw["memory_used"] = {
        "enabled": bool(memory_context),
        "liked_tags": memory_context.get("liked_tags", []),
        "disliked_tags": memory_context.get("disliked_tags", []),
        "negative_keywords": memory_context.get("negative_keywords", []),
        "recent_plan_event_ids": memory_context.get("recent_plan_event_ids", []),
        "memory_item_count": len(memory_context.get("memory_items", [])),
    }
    debug_raw["cache"] = {
        "cache_hit": False,
        "cache_type": None,
    }

    # Store in cache for next request (include full plan data for replay on cache hit)
    _plan_cache[cache_key] = {
        "run_id": runid,
        "inner": {
            "title": inner.get("title"),
            "date_scope": inner.get("date_scope"),
            "summary": inner.get("summary"),
            "items": inner.get("items") or [],
        },
        "debug_raw": dict(debug_raw),
        "cached_at": time.time(),
    }

    run.stage = "completed"
    run.status = "completed"
    run.ended_at = datetime.now(DEFAULT_TIMEZONE)
    run.debug = json.dumps(debug_raw, ensure_ascii=False)

    db.commit()
    db.refresh(run)

    # ---- Post-plan-day memory lifecycle ----
    # 1. Decay existing memory_summary items
    try:
        decay_memory_summary(user.id, db=db)
    except Exception:
        pass

    # 2. Reflect every 3 runs
    try:
        run_count = db.query(PlanRun).filter_by(user_id=user.id, status="completed").count()
        if run_count % 3 == 0:
            reflect_and_store_memory_summary(user.id, db=db)
    except Exception:
        pass

    return {
        "code": 0,
        "data": PlanDayResponseData(
            run_id=run.id, status=run.status, stage=run.stage, poll_after_ms=1000,
        ).model_dump(mode="json"),
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

    stage = run.stage or ("completed" if run.status == "completed" else run.status)

    # Resolve stage_message and progress from debug timings / stage
    stage_messages: dict[str, str] = {
        "load_profile": "加载用户画像...",
        "parse_intent": "解析意图...",
        "read_memory": "读取记忆...",
        "search_events": "搜索活动...",
        "build_schedule": "生成日程...",
        "save_plan": "保存日程...",
        "completed": "日程已生成",
        "failed": run.error_message or "生成失败",
    }
    stage_message = stage_messages.get(stage, "处理中...")

    # progress heuristic: each stage is ~16%, with final stages weighted more
    stage_progress: dict[str, float] = {
        "load_profile": 0.10,
        "parse_intent": 0.25,
        "read_memory": 0.40,
        "search_events": 0.55,
        "build_schedule": 0.80,
        "save_plan": 0.95,
        "completed": 1.0,
        "failed": 1.0,
    }
    progress = stage_progress.get(stage, 0.5)

    # Extract timings_ms from debug
    timings_ms = None
    if run.debug:
        try:
            debug_data = json.loads(run.debug) if isinstance(run.debug, str) else run.debug
            timings_ms = debug_data.get("timings_ms")
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "code": 0,
        "data": RunStatusData(
            run_id=run.id,
            status=run.status,
            stage=stage,
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
            stage_message=stage_message,
            progress=progress,
            timings_ms=timings_ms,
        ).model_dump(mode="json"),
        "message": "ok",
    }
