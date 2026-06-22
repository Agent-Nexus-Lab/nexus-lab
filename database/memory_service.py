"""Memory aggregation and update services.

read_memory — aggregate feedback + history into structured Memory dict.
update_memory_from_feedback — create/update memory_items from user feedback.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from models import (
    MemoryAuditLog,
    MemoryItem,
    Plan,
    PlanItem,
    PlanRun,
    UserEventFeedback,
    UserProfile,
)

DEFAULT_TIMEZONE = timezone(timedelta(hours=8))
MEMORY_EXPIRY_DAYS = 30
MAX_MEMORY_ITEMS = 20


def read_memory(
    user_id: str,
    *,
    db: Session,
    now: datetime | None = None,
    limit: int = MAX_MEMORY_ITEMS,
) -> dict[str, Any]:
    """Aggregate user feedback + history into structured Memory dict.

    Output consumed by search_events / scoring as the `memory` parameter.
    """
    if now is None:
        now = datetime.now(DEFAULT_TIMEZONE)

    liked_tags: list[str] = []
    disliked_tags: list[str] = []
    negative_keywords: list[str] = []
    liked_event_ids: list[str] = []
    disliked_event_ids: list[str] = []
    memory_items: list[dict[str, Any]] = []

    # 1. Active memory_items
    active = (
        db.query(MemoryItem)
        .filter_by(user_id=user_id, status="active")
        .order_by(MemoryItem.priority.desc())
        .limit(limit)
        .all()
    )

    for m in active:
        sc = m.structured_content or {}
        if not isinstance(sc, dict):
            sc = {}

        memory_items.append({
            "memory_id": m.id,
            "memory_type": m.memory_type,
            "content": m.content,
            "confidence": m.confidence,
            "priority": m.priority,
        })

        if m.memory_type in ("liked_tag", "positive_preference", "explicit_interest"):
            liked_tags.extend(sc.get("tags") or [])
            liked_event_ids.extend(sc.get("event_ids") or [])
        elif m.memory_type in ("disliked_tag", "negative_preference"):
            disliked_tags.extend(sc.get("negative_tags") or sc.get("tags") or [])
            negative_keywords.extend(sc.get("keywords") or [])
            disliked_event_ids.extend(sc.get("event_ids") or [])
        elif m.memory_type == "negative_keyword":
            negative_keywords.extend(sc.get("keywords") or [])
        elif m.memory_type == "liked_event":
            liked_event_ids.extend(sc.get("event_ids") or [])
        elif m.memory_type == "disliked_event":
            disliked_event_ids.extend(sc.get("event_ids") or [])

    # 2. Recent plan event_ids (last 3 plans)
    recent_plan_ids = [
        r[0] for r in
        db.query(Plan.id)
        .filter_by(user_id=user_id)
        .order_by(Plan.created_at.desc())
        .limit(3)
        .all()
    ]
    recent_plan_event_ids: list[str] = []
    if recent_plan_ids:
        seen: set[str] = set()
        for (eid,) in db.query(PlanItem.event_id).filter(
            PlanItem.plan_id.in_(recent_plan_ids),
            PlanItem.event_id.isnot(None),
        ).all():
            if eid not in seen:
                seen.add(eid)
                recent_plan_event_ids.append(eid)

    # 3. Recent query texts (last 5 runs)
    recent_query_texts = [
        r[0] for r in
        db.query(PlanRun.request_text)
        .filter_by(user_id=user_id)
        .order_by(PlanRun.started_at.desc())
        .limit(5)
        .all()
        if r[0]
    ]

    # 4. Preferred campuses from profile
    profile = db.query(UserProfile).filter_by(user_id=user_id).first()
    preferred_campuses = profile.preferred_campuses if profile else []

    return {
        "session_id": str(uuid.uuid4()),
        "recent_query_texts": recent_query_texts,
        "recent_plan_event_ids": recent_plan_event_ids,
        "liked_tags": _dedup(liked_tags),
        "disliked_tags": _dedup(disliked_tags),
        "preferred_campuses": preferred_campuses,
        "negative_keywords": _dedup(negative_keywords),
        "liked_event_ids": _dedup(liked_event_ids),
        "disliked_event_ids": _dedup(disliked_event_ids),
        "memory_items": memory_items,
    }


def update_memory_from_feedback(
    *,
    db: Session,
    feedback: UserEventFeedback,
    event_tags: list[str] | None = None,
    event_title: str | None = None,
) -> dict[str, Any]:
    """Create/update memory_items based on a new feedback entry.

    - dislike → disliked_tag per tag + disliked_event + negative keywords from title
    - like → liked_tag per tag + liked_event
    - clicked_source → light liked_tag (only after 2+ clicks on same event)

    Confidence: starts at 0.5, each repeated same action +0.15 (max 1.0).
    Returns {created_memory_ids, updated_memory_ids, audit_log_ids}.
    """
    now = datetime.now(DEFAULT_TIMEZONE)
    feedback_type = feedback.feedback_type
    tags = event_tags or []

    created_ids: list[str] = []
    updated_ids: list[str] = []
    audit_ids: list[str] = []

    if feedback_type not in ("like", "dislike", "clicked_source"):
        return {
            "created_memory_ids": created_ids,
            "updated_memory_ids": updated_ids,
            "audit_log_ids": audit_ids,
        }

    if feedback_type == "dislike":
        for tag in tags:
            _upsert_tag_memory(db, feedback.user_id, "disliked_tag", tag,
                               feedback.event_id, feedback.id, now,
                               created_ids, updated_ids, audit_ids)

        if feedback.event_id:
            _upsert_event_memory(db, feedback.user_id, "disliked_event",
                                 feedback.event_id, feedback.id, now,
                                 created_ids, updated_ids, audit_ids)

        if event_title:
            for kw in _extract_keywords(event_title):
                _upsert_keyword_memory(db, feedback.user_id, kw,
                                       feedback.id, now,
                                       created_ids, updated_ids, audit_ids)

    elif feedback_type == "like":
        for tag in tags:
            _upsert_tag_memory(db, feedback.user_id, "liked_tag", tag,
                               feedback.event_id, feedback.id, now,
                               created_ids, updated_ids, audit_ids)

        if feedback.event_id:
            _upsert_event_memory(db, feedback.user_id, "liked_event",
                                 feedback.event_id, feedback.id, now,
                                 created_ids, updated_ids, audit_ids)

    elif feedback_type == "clicked_source":
        click_count = (
            db.query(UserEventFeedback)
            .filter_by(user_id=feedback.user_id, event_id=feedback.event_id,
                       feedback_type="clicked_source")
            .count()
        )
        if click_count >= 1:
            for tag in tags:
                _upsert_tag_memory(db, feedback.user_id, "liked_tag", tag,
                                   feedback.event_id, feedback.id, now,
                                   created_ids, updated_ids, audit_ids,
                                   confidence=0.35)

    db.commit()
    return {
        "created_memory_ids": created_ids,
        "updated_memory_ids": updated_ids,
        "audit_log_ids": audit_ids,
    }


# ===========================================================================
# Internal helpers
# ===========================================================================


def _upsert_tag_memory(
    db: Session,
    user_id: str,
    memory_type: str,
    tag: str,
    event_id: str,
    source_ref: str,
    now: datetime,
    created_ids: list[str],
    updated_ids: list[str],
    audit_ids: list[str],
    confidence: float | None = None,
) -> str:
    if not tag:
        return ""

    expires_at = now + timedelta(days=MEMORY_EXPIRY_DAYS)

    existing = (
        db.query(MemoryItem)
        .filter_by(user_id=user_id, memory_type=memory_type, status="active")
        .all()
    )
    matched: MemoryItem | None = None
    for m in existing:
        sc = m.structured_content or {}
        if not isinstance(sc, dict):
            sc = {}
        stored = sc.get("tags") or sc.get("negative_tags") or []
        if tag in stored:
            matched = m
            break

    if matched:
        before = {"confidence": matched.confidence, "structured_content": matched.structured_content}
        matched.confidence = min(1.0, matched.confidence + 0.15)
        matched.priority = min(100, matched.priority + 5)
        matched.updated_at = now
        matched.expires_at = expires_at
        matched.source_ref = source_ref

        sc = dict(matched.structured_content or {})
        key = "negative_tags" if memory_type == "disliked_tag" else "tags"
        tag_list = list(sc.get(key) or [])
        if tag not in tag_list:
            tag_list.append(tag)
        sc[key] = tag_list
        sc["evidence_count"] = sc.get("evidence_count", 0) + 1
        matched.structured_content = sc

        audit_ids.append(_write_audit(db, user_id, matched.id, "update", before,
                                      {"confidence": matched.confidence, "structured_content": sc},
                                      f"feedback:{source_ref}"))
        updated_ids.append(matched.id)
        return matched.id

    # Create new
    mem_id = str(uuid.uuid4())
    conf = confidence if confidence is not None else 0.5
    key = "negative_tags" if memory_type == "disliked_tag" else "tags"
    sc = {key: [tag], "evidence_count": 1}
    content = f"用户{'喜欢' if 'liked' in memory_type else '不喜欢'}标签「{tag}」"

    db.add(MemoryItem(
        id=mem_id, user_id=user_id, memory_type=memory_type,
        memory_scope="short_term", content=content, structured_content=sc,
        source_type="feedback", source_ref=source_ref,
        confidence=conf, priority=50, status="active", expires_at=expires_at,
    ))
    audit_ids.append(_write_audit(db, user_id, mem_id, "create", None,
                                  {"memory_type": memory_type, "structured_content": sc, "confidence": conf},
                                  f"feedback:{source_ref}"))
    created_ids.append(mem_id)
    return mem_id


def _upsert_event_memory(
    db: Session,
    user_id: str,
    memory_type: str,
    event_id: str,
    source_ref: str,
    now: datetime,
    created_ids: list[str],
    updated_ids: list[str],
    audit_ids: list[str],
    confidence: float | None = None,
) -> str:
    if not event_id:
        return ""

    expires_at = now + timedelta(days=MEMORY_EXPIRY_DAYS)

    existing = (
        db.query(MemoryItem)
        .filter_by(user_id=user_id, memory_type=memory_type, status="active")
        .all()
    )
    matched: MemoryItem | None = None
    for m in existing:
        sc = m.structured_content or {}
        if not isinstance(sc, dict):
            sc = {}
        if event_id in (sc.get("event_ids") or []):
            matched = m
            break

    if matched:
        before = {"confidence": matched.confidence, "structured_content": matched.structured_content}
        matched.confidence = min(1.0, matched.confidence + 0.15)
        matched.priority = min(100, matched.priority + 5)
        matched.updated_at = now
        matched.expires_at = expires_at
        matched.source_ref = source_ref

        sc = dict(matched.structured_content or {})
        ids = list(sc.get("event_ids") or [])
        if event_id not in ids:
            ids.append(event_id)
        sc["event_ids"] = ids
        sc["evidence_count"] = sc.get("evidence_count", 0) + 1
        matched.structured_content = sc

        audit_ids.append(_write_audit(db, user_id, matched.id, "update", before,
                                      {"confidence": matched.confidence, "structured_content": sc},
                                      f"feedback:{source_ref}"))
        updated_ids.append(matched.id)
        return matched.id

    # Create new
    mem_id = str(uuid.uuid4())
    conf = confidence if confidence is not None else 0.5
    sc = {"event_ids": [event_id], "evidence_count": 1}

    db.add(MemoryItem(
        id=mem_id, user_id=user_id, memory_type=memory_type,
        memory_scope="short_term",
        content=f"用户{'喜欢' if 'liked' in memory_type else '不喜欢'}活动 {event_id}",
        structured_content=sc, source_type="feedback", source_ref=source_ref,
        confidence=conf, priority=50, status="active", expires_at=expires_at,
    ))
    audit_ids.append(_write_audit(db, user_id, mem_id, "create", None,
                                  {"memory_type": memory_type, "structured_content": sc, "confidence": conf},
                                  f"feedback:{source_ref}"))
    created_ids.append(mem_id)
    return mem_id


def _upsert_keyword_memory(
    db: Session,
    user_id: str,
    keyword: str,
    source_ref: str,
    now: datetime,
    created_ids: list[str],
    updated_ids: list[str],
    audit_ids: list[str],
) -> str:
    if not keyword:
        return ""

    expires_at = now + timedelta(days=MEMORY_EXPIRY_DAYS)

    existing = (
        db.query(MemoryItem)
        .filter_by(user_id=user_id, memory_type="negative_keyword", status="active")
        .all()
    )
    matched: MemoryItem | None = None
    for m in existing:
        sc = m.structured_content or {}
        if not isinstance(sc, dict):
            sc = {}
        if keyword in (sc.get("keywords") or []):
            matched = m
            break

    if matched:
        before = {"confidence": matched.confidence, "structured_content": matched.structured_content}
        matched.confidence = min(1.0, matched.confidence + 0.15)
        matched.updated_at = now
        matched.expires_at = expires_at
        matched.source_ref = source_ref

        sc = dict(matched.structured_content or {})
        kws = list(sc.get("keywords") or [])
        if keyword not in kws:
            kws.append(keyword)
        sc["keywords"] = kws
        sc["evidence_count"] = sc.get("evidence_count", 0) + 1
        matched.structured_content = sc

        audit_ids.append(_write_audit(db, user_id, matched.id, "update", before,
                                      {"structured_content": sc}, f"feedback:{source_ref}"))
        updated_ids.append(matched.id)
        return matched.id

    mem_id = str(uuid.uuid4())
    sc = {"keywords": [keyword], "evidence_count": 1}
    db.add(MemoryItem(
        id=mem_id, user_id=user_id, memory_type="negative_keyword",
        memory_scope="short_term",
        content=f"用户不希望看到包含「{keyword}」的内容",
        structured_content=sc, source_type="feedback", source_ref=source_ref,
        confidence=0.5, priority=50, status="active", expires_at=expires_at,
    ))
    audit_ids.append(_write_audit(db, user_id, mem_id, "create", None,
                                  {"memory_type": "negative_keyword", "structured_content": sc},
                                  f"feedback:{source_ref}"))
    created_ids.append(mem_id)
    return mem_id


def _write_audit(
    db: Session,
    user_id: str,
    memory_item_id: str,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    reason: str = "",
) -> str:
    audit_id = str(uuid.uuid4())
    db.add(MemoryAuditLog(
        id=audit_id, user_id=user_id, memory_item_id=memory_item_id,
        action=action, before_state=before, after_state=after,
        actor="system", reason=reason,
    ))
    return audit_id


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _extract_keywords(title: str) -> list[str]:
    """Split title into candidate keywords (2+ chars, non-numeric)."""
    import re
    tokens = re.split(r"[，,、\s]+", title)
    return [t.strip() for t in tokens if len(t.strip()) >= 2 and not t.strip().isdigit()][:3]
