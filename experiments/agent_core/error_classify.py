# -*- coding: utf-8 -*-
"""错误分类与重试策略。

区分可重试的临时错误（timeout/rate_limited/provider_error）与不可重试的
内容结论（not_an_event/no_activity/text_too_short/insufficient_evidence/no_text）
及认证失败（authentication_failed，直接报警不重试）。
"""
from __future__ import annotations

import enum
from typing import Any


class ErrorClass(str, enum.Enum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTH_FAILED = "authentication_failed"
    PROVIDER_ERROR = "provider_error"
    NO_TEXT = "no_text"
    TEXT_TOO_SHORT = "text_too_short"
    NOT_AN_EVENT = "not_an_event"
    NO_ACTIVITY = "no_activity"
    PARSE_ERROR = "parse_error"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


RETRYABLE = {ErrorClass.TIMEOUT, ErrorClass.RATE_LIMITED, ErrorClass.PROVIDER_ERROR}
TERMINAL_CONTENT = {
    ErrorClass.NOT_AN_EVENT,
    ErrorClass.NO_ACTIVITY,
    ErrorClass.TEXT_TOO_SHORT,
    ErrorClass.INSUFFICIENT_EVIDENCE,
    ErrorClass.NO_TEXT,
}


def _is_retryable_http_status(status: int) -> bool:
    return status in (408, 429, 500, 502, 503, 504)


def classify_error(exc_or_status: Any) -> ErrorClass:
    """把异常或 status 字符串归类。

    支持：
      - ErrorClass（直通）
      - str：业务 status（ok/not_an_event/no_activity/text_too_short/parse_error/...）
             或异常类名片段
      - Exception：按类型名 + 消息关键词匹配
    """
    if isinstance(exc_or_status, ErrorClass):
        return exc_or_status

    if isinstance(exc_or_status, str):
        s = exc_or_status.strip().lower()
        mapping = {
            "timeout": ErrorClass.TIMEOUT,
            "rate_limited": ErrorClass.RATE_LIMITED,
            "rate limit": ErrorClass.RATE_LIMITED,
            "429": ErrorClass.RATE_LIMITED,
            "authentication_failed": ErrorClass.AUTH_FAILED,
            "auth": ErrorClass.AUTH_FAILED,
            "401": ErrorClass.AUTH_FAILED,
            "403": ErrorClass.AUTH_FAILED,
            "not_an_event": ErrorClass.NOT_AN_EVENT,
            "no_activity": ErrorClass.NO_ACTIVITY,
            "text_too_short": ErrorClass.TEXT_TOO_SHORT,
            "no_text": ErrorClass.NO_TEXT,
            "parse_error": ErrorClass.PARSE_ERROR,
            "insufficient_evidence": ErrorClass.INSUFFICIENT_EVIDENCE,
        }
        for k, v in mapping.items():
            if k in s:
                return v
        if "provider" in s or "upstream" in s or "502" in s or "503" in s or "504" in s:
            return ErrorClass.PROVIDER_ERROR
        return ErrorClass.PROVIDER_ERROR  # 未知字符串默认 provider_error（可重试）

    if isinstance(exc_or_status, BaseException):
        name = type(exc_or_status).__name__.lower()
        msg = str(exc_or_status).lower()
        if "timeout" in name or "timeout" in msg or "timed out" in msg:
            return ErrorClass.TIMEOUT
        if "rate" in msg and "limit" in msg:
            return ErrorClass.RATE_LIMITED
        if "auth" in name or "auth" in msg or "unauthorized" in msg or "forbidden" in msg:
            return ErrorClass.AUTH_FAILED
        if "parse" in name or "json" in name or "decode" in name or "json" in msg or "decode" in msg or "parse" in msg:
            return ErrorClass.PARSE_ERROR
        if "connection" in name or "network" in name or "urlerror" in name or "oserror" in name:
            return ErrorClass.PROVIDER_ERROR
        # 带状态码的 HTTP 错误
        for tok in msg.split():
            if tok.isdigit():
                code = int(tok)
                if code in (401, 403):
                    return ErrorClass.AUTH_FAILED
                if code == 429:
                    return ErrorClass.RATE_LIMITED
                if _is_retryable_http_status(code):
                    return ErrorClass.PROVIDER_ERROR
        return ErrorClass.PROVIDER_ERROR

    return ErrorClass.PROVIDER_ERROR


def is_retryable(err: ErrorClass) -> bool:
    return err in RETRYABLE


def is_terminal_content(err: ErrorClass) -> bool:
    return err in TERMINAL_CONTENT
