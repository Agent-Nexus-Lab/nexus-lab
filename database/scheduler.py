from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULE_HOURS = 8
DEFAULT_ACCOUNTS_PER_RUN = 20


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _schedule_hours() -> int:
    value = _positive_int_env("COLLECTION_SCHEDULE_HOURS", DEFAULT_SCHEDULE_HOURS)
    if value not in {8, 12}:
        logger.warning(
            "[cron] COLLECTION_SCHEDULE_HOURS=%s unsupported; fallback to %sh",
            value,
            DEFAULT_SCHEDULE_HOURS,
        )
        return DEFAULT_SCHEDULE_HOURS
    return value

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _collect_job() -> None:
    """Periodic job: fetch new articles → extract events → upsert into DB."""
    from database.collection_service import create_collection_run, execute_collection_run
    from database.database import SessionLocal

    db = SessionLocal()
    try:
        run = create_collection_run(db=db, trigger_method="cron")
        batch_id = run.batch_id
    finally:
        db.close()
    logger.info("[cron] starting collection batch %s", batch_id)
    limit = _positive_int_env("COLLECTION_ACCOUNTS_PER_RUN", DEFAULT_ACCOUNTS_PER_RUN)
    execute_collection_run(batch_id, limit=limit)


_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    """Start the background scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    hours = _schedule_hours()
    hour_expression = "0,8,16" if hours == 8 else "0,12"

    _scheduler.add_job(
        _collect_job,
        "cron",
        hour=hour_expression,
        minute="43",
        jitter=30,
        id="auto_collect_periodic",
    )
    _scheduler.start()
    logger.info(
        "[cron] scheduler started, every %sh at minute=43 ±30s, accounts_per_run=%s",
        hours,
        _positive_int_env("COLLECTION_ACCOUNTS_PER_RUN", DEFAULT_ACCOUNTS_PER_RUN),
    )


def shutdown_scheduler() -> None:
    """Shut down the background scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[cron] scheduler shut down")
