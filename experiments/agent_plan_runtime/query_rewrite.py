"""
Query Rewrite — 将 memory_summary 注入下一轮 query 的上下文。

由李颖哲负责。接收原始 query + memory_summary + profile，
输出 enriched_query、positive/negative terms 等，供 search_events 使用。

=== 固定输入输出契约（给曹昕宇 plan-day 接线） ===

rewrite_query(query, memory_summary, profile, ...) 稳定输出：

┌──────────────────┬──────────────────────────────────────────────┐
│ 字段             │ 说明                                         │
├──────────────────┼──────────────────────────────────────────────┤
│ original_query   │ 用户原始 query（原样回传）                   │
│ enriched_query   │ 增强后的搜索关键词（空格分隔）               │
│ positive_terms   │ 偏好词列表                                   │
│ negative_terms   │ 排除词列表                                   │
│ time_hint        │ morning/afternoon/evening/weekend             │
│ location_hint    │ 校区偏好                                     │
│ top_k            │ 推荐数量                                     │
│ memory_used      │ bool，是否使用了 status=active 的 memory     │
│ prompt_version   │ prompt 版本号                                │
│ model            │ 实际使用的模型名                              │
│ used_fallback    │ 是否降级到规则                               │
│ error            │ None | 错误信息                              │
│ duration_ms      │ 调用耗时（毫秒）                             │
│ retry_count      │ 重试次数                                     │
│ memory_influence │ 记忆影响说明（附加，非契约必需）             │
└──────────────────┴──────────────────────────────────────────────┘

降级规则：
1. 有 status=active 的 memory_summary 时作为上下文，但用户本轮明确表达始终优先
2. 没有 active summary 时只使用本轮 query 和 profile
3. 模型超时、输出不合法或调用失败时回到原 query，并设置 used_fallback=true

Usage:
    from experiments.agent_plan_runtime.query_rewrite import rewrite_query

    result = rewrite_query(
        query="今天下午有什么活动",
        memory_summary="用户偏好天文观测，不喜欢商业路演",
        profile={"interest_tags": ["天文"], "preferred_campuses": ["邯郸"]},
    )
"""

from __future__ import annotations

import json
import logging
import os
import re
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

_QUERY_REWRITE_SYSTEM_PROMPT = """你是复旦大学校园日程助手的意图增强器。根据用户的原始 query、memory_summary 和 profile，输出增强后的搜索意图。

## 输入
- query: 用户当前 query（本轮表达始终优先）
- memory_summary: 最近 3 轮对话提炼的记忆摘要（可能为空）
- profile: 用户静态画像（interest_tags, preferred_campuses, available_time）

## 输出 JSON 格式
{
  "enriched_query": "增强后的搜索关键词（空格分隔）",
  "positive_terms": ["偏好词1", "偏好词2"],
  "negative_terms": ["排除词1"],
  "time_hint": "afternoon",
  "location_hint": "邯郸",
  "top_k": 4,
  "memory_influence": "memory_summary 对本次搜索的影响说明"
}

## 规则
1. enriched_query: 融合 query、memory_summary 中的偏好、profile 中的兴趣词，输出用于检索的关键词
2. positive_terms: 从 query + memory + profile 提取应加权的正面词汇
3. negative_terms: 从 memory_summary 中提取应排除的词汇（如"不喜欢路演" → "路演"）
4. time_hint: morning/afternoon/evening/weekend，从 query 提取，默认空字符串
5. location_hint: 从 query 或 memory 中提取校区偏好，默认空字符串
6. top_k: 基于 query 中"几个"提示，默认 4
7. memory_influence: 一句话说明 memory_summary 如何影响了此次搜索
8. 只输出 JSON，不要额外文字
"""


def _resolve_active_memory_summary(memory_summary: Any) -> tuple[str | None, bool]:
    """解析 memory_summary，返回 (有效摘要文本, 是否使用了 active memory)。

    支持两种形式：
    - 字符串：非空即视为 active
    - dict：status == "active" 且 memory_summary 非空时视为 active
    """
    if memory_summary is None:
        return None, False
    if isinstance(memory_summary, str):
        text = memory_summary.strip()
        return (text or None), bool(text)
    if isinstance(memory_summary, dict):
        status = str(memory_summary.get("status", "")).lower()
        text = str(memory_summary.get("memory_summary", "")).strip()
        if status == "active" and text:
            return text, True
        return None, False
    return None, False


