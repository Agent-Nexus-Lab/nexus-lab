# -*- coding: utf-8 -*-
"""入库接口预留：将提取的事件写入 Event DB。

今天只打印 + 返回计数（dry_run=True），调用位置固定供 7月5日接入真实 DB。
真实实现必须：去重（按 source_url + title）、保留 source_url 可回溯、不编造字段。
"""
from __future__ import annotations


def import_events(events: list[dict]) -> dict:
    """将提取的事件入库。

    Args:
        events: extract_article_to_events 产出的事件列表。

    Returns:
        {"imported": N, "skipped": M, "dry_run": bool}。今天 dry_run=True，全部 skip。
    """
    print(f"[import_events] would import {len(events)} events (dry-run)")
    return {"imported": 0, "skipped": len(events), "dry_run": True}
