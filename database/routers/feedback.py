from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
import uuid
from schemas import (
    FeedbackEventRequest, FeedbackEventData,
    FeedbackPlanRequest, FeedbackPlanData,
)
from models import User, UserEventFeedback, Event
from memory_service import update_memory_from_feedback

router = APIRouter(prefix="/api", tags=["feedback"])


@router.post("/feedback/event")
def submit_event_feedback(req: FeedbackEventRequest, db: Session = Depends(get_db)):
    user = db.query(User).first()
    if not user:
        return {"code": 1001, "data": None, "message": "用户不存在"}

    valid_types = {"like", "dislike", "clicked_source"}
    if req.feedback_type not in valid_types:
        return {"code": 1002, "data": None, "message": f"feedback_type 无效，仅支持: {', '.join(valid_types)}"}

    feedback_id = str(uuid.uuid4())
    feedback = UserEventFeedback(
        id=feedback_id,
        user_id=user.id,
        event_id=req.event_id,
        plan_id=req.plan_id,
        plan_item_id=req.plan_item_id,
        run_id=req.run_id,
        feedback_type=req.feedback_type,
        feedback_source=req.feedback_source,
        comment=req.comment,
        feedback_metadata=req.metadata,
    )
    db.add(feedback)
    db.flush()

    # Load event tags/title for memory update
    event = db.query(Event).filter_by(id=req.event_id).first() if req.event_id else None
    event_tags = event.tags if event and event.tags else []
    event_title = event.title if event else None

    mem_result = update_memory_from_feedback(
        db=db,
        feedback=feedback,
        event_tags=event_tags,
        event_title=event_title,
    )

    db.commit()

    return {
        "code": 0,
        "data": FeedbackEventData(
            feedback_id=feedback_id,
            memory_candidate_ids=sorted(set(
                mem_result.get("created_memory_ids", [])
                + mem_result.get("updated_memory_ids", [])
            )),
        ).model_dump(mode="json"),
        "message": "ok",
    }


@router.post("/feedback/plan")
def submit_plan_feedback(req: FeedbackPlanRequest, db: Session = Depends(get_db)):
    user = db.query(User).first()
    if not user:
        return {"code": 1001, "data": None, "message": "用户不存在"}

    valid_types = {"like", "dislike", "regenerate", "too_many_conflicts", "not_enough_items", "not_relevant"}
    if req.feedback_type not in valid_types:
        return {"code": 1002, "data": None, "message": f"feedback_type 无效，仅支持: {', '.join(valid_types)}"}

    feedback_id = str(uuid.uuid4())
    feedback = UserEventFeedback(
        id=feedback_id,
        user_id=user.id,
        event_id=None,
        plan_id=req.plan_id,
        plan_item_id=None,
        run_id=req.run_id,
        feedback_type=req.feedback_type,
        feedback_source="history_page",
        comment=req.comment,
        feedback_metadata=req.metadata,
    )
    db.add(feedback)
    db.commit()

    return {
        "code": 0,
        "data": FeedbackPlanData(feedback_id=feedback_id).model_dump(mode="json"),
        "message": "ok",
    }
