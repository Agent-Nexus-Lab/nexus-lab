"""Memory aggregation and update services.

read_memory — aggregate feedback + history into structured Memory dict.
update_memory_from_feedback — create/update memory_items from user feedback.
reflect_and_store_memory_summary — LLM-powered memory reflection from recent runs.
suppress_memory_summary — user-requested suppression.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from experiments.agent_plan_runtime.memory_reflection import reflect_on_memory

from sqlalchemy.orm import Session

from database.models import (
    MemoryAuditLog,
    MemoryItem,
    Plan,
    PlanItem,
    PlanRun,
    UserEventFeedback,
    UserProfile,
    Event,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = timezone(timedelta(hours=8))
MEMORY_EXPIRY_DAYS = 30
MAX_MEMORY_ITEMS = 20

# Ensure memory_reflection module is importable
_MR_DIR = Path(__file__).resolve().parents[1] / "experiments" / "agent_plan_runtime"
if str(_MR_DIR) not in sys.path:
    sys.path.insert(0, str(_MR_DIR))


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
    memory_summary: str | None = None

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

        if m.memory_type == "memory_summary":
            memory_summary = m.content
            continue

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
        "memory_summary": memory_summary,
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
    content = f"用户{'不喜欢' if 'disliked' in memory_type else '喜欢'}标签「{tag}」"

    db.add(MemoryItem(
        id=mem_id, user_id=user_id, memory_type=memory_type,
        memory_scope="short_term", content=content, structured_content=sc,
        source_type="feedback", source_ref=source_ref,
        confidence=conf, priority=50, status="active", expires_at=expires_at,
    ))
    db.flush()
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
        content=f"用户{'不喜欢' if 'disliked' in memory_type else '喜欢'}活动 {event_id}",
        structured_content=sc, source_type="feedback", source_ref=source_ref,
        confidence=conf, priority=50, status="active", expires_at=expires_at,
    ))
    db.flush()
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
    db.flush()
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
    db.flush()
    return audit_id


# ===========================================================================
# Memory Summary — reflect, store, and suppress
# ===========================================================================


def should_reflect_memory_summary(user_id: str, *, db: Session) -> bool:
    """Return true when three new evidence-eligible runs are available."""
    runs = _eligible_unreflected_runs(user_id, db=db)
    if len(runs) < 3:
        return False
    return not is_memory_suppressed([run.id for run in runs[:3]], user_id=user_id, db=db)


def is_memory_suppressed(
    source_refs: list[str],
    *,
    user_id: str,
    db: Session,
) -> bool:
    """Prevent a deleted evidence batch from recreating the same summary."""
    target = set(source_refs)
    if not target:
        return False
    suppressed = (
        db.query(MemoryItem)
        .filter_by(user_id=user_id, memory_type="memory_summary", status="suppressed")
        .all()
    )
    for item in suppressed:
        structured = item.structured_content or {}
        if not isinstance(structured, dict):
            continue
        evidence_ids = set(structured.get("evidence_run_ids") or [])
        if evidence_ids == target:
            return True
    return False


def reflect_and_store_memory_summary(
    user_id: str,
    *,
    db: Session,
    force: bool = False,
) -> dict[str, Any]:
    """Gather last 3 runs with feedback → reflect_on_memory → store as memory_item.

    Called after every 3 plan-day runs (or force=True for testing).
    Returns the reflection result + stored memory_id.
    """
    now = datetime.now(DEFAULT_TIMEZONE)

    recent_runs = _eligible_unreflected_runs(user_id, db=db)[:3]

    if len(recent_runs) < 3 and not force:
        return {
            "reflected": False,
            "reason": f"only {len(recent_runs)} runs, need 3",
            "memory_id": None,
        }

    rounds: list[dict[str, Any]] = []
    evidence_run_ids = [run.id for run in recent_runs]
    if is_memory_suppressed(evidence_run_ids, user_id=user_id, db=db):
        return {
            "reflected": False,
            "reason": "source_refs_suppressed",
            "memory_id": None,
        }

    source_refs: list[str] = []

    for run in recent_runs:
        plan = db.query(Plan).filter_by(run_id=run.id).first()
        event_titles: list[str] = []
        recommended_event_ids: list[str] = []
        if plan:
            items = db.query(PlanItem).filter_by(plan_id=plan.id).all()
            for pi in items:
                if pi.event_id:
                    recommended_event_ids.append(pi.event_id)
                event = db.query(Event).filter_by(id=pi.event_id).first() if pi.event_id else None
                if event:
                    event_titles.append(event.title)

        # Gather feedback for this run
        feedbacks = (
            db.query(UserEventFeedback)
            .filter_by(run_id=run.id)
            .all()
        )
        liked: list[str] = []
        disliked: list[str] = []
        liked_event_ids: list[str] = []
        disliked_event_ids: list[str] = []
        for fb in feedbacks:
            event = db.query(Event).filter_by(id=fb.event_id).first() if fb.event_id else None
            title = event.title if event else fb.event_id
            if fb.feedback_type == "like":
                liked.append(title)
                if fb.event_id:
                    liked_event_ids.append(fb.event_id)
            elif fb.feedback_type == "dislike":
                disliked.append(title)
                if fb.event_id:
                    disliked_event_ids.append(fb.event_id)
            source_refs.append(fb.id)

        rounds.append({
            "round": len(rounds) + 1,
            "run_id": run.id,
            "request_text": run.request_text or "",
            "recommended_event_titles": event_titles,
            "recommended_event_ids": recommended_event_ids,
            "liked_event_ids": liked_event_ids,
            "disliked_event_ids": disliked_event_ids,
            "feedback": {"liked": liked, "disliked": disliked},
        })
        source_refs.append(run.id)
        source_refs.extend(recommended_event_ids)
        source_refs.extend(liked_event_ids)
        source_refs.extend(disliked_event_ids)
    source_refs = _dedup(source_refs)

    # Check existing memory_summary
    existing = (
        db.query(MemoryItem)
        .filter_by(user_id=user_id, memory_type="memory_summary", status="active")
        .order_by(MemoryItem.updated_at.desc())
        .first()
    )
    existing_memory = None
    if existing and existing.structured_content:
        sc = existing.structured_content
        if isinstance(sc, dict):
            existing_memory = {
                "memory_summary": existing.content,
                "source_refs": sc.get("source_refs", []),
            }

    context = {
        "session_id": str(uuid.uuid4()),
        "rounds": rounds,
        "existing_memory": existing_memory,
        "existing_memory_summary": existing.content if existing else None,
        "source_refs": source_refs,
    }

    try:
        result = reflect_on_memory(context)
    except Exception as exc:
        logger.warning("reflect_on_memory failed: %s", exc)
        return {
            "reflected": False,
            "reason": f"reflect_on_memory error: {exc}",
            "memory_id": None,
        }

    memory_summary_text = result.get("memory_summary", "")
    if not memory_summary_text:
        return {
            "reflected": False,
            "reason": "empty memory_summary returned",
            "memory_id": None,
        }

    expires_after_turns = result.get("expires_after_turns", 6)
    ref_source_refs = source_refs

    if existing is not None:
        old_structured = dict(existing.structured_content or {})
        old_structured["cleanup_reason"] = "replaced_by_new_summary"
        existing.structured_content = old_structured
        existing.status = "expired"
        existing.updated_at = now

    # Store as memory_item
    mem_id = str(uuid.uuid4())
    expires_at = now + timedelta(days=MEMORY_EXPIRY_DAYS)
    structured_content = {
        "source_refs": ref_source_refs,
        "evidence_run_ids": evidence_run_ids,
        "expires_after_turns": expires_after_turns,
        "cleanup_reason": result.get("cleanup_reason"),
        "prompt_version": result.get("prompt_version", ""),
        "used_fallback": result.get("used_fallback", False),
        "last_refreshed_at": now.isoformat(),
    }

    memory_item = MemoryItem(
        id=mem_id,
        user_id=user_id,
        memory_type="memory_summary",
        memory_scope="long_term",
        content=memory_summary_text,
        structured_content=structured_content,
        source_type="reflection",
        source_ref=",".join(ref_source_refs),
        confidence=0.5,
        priority=70,
        status="active",
        expires_at=expires_at,
    )
    db.add(memory_item)
    db.flush()

    # Audit log
    _write_audit(
        db, user_id, mem_id, "create", None,
        {"memory_type": "memory_summary", "content": memory_summary_text,
         "structured_content": structured_content},
        f"reflection:{len(rounds)}_rounds",
    )

    db.commit()

    return {
        "reflected": True,
        "memory_id": mem_id,
        "memory_summary": memory_summary_text,
        "source_refs": ref_source_refs,
        "used_fallback": result.get("used_fallback", False),
    }


def _eligible_unreflected_runs(user_id: str, *, db: Session) -> list[PlanRun]:
    used_ids: set[str] = set()
    summaries = (
        db.query(MemoryItem)
        .filter_by(user_id=user_id, memory_type="memory_summary")
        .all()
    )
    for item in summaries:
        structured = item.structured_content or {}
        if isinstance(structured, dict):
            used_ids.update(structured.get("evidence_run_ids") or [])

    runs = (
        db.query(PlanRun)
        .filter_by(user_id=user_id, status="completed", evidence_eligible=True)
        .order_by(PlanRun.started_at.asc())
        .all()
    )
    return [run for run in runs if run.id not in used_ids]


def suppress_memory_summary(
    memory_id: str,
    *,
    db: Session,
) -> dict[str, Any]:
    """Suppress a memory_summary (user requested deletion).

    Sets status to "suppressed" — the item won't be read by read_memory
    but won't trigger re-generation (unlike "deleted").
    """
    now = datetime.now(DEFAULT_TIMEZONE)

    mem = db.query(MemoryItem).filter_by(id=memory_id).first()
    if not mem:
        return {"suppressed": False, "reason": "memory not found"}

    before = {"status": mem.status, "memory_type": mem.memory_type}

    mem.status = "suppressed"
    mem.updated_at = now
    mem.deleted_at = now

    sc = dict(mem.structured_content or {})
    sc["cleanup_reason"] = "user_requested"
    mem.structured_content = sc

    _write_audit(
        db, mem.user_id, mem.id, "suppress", before,
        {"status": "suppressed", "cleanup_reason": "user_requested"},
        "user_deleted",
    )

    db.commit()

    return {
        "suppressed": True,
        "memory_id": mem.id,
        "previous_status": before["status"],
    }


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
