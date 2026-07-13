"""Memory Reflection — 基于最近 N 轮对话生成 memory_summary。

由李颖哲负责。每 3 轮 plan-day 后调用 LLM 压缩对话记忆为自然语言摘要。

=== 固定输入输出契约（给曹昕宇 plan-day 接线） ===

reflect_on_memory(context) 输入（最近三轮）：
- request_text
- recommended_event_ids / recommended_event_titles
- liked_event_ids / liked（feedback）
- disliked_event_ids / disliked（feedback）
- existing_memory
- existing_memory_summary
- source_refs

稳定输出：

┌──────────────────────┬──────────┬────────────────────────────────────────┐
│ 字段                 │ 入库     │ 说明                                   │
├──────────────────────┼──────────┼────────────────────────────────────────┤
│ memory_summary       │ ✅ 入库  │ 自然语言记忆摘要，存入 memory_items    │
│ source_refs          │ ✅ 入库  │ 可追溯到 run_id/feedback id/event_id   │
│ expires_after_turns  │ ✅ 入库  │ 过期轮数，超时标记 expired             │
│ cleanup_reason       │ ✅ 入库  │ null/expired/user_requested            │
│ status               │ ✅ 入库  │ active/expired/suppressed/             │
│                      │          │ insufficient_evidence                  │
│ prompt_version       │ ✅ 入库  │ 生成时使用的 prompt 版本号             │
│ model                │ debug    │ 实际使用的模型名                       │
│ used_fallback        │ debug    │ 是否使用了规则回退                     │
│ error                │ debug    │ LLM 调用失败时的错误信息               │
│ duration_ms          │ debug    │ 调用耗时（毫秒）                       │
│ retry_count          │ debug    │ 重试次数                               │
│ memory_strength      │ ✅ 入库  │ 记忆强度 0.0-1.0，每轮 ×0.85 衰减      │
└──────────────────────┴──────────┴────────────────────────────────────────┘

要求：
1. 只总结有证据的偏好；不把一次偶然点击夸大成永久特征
2. 本轮表达与旧总结冲突时以本轮为主
3. source_refs 可追溯到 run_id、feedback id 或 event_id
4. 证据不足时不生成新 summary，或者继续保留旧 summary

生命週期函数（由曹昕宇在后端调用）：
- decay_memory_strength(m) → 每轮 plan-day 后调用
- is_memory_expired(m) → 判断是否过期
- suppress_memory(m) → 用户删除后调用
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from llm_call_log import classify_error, log_llm_call

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
- run_id: 该轮运行 id
- request_text: 用户当时的 query
- recommended_event_ids: 当时推荐的活动 event_id 列表
- recommended_event_titles: 当时推荐的活动标题列表
- liked_event_ids / feedback.liked: 用户喜欢的活动
- disliked_event_ids / feedback.disliked: 用户不喜欢的活动
- existing_memory: 如果已有之前的 memory_summary，会附带在输入中
- existing_memory_summary: 旧的摘要文本

## 输出格式
你必须输出以下 JSON：

{
  "memory_summary": "一段 50-150 字的自然语言记忆摘要",
  "source_refs": ["run_id_1", "run_id_2"],
  "memory_strength": 0.85,
  "expires_after_turns": 6,
  "cleanup_reason": null,
  "status": "active"
}

## memory_summary 写作要求
1. 用自然流畅的中文，概括用户在这 3 轮中表现出的偏好模式
2. 必须包含：
   - 用户持续感兴趣的主题或活动类型
   - 用户明确不喜欢的内容（从 disliked 反馈推断）
   - 如果有风格偏好（轻松/互动/正式等），也写进去
3. 不要重复用户每一轮的具体 query，而要提炼模式
4. **只总结有证据的偏好；不要把一次偶然点击夸大成永久特征**
5. **本轮表达与旧总结冲突时以本轮为主**
6. 如果所有 feedback 都为空，写"用户尚未表达明确偏好"，status 设为 insufficient_evidence
7. 如果有已有 memory，在摘要中体现新旧偏好的演变

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
- 也可包含 feedback id 或 event_id 以便溯源

## cleanup_reason 规则
- 正常生成的记忆，cleanup_reason 为 null
- 如果用户明确表示"忘掉这些"或"清除记忆"，则 memory_summary 为空字符串，cleanup_reason 为 "user_requested"

## status 规则
- active: 正常生成的有效记忆
- insufficient_evidence: 证据不足（无反馈），保留旧 summary 或为空
- expired: 已过期（一般由 decay 逻辑产生，此处一般不主动输出）
- suppressed: 用户主动清除

只输出 JSON，不要输出任何额外文字。"""


