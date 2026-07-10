"""Collection V2 — extract_article_to_events: 从文章正文抽取活动 event drafts.

Usage:
    from experiments.agent_maas_cli.extract_article import extract_article_to_events

    result = extract_article_to_events(
        article_text="...",
        metadata={"title": "...", "source_url": "...", "source_name": "...", "publish_time": "..."},
    )
    print(result["status"])   # ok / no_activity / parse_error / ...
    print(result["events"])   # list of {title, summary, start_time, end_time, location, source_url}
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROMPT_PATH = _SCRIPT_DIR / "prompt_collection_v2.md"

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.modelarts-maas.com/openai/v1"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_TIMEOUT_SECONDS = 60
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1.5


def extract_article_to_events(
    article_text: str,
    metadata: dict[str, Any],
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Extract event drafts from a single article using MaaS LLM.

    Args:
        article_text: 清洗后的文章正文。
        metadata: 文章元信息，至少包含 title / source_url / source_name / publish_time。
        base_url: MaaS API 地址，默认读 MAAS_BASE_URL 环境变量。
        model: 模型名，默认 deepseek-v4-pro。
        api_key: API Key，默认读 MAAS_API_KEY 环境变量。
        timeout: 超时秒数，默认 60。
        reference_date: 参考日期（用于相对日期推算），默认今天。

    Returns:
        {
            "status": "ok" | "no_activity" | "not_an_event" | "text_too_short" | "parse_error",
            "events": [{"title", "summary", "start_time", "end_time", "location", "source_url"}, ...],
            "warnings": [...],
            "error": None | "错误描述",
            "used_fallback": false | true,
        }
    """
    try:
        import requests
    except ImportError:
        return _empty_result("parse_error", ["requests 库未安装"], "pip install requests required")

    if not article_text.strip():
        return _empty_result("text_too_short", ["正文为空"], "article_text is empty")

    if len(article_text.strip()) < 100:
        return _empty_result("text_too_short", ["正文太短 (<100 字)，无法判断"], "article_text too short")

    # Load prompt
    try:
        system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _empty_result("parse_error", ["prompt 文件丢失"], "prompt file not found: prompt_collection_v2.md")

    # Resolve credentials
    resolved_api_key = api_key or os.getenv("MAAS_API_KEY")
    if not resolved_api_key:
        return _empty_result(
            "parse_error",
            ["MAAS_API_KEY 未配置，无法调用 LLM"],
            "MAAS_API_KEY is not set. Set it in .env or pass api_key parameter.",
        )

    resolved_model = model or os.getenv("MAAS_MODEL") or DEFAULT_MODEL
    resolved_base_url = (base_url or os.getenv("MAAS_BASE_URL") or DEFAULT_OPENAI_BASE_URL).rstrip("/")
    url = f"{resolved_base_url}/chat/completions"
    timeout_value = timeout or float(os.getenv("MAAS_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))

    # Graceful fallback: works as package import or direct script execution
    try:
        from .schema import collection_tool_schema
    except ImportError:
        import sys as _sys
        _schema_dir = str(Path(__file__).resolve().parent)
        if _schema_dir not in _sys.path:
            _sys.path.insert(0, _schema_dir)
        from schema import collection_tool_schema

    user_payload = {
        "title": metadata.get("title"),
        "source_url": metadata.get("source_url"),
        "source_name": metadata.get("source_name"),
        "publish_time": metadata.get("publish_time"),
        "reference_date": reference_date or _default_reference_date(),
        "timezone": "Asia/Shanghai",
        "source_text": article_text,
    }

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "tools": [collection_tool_schema()],
        "tool_choice": {"type": "function", "function": {"name": "emit_collection_result"}},
    }

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {resolved_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout_value,
                verify=True,
            )
            if not response.ok:
                detail = response.text[:500].replace(resolved_api_key, "[REDACTED]")
                last_error = f"HTTP {response.status_code}: {detail}"
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
                continue

            raw = response.json()
            parsed = _extract_collection_payload(raw)
            return _normalize_collection_result(parsed)

        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = str(exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
            continue
        except (ValueError, json.JSONDecodeError, KeyError) as exc:
            last_error = str(exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
            continue

    return _empty_result("parse_error", [f"MaaS 调用失败: {last_error}"], last_error)


def _extract_collection_payload(raw_response: dict[str, Any]) -> dict[str, Any]:
    """Extract JSON payload from MaaS response (tool_calls or content)."""
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("MaaS response missing choices")

    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        function = tool_calls[0].get("function", {})
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            return json.loads(arguments)
        if isinstance(arguments, dict):
            return arguments

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`").strip()
            if stripped.lower().startswith("json"):
                stripped = stripped[4:].strip()
        return json.loads(stripped)

    raise ValueError("MaaS response did not contain tool arguments or JSON content")


def _normalize_collection_result(parsed: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate the collection extraction result."""
    status = parsed.get("status", "ok")
    if not isinstance(status, str):
        status = "ok"

    raw_events = parsed.get("events")
    events: list[dict[str, Any]] = []
    if isinstance(raw_events, list):
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            event = {
                "title": _or_null(item.get("title")),
                "summary": _or_null(item.get("summary")),
                "start_time": _or_null(item.get("start_time")),
                "end_time": _or_null(item.get("end_time")),
                "location": _or_null(item.get("location")),
                "source_url": _or_null(item.get("source_url")),
            }
            if event["title"]:
                events.append(event)

    warnings = parsed.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = [str(warnings)]

    if not events and status == "ok":
        status = "no_activity"
        warnings.append("no valid events extracted")

    return {
        "status": status,
        "events": events,
        "warnings": warnings,
        "error": None,
        "used_fallback": False,
    }


def _empty_result(status: str, warnings: list[str], error: str | None) -> dict[str, Any]:
    return {
        "status": status,
        "events": [],
        "warnings": warnings,
        "error": error,
        "used_fallback": True,
    }


def _or_null(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() in {"null", "none", "nil", "n/a", "na", "unknown", "未知", "不详", "无"}:
            return None
        return stripped or None
    return str(value)


def _default_reference_date() -> str:
    """Return today's date in YYYY-MM-DD format."""
    from datetime import date
    return date.today().isoformat()
