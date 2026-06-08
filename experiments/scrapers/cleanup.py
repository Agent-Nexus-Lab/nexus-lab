"""Stale event cleanup — remove expired events and orphaned source text files.

Events with start_time older than (now - ttl_days) are removed from
events.json. Source text files that are no longer referenced by any
remaining event are also deleted.

Usage:
    python scrapers/cleanup.py --dry-run          # preview only
    python scrapers/cleanup.py --ttl-days 3       # remove events >3 days past
    python scrapers/cleanup.py --events-path custom.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_core._runtime_compat import DEFAULT_TIMEZONE, parse_datetime

_EXPERIMENTS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS_PATH = _EXPERIMENTS_ROOT / "agent_maas_cli" / "outputs" / "events.json"
DEFAULT_TEXTS_DIR = _EXPERIMENTS_ROOT / "agent_maas_cli" / "texts"
DEFAULT_TTL_DAYS = 3


def cleanup_stale_events(
    events_path: Path | None = None,
    texts_dir: Path | None = None,
    now: datetime | None = None,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove stale events and orphaned text files.

    Args:
        events_path: Path to events.json
        texts_dir: Directory containing source text files
        now: Reference time (defaults to real clock)
        ttl_days: Events older than (now - ttl_days) are removed
        dry_run: If True, don't actually delete anything

    Returns:
        Stats dict with keys: total, removed, kept, texts_removed, texts_kept,
        reference_time
    """
    events_path = events_path or DEFAULT_EVENTS_PATH
    texts_dir = texts_dir or DEFAULT_TEXTS_DIR
    if now is None:
        now = datetime.now(DEFAULT_TIMEZONE)

    cutoff = now - timedelta(days=ttl_days)

    # Load events
    if not events_path.exists():
        return {
            "total": 0, "removed": 0, "kept": 0,
            "texts_removed": 0, "texts_kept": 0,
            "reference_time": now.isoformat(),
        }

    data = json.loads(events_path.read_text(encoding="utf-8"))
    all_events = data.get("events", [])

    # Determine which events to keep
    kept_events: list[dict] = []
    removed_count = 0
    for ev in all_events:
        start = parse_datetime(ev.get("start_time"))
        if start and start < cutoff:
            removed_count += 1
        else:
            kept_events.append(ev)

    # Determine which text files are still referenced
    kept_files: set[str] = {ev.get("source_file", "") for ev in kept_events}
    kept_files.discard("")

    # Check text files
    texts_removed = 0
    texts_kept = 0
    if texts_dir.exists():
        for txt_file in texts_dir.glob("*.txt"):
            if txt_file.name in kept_files:
                texts_kept += 1
            else:
                texts_removed += 1
                if not dry_run:
                    txt_file.unlink()

    # Write back if changed
    if removed_count > 0 and not dry_run:
        data["events"] = kept_events
        # Write atomically
        tmp = events_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(events_path)

    return {
        "total": len(all_events),
        "removed": removed_count,
        "kept": len(kept_events),
        "texts_removed": texts_removed,
        "texts_kept": texts_kept,
        "reference_time": now.isoformat(),
        "cutoff": cutoff.isoformat(),
    }


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Remove stale events (past cutoff) from events.json"
    )
    parser.add_argument(
        "--events-path",
        default=str(DEFAULT_EVENTS_PATH),
        help=f"Path to events.json (default: {DEFAULT_EVENTS_PATH})",
    )
    parser.add_argument(
        "--texts-dir",
        default=str(DEFAULT_TEXTS_DIR),
        help=f"Directory of source text files (default: {DEFAULT_TEXTS_DIR})",
    )
    parser.add_argument(
        "--ttl-days",
        type=int,
        default=DEFAULT_TTL_DAYS,
        help=f"Remove events older than now - N days (default: {DEFAULT_TTL_DAYS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only, do not delete anything",
    )
    args = parser.parse_args(argv)

    stats = cleanup_stale_events(
        events_path=Path(args.events_path),
        texts_dir=Path(args.texts_dir),
        ttl_days=args.ttl_days,
        dry_run=args.dry_run,
    )

    action = "Would remove" if args.dry_run else "Removed"
    print(f"Reference time: {stats['reference_time']}", file=sys.stderr)
    print(f"Cutoff:         {stats.get('cutoff', 'N/A')}", file=sys.stderr)
    print(f"Total events:   {stats['total']}", file=sys.stderr)
    print(f"{action}:        {stats['removed']} events", file=sys.stderr)
    print(f"Kept:           {stats['kept']} events", file=sys.stderr)
    print(f"Texts removed:  {stats['texts_removed']} files", file=sys.stderr)
    print(f"Texts kept:     {stats['texts_kept']} files", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
