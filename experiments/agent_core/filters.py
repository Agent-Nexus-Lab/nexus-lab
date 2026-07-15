"""Hard-constraint filter functions extracted from runtime.py filter_candidates().

Each filter returns (passed: bool, rejection_reason: str | None).
These are composable, independently testable, and produce the same
results as the original inline logic in runtime.py lines 265-310.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from agent_core._runtime_compat import (
    event_text,
    has_online_signal,
    normalize_campus,
    normalize_string_list,
    parse_datetime,
    text_matches_any,
)
from agent_core.query import HardConstraints

FilterResult = tuple[bool, Optional[str]]  # (passed, rejection_reason)


# ---------------------------------------------------------------------------
# Individual filter functions
# ---------------------------------------------------------------------------


def filter_start_time(
    event: dict[str, Any],
    *,
    constraint: HardConstraints,
    now: datetime,
) -> FilterResult:
    """Reject events with missing, past, or out-of-window start_time.

    Corresponds to runtime.py lines 282-289 (missing_start_time, past_event,
    outside_date_scope).
    """
    start_time = parse_datetime(event.get("start_time"))

    # Missing start_time
    if start_time is None:
        if constraint.require_start_time:
            return False, "missing_start_time"
        # If start_time is not required, pass (scoring will handle nulls)
        return True, None

    # Past event
    if constraint.exclude_past and start_time < now:
        return False, "past_event"

    # Before allowed window
    if constraint.start_time_after is not None and start_time < constraint.start_time_after:
        return False, "outside_date_scope"

    # After allowed window
    if constraint.start_time_before is not None and start_time > constraint.start_time_before:
        return False, "outside_date_scope"

    return True, None


def filter_campus(
    event: dict[str, Any],
    *,
    constraint: HardConstraints,
    now: datetime | None = None,
) -> FilterResult:
    """Reject events whose campus is not in the allowed set.

    Corresponds to runtime.py lines 298-300 (campus_mismatch).
    When campuses is empty, all campuses pass.
    """
    if not constraint.campuses:
        return True, None

    event_campus = normalize_campus(event.get("campus"))
    if event_campus not in constraint.campuses:
        return False, "campus_mismatch"

    return True, None


def filter_location(
    event: dict[str, Any],
    *,
    constraint: HardConstraints,
    now: datetime | None = None,
) -> FilterResult:
    """Reject events without location when require_location is True.

    Corresponds to runtime.py lines 291-293 (missing_location).
    Events with online signals (线上/直播/腾讯会议/Zoom) pass even without location.
    """
    if not constraint.require_location:
        return True, None

    if not event.get("location") and not has_online_signal(event):
        return False, "missing_location"

    return True, None


def filter_source_evidence(
    event: dict[str, Any],
    *,
    constraint: HardConstraints,
    now: datetime | None = None,
) -> FilterResult:
    """Reject events without source_url or evidence_text when required.

    Corresponds to runtime.py lines 294-296 (missing_source_evidence).
    """
    if not constraint.require_source_evidence:
        return True, None

    if not event.get("source_url") and not event.get("evidence_text"):
        return False, "missing_source_evidence"

    return True, None


def filter_excluded_tags(
    event: dict[str, Any],
    *,
    constraint: HardConstraints,
    now: datetime | None = None,
) -> FilterResult:
    """Reject events whose text contains any excluded tag.

    Corresponds to runtime.py lines 302-304 (excluded_preference).
    """
    if not constraint.exclude_tags:
        return True, None

    if text_matches_any(event_text(event), list(constraint.exclude_tags)):
        return False, "excluded_preference"

    return True, None


# ---------------------------------------------------------------------------
# Composite filter
# ---------------------------------------------------------------------------

# Filters are applied in this order (matching runtime.py filter_candidates).
_FILTER_CHAIN = [
    filter_start_time,
    filter_campus,
    filter_location,
    filter_source_evidence,
    filter_excluded_tags,
]


def apply_hard_constraints(
    events: list[dict[str, Any]],
    *,
    constraint: HardConstraints,
    now: datetime,
    rejections: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Apply all hard-constraint filters to a list of events.

    Returns the list of surviving events (with normalized campus).
    If rejections is provided, rejected events are recorded there for debug.

    This replaces the inline filter_candidates() logic in runtime.py.
    """
    if rejections is None:
        rejections = []

    filtered: list[dict[str, Any]] = []
    for event in events:
        passed = True
        for filter_fn in _FILTER_CHAIN:
            ok, reason = filter_fn(event, constraint=constraint, now=now)
            if not ok:
                _record_rejection(rejections, event, reason)
                passed = False
                break
        if passed:
            normalized = dict(event)
            normalized["event_id"] = str(event.get("event_id") or "")
            normalized["campus"] = normalize_campus(event.get("campus")) or event.get("campus")
            filtered.append(normalized)

    return filtered


def _record_rejection(
    rejections: list[dict[str, str]],
    event: dict[str, Any],
    reason: str | None,
) -> None:
    rejections.append({
        "event_id": str(event.get("event_id") or ""),
        "title": str(event.get("title") or ""),
        "reason": reason or "unknown",
    })
