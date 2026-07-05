# -*- coding: utf-8 -*-
"""MaaS 提取接口预留：从公众号正文提取活动事件。

今天返回 mock（校验 metadata 必填字段后返回空列表），签名固定供 7月5日接入真实 MaaS。
真实实现必须保证：
  - source_url / source_name 从 metadata 透传到每条 event，不得编造。
  - evidence_text 必须来自原文片段，不得生成。
  - 时间不明确时不得编造，留 None 并标注 uncertain。
"""
from __future__ import annotations

REQUIRED_METADATA = ("source_url", "source_name", "title", "publish_time")


def extract_article_to_events(article_text: str, metadata: dict) -> list[dict]:
    """从公众号正文提取活动事件。

    Args:
        article_text: 公众号文章正文（纯文本）。
        metadata: 必须含 source_url / source_name / title / publish_time。

    Returns:
        event dict 列表（今天返回空列表，mock）。每条 event 保留 source_url /
        source_name / evidence_text。
    """
    missing = [k for k in REQUIRED_METADATA if not metadata.get(k)]
    if missing:
        raise ValueError(f"metadata 缺少必填字段: {missing}")
    if not article_text:
        return []
    # mock：7月5日接入真实 MaaS 时替换
    return []
