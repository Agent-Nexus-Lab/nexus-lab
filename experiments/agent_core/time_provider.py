"""Central time provider with FIXED_NOW support and dev/prod mode gating.

Dual-mode time resolution:
- dev/test:   AGENT_FIXED_NOW env var pins time for reproducible tests
- production: ENVIRONMENT=production forces real clock (ignores AGENT_FIXED_NOW)

Usage:
    from agent_core.time_provider import resolve_now, get_now
    now = resolve_now()           # explicit > env > real
    now = resolve_now(explicit)   # explicit always wins
    now = get_now(mode="prod")    # force real clock
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

DEFAULT_TIMEZONE = timezone(timedelta(hours=8))


def get_now(*, mode: str | None = None) -> datetime:
    """Return current time.

    Args:
        mode:
            'dev' or 'test' — allow AGENT_FIXED_NOW (for reproducible testing)
            'prod' or 'production' — force real clock, ignore AGENT_FIXED_NOW
            None — check ENVIRONMENT env var; 'production'/'prod' → force real,
                   otherwise allow AGENT_FIXED_NOW
    """
    if mode is None:
        env = os.getenv("ENVIRONMENT", "").strip().lower()
        mode = "prod" if env in ("production", "prod") else "dev"

    if mode in ("dev", "test"):
        fixed = os.getenv("AGENT_FIXED_NOW", "").strip()
        if fixed:
            return datetime.fromisoformat(fixed)

    return datetime.now(DEFAULT_TIMEZONE)


def resolve_now(now: datetime | None = None, *, mode: str | None = None) -> datetime:
    """Resolve the effective 'now'.

    Priority: explicit argument > AGENT_FIXED_NOW env var > real clock.

    Args:
        now: Explicit datetime. If provided, always used.
        mode: Passed through to get_now() when `now` is None.
    """
    if now is not None:
        return now
    return get_now(mode=mode)
