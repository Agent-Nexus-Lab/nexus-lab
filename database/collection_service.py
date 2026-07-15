"""Collection run persistence and shared manual/cron execution."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.collection_lock import get_collection_lock
from database.database import SessionLocal
from database.models import CollectionRun

logger = logging.getLogger(__name__)


def create_collection_run(
    *,
    db: Session,
    trigger_method: str,
    sources: list[str] | None = None,
) -> CollectionRun:
    if trigger_method not in {"manual", "cron"}:
        raise ValueError("trigger_method must be manual or cron")
    run = CollectionRun(
        batch_id=str(uuid.uuid4()),
        trigger_method=trigger_method,
        status="running",
        sources=sources or [],
        triggered_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_collection_run(
    batch_id: str,
    *,
    db: Session,
    status: str = "completed",
    sources: list[str] | None = None,
    counts: dict[str, int] | None = None,
    failure_reason: str | None = None,
    duration_ms: int | None = None,
) -> CollectionRun:
    run = _require_run(db, batch_id)
    values = counts or {}
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    if sources is not None:
        run.sources = sources
    for field in (
        "fetched_count",
        "extracted_count",
        "imported_count",
        "updated_count",
        "skipped_count",
        "failed_count",
    ):
        setattr(run, field, int(values.get(field, 0) or 0))
    run.failure_reason = failure_reason
    run.duration_ms = duration_ms
    db.commit()
    db.refresh(run)
    return run


def fail_collection_run(
    batch_id: str,
    *,
    db: Session,
    failure_reason: str,
    duration_ms: int | None = None,
) -> CollectionRun:
    return finish_collection_run(
        batch_id,
        db=db,
        status="failed",
        failure_reason=failure_reason,
        duration_ms=duration_ms,
    )


def get_collection_runs(
    *,
    db: Session,
    batch_id: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[CollectionRun]:
    query = db.query(CollectionRun)
    if batch_id is not None:
        query = query.filter(CollectionRun.batch_id == batch_id)
    return (
        query.order_by(CollectionRun.triggered_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def execute_collection_run(
    batch_id: str,
    *,
    source_ids: list[str] | None = None,
    limit: int = 10,
) -> None:
    """Execute the one shared collector path and persist its real outcome."""
    started = time.perf_counter()
    db = SessionLocal()
    lock = get_collection_lock()
    token: str | None = None
    try:
        token = lock.acquire()
        if token is None:
            finish_collection_run(
                batch_id,
                db=db,
                status="skipped",
                failure_reason="collection_already_running",
                duration_ms=_elapsed_ms(started),
            )
            return

        from experiments.scrapers.auto_collector import run as collect_run

        result = collect_run(
            dry_run=False,
            commit=True,
            limit=limit,
            source_ids=source_ids,
        )
        summary = result.get("commit_summary") or {}
        errors = summary.get("errors") or []
        finish_collection_run(
            batch_id,
            db=db,
            status="completed",
            sources=result.get("scanned_account_ids") or source_ids or [],
            counts={
                "fetched_count": summary.get("fetched_count", 0),
                "extracted_count": summary.get("extracted_count", 0),
                "imported_count": summary.get("imported_count", 0),
                "updated_count": summary.get("updated_count", 0),
                "skipped_count": summary.get("skipped_count", 0),
                "failed_count": summary.get("failed_count", 0),
            },
            failure_reason="; ".join(str(error) for error in errors[:5]) or None,
            duration_ms=_elapsed_ms(started),
        )
    except Exception as exc:
        db.rollback()
        logger.exception("collection batch %s failed", batch_id)
        try:
            fail_collection_run(
                batch_id,
                db=db,
                failure_reason=str(exc),
                duration_ms=_elapsed_ms(started),
            )
        except Exception:
            logger.exception("failed to persist collection failure for %s", batch_id)
    finally:
        if token is not None:
            lock.release(token)
        db.close()


def collection_run_to_dict(run: CollectionRun) -> dict[str, Any]:
    return {
        "batch_id": run.batch_id,
        "triggered_at": run.triggered_at,
        "finished_at": run.finished_at,
        "trigger_method": run.trigger_method,
        "status": run.status,
        "sources": run.sources or [],
        "fetched_count": run.fetched_count or 0,
        "extracted_count": run.extracted_count or 0,
        "imported_count": run.imported_count or 0,
        "updated_count": run.updated_count or 0,
        "skipped_count": run.skipped_count or 0,
        "failed_count": run.failed_count or 0,
        "failure_reason": run.failure_reason,
        "duration_ms": run.duration_ms,
    }


def _require_run(db: Session, batch_id: str) -> CollectionRun:
    run = db.query(CollectionRun).filter(CollectionRun.batch_id == batch_id).first()
    if run is None:
        raise LookupError(f"collection run not found: {batch_id}")
    return run


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
