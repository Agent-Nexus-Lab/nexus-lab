# -*- coding: utf-8 -*-
"""lightweight mapper：公众号文章/小红书 note + MaaS 提取事件 → 6-field event draft。

7月7日新契约：只保留 title / summary / start_time / end_time / location / source_url。
organizer / tags / campus / evidence_text / source_name / source_platform 退场。
语义信息全部写入 summary 自然语言（供 summary_embedding 消费）。

mapper 是纯形状转换：不调网络、不调模型、不编造字段。
缺失字段填 None；缺失 title/start_time 记 validation error。
"""
from __future__ import annotations

from typing import Any

LIGHTWEIGHT_FIELDS = (
    "title", "summary", "start_time", "end_time", "location", "source_url",
)

# MaaS 输出 event 里可能出现的字段名（首选项 + 兼容别名）
_EVENT_FIELD_ALIASES = {
    "title": ("title",),
    "summary": ("summary", "description"),
    "start_time": ("start_time", "start"),
    "end_time": ("end_time", "end"),
    "location": ("location",),
}


def _first(event: dict, key: str) -> Any:
    for alias in _EVENT_FIELD_ALIASES[key]:
        if alias in event and event[alias] is not None:
            return event[alias]
    return None


def _source_from_article(article: dict) -> dict:
    return {
        "source_url": article.get("source_url") or article.get("url"),
        "title": article.get("title"),
    }


def _source_from_note(note: dict) -> dict:
    return {
        "source_url": note.get("source_url") or note.get("url") or note.get("note_url"),
        "title": note.get("title"),
    }


def _map_one(source: dict, event: dict) -> dict:
    """单个 extracted_event → 6-field draft。"""
    return {
        "title": _first(event, "title") or source.get("title"),
        "summary": _first(event, "summary"),
        "start_time": _first(event, "start_time"),
        "end_time": _first(event, "end_time"),
        "location": _first(event, "location"),
        "source_url": source.get("source_url"),
    }


def validate_draft(draft: dict) -> list[str]:
    """检查 6-field draft 完整性。

    缺失 title 或 source_url → error（无法去重/无法展示）
    缺失 start_time → error（排序需要）
    缺失 summary / end_time / location → warning（不影响入库，但标出）
    """
    warnings: list[str] = []
    if not draft.get("title"):
        warnings.append("ERROR: missing title")
    if not draft.get("source_url"):
        warnings.append("ERROR: missing source_url (去重依赖)")
    if not draft.get("start_time"):
        warnings.append("ERROR: missing start_time (排序依赖)")
    if not draft.get("summary"):
        warnings.append("WARNING: missing summary (embedding 质量下降)")
    if not draft.get("end_time"):
        warnings.append("WARNING: missing end_time")
    if not draft.get("location"):
        warnings.append("WARNING: missing location")
    return warnings


def map_wechat_article_to_drafts(
    article: dict,
    extracted_events: list[dict],
) -> tuple[list[dict], list[str]]:
    """公众号文章 + MaaS 提取事件 → (6-field drafts, validation_warnings)。

    - source_url 从 article 透传，不编造。
    - extracted_events 为空（MaaS stub 或未提取到活动）→ 返回 ([], [])。
    """
    source = _source_from_article(article)
    drafts: list[dict] = []
    all_warnings: list[str] = []
    for e in (extracted_events or []):
        draft = _map_one(source, e)
        vw = validate_draft(draft)
        if vw:
            vid = draft.get("title") or draft.get("source_url") or "?"
            all_warnings.append(f"[{vid[:60]}] {'; '.join(vw)}")
        drafts.append(draft)
    return drafts, all_warnings


def map_xiaohongshu_note_to_drafts(
    note: dict,
    extracted_events: list[dict],
) -> tuple[list[dict], list[str]]:
    """小红书 note + MaaS 提取事件 → (6-field drafts, validation_warnings)。"""
    source = _source_from_note(note)
    drafts: list[dict] = []
    all_warnings: list[str] = []
    for e in (extracted_events or []):
        draft = _map_one(source, e)
        vw = validate_draft(draft)
        if vw:
            vid = draft.get("title") or draft.get("source_url") or "?"
            all_warnings.append(f"[{vid[:60]}] {'; '.join(vw)}")
        drafts.append(draft)
    return drafts, all_warnings
