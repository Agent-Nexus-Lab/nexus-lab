from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from schemas import PlanDayRequest, PlanDayResponseData, RunItem, RunStatusData
from models import User, PlanRun, Plan, PlanItem, Event, UserProfile
import uuid
from datetime import datetime
import time

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
    profile = db.query(UserProfile).filter_by(user_id=user.id).first()
    if not profile:
        return {
            "code": 1001,
            "data": None,
            "message": "用户画像未创建，请先提交偏好信息"
        }
    runid = str(uuid.uuid4())
    run = PlanRun(
        id=runid,
        user_id=user.id,
        status="queued",
        request_text=req.request_text,
    )
    db.add(run)
    db.flush()
    planid = str(uuid.uuid4())
    plan = Plan(
        id=planid,
        run_id = runid,
        user_id=user.id,
        title="标题测试",
        date_scope=req.date_scope,
        summary=req.request_text,
    )
    db.add(plan)
    db.flush()
    planitem = PlanItem(
        id = str(uuid.uuid4()),
        plan_id = planid,
        event_id = "17fe89ad-feb2-49a8-9015-6fbd29cb9e4f",
        start_time = datetime.fromisoformat("2026-05-18T19:00:00+08:00"),
        end_time = datetime.fromisoformat("2026-05-18T20:30:00+08:00"),
        reason_text = "主题高度匹配你的 AI 兴趣标签，时间在晚间符合你的空闲时段，步行 5 分钟可达",
        display_order = 1,
    )
    db.add(planitem)
    db.flush()
    planitem = PlanItem(
        id = str(uuid.uuid4()),
        plan_id = planid,
        event_id = "1ec741ec-421a-43a4-8bb8-48fe9aa726f5",
        start_time = datetime.fromisoformat("2026-05-18T20:00:00+08:00"),
        end_time = datetime.fromisoformat("2026-05-18T21:30:00+08:00"),
        reason_text = "同时匹配 AI 和创业两个兴趣标签，互动形式契合你偏好的活动风格",
        display_order = 2,
    )
    db.add(planitem)
    db.flush()
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
    elapsed = time.time() - run.started_at.timestamp()
    # 这应该怎样判断之前安排planitem是否安排完成
    if elapsed < 5:
        return {
            "code": 0,
            "data": {
                "run_id": run_id,
                "status": "running",
                "plan_id": None,
                "title": None,
                "summary": None,
                "items": None,
                "started_at": datetime.now().isoformat() + "+08:00",
                "error_message": None
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
            status="completed",
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
