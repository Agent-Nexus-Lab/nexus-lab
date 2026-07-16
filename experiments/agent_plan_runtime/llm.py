from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()
PROMPT_VERSION = "v1"
DEFAULT_OPENAI_BASE_URL = "https://api.modelarts-maas.com/openai/v1"
DEFAULT_MODEL = "deepseek-v4-flash"
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1.5

# Phase 2: prompt version for fallback tracking
PROMPT_VERSION = "2026-07-04-v1"

_REWRITE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "emit_rewrite_result",
        "description": "输出改写后的日程摘要和每个活动的推荐理由",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "整体日程的自然语言摘要，概括安排了几个活动、主题方向和校区分布",
                },
                "reasons": {
                    "type": "array",
                    "description": "每个活动的推荐理由列表，顺序与输入 items 保持一致",
                    "items": {
                        "type": "object",
                        "properties": {
                            "event_id": {
                                "type": "string",
                                "description": "活动唯一标识，必须与输入 item 的 event_id 完全一致",
                            },
                            "reason_text": {
                                "type": "string",
                                "description": "该活动的推荐理由，50-150字，结合用户偏好和活动特点",
                            },
                        },
                        "required": ["event_id", "reason_text"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": 4,
                },
            },
            "required": ["summary", "reasons"],
            "additionalProperties": False,
        },
    },
}

_REWRITE_SYSTEM_PROMPT = """你是复旦大学校园日程助手，负责将已由规则选出的活动日程改写成更自然的自然语言表达。

## 核心约束
1. 只能改写 summary 和 reason_text，禁止新增、删除、替换活动
2. 禁止编造时间、地点、链接、主办方
3. event_id 必须与输入完全一致，不得修改
4. reasons 数组顺序必须与输入 items 顺序一致
5. reason_text 每条 50-150 字，结合用户偏好标签和活动特点撰写

## 输出格式
必须通过 emit_rewrite_result 函数返回结果，不要输出额外文字。
summary 格式示例："为你安排了3个活动，主要匹配天文、图书馆偏好，地点集中在江湾校区。"
reason_text 格式示例："复旦天文协会主办的观星活动，完美匹配你对天文的兴趣，地点在江湾校区也很方便。"

完整 JSON 输出示例：
{
  "summary": "为你安排了3个活动，主要匹配天文、图书馆偏好，地点集中在江湾校区。",
  "reasons": [
    {"event_id": "evt-001", "reason_text": "复旦天文协会主办的观星活动，完美匹配你对天文的兴趣，地点在江湾校区也很方便。"},
    {"event_id": "evt-002", "reason_text": "图书馆主办的阅读分享会，契合你对图书馆和轻松氛围的偏好。"}
  ]
}"""


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
        raise RuntimeError("MAAS_API_KEY is required for LLM rewrite")

    resolved_model = model or os.getenv("MAAS_MODEL") or DEFAULT_MODEL
    resolved_base_url = (base_url or os.getenv("MAAS_BASE_URL") or DEFAULT_OPENAI_BASE_URL).rstrip("/")
    url = f"{resolved_base_url}/chat/completions"
    payload = _build_request_payload(result, model=resolved_model)
    timeout_value = timeout or float(os.getenv("MAAS_TIMEOUT", "60"))

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout_value,
            )
            if not response.ok:
                detail = response.text[:1000].replace(api_key, "[REDACTED]")
                last_error = RuntimeError(f"MaaS HTTP {response.status_code}: {detail}")
                logger.warning("LLM rewrite attempt %d failed: %s", attempt + 1, last_error)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
                continue

            raw = response.json()
            parsed = _extract_rewrite_payload(raw)
            _validate_rewrite_payload(parsed)
            return parsed

        except (ValueError, json.JSONDecodeError, KeyError) as exc:
            last_error = exc
            logger.warning("LLM rewrite attempt %d parse error: %s", attempt + 1, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
            continue

    raise RuntimeError(f"LLM rewrite failed after {MAX_RETRIES + 1} attempts: {last_error}")


def _build_request_payload(result: dict[str, Any], *, model: str) -> dict[str, Any]:
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
    user_payload = {
        "title": data.get("title") if isinstance(data, dict) else None,
        "summary": data.get("summary") if isinstance(data, dict) else None,
        "items": safe_items,
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": float(os.getenv("MAAS_TEMPERATURE", "0.2")),
        "tools": [_REWRITE_TOOL_SCHEMA],
        "tool_choice": {"type": "function", "function": {"name": "emit_rewrite_result"}},
    }
    thinking = os.getenv("MAAS_THINKING", "default")
    if thinking != "default":
        payload["thinking"] = {"type": thinking}
    max_tokens = os.getenv("MAAS_MAX_TOKENS")
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    return payload


def _extract_rewrite_payload(raw_response: dict[str, Any]) -> dict[str, Any]:
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("MaaS response missing choices")
    message = choices[0].get("message", {})

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        func = tool_calls[0].get("function", {})
        arguments = func.get("arguments")
        if isinstance(arguments, str):
            return json.loads(arguments)
        if isinstance(arguments, dict):
            return arguments

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        payload = _parse_json_content(content)
        if isinstance(payload, dict):
            return payload

    raise ValueError("MaaS response did not contain valid JSON content")


def _parse_json_content(content: str) -> dict[str, Any]:
    stripped = content.strip()

    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()

    json_match = re.search(r'\{[\s\S]*"(?:summary|reasons)"[\s\S]*\}', stripped)
    if json_match:
        payload = json.loads(json_match.group(0))
        if isinstance(payload, dict):
            return payload

    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("rewrite payload must be a JSON object")
    return payload


def _validate_rewrite_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
        raise ValueError("rewrite payload missing non-empty summary")
    reasons = payload.get("reasons")
    if not isinstance(reasons, list):
        raise ValueError("rewrite payload missing reasons array")
    for i, reason in enumerate(reasons):
        if not isinstance(reason, dict):
            raise ValueError(f"reasons[{i}] is not an object")
        if not isinstance(reason.get("event_id"), str) or not reason["event_id"].strip():
            raise ValueError(f"reasons[{i}] missing event_id")
        if not isinstance(reason.get("reason_text"), str) or not reason["reason_text"].strip():
            raise ValueError(f"reasons[{i}] missing reason_text")
