# -*- coding: utf-8 -*-
"""从数据库读取可见 Event 供 agent_core.search_events 消费（采集可靠性契约四）。

替代 agent.py router 里的 db.query(Event).all() 全量加载：过滤
is_user_visible=True 且 verification_status != 'rejected'，可选按 campus /
时间区间预过滤，返回含 embedding 字段的 dict 列表。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .models import Event


def search_events_db(
    db: Session,
    *,
    campus: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """读可见 Event 为 dict 列表。

    过滤：is_user_visible=True 且 verification_status != 'rejected'。
    可选预过滤：campus（精确）、start_time ∈ [date_from, date_to]。
    按 start_time 升序，limit 截断。
    """
    q = db.query(Event).filter(
        Event.is_user_visible.is_(True),
        Event.verification_status != "rejected",
    )
    if campus:
        q = q.filter(Event.campus == campus)
    if date_from is not None:
        q = q.filter(Event.start_time >= date_from)
    if date_to is not None:
        q = q.filter(Event.start_time <= date_to)
    q = q.order_by(Event.start_time.asc())
    if limit and limit > 0:
        q = q.limit(limit)

    events = q.all()
    return [_event_to_dict(e) for e in events]


def _event_to_dict(event: Event) -> dict[str, Any]:
    """与梓腾侧 agent_core 期望对齐的 dict 结构。"""
    return {
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
        "source_name": event.source_name,
        "evidence_text": event.evidence_text,
        # embedding 字段（未生成则 None，scoring 走 keyword_fallback）
        "summary_embedding": getattr(event, "summary_embedding", None),
        "embedding_model": getattr(event, "embedding_model", None),
        # 采集可靠性元数据
        "text_source": getattr(event, "text_source", None),
        "text_quality": getattr(event, "text_quality", None),
        "category": getattr(event, "category", None),
    }
