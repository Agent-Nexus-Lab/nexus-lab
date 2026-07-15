"""Persistent background execution for plan-day runs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.plan_service import plan_day_service
from database.database import SessionLocal
from database.memory_service import (
    read_memory,
    reflect_and_store_memory_summary,
    should_reflect_memory_summary,
)
from database.models import Plan, PlanItem, PlanRun, User, UserProfile
from database.search_events_db import search_events_db
from experiments.agent_intent_parser.intent_parser import parse_intent
from experiments.agent_plan_runtime.runtime import DEFAULT_TIMEZONE

logger = logging.getLogger(__name__)

LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))

STAGES = {
    "queued": ("任务已入队", 0.0),
    "load_profile": ("加载用户画像", 0.10),
    "parse_intent": ("解析本轮需求", 0.25),
    "read_memory": ("读取偏好记忆", 0.40),
    "search_events": ("搜索可推荐活动", 0.60),
    "build_schedule": ("生成并排序日程", 0.80),
    "save_plan": ("保存规划结果", 0.95),
    "completed": ("日程已生成", 1.0),
}


def create_plan_run(
    *,
    db: Session,
    user_id: str,
    request_text: str,
    date_scope: str,
    reference_now: datetime | None = None,
) -> PlanRun:
    run = PlanRun(
        id=str(uuid.uuid4()),
        user_id=user_id,
        status="queued",
        request_text=request_text,
        date_scope=date_scope,
        stage="queued",
        stage_message=STAGES["queued"][0],
        progress=STAGES["queued"][1],
        error_message=None,
        debug=None,
        client_context={
            "reference_now": reference_now.isoformat() if reference_now else None,
        },
        cache_hit=False,
        evidence_eligible=False,
        request_fingerprint=_request_fingerprint(request_text, date_scope, reference_now),
        started_at=datetime.now(DEFAULT_TIMEZONE),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def execute_plan_run(run_id: str, reference_now: datetime | None = None) -> None:
    db = SessionLocal()
    started = time.perf_counter()
    run = db.query(PlanRun).filter_by(id=run_id).first()
    if run is None:
        db.close()
        return

    try:
        run.status = "running"
        _set_stage(db, run, "load_profile")
        user = db.query(User).filter_by(id=run.user_id).first()
        profile_raw = db.query(UserProfile).filter_by(user_id=run.user_id).first()
        if user is None or profile_raw is None:
            raise RuntimeError("用户画像未创建")
        profile = {
            "preferred_campuses": profile_raw.preferred_campuses or [],
            "interest_tags": profile_raw.interest_tags or [],
            "activity_style_tags": profile_raw.activity_style_tags or [],
            "available_time": profile_raw.available_time or "",
            "campus": user.campus or "",
            "profile_summary": profile_raw.profile_summary or "",
        }
        profile_loaded_at = time.perf_counter()

        _set_stage(db, run, "parse_intent")
        intent = parse_intent(
            query=run.request_text,
            profile=profile,
            use_llm=True,
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
            timeout=LLM_TIMEOUT,
        )
        run.intent_json = intent.model_dump()
        db.commit()

        _set_stage(db, run, "read_memory")
        memory_started = time.perf_counter()
        memory_context = read_memory(run.user_id, db=db)
        memory_finished = time.perf_counter()

        _set_stage(db, run, "search_events")
        events = search_events_db(db, limit=200)

        _set_stage(db, run, "build_schedule")
        clock = reference_now or datetime.now(DEFAULT_TIMEZONE)
        result = plan_day_service(
            events=events,
            profile=profile,
            request_text=run.request_text,
            date_scope=run.date_scope or "today",
            now=clock,
            include_debug=True,
            enable_llm_rewrite=True,
            llm_base_url=LLM_BASE_URL,
            llm_model=LLM_MODEL,
            llm_timeout=LLM_TIMEOUT,
            memory=memory_context,
            user_id=run.user_id,
        )

        _set_stage(db, run, "save_plan")
        payload = result.model_dump(mode="python")
        inner = payload.get("data") or {}
        plan = Plan(
            id=str(uuid.uuid4()),
            run_id=run.id,
            user_id=run.user_id,
            title=inner.get("title"),
            date_scope=inner.get("date_scope") or run.date_scope,
            summary=inner.get("summary"),
        )
        db.add(plan)
        db.flush()

        items = inner.get("items") or []
        for item_raw in items:
            db.add(PlanItem(
                id=str(uuid.uuid4()),
                plan_id=plan.id,
                event_id=item_raw.get("event_id"),
                start_time=_parse_result_datetime(item_raw.get("start_time")),
                end_time=_parse_result_datetime(item_raw.get("end_time")),
                reason_text=item_raw.get("reason_text", ""),
                score=item_raw.get("score"),
                score_components=item_raw.get("score_components"),
                display_order=item_raw.get("display_order", 0),
            ))

        debug_raw = inner.get("debug") or {}
        if not isinstance(debug_raw, dict):
            debug_raw = {}
        timings = debug_raw.get("timings_ms") or {}
        if not isinstance(timings, dict):
            timings = {}
        timings.update({
            "load_profile": round((profile_loaded_at - started) * 1000),
            "read_memory": round((memory_finished - memory_started) * 1000),
            "total": round((time.perf_counter() - started) * 1000),
        })
        debug_raw["timings_ms"] = timings
        debug_raw["reference_now"] = clock.isoformat()
        debug_raw["memory_used"] = {
            "enabled": bool(memory_context),
            "memory_summary": memory_context.get("memory_summary"),
            "liked_tags": memory_context.get("liked_tags", []),
            "disliked_tags": memory_context.get("disliked_tags", []),
            "negative_keywords": memory_context.get("negative_keywords", []),
            "recent_plan_event_ids": memory_context.get("recent_plan_event_ids", []),
            "memory_item_count": len(memory_context.get("memory_items", [])),
        }
        cache_info = debug_raw.get("cache") or {}
        cache_hit = bool(cache_info.get("cache_hit")) if isinstance(cache_info, dict) else False
        duplicate = _has_previous_evidence_run(db, run)

        run.cache_hit = cache_hit
        run.evidence_eligible = bool(items) and not cache_hit and not duplicate
        run.debug = json.dumps(debug_raw, ensure_ascii=False, default=str)
        run.status = "completed"
        run.ended_at = datetime.now(DEFAULT_TIMEZONE)
        run.stage = "completed"
        run.stage_message = STAGES["completed"][0]
        run.progress = STAGES["completed"][1]
        db.commit()

        if run.evidence_eligible and should_reflect_memory_summary(run.user_id, db=db):
            reflect_and_store_memory_summary(run.user_id, db=db)
    except Exception as exc:
        db.rollback()
        logger.exception("plan run %s failed", run_id)
        failed = db.query(PlanRun).filter_by(id=run_id).first()
        if failed is not None:
            failed.status = "failed"
            failed.error_message = str(exc)
            failed.stage_message = f"{failed.stage_message or failed.stage or '规划'}失败"
            failed.ended_at = datetime.now(DEFAULT_TIMEZONE)
            failed.debug = json.dumps({
                "failed_stage": failed.stage,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }, ensure_ascii=False)
            db.commit()
    finally:
        db.close()


def _set_stage(db: Session, run: PlanRun, stage: str) -> None:
    message, progress = STAGES[stage]
    run.stage = stage
    run.stage_message = message
    run.progress = progress
    db.commit()


def _has_previous_evidence_run(db: Session, run: PlanRun) -> bool:
    return db.query(PlanRun).filter(
        PlanRun.user_id == run.user_id,
        PlanRun.id != run.id,
        PlanRun.status == "completed",
        PlanRun.evidence_eligible.is_(True),
        PlanRun.request_fingerprint == run.request_fingerprint,
    ).first() is not None


def _request_fingerprint(
    request_text: str,
    date_scope: str,
    reference_now: datetime | None,
) -> str:
    clock = reference_now or datetime.now(DEFAULT_TIMEZONE)
    raw = f"{request_text.strip()}::{date_scope}::{clock.date().isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_result_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