def rewrite_query(
    query: str,
    memory_summary: Any = None,
    profile: dict[str, Any] | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Rewrite query with memory_summary context.

    Args:
        query: 用户原始 query
        memory_summary: memory_reflection 生成的记忆摘要（字符串或带 status 的 dict）
        profile: 用户画像
        base_url/model/api_key/timeout: MaaS 配置

    Returns:
        固定契约字段：original_query / enriched_query / positive_terms /
        negative_terms / time_hint / location_hint / top_k / memory_used /
        prompt_version / model / used_fallback / error / duration_ms /
        retry_count (+ memory_influence)
    """
    start = time.perf_counter()
    resolved_api_key = api_key or os.getenv("MAAS_API_KEY")
    resolved_model = model or os.getenv("MAAS_MODEL") or DEFAULT_MODEL
    active_summary, memory_used = _resolve_active_memory_summary(memory_summary)

    retry_count = 0
    error: str | None = None
    error_type = "none"

    if resolved_api_key:
        try:
            result = _call_llm_rewrite(
                query=query,
                memory_summary=active_summary,
                memory_used=memory_used,
                profile=profile,
                base_url=base_url,
                model=resolved_model,
                api_key=resolved_api_key,
                timeout=timeout,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            result["original_query"] = query
            result["memory_used"] = memory_used
            result["model"] = resolved_model
            result["duration_ms"] = duration_ms
            result["retry_count"] = result.get("retry_count", 0)
            log_llm_call({
                "module": "query_rewrite",
                "prompt_version": PROMPT_VERSION,
                "model": resolved_model,
                "duration_ms": duration_ms,
                "used_fallback": result["used_fallback"],
                "error_type": "none",
                "retry_count": result["retry_count"],
            })
            return result
        except Exception as exc:
            error = str(exc)
            error_type = classify_error(exc)
            logger.warning("LLM query rewrite failed, using rule fallback: %s", exc)

    result = _rule_based_rewrite(query, active_summary, memory_used, profile)
    result["model"] = resolved_model if resolved_api_key else DEFAULT_MODEL
    result["error"] = error
    result["duration_ms"] = int((time.perf_counter() - start) * 1000)
    result["retry_count"] = 0
    log_llm_call({
        "module": "query_rewrite",
        "prompt_version": PROMPT_VERSION,
        "model": result["model"],
        "duration_ms": result["duration_ms"],
        "used_fallback": True,
        "error_type": error_type,
        "retry_count": 0,
    })
    return result


def _rule_based_rewrite(
    query: str,
    memory_summary: str | None,
    memory_used: bool | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Simple rule-based query rewrite (no LLM)."""
    if memory_used is None:
        memory_used = bool(memory_summary)
    profile = profile or {}
    terms: list[str] = [query]

    interest_tags = profile.get("interest_tags", [])
    if isinstance(interest_tags, list):
        terms.extend(interest_tags)

    positive_terms: list[str] = []
    negative_terms: list[str] = []
    memory_influence = ""

    if memory_summary:
        if "偏好" in memory_summary or "喜欢" in memory_summary or "感兴趣" in memory_summary:
            for kw in ["天文", "AI", "摄影", "展览", "工作坊", "讲座", "观星", "音乐", "体育",
                        "轻松", "互动", "实践", "安静", "社交", "创业", "学术"]:
                if kw in memory_summary:
                    positive_terms.append(kw)
        if "不喜欢" in memory_summary or "不感兴趣" in memory_summary:
            for kw in ["路演", "商业", "讲座", "体育", "比赛"]:
                if kw in memory_summary and "不喜欢" in memory_summary:
                    negative_terms.append(kw)
        memory_influence = "memory_summary 提供了用户偏好和排除信号" if positive_terms or negative_terms else "memory_summary 无明确偏好"

    time_hint = ""
    if any(w in query for w in ["上午", "早上"]):
        time_hint = "morning"
    elif any(w in query for w in ["下午"]):
        time_hint = "afternoon"
    elif any(w in query for w in ["晚上", "今晚"]):
        time_hint = "evening"
    elif any(w in query for w in ["周末"]):
        time_hint = "weekend"

    location_hint = ""
    for campus in ["邯郸", "江湾", "枫林", "张江"]:
        if campus in query:
            location_hint = campus
            break
    if not location_hint and profile.get("preferred_campuses"):
        campuses = profile["preferred_campuses"]
        if isinstance(campuses, list) and campuses:
            location_hint = campuses[0]

    top_k = 4
    match = re.search(r"(\d+)\s*个", query)
    if match:
        top_k = min(max(int(match.group(1)), 1), 10)

    enriched = " ".join(dict.fromkeys(terms))

    return {
        "original_query": query,
        "enriched_query": enriched,
        "positive_terms": positive_terms,
        "negative_terms": negative_terms,
        "time_hint": time_hint,
        "location_hint": location_hint,
        "top_k": top_k,
        "memory_used": memory_used,
        "memory_influence": memory_influence,
        "prompt_version": PROMPT_VERSION,
        "model": DEFAULT_MODEL,
        "used_fallback": True,
        "error": None,
        "duration_ms": 0,
        "retry_count": 0,
    }


def _call_llm_rewrite(
    query: str,
    memory_summary: str | None,
    memory_used: bool,
    profile: dict[str, Any] | None,
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

    user_payload = {
        "query": query,
        "memory_summary": memory_summary or "",
        "profile": profile or {},
    }

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _QUERY_REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0.1,
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
            return _normalize_rewrite(parsed, model=model, memory_used=memory_used, retry_count=retry_count)

        except (requests.Timeout, requests.ConnectionError, ValueError, json.JSONDecodeError, KeyError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                retry_count += 1
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
            continue

    raise RuntimeError(f"LLM query rewrite failed after all retries: {last_exc}")


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


def _normalize_rewrite(
    parsed: dict[str, Any],
    *,
    model: str,
    memory_used: bool,
    retry_count: int,
) -> dict[str, Any]:
    return {
        "enriched_query": str(parsed.get("enriched_query", "")),
        "positive_terms": _list_str(parsed.get("positive_terms")),
        "negative_terms": _list_str(parsed.get("negative_terms")),
        "time_hint": str(parsed.get("time_hint", "")),
        "location_hint": str(parsed.get("location_hint", "")),
        "top_k": max(1, min(10, int(parsed.get("top_k", 4)))),
        "memory_used": memory_used,
        "memory_influence": str(parsed.get("memory_influence", "")),
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "used_fallback": False,
        "error": None,
        "duration_ms": 0,
        "retry_count": retry_count,
    }


def _list_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return []
