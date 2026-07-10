"""Memory Reflection — 基于最近 N 轮对话生成 memory_summary。

由李颖哲负责。每 3 轮 plan-day 后调用 LLM 压缩对话记忆为自然语言摘要。

Usage:
    from experiments.agent_plan_runtime.memory_reflection import reflect_on_memory

    context = {
        "session_id": "sess_001",
        "rounds": [
            {
                "round": 1,
                "request_text": "今天下午有什么天文活动",
                "recommended_event_titles": ["天文摄影讲座", "观星活动"],
                "feedback": {"liked": ["天文摄影讲座"], "disliked": ["观星活动"]},
            },
            ...
        ],
        "existing_memory": None,  # or previous memory_summary dict
    }

    result = reflect_on_memory(context)
    # => {
    #   "memory_summary": "...",
    #   "source_refs": ["run_001", "run_002"],
    #   "memory_strength": 0.85,
    #   "expires_after_turns": 6,
    #   "cleanup_reason": None,
    # }
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# 与 llm.py 共享同一份 MaaS 配置
DEFAULT_OPENAI_BASE_URL = "https://api.modelarts-maas.com/openai/v1"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1.0

# 衰减配置
MEMORY_STRENGTH_DECAY = 0.85          # 每轮 plan-day 后 ×0.85
MEMORY_EXPIRY_THRESHOLD = 0.15        # 低于此值时标记 expired
MEMORY_DEFAULT_STRENGTH = 0.85        # 新生成的 memory_summary 初始强度
MEMORY_DEFAULT_EXPIRES_AFTER = 6      # 默认 6 轮后过期

# Prompt 版本
PROMPT_VERSION = "2026-07-08-v1"


_MEMORY_REFLECTION_SYSTEM_PROMPT = """你是复旦大学校园日程助手的记忆管理器。你的任务是根据用户最近几轮对话和反馈，生成一段自然语言记忆摘要（memory_summary），帮助后续推荐更符合用户偏好。

## 输入格式
你会收到一个 JSON，包含最近 3 轮对话记录。每轮包含：
- round: 轮次编号
- request_text: 用户当时的 query
- recommended_event_titles: 当时推荐的活动标题列表
- feedback: 用户反馈，包含 liked（喜欢的活动标题）和 disliked（不喜欢的活动标题）
- existing_memory: 如果已有之前的 memory_summary，会附带在输入中

## 输出格式
你必须输出以下 JSON：

{
  "memory_summary": "一段 50-150 字的自然语言记忆摘要",
  "source_refs": ["run_id_1", "run_id_2"],
  "memory_strength": 0.85,
  "expires_after_turns": 6,
  "cleanup_reason": null
}

## memory_summary 写作要求
1. 用自然流畅的中文，概括用户在这 3 轮中表现出的偏好模式
2. 必须包含：
   - 用户持续感兴趣的主题或活动类型
   - 用户明确不喜欢的内容（从 disliked 反馈推断）
   - 如果有风格偏好（轻松/互动/正式等），也写进去
3. 不要重复用户每一轮的具体 query，而要提炼模式
4. 如果所有 feedback 都为空，写"用户尚未表达明确偏好"
5. 如果有已有 memory，在摘要中体现新旧偏好的演变

示例：
- "用户对天文学和摄影类活动有明显偏好，连续两轮都选择了天文相关活动。对纯理论讲座不太感兴趣。偏好轻松互动的活动形式。"
- "用户偏好实践类活动（如工作坊、动手实验），不喜欢商业路演类活动。对邯郸校区活动有地理位置偏好。"

## memory_strength 规则
- 新生成的记忆，如果有 ≥2 条有效反馈（liked 或 disliked 不为空），设为 0.85
- 如果只有 1 条反馈，设为 0.60
- 如果 3 轮都没有反馈，设为 0.30

## expires_after_turns 规则
- 默认 6 轮后过期
- 如果记忆强度低（<0.5），设为 3 轮

## source_refs 规则
- 列出参与生成此 memory 的 run_id 列表（从输入 rounds 中获取）

