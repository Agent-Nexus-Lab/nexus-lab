from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _collect_job() -> None:
    """Hourly job: fetch articles → extract events → upsert into DB."""
    from experiments.scrapers.auto_collector import run as collect_run

    started = datetime.now()
    logger.info("[cron] auto_collector started at %s (limit=10)", started.isoformat())
    try:
        result = collect_run(dry_run=False, commit=True, limit=10)
        summary = result.get("commit_summary", {})
        elapsed = (datetime.now() - started).total_seconds()
        logger.info(
            "[cron] done in %.1fs: fetched=%d extracted=%d imported=%d updated=%d skipped=%d failed=%d",
            elapsed,
            summary.get("fetched_count", 0),
            summary.get("extracted_count", 0),
            summary.get("imported_count", 0),
            summary.get("updated_count", 0),
            summary.get("skipped_count", 0),
            summary.get("failed_count", 0),
        )
        warnings = result.get("warnings", [])
        if warnings:
            for w in warnings[:5]:  # log first 5 warnings only
                logger.warning("[cron] %s", w)
    except Exception:
        logger.exception("[cron] auto_collector failed after %.1fs",
                         (datetime.now() - started).total_seconds())


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
    logger.info("[cron] scheduler started, hourly at minute=7 ±30s")


def shutdown_scheduler() -> None:
    """Shut down the background scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[cron] scheduler shut down")
