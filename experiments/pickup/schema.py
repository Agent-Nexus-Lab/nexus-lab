from __future__ import annotations

import uuid
from typing import Any


TOP_LEVEL_FIELDS = ["source_name", "source_url", "events", "warnings"]
EVENTS_FILE_FIELDS = ["events"]
CAMPUS_VALUES = ["邯郸", "江湾", "枫林", "张江", "其他"]
DEFAULT_CAMPUS = "邯郸"
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


def maas_tool_schema() -> dict[str, Any]:
    """Return the function schema used to force structured MaaS output."""
    event_properties = {
        "title": {"type": ["string", "null"]},
        "summary": {"type": ["string", "null"]},
        "start_time": {"type": ["string", "null"]},
        "end_time": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "campus": {"type": ["string", "null"]},
        "organizer": {"type": ["string", "null"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "evidence_text": {"type": ["string", "null"]},
    }

    return {
        "type": "function",
        "function": {
            "name": "emit_event_extraction_result",
            "description": "Emit structured campus activity extraction results from source text facts only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_name": {"type": ["string", "null"]},
                    "source_url": {"type": ["string", "null"]},
                    "events": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": event_properties,
                            "required": EVENT_FIELDS,
                            "additionalProperties": False,
                        },
                    },
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
                "required": TOP_LEVEL_FIELDS,
                "additionalProperties": False,
            },
        },
    }


