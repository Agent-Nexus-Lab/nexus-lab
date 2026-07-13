"""
Answer Composer — 将已排序的活动结果解释为自然语言推荐理由。

由李颖哲负责。只解释已排序结果，不新增、不删除、不重排。

=== 固定输入输出契约（给曹昕宇 plan-day 接线） ===

compose_answer(ranked_items, memory_summary, request_text, ...) 稳定输出：

┌────────────────────┬──────────────────────────────────────────────┐
│ 字段               │ 说明                                         │
├────────────────────┼──────────────────────────────────────────────┤
│ summary            │ 整体日程自然语言摘要                         │
│ recommended_items  │ 推荐活动列表（event_id + explanation，顺序不变）│
│ tradeoffs          │ 推荐之间的取舍说明列表                       │
│ follow_up_question │ 给用户的追问（可空字符串）                   │
│ prompt_version     │ prompt 版本号                                │
│ model              │ 实际使用的模型名                             │
│ used_fallback      │ 是否降级到规则                               │
│ error              │ None | 错误信息                              │
│ duration_ms        │ 调用耗时（毫秒）                             │
│ retry_count        │ 重试次数                                     │
│ memory_note        │ 记忆影响说明（附加，非契约必需）             │
└────────────────────┴──────────────────────────────────────────────┘

核心约束（必须遵守）：
1. 活动数量、event_id 和顺序不变
2. 不增加数据库不存在的活动，不删除算法选中的活动
3. 失败时返回原排序结果，只降低文案丰富度

Usage:
    from experiments.agent_plan_runtime.answer_composer import compose_answer

    result = compose_answer(
        ranked_items=[
            {"event_id": "evt-001", "title": "天文观测夜", "score": 0.92, "reason_text": "匹配天文偏好"},
            {"event_id": "evt-002", "title": "AI讲座",     "score": 0.75, "reason_text": "匹配AI兴趣"},
        ],
        memory_summary="用户偏好天文观测，不喜欢商业路演",
        request_text="今天下午有什么活动",
    )
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from llm_call_log import classify_error, log_llm_call

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
- items: 已排序的活动列表 [{event_id, title, score, reason_text, start_time, location, tags}]
- memory_summary: 用户记忆摘要（可能为空）
- request_text: 用户原始 query

## 输出 JSON 格式
{
  "summary": "整体日程自然语言摘要",
  "recommended_items": [
    {
      "event_id": "evt-001",
      "explanation": "推荐理由，结合用户偏好和活动特点撰写"
    }
  ],
  "tradeoffs": ["活动A与活动B的取舍说明", "..."],
  "follow_up_question": "给用户的追问，例如是否需要调整时间或校区",
  "memory_note": "记忆对本次推荐的影响说明"
}

## summary 要求
- 概括安排了几个活动、主题方向和校区分布
- 如果 memory_summary 影响了推荐，在 summary 中提及

## explanation 要求
- 结合输入的 reason_text 和 score 信息撰写
- 提及活动与用户偏好的匹配关系
- 如果 memory_summary 中用户明确不喜欢某类活动，而当前推荐避开了该类活动，应说明

## tradeoffs 要求
- 列出推荐活动之间的取舍（如时间冲突、校区距离、主题差异）
- 若只有 1 个活动，tradeoffs 可为空数组

## follow_up_question 要求
- 给出一个简短追问，帮助下一轮更精准推荐
- 若无合适追问，返回空字符串

## memory_note 要求
- 如果 memory_summary 为空，memory_note 为空字符串
- 如果 memory_summary 影响了推荐方向，用一句话说明

只输出 JSON，不要额外文字。"""


