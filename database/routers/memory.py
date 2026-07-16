from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db, get_demo_user
import uuid
from datetime import datetime, timezone, timedelta
from models import User, MemoryItem, MemoryAuditLog
from schemas import MemoryItemData, MemoryListData, MemoryActionRequest, MemoryActionData
import sys
from pathlib import Path
_parent_dir = str(Path(__file__).parent.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
from memory_service import suppress_memory_summary

DEFAULT_TIMEZONE = timezone(timedelta(hours=8))

router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/memory")
def get_memory(
    status: str = Query("active", description="active / pending / rejected / deleted / all"),
    memory_scope: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    user = get_demo_user(db)
    if not user:
        return {"code": 1001, "data": None, "message": "用户不存在"}

    q = db.query(MemoryItem).filter_by(user_id=user.id)
    if status != "all":
        q = q.filter_by(status=status)

    total = q.count()
    rows = q.order_by(MemoryItem.priority.desc(), MemoryItem.updated_at.desc()) \
            .offset((page - 1) * page_size) \
            .limit(page_size) \
            .all()

    items = []
    for m in rows:
        items.append(MemoryItemData(
            memory_id=m.id,
            memory_type=m.memory_type,
            memory_scope=m.memory_scope,
            content=m.content,
            structured_content=m.structured_content,
            source_type=m.source_type,
            source_ref=m.source_ref,
            confidence=m.confidence,
            priority=m.priority,
            status=m.status,
            created_at=m.created_at,
            updated_at=m.updated_at,
            expires_at=m.expires_at,
        ))

    return {
        "code": 0,
        "data": MemoryListData(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump(mode="json"),
        "message": "ok",
    }


@router.post("/memory/{memory_id}/confirm")
def confirm_memory(memory_id: str, req: MemoryActionRequest = MemoryActionRequest(), db: Session = Depends(get_db)):
    user = get_demo_user(db)
    if not user:
        return {"code": 1001, "data": None, "message": "用户不存在"}

    mem = db.query(MemoryItem).filter_by(id=memory_id, user_id=user.id).first()
    if not mem:
        return {"code": 1002, "data": None, "message": "记忆不存在"}

    now = datetime.now(DEFAULT_TIMEZONE)
    before = {"status": mem.status, "confidence": mem.confidence}

    mem.status = "active"
    mem.confidence = min(1.0, mem.confidence + 0.3)
    mem.last_confirmed_at = now
    mem.updated_at = now

    audit = MemoryAuditLog(
        id=str(uuid.uuid4()),
        user_id=user.id,
        memory_item_id=mem.id,
        action="confirm",
        before_state=before,
        after_state={"status": mem.status, "confidence": mem.confidence},
        actor="user",
        reason=req.comment or "",
    )
    db.add(audit)
    db.commit()

    return {
        "code": 0,
        "data": MemoryActionData(
            memory_id=mem.id, status=mem.status, last_confirmed_at=mem.last_confirmed_at,
        ).model_dump(mode="json"),
        "message": "ok",
    }


@router.post("/memory/{memory_id}/reject")
def reject_memory(memory_id: str, req: MemoryActionRequest = MemoryActionRequest(), db: Session = Depends(get_db)):
    user = get_demo_user(db)
    if not user:
        return {"code": 1001, "data": None, "message": "用户不存在"}

    mem = db.query(MemoryItem).filter_by(id=memory_id, user_id=user.id).first()
    if not mem:
        return {"code": 1002, "data": None, "message": "记忆不存在"}

    now = datetime.now(DEFAULT_TIMEZONE)
    before = {"status": mem.status}

    mem.status = "rejected"
    mem.updated_at = now
    mem.deleted_at = now

    audit = MemoryAuditLog(
        id=str(uuid.uuid4()),
        user_id=user.id,
        memory_item_id=mem.id,
        action="reject",
        before_state=before,
        after_state={"status": "rejected"},
        actor="user",
        reason=req.comment or "",
    )
    db.add(audit)
    db.commit()

    return {
        "code": 0,
        "data": MemoryActionData(memory_id=mem.id, status=mem.status).model_dump(mode="json"),
        "message": "ok",
    }


@router.delete("/memory/{memory_id}")
def delete_memory(memory_id: str, db: Session = Depends(get_db)):
    user = get_demo_user(db)
    if not user:
        return {"code": 1001, "data": None, "message": "用户不存在"}

    mem = db.query(MemoryItem).filter_by(id=memory_id, user_id=user.id).first()
    if not mem:
        return {"code": 1002, "data": None, "message": "记忆不存在"}

    # memory_summary → suppress (won't be read, won't re-trigger reflection)
    if mem.memory_type == "memory_summary":
        result = suppress_memory_summary(memory_id, db=db)
        return {
            "code": 0,
            "data": MemoryActionData(
                memory_id=mem.id, status=mem.status,
            ).model_dump(mode="json"),
            "message": "ok (suppressed)",
        }

    now = datetime.now(DEFAULT_TIMEZONE)
    before = {"status": mem.status}

    mem.status = "deleted"
    mem.deleted_at = now
    mem.updated_at = now

    audit = MemoryAuditLog(
        id=str(uuid.uuid4()),
        user_id=user.id,
        memory_item_id=mem.id,
        action="delete",
        before_state=before,
        after_state={"status": "deleted"},
        actor="user",
        reason="user deleted memory",
    )
    db.add(audit)
    db.commit()

    return {
        "code": 0,
        "data": MemoryActionData(memory_id=mem.id, status=mem.status).model_dump(mode="json"),
        "message": "ok",
    }
