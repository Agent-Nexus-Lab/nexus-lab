# -*- coding: utf-8 -*-
"""schema_mapper：把公众号文章 / 小红书 note + MaaS 提取事件 → 统一 event draft。

字段契约来源：
  - 任务文档"MaaS 输出 event draft 字段"：
    title、summary、start_time、end_time、location、campus、organizer、tags、
    source_url、source_name、evidence_text
  - experiments/agent_maas_cli/prompt.md：source_url/source_name 透传、
    evidence_text 来自原文片段、campus 枚举、时间不明确不编造。

mapper 是纯形状转换：不调网络、不调模型、不编造字段。缺失字段补 None/[]。
"""
from __future__ import annotations

from typing import Any

EVENT_DRAFT_FIELDS = (
    "title", "summary", "start_time", "end_time", "location", "campus",
    "organizer", "tags", "source_url", "source_name", "source_platform",
    "evidence_text",
)

# MaaS 输出 event 里可能出现的字段名（首选项 + 兼容别名）
_EVENT_FIELD_ALIASES = {
    "title": ("title",),
    "summary": ("summary", "description"),
    "start_time": ("start_time", "start"),
    "end_time": ("end_time", "end"),
    "location": ("location",),
    "campus": ("campus",),
    "organizer": ("organizer", "host"),
    "tags": ("tags", "tag_list"),
    "evidence_text": ("evidence_text", "evidence"),
}


def _first(event: dict, key: str) -> Any:
    for alias in _EVENT_FIELD_ALIASES[key]:
        if alias in event and event[alias] is not None:
            return event[alias]
    return None


def _map_to_draft(source: dict, event: dict, platform: str) -> dict:
    """单个 event → event draft。

    source 提供 source_url / source_name（从文章/note 透传，不编造）。
    event 提供 title/summary/start_time/.../evidence_text（MaaS 提取）。
    """
    tags = _first(event, "tags") or []
    if not isinstance(tags, list):
        tags = [tags]
    return {
        "title": _first(event, "title") or source.get("title"),
        "summary": _first(event, "summary"),
        "start_time": _first(event, "start_time"),
        "end_time": _first(event, "end_time"),
        "location": _first(event, "location"),
        "campus": _first(event, "campus"),
        "organizer": _first(event, "organizer"),
        "tags": tags,
        "source_url": source.get("source_url") or source.get("url"),
        "source_name": source.get("source_name"),
        "source_platform": platform,
        "evidence_text": _first(event, "evidence_text"),
    }


def _source_from_article(article: dict) -> dict:
    """从公众号文章提取 source 字段（cn8n 返回的 article 形状）。"""
    return {
        "source_url": article.get("source_url") or article.get("url"),
        "source_name": article.get("source_name") or article.get("account"),
        "title": article.get("title"),
    }


def _source_from_note(note: dict) -> dict:
    """从小红书 note 提取 source 字段。"""
    return {
        "source_url": note.get("source_url") or note.get("url") or note.get("note_url"),
        "source_name": note.get("source_name") or note.get("author"),
        "title": note.get("title"),
    }


def map_wechat_article_to_drafts(article: dict, extracted_events: list[dict]) -> list[dict]:
    """公众号文章 + MaaS 提取事件 → event draft 列表。

    - source_platform = "wechat"
    - source_url / source_name 从 article 透传，不编造。
    - evidence_text 必须来自 extracted_events（MaaS 原文片段），不生成。
    - extracted_events 为空（MaaS stub 或未提取到活动）→ 返回 []。
    """
    source = _source_from_article(article)
    return [_map_to_draft(source, e, "wechat") for e in (extracted_events or [])]


def map_xiaohongshu_note_to_drafts(note: dict, extracted_events: list[dict]) -> list[dict]:
    """小红书 note + MaaS 提取事件 → event draft 列表（最小版本）。

    - source_platform = "xiaohongshu"
    - 结构与 wechat mapper 共用 _map_to_draft，仅 source_platform 不同。
    """
    source = _source_from_note(note)
    return [_map_to_draft(source, e, "xiaohongshu") for e in (extracted_events or [])]
