from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
import uuid
from schemas import FeedbackEventRequest, FeedbackEventData
from models import User, UserEventFeedback

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
        metadata=req.metadata,
    )
    db.add(feedback)
    db.commit()

    return {
        "code": 0,
        "data": FeedbackEventData(feedback_id=feedback_id).model_dump(mode="json"),
        "message": "ok",
    }
