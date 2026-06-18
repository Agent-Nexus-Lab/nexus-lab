from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from schemas import (
    SourceCreateRequest, SourceCreateData,
    SourceItem, SourceListData,
    ImportUrlRequest, ImportUrlData,
    AdminEventItem, EventListData,
)
from models import Source, RawDocument, Event
import uuid
from datetime import datetime

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/sources")
def create_source(req: SourceCreateRequest, db: Session = Depends(get_db)):
    source = Source(
        id=str(uuid.uuid4()),
        name=req.name,
        source_type=req.source_type,
        base_url=req.base_url,
        feed_url=req.feed_url,
        is_active=req.is_active,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return {
        "code": 0,
        "data": SourceCreateData(
            source_id=source.id,
            name=source.name,
            source_type=source.source_type,
            base_url=source.base_url,
            feed_url=source.feed_url,
            is_active=source.is_active,
            created_at=datetime.now(),
        ).model_dump(mode="json"),
        "message": "ok",
    }


@router.get("/sources")
def list_sources(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    total = db.query(Source).count()
    sources = (
        db.query(Source)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = []
    for s in sources:
        event_count = db.query(Event).filter_by(source_id=s.id).count()
        items.append(SourceItem(
            source_id=s.id,
            name=s.name,
            source_type=s.source_type,
            base_url=s.base_url,
            feed_url=s.feed_url,
            is_active=s.is_active,
            last_crawled_at=s.last_crawled_at,
            event_count=event_count,
        ))
    return {
        "code": 0,
        "data": SourceListData(items=items, total=(total-1)//page_size+1, page=page, page_size=page_size).model_dump(mode="json"),
        "message": "ok",
    }


@router.post("/import-url")
def import_url(req: ImportUrlRequest, db: Session = Depends(get_db)):
    if req.source_id:
        source = db.query(Source).filter_by(id=req.source_id).first()
        if not source:
            raise HTTPException(404, "来源不存在")
    doc = RawDocument(
        id=str(uuid.uuid4()),
        source_id=req.source_id,
        url=req.url,
        status="queued",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {
        "code": 0,
        "data": ImportUrlData(
            document_id=doc.id,
            url=req.url,
            status=doc.status,
        ).model_dump(mode="json"),
        "message": "ok",
    }


@router.get("/events")
def list_events(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    total = db.query(Event).count()
    events = (
        db.query(Event)
        .order_by(Event.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = []
    for e in events:
        source = db.query(Source).filter_by(id=e.source_id).first() if e.source_id else None
        items.append(AdminEventItem(
            event_id=e.id,
            title=e.title,
            summary=e.summary,
            start_time=e.start_time,
            end_time=e.end_time,
            location=e.location,
            campus=e.campus,
            organizer=e.organizer,
            source_name=source.name if source else None,
            source_url=e.source_url,
            tags=e.tags,
            quality_score=e.quality_score or 0.5,
            verification_status=e.verification_status or "unverified",
            is_user_visible=e.is_user_visible if e.is_user_visible is not None else True,
            created_at=e.created_at or datetime.min,
        ))
    return {
        "code": 0,
        "data": EventListData(items=items, total=(total-1)/page_size+1, page=page, page_size=page_size).model_dump(mode="json"),
        "message": "ok",
    }
