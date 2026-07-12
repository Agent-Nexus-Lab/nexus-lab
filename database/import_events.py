"""EventImportService — upsert events from auto_collector drafts into the DB.

Provides:
  upsert_event(event_dict, db)   — insert or update a single event draft
  import_many(drafts, db)        — batch import, returns {imported, updated, skipped, failed, errors}

Called by auto_collector when --commit is passed, replacing the stopgap events.json path.
Also callable from admin router or cron-triggered collection.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models import Event

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = timezone.utc


def upsert_event(
    event_dict: dict[str, Any],
    *,
    db: Session,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Insert or update a single event.

    Dedup key: (source_url, title). If a matching event exists, update its
    summary / start_time / end_time / location. Otherwise insert a new row.
    """
    title = event_dict.get("title")
    source_url = event_dict.get("source_url")

    if not title:
        return {"action": "skipped", "event_id": "", "reason": "missing title"}

    start_time = _parse_datetime(event_dict.get("start_time"))
    end_time = _parse_datetime(event_dict.get("end_time"))

    existing: Event | None = None

    if source_url and title:
        existing = (
            db.query(Event)
            .filter_by(source_url=source_url, title=title)
            .first()
        )

    if not existing and start_time and title:
        location = event_dict.get("location")
        candidates = db.query(Event).filter_by(title=title).all()
        for e in candidates:
            if e.start_time and e.start_time == start_time:
                if location and e.location != location:
                    continue
                existing = e
                break

    now = datetime.now(DEFAULT_TIMEZONE)

    if existing:
        updated_fields: list[str] = []
        for field in ("summary", "start_time", "end_time", "location", "source_name"):
            new_val = event_dict.get(field)
            if new_val and getattr(existing, field) != new_val:
                setattr(existing, field, new_val)
                updated_fields.append(field)
        if source_id and existing.source_id != source_id:
            existing.source_id = source_id
            updated_fields.append("source_id")

        if updated_fields:
            existing.updated_at = now
            db.flush()
            return {"action": "updated", "event_id": existing.id, "reason": f"updated {updated_fields}"}
        else:
            return {"action": "skipped", "event_id": existing.id, "reason": "no changes"}

    event_id = str(uuid.uuid4())

    tags = event_dict.get("tags") or []
    if isinstance(tags, str):
        import json
        try:
            tags = json.loads(tags)
        except json.JSONDecodeError:
            tags = [tags]

    event = Event(
        id=event_id,
        title=title,
        summary=event_dict.get("summary"),
        start_time=start_time,
        end_time=end_time,
        location=event_dict.get("location"),
        campus=event_dict.get("campus"),
        organizer=event_dict.get("organizer"),
        source_id=source_id,
        source_url=source_url,
        source_name=event_dict.get("source_name"),
        evidence_text=event_dict.get("evidence_text"),
        tags=tags,
        quality_score=event_dict.get("quality_score", 0.5),
        verification_status="unverified",
        is_user_visible=True,
    )
    db.add(event)
    db.flush()

    return {"action": "inserted", "event_id": event_id, "reason": "new event"}


def import_many(
    drafts: list[dict[str, Any]],
    *,
    db: Session,
    source_id: str | None = None,
) -> dict[str, int]:
    """Batch import event drafts via upsert_event.

    The caller must commit after this returns.
    Returns {"imported": int, "updated": int, "skipped": int, "failed": int, "errors": [str]}.
    """
    imported = 0
    updated = 0
    skipped = 0
    failed = 0
    errors: list[str] = []

    for i, draft in enumerate(drafts):
        try:
            result = upsert_event(draft, db=db, source_id=source_id)
            action = result.get("action", "failed")
            if action == "inserted":
                imported += 1
            elif action == "updated":
                updated += 1
            elif action == "skipped":
                skipped += 1
            else:
                failed += 1
                errors.append(f"[{i}] unknown action: {result}")
        except Exception as exc:
            failed += 1
            errors.append(f"[{i}] {draft.get('title', '?')}: {exc}")
            logger.warning("import_many failed on draft %d: %s", i, exc)

    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
    }


def import_many_standalone(
    drafts: list[dict[str, Any]],
    *,
    source_id: str | None = None,
) -> dict[str, int]:
    """Convenience wrapper that creates its own DB session and commits.

    Used by auto_collector which runs outside the FastAPI request cycle.
    """
    from database import SessionLocal

    db = SessionLocal()
    try:
        result = import_many(drafts, db=db, source_id=source_id)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a datetime from various formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
                     "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        logger.warning("Could not parse datetime: %s", value)
    return None
