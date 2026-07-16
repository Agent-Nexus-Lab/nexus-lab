"""Validated Event upsert and batch import services."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from .models import Event

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = timezone.utc
MUTABLE_FIELDS = (
    "summary",
    "end_time",
    "location",
    "campus",
    "organizer",
    "source_name",
    "evidence_text",
    "tags",
    "quality_score",
    "text_source",
    "text_quality",
    "category",
    "summary_embedding",
    "enriched_query_embedding",
    "embedding_model",
)


class EventValidationError(ValueError):
    """Raised when an event draft cannot be stored safely."""


def upsert_event(
    event_dict: dict[str, Any],
    *,
    db: Session,
    source_id: str | None = None,
    reference_now: datetime | None = None,
) -> dict[str, Any]:
    """Insert or update one event using the formal deduplication contract."""
    normalized = _normalize_event(event_dict, reference_now=reference_now)
    existing = _find_existing(db, normalized)
    now = _ensure_aware(reference_now or datetime.now(DEFAULT_TIMEZONE))

    if existing is not None:
        updated_fields: list[str] = []
        for field in MUTABLE_FIELDS:
            if field not in normalized:
                continue
            new_value = normalized[field]
            if not _values_equal(getattr(existing, field), new_value):
                setattr(existing, field, new_value)
                updated_fields.append(field)

        if source_id is not None and existing.source_id != source_id:
            existing.source_id = source_id
            updated_fields.append("source_id")

        status, visible = _derive_publication_state(
            title=existing.title,
            start_time=existing.start_time,
            end_time=existing.end_time,
            location=existing.location,
            source_url=existing.source_url,
            requested_status=normalized["verification_status"],
            reference_now=now,
        )
        if existing.verification_status != status:
            existing.verification_status = status
            updated_fields.append("verification_status")
        if existing.is_user_visible != visible:
            existing.is_user_visible = visible
            updated_fields.append("is_user_visible")

        if not updated_fields:
            return {"action": "skipped", "event_id": existing.id, "reason": "no changes"}

        existing.updated_at = now
        db.flush()
        return {
            "action": "updated",
            "event_id": existing.id,
            "reason": f"updated {updated_fields}",
        }

    event_id = str(uuid.uuid4())
    event = Event(
        id=event_id,
        title=normalized["title"],
        summary=normalized.get("summary"),
        start_time=normalized.get("start_time"),
        end_time=normalized.get("end_time"),
        location=normalized.get("location"),
        campus=normalized.get("campus"),
        organizer=normalized.get("organizer"),
        source_id=source_id,
        source_url=normalized.get("source_url"),
        source_name=normalized.get("source_name"),
        evidence_text=normalized.get("evidence_text"),
        tags=normalized.get("tags", []),
        quality_score=normalized.get("quality_score", 0.5),
        verification_status=normalized["verification_status"],
        is_user_visible=normalized["is_user_visible"],
        text_source=normalized.get("text_source"),
        text_quality=normalized.get("text_quality"),
        category=normalized.get("category"),
        summary_embedding=normalized.get("summary_embedding"),
        enriched_query_embedding=normalized.get("enriched_query_embedding"),
        embedding_model=normalized.get("embedding_model"),
    )
    db.add(event)
    db.flush()
    return {"action": "inserted", "event_id": event_id, "reason": "new event"}


def import_many(
    drafts: list[dict[str, Any]],
    *,
    db: Session,
    source_id: str | None = None,
    reference_now: datetime | None = None,
) -> dict[str, Any]:
    """Import drafts independently so one bad row does not poison the batch."""
    result: dict[str, Any] = {
        "imported": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
        "event_ids": [],
    }

    for index, draft in enumerate(drafts):
        try:
            with db.begin_nested():
                item = upsert_event(
                    draft,
                    db=db,
                    source_id=source_id,
                    reference_now=reference_now,
                )
            action = item["action"]
            if action == "inserted":
                result["imported"] += 1
            elif action == "updated":
                result["updated"] += 1
            elif action == "skipped":
                result["skipped"] += 1
            else:
                raise RuntimeError(f"unknown action: {action}")
            if action in {"inserted", "updated"}:
                result["event_ids"].append(item["event_id"])
        except Exception as exc:
            result["failed"] += 1
            title = draft.get("title") if isinstance(draft, dict) else None
            result["errors"].append(f"[{index}] {title or '?'}: {exc}")
            logger.warning("import_many failed on draft %d: %s", index, exc)

    return result


def import_many_standalone(
    drafts: list[dict[str, Any]],
    *,
    source_id: str | None = None,
    reference_now: datetime | None = None,
) -> dict[str, Any]:
    """Create a session, import the batch, and commit or roll back atomically."""
    from database.database import SessionLocal

    db = SessionLocal()
    try:
        result = import_many(
            drafts,
            db=db,
            source_id=source_id,
            reference_now=reference_now,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _normalize_event(
    event_dict: dict[str, Any],
    *,
    reference_now: datetime | None,
) -> dict[str, Any]:
    if not isinstance(event_dict, dict):
        raise EventValidationError("event draft must be an object")

    title = str(event_dict.get("title") or "").strip()
    if not title:
        raise EventValidationError("title is required")

    source_url = _normalize_source_url(event_dict.get("source_url"))
    start_time = _parse_datetime(event_dict.get("start_time"), field="start_time")
    end_time = _parse_datetime(event_dict.get("end_time"), field="end_time")
    if start_time is not None and end_time is not None and end_time < start_time:
        raise EventValidationError("end_time cannot be earlier than start_time")

    normalized = dict(event_dict)
    normalized["title"] = title
    normalized["source_url"] = source_url
    normalized["start_time"] = start_time
    normalized["end_time"] = end_time
    normalized["location"] = _optional_text(event_dict.get("location"))
    normalized["tags"] = _normalize_tags(event_dict.get("tags"))

    status, visible = _derive_publication_state(
        title=title,
        start_time=start_time,
        end_time=end_time,
        location=normalized["location"],
        source_url=source_url,
        requested_status=event_dict.get("verification_status"),
        reference_now=_ensure_aware(reference_now or datetime.now(DEFAULT_TIMEZONE)),
    )
    normalized["verification_status"] = status
    normalized["is_user_visible"] = visible
    return normalized


def _find_existing(db: Session, event: dict[str, Any]) -> Event | None:
    query = db.query(Event).filter(Event.title == event["title"])
    source_url = event.get("source_url")
    start_time = event.get("start_time")
    if source_url:
        return query.filter(
            Event.source_url == source_url,
            Event.start_time == start_time,
        ).first()
    return query.filter(
        Event.source_url.is_(None),
        Event.start_time == start_time,
        Event.location == event.get("location"),
    ).first()


def _derive_publication_state(
    *,
    title: str,
    start_time: datetime | None,
    end_time: datetime | None,
    location: str | None,
    source_url: str | None,
    requested_status: Any,
    reference_now: datetime,
) -> tuple[str, bool]:
    requested = str(requested_status or "").strip().lower()
    if requested == "rejected":
        return "rejected", False

    complete = bool(title and start_time and location and source_url)
    if start_time is None:
        status = "pending"
    elif requested in {"verified", "unverified", "pending"}:
        status = requested
    else:
        status = "unverified"

    effective_end = end_time or start_time
    not_expired = effective_end is not None and _ensure_aware(effective_end) >= reference_now
    visible = complete and not_expired and status != "rejected"
    return status, visible


def _normalize_source_url(value: Any) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise EventValidationError("source_url must be a valid http/https URL")
    return text


def _parse_datetime(value: Any, *, field: str) -> datetime | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise EventValidationError(f"{field} must be a datetime string")

    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise EventValidationError(f"{field} is invalid: {value}")


def _normalize_tags(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        return decoded if isinstance(decoded, list) else [decoded]
    return [value]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=DEFAULT_TIMEZONE)
    return value.astimezone(DEFAULT_TIMEZONE)


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, datetime) and isinstance(right, datetime):
        return _ensure_aware(left) == _ensure_aware(right)
    return left == right
