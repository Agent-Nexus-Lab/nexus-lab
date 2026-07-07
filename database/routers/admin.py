from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from schemas import (
    SourceCreateRequest, SourceCreateData,
    SourceItem, SourceListData,
    ImportUrlRequest, ImportUrlData,
    AdminEventItem, EventListData,
    DataHealthData,
    CampusBreakdown, SourceBreakdownItem, QualitySummaryData,
)
from models import Source, RawDocument, Event
import uuid
from datetime import datetime, timedelta, timezone

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _event_is_visible(event: Event) -> bool:
    return event.is_user_visible is not False


def _source_bucket(event: Event, sources_by_id: dict[str, Source]) -> str:
    if event.source_id and event.source_id in sources_by_id:
        return sources_by_id[event.source_id].source_type or "unknown"
    if event.source_name:
        return event.source_name
    return "unknown"


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


@router.get("/data-health")
def get_data_health(db: Session = Depends(get_db)):
    now = _as_utc_naive(datetime.now(timezone.utc))
    future_3d = now + timedelta(days=3)
    future_7d = now + timedelta(days=7)
    future_14d = now + timedelta(days=14)
    expired_cutoff = now - timedelta(days=7)

    events = db.query(Event).all()
    sources = db.query(Source).all()
    sources_by_id = {source.id: source for source in sources}

    visible_events = [event for event in events if _event_is_visible(event)]
    future_events = [
        event for event in visible_events
        if event.start_time and _as_utc_naive(event.start_time) >= now
    ]

    def count_before(cutoff: datetime) -> int:
        return sum(1 for event in future_events if _as_utc_naive(event.start_time) < cutoff)

    source_breakdown: dict[str, int] = {}
    for event in visible_events:
        bucket = _source_bucket(event, sources_by_id)
        source_breakdown[bucket] = source_breakdown.get(bucket, 0) + 1

    recently_expired = sum(
        1 for event in visible_events
        if event.end_time
        and expired_cutoff <= _as_utc_naive(event.end_time) < now
    )

    latest_source_time = max(
        [source.last_crawled_at for source in sources if source.last_crawled_at],
        default=None,
    )
    latest_doc = (
        db.query(RawDocument)
        .order_by(RawDocument.fetched_at.desc())
        .first()
    )
    latest_doc_time = latest_doc.fetched_at if latest_doc and latest_doc.fetched_at else None

    last_collection_time = max(
        [value for value in [latest_source_time, latest_doc_time] if value],
        default=None,
    )
    last_collection_result = latest_doc.status if latest_doc and latest_doc.status else "unknown"

    future_events_3d = count_before(future_3d)
    future_events_7d = count_before(future_7d)
    future_events_14d = count_before(future_14d)

    alerts = []
    if future_events_3d < 5:
        alerts.append("未来 3 天活动不足 5 个，建议立即触发采集。")
    if future_events_7d < 5:
        alerts.append("未来 7 天活动不足 5 个，推荐结果可能偏少。")
    if not last_collection_time:
        alerts.append("还没有采集记录，请确认自动采集器是否已接入。")
    elif now - _as_utc_naive(last_collection_time) > timedelta(hours=24):
        alerts.append("最近一次采集已超过 24 小时，请检查采集任务。")
    if last_collection_result not in {"success", "completed", "done", "ok", "unknown"}:
        alerts.append(f"最近一次采集状态为 {last_collection_result}，需要排查。")

    return {
        "code": 0,
        "data": DataHealthData(
            total_events=len(visible_events),
            future_events_3d=future_events_3d,
            future_events_7d=future_events_7d,
            future_events_14d=future_events_14d,
            recently_expired=recently_expired,
            sources_breakdown=source_breakdown,
            last_collection_time=last_collection_time,
            last_collection_result=last_collection_result,
            is_healthy=len(alerts) == 0,
            alerts=alerts,
        ).model_dump(mode="json"),
        "message": "ok",
    }


@router.get("/events/quality-summary")
def get_quality_summary(
    now: str | None = None,
    campus: str | None = None,
    source_id: str | None = None,
    db: Session = Depends(get_db),
):
    ref_now: datetime
    if now:
        try:
            ref_now = datetime.fromisoformat(now)
        except ValueError:
            ref_now = datetime.now(timezone.utc)
    else:
        ref_now = datetime.now(timezone.utc)

    events_query = db.query(Event)
    if campus:
        events_query = events_query.filter_by(campus=campus)
    if source_id:
        events_query = events_query.filter_by(source_id=source_id)

    events = events_query.all()

    def start_utc(e: Event) -> datetime | None:
        return e.start_time if e.start_time else None

    def end_utc(e: Event) -> datetime | None:
        return e.end_time if e.end_time else None

    total_events = len(events)
    visible_events = sum(1 for e in events if e.is_user_visible is not False)
    future_events = sum(1 for e in events if start_utc(e) and start_utc(e) >= ref_now)
    expired_events = sum(1 for e in events if end_utc(e) and end_utc(e) < ref_now)
    stale_events = sum(
        1 for e in events
        if e.updated_at and (ref_now - (e.updated_at.replace(tzinfo=None) if e.updated_at.tzinfo else e.updated_at.replace(tzinfo=timezone.utc))).days > 7
    )
    missing_time_count = sum(1 for e in events if not e.start_time or not e.end_time)
    missing_location_count = sum(1 for e in events if not e.location)
    missing_source_url_count = sum(1 for e in events if not e.source_url)
    missing_evidence_count = sum(1 for e in events if not e.evidence_text)

    # by_campus
    campus_map: dict[str, dict[str, int]] = {}
    for e in events:
        c = e.campus or "未知"
        if c not in campus_map:
            campus_map[c] = {"future_events": 0, "expired_events": 0}
        if start_utc(e) and start_utc(e) >= ref_now:
            campus_map[c]["future_events"] += 1
        if end_utc(e) and end_utc(e) < ref_now:
            campus_map[c]["expired_events"] += 1
    by_campus = [
        CampusBreakdown(campus=c, future_events=v["future_events"], expired_events=v["expired_events"])
        for c, v in sorted(campus_map.items())
    ]

    # by_source
    all_source_ids = {e.source_id for e in events if e.source_id}
    sources = db.query(Source).filter(Source.id.in_(all_source_ids)).all() if all_source_ids else []
    source_name_map = {s.id: s.name for s in sources}

    source_map: dict[str, dict[str, int]] = {}
    for e in events:
        sid = e.source_id or "unknown"
        if sid not in source_map:
            source_map[sid] = {"future_events": 0, "missing_evidence_count": 0}
        if start_utc(e) and start_utc(e) >= ref_now:
            source_map[sid]["future_events"] += 1
        if not e.evidence_text:
            source_map[sid]["missing_evidence_count"] += 1
    by_source = [
        SourceBreakdownItem(
            source_id=sid,
            source_name=source_name_map.get(sid, "未知来源"),
            future_events=v["future_events"],
            missing_evidence_count=v["missing_evidence_count"],
        )
        for sid, v in sorted(source_map.items())
    ]

    return {
        "code": 0,
        "data": QualitySummaryData(
            total_events=total_events,
            future_events=future_events,
            expired_events=expired_events,
            visible_events=visible_events,
            stale_events=stale_events,
            missing_time_count=missing_time_count,
            missing_location_count=missing_location_count,
            missing_source_url_count=missing_source_url_count,
            missing_evidence_count=missing_evidence_count,
            by_campus=by_campus,
            by_source=by_source,
            generated_at=datetime.now(timezone.utc),
        ).model_dump(mode="json"),
        "message": "ok",
    }
