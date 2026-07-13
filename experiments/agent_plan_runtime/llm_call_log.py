"""统一 LLM 调用记录 — 三个模块（query_rewrite / answer_composer / memory_reflection）共享。

记录字段（与曹昕宇 plan-day 接线一致）：
- module: 调用方模块名（query_rewrite / answer_composer / memory_reflection）
- prompt_version
- model
- duration_ms
- used_fallback
- error_type
- retry_count

安全规则：
- 严禁记录 API Key
- 不得无控制地记录完整用户隐私内容（仅记录 error_type 摘要与脱敏后的提示）
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 受控字段白名单，避免误把隐私内容写进日志
_RECORD_FIELDS = (
    "module",
    "prompt_version",
    "model",
    "duration_ms",
    "used_fallback",
    "error_type",
    "retry_count",
)


def log_llm_call(record: dict[str, Any]) -> None:
    """记录一次 LLM 调用（结构化 INFO 日志）。

    只输出白名单字段，自动丢弃 API Key、原始 query / 私有画像等敏感内容。
    """
    safe = {key: record.get(key) for key in _RECORD_FIELDS}
    # error_type 仅保留类型字符串，不展开原始异常文本（可能含隐私）
    if safe.get("error_type") is None:
        safe["error_type"] = "none"
    logger.info("llm_call_record %s", safe)


def classify_error(exc: BaseException | None) -> str:
    """将异常归一化为稳定的 error_type 字符串。"""
    if exc is None:
        return "none"
    name = type(exc).__name__
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "connection" in text:
        return "connection_error"
    if "json" in text or "decode" in text or "parse" in text:
        return "invalid_output"
    if "missing" in text or "choices" in text:
        return "invalid_response"
    return name
