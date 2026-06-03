"""Schema helpers extracted from agent-maas-cli/schema.py.

These functions are needed by agent_core/datasource.py for building and
validating aggregated events.  Extracting them here makes agent_core
self-contained without depending on agent-maas-cli at import time.
"""

from __future__ import annotations

import uuid
from typing import Any

CAMPUS_VALUES = ["邯郸", "江湾", "枫林", "张江", "其他"]

EVENT_FIELDS = [
    "title",
    "summary",
    "start_time",
    "end_time",
    "location",
    "campus",
    "organizer",
    "tags",
    "evidence_text",
]

AGGREGATED_EVENT_FIELDS = [
    "event_id",
    "source_file",
    "source_name",
    "source_url",
    *EVENT_FIELDS,
]


def build_aggregated_event(
    event: dict[str, Any],
    *,
    event_id: str,
    source_file: str,
    source_name: str | None,
    source_url: str | None,
) -> dict[str, Any]:
    """Wrap a raw extraction event with identity metadata."""
    aggregated: dict[str, Any] = {
        "event_id": event_id,
        "source_file": source_file,
        "source_name": source_name,
        "source_url": source_url,
    }
    for field in EVENT_FIELDS:
        aggregated[field] = event.get(field)
    return aggregated


def validate_events_file(payload: dict[str, Any]) -> None:
    """Ensure payload is a valid events.json structure."""
    if not isinstance(payload, dict):
        raise ValueError("events file must be a JSON object")

    if "events" not in payload:
        raise ValueError("events file missing 'events' field")
    extra = [field for field in payload if field != "events"]
    if extra:
        raise ValueError(f"events file has unexpected fields: {', '.join(extra)}")

    if not isinstance(payload["events"], list):
        raise ValueError("events must be an array")
    for index, event in enumerate(payload["events"], start=1):
        _validate_aggregated_event(event, index)


def _validate_aggregated_event(event: Any, index: int) -> None:
    if not isinstance(event, dict):
        raise ValueError(f"events[{index}] must be an object")

    missing = [field for field in AGGREGATED_EVENT_FIELDS if field not in event]
    if missing:
        raise ValueError(f"events[{index}] missing fields: {', '.join(missing)}")
    extra = [field for field in event if field not in AGGREGATED_EVENT_FIELDS]
    if extra:
        raise ValueError(f"events[{index}] has unexpected fields: {', '.join(extra)}")

    _assert_uuid4(event["event_id"], f"events[{index}].event_id")
    _assert_nonempty_string(event["source_file"], f"events[{index}].source_file")


def _assert_nonempty_string(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _assert_uuid4(value: Any, name: str) -> None:
    _assert_nonempty_string(value, name)
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a UUID") from exc
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ValueError(f"{name} must be a UUIDv4 string")
