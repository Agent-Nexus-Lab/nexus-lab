from __future__ import annotations

import json
import os
from typing import Any


DEFAULT_OPENAI_BASE_URL = "https://api.modelarts-maas.com/openai/v1"
DEFAULT_MODEL = "deepseek-v4-pro"


def rewrite_with_maas(
    result: dict[str, Any],
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    import requests

    api_key = os.getenv("MAAS_API_KEY")
    if not api_key:
        raise RuntimeError("MAAS_API_KEY is required for --llm-mode maas")

    payload = build_request_payload(result, model=model or os.getenv("MAAS_MODEL") or DEFAULT_MODEL)
    url = f"{(base_url or os.getenv('MAAS_BASE_URL') or DEFAULT_OPENAI_BASE_URL).rstrip('/')}/chat/completions"
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if not response.ok:
        detail = response.text[:1000].replace(api_key, "[REDACTED]")
        raise RuntimeError(f"MaaS HTTP {response.status_code}: {detail}")
    return extract_rewrite_payload(response.json())


def build_request_payload(result: dict[str, Any], *, model: str) -> dict[str, Any]:
    data = result.get("data", {})
    items = data.get("items") if isinstance(data, dict) else []
    safe_items = [
        {
            "event_id": item.get("event_id"),
            "title": item.get("title"),
            "summary": item.get("summary"),
            "start_time": item.get("start_time"),
            "end_time": item.get("end_time"),
            "location": item.get("location"),
            "campus": item.get("campus"),
            "tags": item.get("tags"),
            "quality_score": item.get("quality_score"),
            "template_reason_text": item.get("reason_text"),
        }
        for item in items
        if isinstance(item, dict)
    ]
    system_prompt = (
        "你只负责把已经由规则选出的校园活动日程改写得更自然。"
        "禁止新增、删除、替换活动，禁止编造时间、地点、链接、主办方。"
        "必须返回严格 JSON："
        '{"summary":"...","reasons":[{"event_id":"...","reason_text":"..."}]}'
    )
    user_payload = {
        "title": data.get("title") if isinstance(data, dict) else None,
        "summary": data.get("summary") if isinstance(data, dict) else None,
        "items": safe_items,
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": float(os.getenv("MAAS_TEMPERATURE", "0.2")),
    }
    thinking = os.getenv("MAAS_THINKING", "disabled")
    if thinking != "default":
        payload["thinking"] = {"type": thinking}
    max_tokens = os.getenv("MAAS_MAX_TOKENS")
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    return payload


def extract_rewrite_payload(raw_response: dict[str, Any]) -> dict[str, Any]:
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
        return parse_json_content(content)
    raise ValueError("MaaS response did not contain JSON content")


def parse_json_content(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("rewrite payload must be a JSON object")
    return payload
