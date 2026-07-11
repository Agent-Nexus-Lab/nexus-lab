"""
Query Rewrite — 将 memory_summary 注入下一轮 query 的上下文。

由李颖哲负责。接收原始 query + memory_summary + profile，
输出 enriched_query、positive/negative terms 等，供 search_events 使用。

Usage:
    from experiments.agent_plan_runtime.query_rewrite import rewrite_query

    result = rewrite_query(
        query="今天下午有什么活动",
        memory_summary="用户偏好天文观测，不喜欢商业路演",
        profile={"interest_tags": ["天文"], "preferred_campuses": ["邯郸"]},
    )
    # => {
    #   "enriched_query": "天文 观星 观测 展览 工作坊",
    #   "positive_terms": ["天文", "观星", "展览"],
    #   "negative_terms": ["路演", "商业"],
    #   "time_hint": "afternoon",
    #   "location_hint": "邯郸",
    #   "top_k": 4,
    #   "memory_influence": "memory_summary强化天文偏好，排除商业类活动",
    #   "prompt_version": "2026-07-08-v1",
    # }
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.modelarts-maas.com/openai/v1"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1.0

PROMPT_VERSION = "2026-07-08-v1"

_QUERY_REWRITE_SYSTEM_PROMPT = """你是复旦大学校园日程助手的意图增强器。根据用户的原始 query、memory_summary 和 profile，输出增强后的搜索意图。

## 输入
- query: 用户当前 query
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


def rewrite_query(
    query: str,
    memory_summary: str | None = None,
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
        memory_summary: memory_reflection 生成的记忆摘要
        profile: 用户画像
        base_url/model/api_key/timeout: MaaS 配置

    Returns:
        {
            "enriched_query": str,
            "positive_terms": [str],
            "negative_terms": [str],
            "time_hint": str,
            "location_hint": str,
            "top_k": int,
            "memory_influence": str,
            "prompt_version": str,
            "used_fallback": bool,
            "error": None | str,
        }
    """
    resolved_api_key = api_key or os.getenv("MAAS_API_KEY")

    if resolved_api_key:
        try:
            return _call_llm_rewrite(
                query=query,
                memory_summary=memory_summary,
                profile=profile,
                base_url=base_url,
                model=model,
                api_key=resolved_api_key,
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning("LLM query rewrite failed, using rule fallback: %s", exc)

    return _rule_based_rewrite(query, memory_summary, profile)


def _rule_based_rewrite(
    query: str,
    memory_summary: str | None,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Simple rule-based query rewrite (no LLM)."""
    profile = profile or {}
    terms: list[str] = []

    # From query
    terms.append(query)

    # From profile interest_tags
    interest_tags = profile.get("interest_tags", [])
    if isinstance(interest_tags, list):
        terms.extend(interest_tags)

    # From memory_summary: extract positive signals
    positive_terms: list[str] = []
    negative_terms: list[str] = []
    memory_influence = ""

    if memory_summary:
        # Simple keyword extraction from memory_summary
        if "偏好" in memory_summary or "喜欢" in memory_summary or "感兴趣" in memory_summary:
            # Extract preference indicators
            for kw in ["天文", "AI", "摄影", "展览", "工作坊", "讲座", "观星", "音乐", "体育",
                        "轻松", "互动", "实践", "安静", "社交", "创业", "学术"]:
                if kw in memory_summary:
                    positive_terms.append(kw)
        if "不喜欢" in memory_summary or "不感兴趣" in memory_summary:
            for kw in ["路演", "商业", "讲座", "体育", "比赛"]:
                if kw in memory_summary and "不喜欢" in memory_summary:
                    negative_terms.append(kw)
        memory_influence = f"memory_summary 提供了用户偏好和排除信号" if positive_terms or negative_terms else "memory_summary 无明确偏好"

    # Time hint from query
    time_hint = ""
    if any(w in query for w in ["上午", "早上"]):
        time_hint = "morning"
    elif any(w in query for w in ["下午"]):
        time_hint = "afternoon"
    elif any(w in query for w in ["晚上", "今晚"]):
        time_hint = "evening"
    elif any(w in query for w in ["周末"]):
        time_hint = "weekend"

    # Location hint from query
    location_hint = ""
    for campus in ["邯郸", "江湾", "枫林", "张江"]:
        if campus in query:
            location_hint = campus
            break
    if not location_hint and profile.get("preferred_campuses"):
        campuses = profile["preferred_campuses"]
        if isinstance(campuses, list) and campuses:
            location_hint = campuses[0]

    # Top K
    top_k = 4
    match = re.search(r"(\d+)\s*个", query)
    if match:
        top_k = min(max(int(match.group(1)), 1), 10)

    enriched = " ".join(dict.fromkeys(terms))

    return {
        "enriched_query": enriched,
        "positive_terms": positive_terms,
        "negative_terms": negative_terms,
        "time_hint": time_hint,
        "location_hint": location_hint,
        "top_k": top_k,
        "memory_influence": memory_influence,
        "prompt_version": PROMPT_VERSION,
        "used_fallback": True,
        "error": None,
    }


def _call_llm_rewrite(
    query: str,
    memory_summary: str | None,
    profile: dict[str, Any] | None,
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

    user_payload = {
        "query": query,
        "memory_summary": memory_summary or "",
        "profile": profile or {},
    }

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": _QUERY_REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0.1,
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
            return _normalize_rewrite(parsed)

        except (requests.Timeout, requests.ConnectionError, ValueError, json.JSONDecodeError, KeyError) as exc:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
            continue

    raise RuntimeError("LLM query rewrite failed after all retries")


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


def _normalize_rewrite(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "enriched_query": str(parsed.get("enriched_query", "")),
        "positive_terms": _list_str(parsed.get("positive_terms")),
        "negative_terms": _list_str(parsed.get("negative_terms")),
        "time_hint": str(parsed.get("time_hint", "")),
        "location_hint": str(parsed.get("location_hint", "")),
        "top_k": max(1, min(10, int(parsed.get("top_k", 4)))),
        "memory_influence": str(parsed.get("memory_influence", "")),
        "prompt_version": PROMPT_VERSION,
        "used_fallback": False,
        "error": None,
    }


def _list_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return []