def compose_answer(
    ranked_items: list[dict[str, Any]],
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
        ranked_items: 已排序的活动列表 [{event_id, title, score, reason_text, ...}]
        memory_summary: 用户记忆摘要
        request_text: 用户原始 query

    Returns:
        固定契约字段：summary / recommended_items / tradeoffs /
        follow_up_question / prompt_version / model / used_fallback /
        error / duration_ms / retry_count (+ memory_note)
    """
    start = time.perf_counter()
    resolved_api_key = api_key or os.getenv("MAAS_API_KEY")
    resolved_model = model or os.getenv("MAAS_MODEL") or DEFAULT_MODEL

    if not ranked_items:
        result = _empty_answer(request_text, memory_summary)
        result["model"] = resolved_model
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        result["retry_count"] = 0
        log_llm_call({
            "module": "answer_composer",
            "prompt_version": PROMPT_VERSION,
            "model": resolved_model,
            "duration_ms": result["duration_ms"],
            "used_fallback": True,
            "error_type": "none",
            "retry_count": 0,
        })
        return result

    error: str | None = None
    error_type = "none"

    if resolved_api_key:
        try:
            result = _call_llm_compose(
                items=ranked_items,
                memory_summary=memory_summary,
                request_text=request_text,
                base_url=base_url,
                model=resolved_model,
                api_key=resolved_api_key,
                timeout=timeout,
            )
            # 校验 LLM 输出未破坏排序；若破坏则降级
            if not validate_composer_preserves_ranking(ranked_items, result):
                logger.warning("Composer LLM output broke ranking, falling back to rule-based.")
                raise RuntimeError("composer_ranking_violation")
            duration_ms = int((time.perf_counter() - start) * 1000)
            result["model"] = resolved_model
            result["duration_ms"] = duration_ms
            result["error"] = None
            log_llm_call({
                "module": "answer_composer",
                "prompt_version": PROMPT_VERSION,
                "model": resolved_model,
                "duration_ms": duration_ms,
                "used_fallback": False,
                "error_type": "none",
                "retry_count": result.get("retry_count", 0),
            })
            return result
        except Exception as exc:
            error = str(exc)
            error_type = classify_error(exc)
            logger.warning("LLM answer compose failed, using rule fallback: %s", exc)

    result = _rule_based_compose(ranked_items, memory_summary, request_text)
    result["model"] = resolved_model
    result["error"] = error
    result["duration_ms"] = int((time.perf_counter() - start) * 1000)
    result["retry_count"] = 0
    log_llm_call({
        "module": "answer_composer",
        "prompt_version": PROMPT_VERSION,
        "model": resolved_model,
        "duration_ms": result["duration_ms"],
        "used_fallback": True,
        "error_type": error_type,
        "retry_count": 0,
    })
    return result


def validate_composer_preserves_ranking(
    input_items: list[dict[str, Any]],
    composer_output: dict[str, Any],
) -> bool:
    """校验 composer 输出是否保持了输入的活动数量、event_id 和顺序。

    - 数量必须一致
    - event_id 集合必须一致（不增不删）
    - 顺序必须一致
    """
    recommended = composer_output.get("recommended_items")
    if not isinstance(recommended, list):
        # 兼容旧字段 items
        recommended = composer_output.get("items")
    if not isinstance(recommended, list):
        return False

    input_ids = [str(item.get("event_id", "")) for item in input_items if isinstance(item, dict)]
    output_ids = [str(item.get("event_id", "")) for item in recommended if isinstance(item, dict)]

    if len(input_ids) != len(output_ids):
        return False
    if set(input_ids) != set(output_ids):
        return False
    return input_ids == output_ids


def _rule_based_compose(
    items: list[dict[str, Any]],
    memory_summary: str | None,
    request_text: str,
) -> dict[str, Any]:
    """Rule-based answer compose (no LLM)."""
    count = len(items)
    titles = [item.get("title", "") for item in items[:3]]
    titles_text = "、".join(titles) if titles else "多种类型"

    summary = f"为你安排了 {count} 个活动，包括 {titles_text}。"
    if memory_summary:
        summary += " 已参考你的偏好的推荐方向。"

    memory_note = ""
    if memory_summary:
        memory_note = "本次推荐已参考你的历史偏好和反馈进行调整"

    recommended_items: list[dict[str, Any]] = []
    for item in items:
        reason = item.get("reason_text", "")
        score = item.get("score", 0)
        title = item.get("title", "")
        explanation = f"{title}（评分 {score:.2f}）。{reason}" if reason else f"{title}，综合匹配度 {score:.2f}"
        recommended_items.append({
            "event_id": item.get("event_id", ""),
            "explanation": explanation.strip(),
        })

    # tradeoffs：基于相邻活动的校区/主题差异
    tradeoffs: list[str] = []
    for prev, curr in zip(items, items[1:]):
        prev_campus = prev.get("campus") or prev.get("location", "")
        curr_campus = curr.get("campus") or curr.get("location", "")
        if prev_campus and curr_campus and prev_campus != curr_campus:
            tradeoffs.append(f"「{prev.get('title', '')}」与「{curr.get('title', '')}」校区不同，需预留通勤时间。")
        else:
            tradeoffs.append(f"「{prev.get('title', '')}」与「{curr.get('title', '')}」时间衔接，注意合理安排。")

    follow_up = "需要我帮你调整时间或校区范围吗？" if count >= 2 else "想看看其他类型的活动吗？"

    return {
        "summary": summary,
        "recommended_items": recommended_items,
        "tradeoffs": tradeoffs,
        "follow_up_question": follow_up,
        "memory_note": memory_note,
        "prompt_version": PROMPT_VERSION,
        "model": DEFAULT_MODEL,
        "used_fallback": True,
        "error": None,
        "duration_ms": 0,
        "retry_count": 0,
    }


def _empty_answer(request_text: str, memory_summary: str | None) -> dict[str, Any]:
    return {
        "summary": f"很遗憾，没有找到符合「{request_text[:20]}」的活动。",
        "recommended_items": [],
        "tradeoffs": [],
        "follow_up_question": "要不要换个时间或关键词再试试？",
        "memory_note": "",
        "prompt_version": PROMPT_VERSION,
        "model": DEFAULT_MODEL,
        "used_fallback": True,
        "error": None,
        "duration_ms": 0,
        "retry_count": 0,
    }


def _call_llm_compose(
    items: list[dict[str, Any]],
    memory_summary: str | None,
    request_text: str,
    *,
    base_url: str | None = None,
    model: str,
    api_key: str,
    timeout: float | None = None,
) -> dict[str, Any]:
    import requests

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
        "model": model,
        "messages": [
            {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    retry_count = 0
    last_exc: Exception | None = None
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
                last_exc = RuntimeError(f"MaaS HTTP {response.status_code}")
                if attempt < MAX_RETRIES:
                    retry_count += 1
                    time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
                continue
            raw = response.json()
            parsed = _extract_json(raw)
            return _normalize_compose(parsed, model=model, retry_count=retry_count)

        except (requests.Timeout, requests.ConnectionError, ValueError, json.JSONDecodeError, KeyError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                retry_count += 1
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
            continue

    raise RuntimeError(f"LLM answer compose failed after all retries: {last_exc}")


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


def _normalize_compose(
    parsed: dict[str, Any],
    *,
    model: str,
    retry_count: int,
) -> dict[str, Any]:
    # 优先取 recommended_items，兼容 items
    raw_items = parsed.get("recommended_items")
    if not isinstance(raw_items, list):
        raw_items = parsed.get("items", [])
    recommended_items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict):
                recommended_items.append({
                    "event_id": str(item.get("event_id", "")),
                    "explanation": str(item.get("explanation", "")),
                })

    raw_tradeoffs = parsed.get("tradeoffs", [])
    tradeoffs = [str(t) for t in raw_tradeoffs if isinstance(t, (str, int, float))] if isinstance(raw_tradeoffs, list) else []

    return {
        "summary": str(parsed.get("summary", "")),
        "recommended_items": recommended_items,
        "tradeoffs": tradeoffs,
        "follow_up_question": str(parsed.get("follow_up_question", "")),
        "memory_note": str(parsed.get("memory_note", "")),
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "used_fallback": False,
        "error": None,
        "duration_ms": 0,
        "retry_count": retry_count,
    }
