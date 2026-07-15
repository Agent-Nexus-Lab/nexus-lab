# -*- coding: utf-8 -*-
"""文章去重与处理状态读写（采集可靠性契约二）。

全部函数接受 db: Session，不在内部 commit —— 调用方（auto_collector adapter）
每篇处理完统一 commit，保证细粒度事务边界。

status 枚举：
    pending / processing / completed / failed /
    skipped_not_an_event / skipped_no_activity / skipped_text_too_short

调用方判定（is_article_processed 返回 dict 时）：
    completed + content_hash 一致 → 跳过（已成功，内容未变）
    skipped_*                  → 跳过（终态内容，不重复调 LLM）
    completed + hash 变化       → 重新提取（内容更新）
    failed                     → 按 retry_count 决定重试
    pending / processing       → 视为未完成，重新提取
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .models import RawDocument

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = timezone.utc

# 终态内容判定（不重试）
TERMINAL_STATUSES = {
    "completed",
    "skipped_not_an_event",
    "skipped_no_activity",
    "skipped_text_too_short",
}


def is_article_processed(
    db: Session,
    source_url: str,
    content_hash: str | None = None,
) -> dict[str, Any] | None:
    """查 RawDocument by source_url。

    返回 None：未处理过，调用方应重新提取。
    返回 dict：含 status/content_hash/processed_at/retry_count/last_error/raw_document_id。
    """
    if not source_url:
        return None
    doc = (
        db.query(RawDocument)
        .filter(RawDocument.source_url == source_url)
        .first()
    )
    if doc is None:
        # 回退查旧 url 字段（迁移前数据兼容）
        doc = db.query(RawDocument).filter(RawDocument.url == source_url).first()
    if doc is None:
        return None
    return {
        "status": doc.status,
        "content_hash": doc.content_hash,
        "processed_at": doc.processed_at,
        "retry_count": doc.retry_count or 0,
        "last_error": doc.last_error,
        "raw_document_id": doc.id,
    }


def mark_article_processing(
    db: Session,
    source_url: str,
    *,
    title: str | None,
    content_hash: str,
    published_at: datetime | None = None,
    source_id: str | None = None,
) -> str:
    """创建或更新 RawDocument，置 status=processing，返回 raw_document_id。

    若同 source_url 已存在，更新 content_hash/published_at/title，retry_count 不动。
    """
    now = datetime.now(DEFAULT_TIMEZONE)
    doc = (
        db.query(RawDocument)
        .filter(RawDocument.source_url == source_url)
        .first()
    )
    if doc is None and source_url:
        doc = db.query(RawDocument).filter(RawDocument.url == source_url).first()

    if doc is not None:
        content_changed = doc.content_hash != content_hash
        doc.title = title or doc.title
        doc.content_hash = content_hash
        if source_id is not None:
            doc.source_id = source_id
        if published_at is not None:
            doc.published_at = published_at
        doc.status = "processing"
        doc.fetched_at = now
        if content_changed:
            doc.retry_count = 0
            doc.last_error = None
            doc.processed_at = None
        db.flush()
        return doc.id

    raw_id = str(uuid.uuid4())
    doc = RawDocument(
        id=raw_id,
        source_url=source_url,
        url=source_url,  # 兼容旧字段
        title=title,
        source_id=source_id,
        content_hash=content_hash,
        published_at=published_at,
        status="processing",
        retry_count=0,
        fetched_at=now,
    )
    db.add(doc)
    db.flush()
    return raw_id


def mark_article_completed(db: Session, raw_document_id: str) -> None:
    """置 status=completed, processed_at=now。"""
    doc = db.query(RawDocument).filter(RawDocument.id == raw_document_id).first()
    if doc is None:
        logger.warning("mark_article_completed: raw_document %s not found", raw_document_id)
        return
    doc.status = "completed"
    doc.last_error = None
    doc.processed_at = datetime.now(DEFAULT_TIMEZONE)
    db.flush()


def mark_article_failed(
    db: Session,
    raw_document_id: str,
    *,
    error: str,
    retry_count: int,
    is_terminal: bool,
) -> None:
    """置失败或终态 skipped_*，记 last_error/retry_count/processed_at。

    is_terminal=True 时 error 应为 skipped_* 对应的 ErrorClass 名
    （not_an_event / no_activity / text_too_short / insufficient_evidence / no_text），
    本函数映射到对应 status。
    """
    doc = db.query(RawDocument).filter(RawDocument.id == raw_document_id).first()
    if doc is None:
        logger.warning("mark_article_failed: raw_document %s not found", raw_document_id)
        return

    if is_terminal:
        status = _terminal_status_of(error)
    else:
        status = "failed"

    doc.status = status
    doc.last_error = (error or "")[:2000]
    doc.retry_count = retry_count
    doc.processed_at = datetime.now(DEFAULT_TIMEZONE)
    db.flush()


# ErrorClass 名 → status 映射
_TERMINAL_MAP = {
    "not_an_event": "skipped_not_an_event",
    "no_activity": "skipped_no_activity",
    "text_too_short": "skipped_text_too_short",
    "insufficient_evidence": "skipped_text_too_short",
    "no_text": "skipped_text_too_short",
}


def _terminal_status_of(error: str) -> str:
    """把 ErrorClass 名映射到 skipped_* status；未知归 skipped_text_too_short。"""
    if not error:
        return "failed"
    key = error.strip().lower()
    return _TERMINAL_MAP.get(key, "skipped_text_too_short")
