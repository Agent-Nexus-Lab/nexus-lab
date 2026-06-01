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


load_dotenv()
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", 30.0))

router = APIRouter(prefix="/api/agent", tags=["agent"])

@router.post("/plan-day")
def plan_day(req: PlanDayRequest, db: Session = Depends(get_db)):
    user = db.query(User).first()
    if not user:
        return {
        "code": 1001,
        "data": None,
        "message": "用户画像未创建，请先提交偏好信息"
        }
    profile_raw = db.query(UserProfile).filter_by(user_id=user.id).first()
    if not profile_raw:
        return {
            "code": 1001,
            "data": None,
            "message": "用户画像未创建，请先提交偏好信息"
        }
    events_raw = db.query(Event).all()
    events = []
    for event in events_raw:
        event_dict = {
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
        }
        events.append(event_dict)
    profile = {
        "preferred_campuses": profile_raw.preferred_campuses or [],
        "interest_tags": profile_raw.interest_tags or [],
        "activity_style_tags": profile_raw.activity_style_tags or [],
        "available_time": profile_raw.available_time or "",
        "campus": user.campus or "",
        "profile_summary": profile_raw.profile_summary or "",
    }
    runid = str(uuid.uuid4())
    run = PlanRun(
        id=runid,
        user_id=user.id,
        status="running",
        request_text=req.request_text,
        ended_at = None,
        error_message = None,
        debug = None
    )
    db.add(run)
    db.flush()
    try:
        result = plan_day_funct(
            events = events,
            profile = profile,
            request_text = req.request_text,
            date_scope = req.date_scope,
            # 方便调试这改成固定时间，记得再改回来
            now = datetime.fromisoformat("2026-05-15T12:00:00+08:00"),
            include_debug = True,
            enable_llm_rewrite = True,
            llm_base_url = LLM_BASE_URL,
            llm_model = LLM_MODEL,
            llm_timeout=LLM_TIMEOUT
        )
        data = result.model_dump()
        plan_id = data.get("plan_id") or str(uuid.uuid4())
        plan = Plan(
            id = plan_id,
            run_id = runid,
            user_id = user.id,
            title = data.get("title"),
            date_scope = data.get("date_scope"),
            summary = data.get("summary"),
        )
        db.add(plan)
        db.flush()

        items = data.get("items") or []
        for item_raw in items:
            item = PlanItem(
                id = str(uuid.uuid4()),
                plan_id = plan_id,
                event_id = item_raw.get("event_id"),
                start_time=datetime.fromisoformat(item_raw["start_time"]).astimezone(DEFAULT_TIMEZONE),
                end_time=datetime.fromisoformat(item_raw["end_time"]).astimezone(DEFAULT_TIMEZONE) if item_raw.get("end_time") else None,
                reason_text=item_raw.get("reason_text", ""),
                display_order=item_raw.get("display_order", 0),
            )
            db.add(item)
        run.status = "completed"
        run.ended_at = datetime.now(DEFAULT_TIMEZONE)
        debug_data = data.get("error_message")
        run.debug = json.dumps(debug_data, ensure_ascii=False) if debug_data else None
    except  Exception as e:
        run.status = "failed"
        run.error_message = str(e)
        run.ended_at = datetime.now(DEFAULT_TIMEZONE)
        db.commit()
        return{
            "code": 500,
            "data": None,
            "message": f"生成失败：{str(e)}"
        }
    db.commit()
    db.refresh(run)

    # 这应该是post根据plan生成planitem并保存到planitem的数据库中
    return {
        "code": 0,
        "data": PlanDayResponseData(run_id=run.id, status=run.status).model_dump(mode="json"),
        "message": "ok",
    }


@router.get("/runs/{run_id}")
def get_run_status(run_id: str, db: Session = Depends(get_db)):
    run = db.query(PlanRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(404, "运行记录不存在")
    # 这应该判断之前安排planitem是否安排完成
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
                "debug": None
            },
            "message": "ok"
        }
    plan = db.query(Plan).filter_by(run_id=run.id).first()
    items = []
    # 完成的话就找item并保存
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
                reason_text=pi.reason_text,
                display_order=pi.display_order or 0,
                quality_score=event.quality_score if event else None,
            ))
    return {
        "code": 0,
        "data": RunStatusData(
            run_id=run.id,
            status=run.status,
            plan_id=plan.id if plan else None,
            title=plan.title if plan else None,
            summary=plan.summary if plan else None,
            date_scope=plan.date_scope if plan else None,
            items=items if items else None,
            started_at=run.started_at,
            ended_at=run.ended_at,
            error_message=run.error_message,
        ).model_dump(mode="json"),
        "message": "ok",
    }