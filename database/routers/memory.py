from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from models import User, MemoryItem
from schemas import MemoryItemData, MemoryListData

router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/memory")
def get_memory(
    status: str = Query("active", description="active / pending / rejected / deleted / all"),
    memory_scope: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    user = db.query(User).first()
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
