"""
Answer Composer — 将已排序的活动结果解释为自然语言推荐理由。

由李颖哲负责。只解释已排序结果，不新增、不删除、不重排。

Usage:
    from experiments.agent_plan_runtime.answer_composer import compose_answer

    result = compose_answer(
        items=[
            {"title": "天文观测夜", "score": 0.92, "reason_text": "匹配天文偏好"},
            {"title": "AI讲座",     "score": 0.75, "reason_text": "匹配AI兴趣"},
        ],
        memory_summary="用户偏好天文观测，不喜欢商业路演",
        request_text="今天下午有什么活动",
    )
    # => {
    #   "summary": "为你找到2个活动，主要匹配天文偏好...",
    #   "items": [{"title": "...", "explanation": "..."}, ...],
    #   "memory_note": "已参考你的偏好调整推荐方向",
    # }
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.modelarts-maas.com/openai/v1"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1.0

PROMPT_VERSION = "2026-07-08-v1"

_ANSWER_SYSTEM_PROMPT = """你是复旦大学校园日程助手的推荐解说员。你的任务是解释已排序的活动结果，让用户理解为什么这些活动被推荐。

## 核心约束（必须遵守）
1. **只能解释已有结果，禁止新增、删除、替换活动**
2. 活动顺序必须与输入 items 完全一致，禁止重新排序
3. event_id 必须与输入完全一致
4. 每条 explanation 50-150 字，结合用户偏好和活动特点

## 输入
- items: 已排序的活动列表 [{title, score, reason_text, start_time, location, tags}]
- memory_summary: 用户记忆摘要（可能为空）
- request_text: 用户原始 query

## 输出 JSON 格式
{
  "summary": "整体日程自然语言摘要",
  "items": [
    {
      "event_id": "evt-001",
      "explanation": "推荐理由，结合用户偏好和活动特点撰写"
    }
  ],
  "memory_note": "记忆对本次推荐的影响说明"
}

## summary 要求
- 概括安排了几个活动、主题方向和校区分布
- 如果 memory_summary 影响了推荐，在 summary 中提及

## explanation 要求
- 结合输入的 reason_text 和 score 信息撰写
- 提及活动与用户偏好的匹配关系
- 如果 memory_summary 中用户明确不喜欢某类活动，而当前推荐避开了该类活动，应说明

## memory_note 要求
- 如果 memory_summary 为空，memory_note 为空字符串
- 如果 memory_summary 影响了推荐方向，用一句话说明

只输出 JSON，不要额外文字。"""


def compose_answer(
    items: list[dict[str, Any]],
    memory_summary: str | None = None,
    request_text: str = "",
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Compose natural language explanation for sorted results.

    Args:
        items: 已排序的活动列表 [{title, score, reason_text, ...}]
        memory_summary: 用户记忆摘要
        request_text: 用户原始 query

    Returns:
        {"summary": str, "items": [{"event_id": str, "explanation": str}], "memory_note": str}
    """
    if not items:
        return _empty_answer(request_text, memory_summary)

    resolved_api_key = api_key or os.getenv("MAAS_API_KEY")

    if resolved_api_key:
        try:
            return _call_llm_compose(
                items=items,
                memory_summary=memory_summary,
                request_text=request_text,
                base_url=base_url,
                model=model,
                api_key=resolved_api_key,
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning("LLM answer compose failed, using rule fallback: %s", exc)

    return _rule_based_compose(items, memory_summary, request_text)


def _rule_based_compose(
    items: list[dict[str, Any]],
    memory_summary: str | None,
    request_text: str,
) -> dict[str, Any]:
    """Rule-based answer compose (no LLM)."""
    count = len(items)
    titles = [item.get("title", "") for item in items[:3]]
    titles_text = "、".join(titles) if titles else "多种类型"

    # Summary
    summary = f"为你安排了 {count} 个活动，包括 {titles_text}。"
    if memory_summary:
        summary += " 已参考你的偏好的推荐方向。"

    # Memory note
    memory_note = ""
    if memory_summary:
        memory_note = "本次推荐已参考你的历史偏好和反馈进行调整"

    # Item explanations
    composed_items: list[dict[str, Any]] = []
    for item in items:
        reason = item.get("reason_text", "")
        score = item.get("score", 0)
        title = item.get("title", "")
        explanation = f"{title}（评分 {score:.2f}）。{reason}" if reason else f"{title}，综合匹配度 {score:.2f}"

        composed_items.append({
            "event_id": item.get("event_id", ""),
            "explanation": explanation.strip(),
        })

    return {
        "summary": summary,
        "items": composed_items,
        "memory_note": memory_note,
        "prompt_version": PROMPT_VERSION,
        "used_fallback": True,
        "error": None,
    }


def _empty_answer(request_text: str, memory_summary: str | None) -> dict[str, Any]:
    return {
        "summary": f"很遗憾，没有找到符合「{request_text[:20]}」的活动。",
        "items": [],
        "memory_note": "",
        "prompt_version": PROMPT_VERSION,
        "used_fallback": True,
        "error": None,
    }


def _call_llm_compose(
    items: list[dict[str, Any]],
    memory_summary: str | None,
    request_text: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str,
    timeout: float | None = None,
) -> dict[str, Any]:
    import requests

    resolved_model = model or os.getenv("MAAS_MODEL") or DEFAULT_MODEL
    resolved_base_url = (base_url or os.getenv("MAAS_BASE_URL") or DEFAULT_OPENAI_BASE_URL).rstrip("/")
    url = f"{resolved_base_url}/chat/completions"
    timeout_value = timeout or float(os.getenv("MAAS_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))

    safe_items = [
        {
            "event_id": item.get("event_id", ""),
            "title": item.get("title", ""),
            "score": item.get("score", 0),
            "reason_text": item.get("reason_text", ""),
            "start_time": item.get("start_time"),
            "location": item.get("location"),
            "tags": item.get("tags"),
        }
        for item in items
        if isinstance(item, dict)
    ]

    user_payload = {
        "items": safe_items,
        "memory_summary": memory_summary or "",
        "request_text": request_text,
    }

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

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
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
                continue
            raw = response.json()
            parsed = _extract_json(raw)
            return _normalize_compose(parsed)

        except (requests.Timeout, requests.ConnectionError, ValueError, json.JSONDecodeError, KeyError) as exc:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
            continue

    raise RuntimeError("LLM answer compose failed after all retries")


def _extract_json(raw_response: dict[str, Any]) -> dict[str, Any]:
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("MaaS response missing choices")
    content = choices[0].get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("MaaS response missing content")
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    return json.loads(stripped)


def _normalize_compose(parsed: dict[str, Any]) -> dict[str, Any]:
    raw_items = parsed.get("items", [])
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict):
                items.append({
                    "event_id": str(item.get("event_id", "")),
                    "explanation": str(item.get("explanation", "")),
                })

    return {
        "summary": str(parsed.get("summary", "")),
        "items": items,
        "memory_note": str(parsed.get("memory_note", "")),
        "prompt_version": PROMPT_VERSION,
        "used_fallback": False,
        "error": None,
    }