def _normalize_rounds(rounds: Any) -> list[dict[str, Any]]:
    """规范化每轮输入，统一 event_ids 与 titles 两种形式。"""
    normalized: list[dict[str, Any]] = []
    if not isinstance(rounds, list):
        return normalized
    for r in rounds:
        if not isinstance(r, dict):
            continue
        feedback = r.get("feedback") or {}
        item = {
            "round": r.get("round"),
            "run_id": r.get("run_id"),
            "request_text": r.get("request_text", ""),
            "recommended_event_ids": r.get("recommended_event_ids") or [],
            "recommended_event_titles": r.get("recommended_event_titles") or [],
            "liked_event_ids": r.get("liked_event_ids") or feedback.get("liked") or [],
            "disliked_event_ids": r.get("disliked_event_ids") or feedback.get("disliked") or [],
        }
        normalized.append(item)
    return normalized


def _collect_feedback(rounds: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    """汇总 liked/disliked（同时兼容 id 与 title）。返回 (liked, disliked, source_refs)。"""
    all_liked: list[str] = []
    all_disliked: list[str] = []
    source_refs: list[str] = []
    for r in rounds:
        liked = r.get("liked_event_ids") or []
        disliked = r.get("disliked_event_ids") or []
        all_liked.extend([str(x) for x in liked if x])
        all_disliked.extend([str(x) for x in disliked if x])
        if r.get("run_id"):
            source_refs.append(str(r["run_id"]))
    return all_liked, all_disliked, source_refs


def _build_title_map(rounds: list[dict[str, Any]]) -> dict[str, str]:
    """从各轮 recommended_event_ids / recommended_event_titles 构建 id→title 映射。"""
    title_map: dict[str, str] = {}
    for r in rounds:
        ids = r.get("recommended_event_ids") or []
        titles = r.get("recommended_event_titles") or []
        if isinstance(ids, list) and isinstance(titles, list):
            for eid, title in zip(ids, titles):
                if eid and title:
                    title_map[str(eid)] = str(title)
    return title_map


def _label(eid: str, title_map: dict[str, str]) -> str:
    """优先用标题，否则用 id。"""
    return title_map.get(str(eid), str(eid))


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
        context: 包含 rounds / existing_memory / existing_memory_summary 等
        base_url/model/api_key/timeout: MaaS 配置

    Returns:
        固定契约字段：memory_summary / source_refs / expires_after_turns /
        cleanup_reason / status / prompt_version / model / used_fallback /
        error / duration_ms / retry_count / memory_strength
    """
    start = time.perf_counter()
    resolved_model = model or os.getenv("MAAS_MODEL") or DEFAULT_MODEL

    rounds = _normalize_rounds(context.get("rounds"))
    if not rounds:
        result = _empty_reflection("no_context", "no rounds provided")
        result["model"] = resolved_model
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        result["retry_count"] = 0
        _log(resolved_model, result, "none", 0)
        return result

    existing_memory = context.get("existing_memory")
    existing_memory_summary = (
        context.get("existing_memory_summary")
        or (existing_memory or {}).get("memory_summary")
        if isinstance(existing_memory, dict)
        else context.get("existing_memory_summary")
    )

    liked, disliked, source_refs = _collect_feedback(rounds)
    total_feedback = len(liked) + len(disliked)

    # 证据不足：无任何反馈 → 不生成新 summary，保留旧 summary，status=insufficient_evidence
    if total_feedback == 0:
        result = _insufficient_evidence(existing_memory_summary, source_refs)
        result["model"] = resolved_model
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        result["retry_count"] = 0
        _log(resolved_model, result, "none", 0)
        return result

    resolved_api_key = api_key or os.getenv("MAAS_API_KEY")
    if not resolved_api_key:
        result = _rule_based_reflection(context, reason="MAAS_API_KEY not set")
        result["model"] = resolved_model
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        result["retry_count"] = 0
        _log(resolved_model, result, "none", 0)
        return result

    error: str | None = None
    error_type = "none"
    try:
        result = _call_llm_reflection(
            context,
            rounds,
            base_url=base_url,
            model=resolved_model,
            api_key=resolved_api_key,
            timeout=timeout,
        )
        result["model"] = resolved_model
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        _log(resolved_model, result, "none", result.get("retry_count", 0))
        return result
    except Exception as exc:
        error = str(exc)
        error_type = classify_error(exc)
        logger.warning("LLM memory reflection failed, using rule-based fallback: %s", exc)

    result = _rule_based_reflection(context, reason=f"LLM failed: {error}")
    result["model"] = resolved_model
    result["error"] = error
    result["duration_ms"] = int((time.perf_counter() - start) * 1000)
    result["retry_count"] = 0
    _log(resolved_model, result, error_type, 0)
    return result


def _log(model: str, result: dict[str, Any], error_type: str, retry_count: int) -> None:
    log_llm_call({
        "module": "memory_reflection",
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "duration_ms": result.get("duration_ms", 0),
        "used_fallback": result.get("used_fallback", True),
        "error_type": error_type,
        "retry_count": retry_count,
    })


def _call_llm_reflection(
    context: dict[str, Any],
    rounds: list[dict[str, Any]],
    *,
    base_url: str | None = None,
    model: str,
    api_key: str,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Call MaaS LLM for memory reflection."""
    import requests

    resolved_base_url = (base_url or os.getenv("MAAS_BASE_URL") or DEFAULT_OPENAI_BASE_URL).rstrip("/")
    url = f"{resolved_base_url}/chat/completions"
    timeout_value = timeout or float(os.getenv("MAAS_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))

    existing_memory = context.get("existing_memory")
    user_payload = {
        "rounds": rounds,
        "existing_memory": existing_memory,
        "existing_memory_summary": (
            context.get("existing_memory_summary")
            or (existing_memory or {}).get("memory_summary")
            if isinstance(existing_memory, dict)
            else context.get("existing_memory_summary")
        ),
        "session_id": context.get("session_id"),
    }

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _MEMORY_REFLECTION_SYSTEM_PROMPT},
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
            parsed = _extract_json_response(raw)
            return _normalize_reflection(parsed, context, rounds, model=model, retry_count=retry_count)

        except (requests.Timeout, requests.ConnectionError, ValueError, json.JSONDecodeError, KeyError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                retry_count += 1
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
            continue

    raise RuntimeError(f"LLM memory reflection failed after all retries: {last_exc}")


def _rule_based_reflection(
    context: dict[str, Any],
    reason: str = "",
) -> dict[str, Any]:
    """Simple rule-based memory reflection fallback (no LLM).

    从 context 中自动解析 rounds / liked / disliked / source_refs / 旧 summary。
    """
    rounds = _normalize_rounds(context.get("rounds"))
    existing_memory = context.get("existing_memory")
    existing_memory_summary = (
        context.get("existing_memory_summary")
        or (existing_memory or {}).get("memory_summary")
        if isinstance(existing_memory, dict)
        else context.get("existing_memory_summary")
    )
    liked, disliked, source_refs = _collect_feedback(rounds)
    title_map = _build_title_map(rounds)

    parts: list[str] = []

    if liked:
        liked_unique = list(dict.fromkeys(_label(x, title_map) for x in liked))
        liked_text = "、".join(liked_unique[:3])
        parts.append(f"用户对「{liked_text}」等活动感兴趣")
    if disliked:
        disliked_unique = list(dict.fromkeys(_label(x, title_map) for x in disliked))
        disliked_text = "、".join(disliked_unique[:3])
        parts.append(f"不喜欢「{disliked_text}」类活动")

    if not parts:
        # 证据不足，保留旧 summary
        return _insufficient_evidence(existing_memory_summary, source_refs, reason=reason)

    # 单次反馈不夸大为永久特征：仅 1 条反馈时降低强度
    total = len(liked) + len(disliked)
    strength = 0.85 if total >= 2 else 0.60
    expires = 6 if strength >= 0.5 else 3

    summary = "；".join(parts) + "。"
    # 本轮与旧总结冲突时以本轮为主：直接用本轮总结覆盖

    return {
        "memory_summary": summary,
        "source_refs": source_refs,
        "memory_strength": round(strength, 2),
        "expires_after_turns": expires,
        "cleanup_reason": None,
        "status": "active",
        "error": reason if reason else None,
        "used_fallback": True,
        "prompt_version": PROMPT_VERSION,
        "model": DEFAULT_MODEL,
        "duration_ms": 0,
        "retry_count": 0,
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


def _normalize_reflection(
    parsed: dict[str, Any],
    context: dict[str, Any],
    rounds: list[dict[str, Any]] | None = None,
    *,
    model: str = DEFAULT_MODEL,
    retry_count: int = 0,
) -> dict[str, Any]:
    memory_summary = str(parsed.get("memory_summary", "")).strip()
    source_refs = parsed.get("source_refs") if isinstance(parsed.get("source_refs"), list) else []
    # 若 LLM 未给出 source_refs，从 rounds 兜底
    if not source_refs and rounds:
        _, _, fallback_refs = _collect_feedback(rounds)
        source_refs = fallback_refs

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
    status = str(parsed.get("status", "")).lower() or "active"
    if status not in {"active", "expired", "suppressed", "insufficient_evidence"}:
        status = "active"

    # 证据不足时以 insufficient_evidence 兜底
    if rounds:
        liked, disliked, _ = _collect_feedback(rounds)
        if not liked and not disliked and status == "active":
            status = "insufficient_evidence"

    return {
        "memory_summary": memory_summary,
        "source_refs": [str(r) for r in source_refs],
        "memory_strength": round(memory_strength, 2),
        "expires_after_turns": expires_after_turns,
        "cleanup_reason": cleanup_reason,
        "status": status,
        "error": None,
        "used_fallback": False,
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "duration_ms": 0,
        "retry_count": retry_count,
    }


def _insufficient_evidence(
    existing_memory_summary: str | None,
    source_refs: list[str],
    reason: str = "",
) -> dict[str, Any]:
    """证据不足：保留旧 summary 或为空，status=insufficient_evidence。"""
    summary = (existing_memory_summary or "").strip() or "用户尚未表达明确偏好。"
    return {
        "memory_summary": summary,
        "source_refs": source_refs,
        "memory_strength": 0.30,
        "expires_after_turns": 3,
        "cleanup_reason": None,
        "status": "insufficient_evidence",
        "error": reason if reason else None,
        "used_fallback": True,
        "prompt_version": PROMPT_VERSION,
        "model": DEFAULT_MODEL,
        "duration_ms": 0,
        "retry_count": 0,
    }


def _empty_reflection(status: str, reason: str) -> dict[str, Any]:
    return {
        "memory_summary": "",
        "source_refs": [],
        "memory_strength": 0.0,
        "expires_after_turns": 1,
        "cleanup_reason": status,
        "status": status,
        "error": reason,
        "used_fallback": True,
        "prompt_version": PROMPT_VERSION,
        "model": DEFAULT_MODEL,
        "duration_ms": 0,
        "retry_count": 0,
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
        result["status"] = "expired"
    else:
        # 未过期时确保 status 存在（输入可能没有 status 字段）
        result.setdefault("status", "active")
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
    result["status"] = "suppressed"
    return result
