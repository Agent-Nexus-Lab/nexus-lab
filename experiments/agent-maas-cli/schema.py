from __future__ import annotations

from typing import Any


TOP_LEVEL_FIELDS = ["source_name", "source_url", "events", "warnings"]
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
        if _has_event_signal(event):
            events.append(event)

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
        else:
            _assert_null_or_string(event[field], f"events[{index}].{field}")

    if not event["title"]:
        raise ValueError(f"events[{index}].title must be non-empty")
    if not (event["start_time"] or event["location"] or event["evidence_text"]):
        raise ValueError(f"events[{index}] must include start_time, location, or evidence_text")


def _has_event_signal(event: dict[str, Any]) -> bool:
    return bool(event.get("title") and (event.get("start_time") or event.get("location") or event.get("evidence_text")))


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
