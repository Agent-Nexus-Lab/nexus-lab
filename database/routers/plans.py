from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db, get_demo_user
from schemas import PlanListItem, PlanListData, PlanDetailData, RunItem
from models import User, Plan, PlanItem, Event
from datetime import datetime

router = APIRouter(prefix="/api", tags=["plans"])


@router.get("/plans")
def list_plans(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    user = get_demo_user(db)
    if not user:
        return {
            "code": 0,
            "data": PlanListData(items=[], total=0, page=page, page_size=page_size).model_dump(mode="json"),
            "message": "ok",
        }
    total = db.query(Plan).filter_by(user_id=user.id).count()
    plans = (
        db.query(Plan)
        .filter_by(user_id=user.id)
        .order_by(Plan.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = []
    for plan in plans:
        item_count = db.query(PlanItem).filter_by(plan_id=plan.id).count()
        items.append(PlanListItem(
            plan_id=plan.id,
            title=plan.title or "",
            date_scope=plan.date_scope or "",
            summary=plan.summary,
            item_count=item_count,
            created_at=plan.created_at or datetime.min,
        ))
    return {
        "code": 0,
        "data": PlanListData(items=items, total=total, page=page, page_size=page_size).model_dump(mode="json"),
        "message": "ok",
    }


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, db: Session = Depends(get_db)):
    plan = db.query(Plan).filter_by(id=plan_id).first()
    if not plan:
        raise HTTPException(404, "日程不存在")
    plan_items = (
        db.query(PlanItem)
        .filter_by(plan_id=plan.id)
        .order_by(PlanItem.display_order)
        .all()
    )
    items = []
    for pi in plan_items:
        event = db.query(Event).filter_by(id=pi.event_id).first() if pi.event_id else None
        items.append(RunItem(
            plan_item_id=pi.id,
            event_id=pi.event_id or "",
            title=event.title if event else "",
            summary=event.summary if event else None,
            start_time=pi.start_time or datetime.min,
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
    return {
        "code": 0,
        "data": PlanDetailData(
            plan_id=plan.id,
            title=plan.title or "",
            date_scope=plan.date_scope or "",
            summary=plan.summary,
            items=items,
            created_at=plan.created_at or datetime.min,
        ).model_dump(mode="json"),
        "message": "ok",
    }
