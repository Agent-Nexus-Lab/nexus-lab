"""Seed data filter — keep only future events before importing into events.json.

Usage:
    python -m agent_core.seed_filter [--input events.json] [--output events_filtered.json]

Or programmatic:
    from agent_core.seed_filter import filter_future_events
    filtered, stats = filter_future_events(events, now=now)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_core._runtime_compat import parse_datetime
from agent_core.time_provider import resolve_now

DEFAULT_TIMEZONE = timezone(timedelta(hours=8))

# Default paths relative to experiments/
DEFAULT_EVENTS_PATH = _EXPERIMENTS_ROOT / "agent_maas_cli" / "outputs" / "events.json"


def filter_future_events(
    events: list[dict[str, Any]],
    now: datetime | None = None,
    *,
    keep_no_start_time: bool = False,
    future_buffer: timedelta | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Filter a list of events to only those with future start times.

    Args:
        events: List of event dicts in AGGREGATED_EVENT_FIELDS format.
        now: Reference datetime. Falls back to AGENT_FIXED_NOW or real time.
        keep_no_start_time: If True, keep events with null start_time (e.g. TBD events).
        future_buffer: If set, also allow events within this buffer before now
                       (e.g. timedelta(hours=1) to keep events that just started).

    Returns:
        (filtered_events, stats) where stats = {total, kept, rejected_past, rejected_no_time}
    """
    if now is None:
        now = resolve_now()

    filtered: list[dict[str, Any]] = []
    stats = {
        "total": len(events),
        "kept": 0,
        "rejected_past": 0,
        "rejected_no_time": 0,
        "reference_time": now.isoformat(),
    }

    cutoff = now
    if future_buffer:
        cutoff = now - future_buffer

    for event in events:
        start_time = parse_datetime(event.get("start_time"))

        if start_time is None:
            if keep_no_start_time:
                filtered.append(event)
                stats["kept"] += 1
            else:
                stats["rejected_no_time"] += 1
            continue

        if start_time >= cutoff:
            filtered.append(event)
            stats["kept"] += 1
        else:
            stats["rejected_past"] += 1

    return filtered, stats


def load_events(path: Path | None = None) -> list[dict[str, Any]]:
    """Load events from a JSON file (events.json format)."""
    p = Path(path) if path else DEFAULT_EVENTS_PATH
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("events file must be a JSON object with an events array")
    return payload["events"]


def save_events(events: list[dict[str, Any]], path: Path | None = None) -> None:
    """Save events to a JSON file (events.json format)."""
    p = Path(path) if path else DEFAULT_EVENTS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"events": events}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def print_stats(stats: dict[str, Any]) -> None:
    """Print human-readable filter statistics."""
    print(f"Total events:        {stats['total']}")
    print(f"Kept (future):       {stats['kept']}")
    print(f"Rejected (past):     {stats['rejected_past']}")
    print(f"Rejected (no time):  {stats['rejected_no_time']}")
    print(f"Reference time:      {stats['reference_time']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Filter events.json to keep only future events."
    )
    parser.add_argument(
        "--input", type=Path, default=None,
        help=f"Input events.json path (default: {DEFAULT_EVENTS_PATH})",
    )
    parser.add_argument("--output", type=Path, default=None, help="Output path (default: overwrite input)")
    parser.add_argument(
        "--keep-no-start-time", action="store_true",
        help="Keep events with null start_time (e.g. TBD events)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print stats only, do not write output",
    )
    args = parser.parse_args(argv)

    input_path = args.input or DEFAULT_EVENTS_PATH
    output_path = args.output or input_path

    events = load_events(input_path)
    filtered, stats = filter_future_events(
        events,
        keep_no_start_time=args.keep_no_start_time,
    )

    print_stats(stats)
    print()

    if args.dry_run:
        print("[dry-run] No changes written.")
    else:
        save_events(filtered, output_path)
        print(f"Written {stats['kept']} events to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