## cleanup_reason 规则
- 正常生成的记忆，cleanup_reason 为 null
- 如果用户明确表示"忘掉这些"或"清除记忆"，则 memory_summary 为空字符串，cleanup_reason 为 "user_requested"

只输出 JSON，不要输出任何额外文字。"""


def reflect_on_memory(
    context: dict[str, Any],
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Generate memory_summary from recent N rounds of conversation.

    Args:
        context: {
            "session_id": str,
            "rounds": [{"round": int, "request_text": str,
                        "recommended_event_titles": [str],
                        "feedback": {"liked": [str], "disliked": [str]}}],
            "existing_memory": None | {"memory_summary": str, "memory_strength": float, ...},
        }
        base_url: MaaS API 地址，默认读环境变量。
        model: 模型名，默认 deepseek-v4-pro。
        api_key: API Key，默认读 MAAS_API_KEY。
        timeout: 超时秒数。

    Returns:
        {
            "memory_summary": str,
            "source_refs": [str],
            "memory_strength": float,
            "expires_after_turns": int,
            "cleanup_reason": None | str,
            "error": None | str,
            "used_fallback": bool,
            "prompt_version": str,
        }
    """
    rounds = context.get("rounds")
    if not isinstance(rounds, list) or len(rounds) == 0:
        return _empty_reflection("no_context", "no rounds provided")

    # Try rule-based fast path first: if no feedback at all, don't call LLM
    valid_rounds = [r for r in rounds if isinstance(r, dict)]
    if not valid_rounds:
        return _empty_reflection("no_context", "no valid rounds")

    has_feedback = any(
        (r.get("feedback") or {}).get("liked") or (r.get("feedback") or {}).get("disliked")
        for r in valid_rounds
    )

    # If LLM unavailable, use rule-based fallback
    resolved_api_key = api_key or os.getenv("MAAS_API_KEY")
    if not resolved_api_key:
        return _rule_based_reflection(context, reason="MAAS_API_KEY not set")

    # Call LLM
    try:
        return _call_llm_reflection(
            context,
            base_url=base_url,
            model=model,
            api_key=resolved_api_key,
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning("LLM memory reflection failed, using rule-based fallback: %s", exc)
        return _rule_based_reflection(context, reason=f"LLM failed: {exc}")


def _call_llm_reflection(
    context: dict[str, Any],
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Call MaaS LLM for memory reflection."""
    import requests

    resolved_model = model or os.getenv("MAAS_MODEL") or DEFAULT_MODEL
    resolved_base_url = (base_url or os.getenv("MAAS_BASE_URL") or DEFAULT_OPENAI_BASE_URL).rstrip("/")
    url = f"{resolved_base_url}/chat/completions"
    timeout_value = timeout or float(os.getenv("MAAS_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))

    user_payload = {
        "rounds": context.get("rounds", []),
        "existing_memory": context.get("existing_memory"),
        "session_id": context.get("session_id"),
    }

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": _MEMORY_REFLECTION_SYSTEM_PROMPT},
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
            parsed = _extract_json_response(raw)
            return _normalize_reflection(parsed, context)

        except (requests.Timeout, requests.ConnectionError, ValueError, json.JSONDecodeError, KeyError) as exc:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
            continue

    raise RuntimeError("LLM memory reflection failed after all retries")


def _rule_based_reflection(context: dict[str, Any], reason: str = "") -> dict[str, Any]:
    """Simple rule-based memory reflection fallback (no LLM)."""
    rounds = [r for r in context.get("rounds", []) if isinstance(r, dict)]

    all_liked: list[str] = []
    all_disliked: list[str] = []
    all_requests: list[str] = []
    source_refs: list[str] = []

    for r in rounds:
        feedback = r.get("feedback") or {}
        liked = feedback.get("liked") or []
        disliked = feedback.get("disliked") or []
        all_liked.extend(liked)
        all_disliked.extend(disliked)
        all_requests.append(r.get("request_text", ""))
        if r.get("run_id"):
            source_refs.append(r["run_id"])

    parts: list[str] = []

    if all_liked:
        liked_text = "、".join(all_liked[:3])
        parts.append(f"用户对「{liked_text}」等活动感兴趣")
    if all_disliked:
        disliked_text = "、".join(all_disliked[:3])
        parts.append(f"不喜欢「{disliked_text}」类活动")

    if not parts:
        parts.append("用户尚未表达明确偏好")

    strength = 0.85 if len(all_liked) + len(all_disliked) >= 2 else 0.60 if len(all_liked) + len(all_disliked) == 1 else 0.30
    expires = 6 if strength >= 0.5 else 3

    return {
        "memory_summary": "；".join(parts) + "。",
        "source_refs": source_refs,
        "memory_strength": round(strength, 2),
        "expires_after_turns": expires,
        "cleanup_reason": None,
        "error": reason if reason else None,
        "used_fallback": True,
        "prompt_version": PROMPT_VERSION,
    }


def _extract_json_response(raw_response: dict[str, Any]) -> dict[str, Any]:
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


def _normalize_reflection(parsed: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    memory_summary = str(parsed.get("memory_summary", "")).strip()
    source_refs = parsed.get("source_refs") if isinstance(parsed.get("source_refs"), list) else []
    try:
        memory_strength = float(parsed.get("memory_strength", MEMORY_DEFAULT_STRENGTH))
    except (TypeError, ValueError):
        memory_strength = MEMORY_DEFAULT_STRENGTH
    memory_strength = max(0.0, min(1.0, memory_strength))

    try:
        expires_after_turns = int(parsed.get("expires_after_turns", MEMORY_DEFAULT_EXPIRES_AFTER))
    except (TypeError, ValueError):
        expires_after_turns = MEMORY_DEFAULT_EXPIRES_AFTER
    expires_after_turns = max(1, expires_after_turns)

    cleanup_reason = str(parsed.get("cleanup_reason", "")) or None

    return {
        "memory_summary": memory_summary,
        "source_refs": [str(r) for r in source_refs],
        "memory_strength": round(memory_strength, 2),
        "expires_after_turns": expires_after_turns,
        "cleanup_reason": cleanup_reason,
        "error": None,
        "used_fallback": False,
        "prompt_version": PROMPT_VERSION,
    }


def _empty_reflection(status: str, reason: str) -> dict[str, Any]:
    return {
        "memory_summary": "",
        "source_refs": [],
        "memory_strength": 0.0,
        "expires_after_turns": 1,
        "cleanup_reason": status,
        "error": reason,
        "used_fallback": True,
        "prompt_version": PROMPT_VERSION,
    }


def decay_memory_strength(memory: dict[str, Any]) -> dict[str, Any]:
    """Apply per-round decay to memory strength.

    Called after each plan-day. Returns updated memory dict.
    """
    current = memory.get("memory_strength", 0.0)
    new_strength = round(current * MEMORY_STRENGTH_DECAY, 2)
    result = dict(memory)
    result["memory_strength"] = new_strength
    if new_strength < MEMORY_EXPIRY_THRESHOLD and not result.get("cleanup_reason"):
        result["cleanup_reason"] = "expired_below_threshold"
    return result


def is_memory_expired(memory: dict[str, Any]) -> bool:
    """Check if memory should no longer be used.

    user_requested is handled separately — frontend controls display,
    backend suppresses re-generation.
    """
    cleanup = memory.get("cleanup_reason")
    if cleanup and cleanup != "user_requested":
        return True
    if cleanup == "user_requested":
        return False  # user-suppressed, but not auto-expired
    return memory.get("memory_strength", 0.0) < MEMORY_EXPIRY_THRESHOLD


def suppress_memory(memory: dict[str, Any]) -> dict[str, Any]:
    """Mark memory as suppressed (user deleted)."""
    result = dict(memory)
    result["cleanup_reason"] = "user_requested"
    result["memory_strength"] = 0.0
    return result
