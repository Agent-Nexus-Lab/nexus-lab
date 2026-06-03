"""Freshness gating — detect stale data and ensure future events are available.

This module addresses the core problem: if all cached events are in the past,
the runtime will always return "no matching events". Freshness checks combine
a TTL window with a future-event liveness test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from agent_core._runtime_compat import parse_datetime


DEFAULT_FRESHNESS_TTL = timedelta(hours=24)
FUTURE_EVENT_BUFFER = timedelta(days=7)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def has_future_events(
    events: list[dict[str, Any]],
    now: datetime | None = None,
    buffer: timedelta | None = None,
) -> bool:
    """Return True if at least one event starts within [now, now + buffer].

    This is the liveness check: if no events fall in the upcoming window,
    the data is effectively stale regardless of TTL.
    """
    if now is None:
        from agent_core.time_provider import resolve_now
        now = resolve_now()
    if buffer is None:
        buffer = FUTURE_EVENT_BUFFER

    horizon = now + buffer
    for event in events:
        start = parse_datetime(event.get("start_time"))
        if start is not None and now <= start <= horizon:
            return True
    return False


def needs_refresh(
    events: list[dict[str, Any]],
    *,
    last_fetched_at: datetime | None,
    freshness_ttl: timedelta | None = None,
    now: datetime | None = None,
) -> bool:
    """Return True if data needs re-fetch: either TTL-expired or no future events.

    This is the single decision point for whether a DataSource should re-scrape.
    It combines the TTL check (is the data too old?) with the liveness check
    (are there any useful events remaining?).
    """
    if now is None:
        from agent_core.time_provider import resolve_now
        now = resolve_now()
    if freshness_ttl is None:
        freshness_ttl = DEFAULT_FRESHNESS_TTL

    # Never fetched — definitely needs refresh
    if last_fetched_at is None:
        return True

    # Exceeded TTL
    if (now - last_fetched_at) > freshness_ttl:
        return True

    # No useful events remaining (all past or too far future)
    if not has_future_events(events, now=now):
        return True

    return False


def event_freshness_score(
    start_time: datetime | None,
    now: datetime,
    *,
    upcoming_ideal_days: float = 7.0,
) -> float:
    """Score how close an event is to now.

    Returns 1.0 for events happening right now, decreasing linearly to 0.0
    for events more than upcoming_ideal_days in the future.

    Mirrors score_freshness() from runtime.py (line 573).
    """
    if start_time is None:
        return 0.0
    days_until = max(0.0, (start_time - now).total_seconds() / 86400.0)
    return max(0.0, 1.0 - min(days_until, upcoming_ideal_days) / upcoming_ideal_days)
