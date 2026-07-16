from __future__ import annotations

import logging
import sys
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _collect_job() -> None:
    """Hourly job: fetch articles → extract events → upsert into DB."""
    from database.collection_service import create_collection_run, execute_collection_run
    from database.database import SessionLocal

    db = SessionLocal()
    try:
        run = create_collection_run(db=db, trigger_method="cron")
        batch_id = run.batch_id
    finally:
        db.close()
    logger.info("[cron] starting collection batch %s", batch_id)
    execute_collection_run(batch_id, limit=10)


_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    """Start the background scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()

    _scheduler.add_job(
        _collect_job,
        "cron",
        minute="43",
        jitter=30,
        id="auto_collect_hourly",
    )
    _scheduler.start()
    logger.info("[cron] scheduler started, hourly at minute=43 ±30s")


def shutdown_scheduler() -> None:
    """Shut down the background scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[cron] scheduler shut down")
