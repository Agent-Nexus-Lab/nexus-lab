from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db, get_demo_user
from database.models import Event, Plan, PlanItem, PlanRun, User, UserProfile
from database.plan_run_service import create_plan_run, execute_plan_run
from schemas import PlanDayRequest, PlanDayResponseData, RunItem, RunStatusData

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/plan-day", status_code=202)
def plan_day(
    req: PlanDayRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = get_demo_user(db)
    if user is None:
        return {"code": 1001, "data": None, "message": "用户画像未创建"}
    if db.query(UserProfile).filter_by(user_id=user.id).first() is None:
        return {"code": 1001, "data": None, "message": "用户画像未创建"}

    run = create_plan_run(
        db=db,
        user_id=user.id,
        request_text=req.request_text,
        date_scope=req.date_scope,
        reference_now=req.reference_now,
    )
    background_tasks.add_task(execute_plan_run, run.id, req.reference_now)
    return {
        "code": 0,
        "data": PlanDayResponseData(
            run_id=run.id,
            status=run.status,
            stage=run.stage,
            poll_after_ms=500,
        ).model_dump(mode="json"),
        "message": "accepted",
    }


@router.get("/runs/{run_id}")
def get_run_status(run_id: str, db: Session = Depends(get_db)):
    run = db.query(PlanRun).filter_by(id=run_id).first()
    if run is None:
        raise HTTPException(404, "运行记录不存在")

    plan = db.query(Plan).filter_by(run_id=run.id).first()
    items: list[RunItem] = []
    if plan is not None:
        plan_items = (
            db.query(PlanItem)
            .filter_by(plan_id=plan.id)
            .order_by(PlanItem.display_order)
            .all()
        )
        for plan_item in plan_items:
            event = db.query(Event).filter_by(id=plan_item.event_id).first() if plan_item.event_id else None
            items.append(RunItem(
                plan_item_id=plan_item.id,
                event_id=plan_item.event_id or "",
                title=event.title if event else "",
                summary=event.summary if event else None,
                start_time=plan_item.start_time,
                end_time=plan_item.end_time,
                location=event.location if event else None,
                campus=event.campus if event else None,
                organizer=event.organizer if event else None,
                tags=event.tags if event else None,
                source_url=event.source_url if event else None,
                source_name=event.source_name if event else None,
                reason_text=plan_item.reason_text,
                score=plan_item.score,
                score_components=plan_item.score_components,
                display_order=plan_item.display_order or 0,
                quality_score=event.quality_score if event else None,
            ))

    debug_data = _parse_debug(run.debug)
    timings_ms = debug_data.get("timings_ms") if isinstance(debug_data, dict) else None
    memory_used = debug_data.get("memory_used") if isinstance(debug_data, dict) else None

    response = RunStatusData(
        run_id=run.id,
        status=run.status,
        stage=run.stage,
        plan_id=plan.id if plan else None,
        title=plan.title if plan else None,
        summary=plan.summary if plan else None,
        date_scope=plan.date_scope if plan else run.date_scope,
        request_text=run.request_text,
        memory_used=memory_used,
        items=items if items else None,
        started_at=run.started_at,
        ended_at=run.ended_at,
        error_message=run.error_message,
        debug=run.debug,
        cache_hit=bool(run.cache_hit),
        stage_message=run.stage_message,
        progress=run.progress,
        timings_ms=timings_ms,
    )
    return {"code": 0, "data": response.model_dump(mode="json"), "message": "ok"}


def _parse_debug(value: str | dict | None) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}