def normalize_response(payload: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("response must be a JSON object")

    fallback = fallback or {}
    normalized = {
        "source_name": _null_or_string(payload.get("source_name")) or _null_or_string(fallback.get("source_name")),
        "source_url": _null_or_string(payload.get("source_url")) or _null_or_string(fallback.get("source_url")),
        "events": _normalize_events(payload.get("events")),
        "warnings": _normalize_string_list(payload.get("warnings")),
    }

    validate_response(normalized)
    return normalized


def validate_response(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("response must be a JSON object")

    missing = [field for field in TOP_LEVEL_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"response missing fields: {', '.join(missing)}")

    _assert_null_or_string(payload["source_name"], "source_name")
    _assert_null_or_string(payload["source_url"], "source_url")

    if not isinstance(payload["events"], list):
        raise ValueError("events must be an array")
    for index, event in enumerate(payload["events"], start=1):
        _validate_event(event, index)

    if not isinstance(payload["warnings"], list) or any(not isinstance(item, str) for item in payload["warnings"]):
        raise ValueError("warnings must be a string array")


def build_aggregated_event(
    event: dict[str, Any],
    *,
    event_id: str,
    source_file: str,
    source_name: str | None,
    source_url: str | None,
) -> dict[str, Any]:
    aggregated = {
        "event_id": event_id,
        "source_file": source_file,
        "source_name": _null_or_string(source_name),
        "source_url": _null_or_string(source_url),
    }
    for field in EVENT_FIELDS:
        aggregated[field] = event.get(field)
    _validate_aggregated_event(aggregated, 1)
    return aggregated


def validate_events_file(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("events file must be a JSON object")

    missing = [field for field in EVENTS_FILE_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"events file missing fields: {', '.join(missing)}")
    extra = [field for field in payload if field not in EVENTS_FILE_FIELDS]
    if extra:
        raise ValueError(f"events file has unexpected fields: {', '.join(extra)}")

    if not isinstance(payload["events"], list):
        raise ValueError("events must be an array")
    for index, event in enumerate(payload["events"], start=1):
        _validate_aggregated_event(event, index)


def build_error_response(message: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = fallback or {}
    return normalize_response(
        {
            "source_name": fallback.get("source_name"),
            "source_url": fallback.get("source_url"),
            "events": [],
            "warnings": [message],
        },
        fallback,
    )


def _normalize_events(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    events: list[dict[str, Any]] = []
    for raw_event in value:
        if not isinstance(raw_event, dict):
            continue

        event = {
            "title": _null_or_string(raw_event.get("title")),
            "summary": _null_or_string(raw_event.get("summary")),
            "start_time": _null_or_string(raw_event.get("start_time")),
            "end_time": _null_or_string(raw_event.get("end_time")),
            "location": _null_or_string(raw_event.get("location")),
            "campus": _null_or_string(raw_event.get("campus")),
            "organizer": _null_or_string(raw_event.get("organizer")),
            "tags": _normalize_string_list(raw_event.get("tags")),
            "evidence_text": _null_or_string(raw_event.get("evidence_text")),
        }
        event["start_time"] = _remove_unsubstantiated_full_day_time(event["start_time"], event["evidence_text"])
        event["end_time"] = _remove_unsubstantiated_full_day_time(event["end_time"], event["evidence_text"])
        if _has_event_signal(event):
            events.extend(_expand_event_by_campus(event))

    return events


def _validate_event(event: Any, index: int) -> None:
    if not isinstance(event, dict):
        raise ValueError(f"events[{index}] must be an object")

    missing = [field for field in EVENT_FIELDS if field not in event]
    if missing:
        raise ValueError(f"events[{index}] missing fields: {', '.join(missing)}")

    for field in EVENT_FIELDS:
        if field == "tags":
            if not isinstance(event[field], list) or any(not isinstance(tag, str) for tag in event[field]):
                raise ValueError(f"events[{index}].tags must be a string array")
        elif field == "campus":
            _assert_nonempty_string(event[field], f"events[{index}].campus")
            if event[field] not in CAMPUS_VALUES:
                raise ValueError(f"events[{index}].campus must be one of: {', '.join(CAMPUS_VALUES)}")
        else:
            _assert_null_or_string(event[field], f"events[{index}].{field}")
            if field in {"start_time", "end_time"} and _is_date_only_string(event[field]):
                raise ValueError(f"events[{index}].{field} must include time and timezone or be null")

    if not event["title"]:
        raise ValueError(f"events[{index}].title must be non-empty")
    if not (event["start_time"] or event["location"] or event["evidence_text"]):
        raise ValueError(f"events[{index}] must include start_time, location, or evidence_text")


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
    _assert_null_or_string(event["source_name"], f"events[{index}].source_name")
    _assert_null_or_string(event["source_url"], f"events[{index}].source_url")
    _validate_event({field: event[field] for field in EVENT_FIELDS}, index)


def _has_event_signal(event: dict[str, Any]) -> bool:
    return bool(event.get("title") and (event.get("start_time") or event.get("location") or event.get("evidence_text")))


def _expand_event_by_campus(event: dict[str, Any]) -> list[dict[str, Any]]:
    campuses = _extract_event_campuses(event) or [DEFAULT_CAMPUS]
    expanded: list[dict[str, Any]] = []
    for campus in campuses:
        campus_event = dict(event)
        campus_event["campus"] = campus
        expanded.append(campus_event)
    return expanded


def _extract_event_campuses(event: dict[str, Any]) -> list[str]:
    field_campuses = _extract_campuses(event.get("campus"), allow_short=True)
    text_campuses = _unique_preserving_order(
        [
            *_extract_campuses(event.get("location"), allow_short=False),
            *_extract_campuses(event.get("evidence_text"), allow_short=False),
        ]
    )
    if text_campuses:
        return text_campuses
    return _unique_preserving_order(field_campuses)


def _extract_campuses(value: Any, *, allow_short: bool) -> list[str]:
    text = _null_or_string(value)
    if text is None:
        return []

    campuses: list[str] = []
    for campus in CAMPUS_VALUES:
        if campus == "其他":
            if "其他" in text or "校外" in text:
                campuses.append(campus)
            continue
        if f"{campus}校区" in text or (allow_short and campus in text):
            campuses.append(campus)
    return campuses


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        string = _null_or_string(item)
        if string is not None:
            normalized.append(string)
    return normalized


def _null_or_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.replace("\ufffd", "").strip()
        if _is_null_like_string(stripped):
            return None
        return stripped or None
    return str(value)


def _is_null_like_string(value: str) -> bool:
    return value.strip().lower() in {"null", "none", "nil", "n/a", "na", "unknown", "未知", "不详", "无"}


def _assert_null_or_string(value: Any, name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null")


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


def _remove_unsubstantiated_full_day_time(value: str | None, evidence_text: str | None) -> str | None:
    if value is None:
        return None
    if _is_date_only_string(value):
        return None
    evidence = evidence_text or ""
    if "T00:00:00" in value and "00:00" not in evidence:
        return None
    if "T23:59:59" in value and "23:59" not in evidence:
        return None
    return value


def _is_date_only_string(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return len(value) == 10 and value[4] == "-" and value[7] == "-" and value.replace("-", "").isdigit()
