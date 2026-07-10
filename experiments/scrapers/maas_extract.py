# -*- coding: utf-8 -*-
"""MaaS 抽取适配器：re-export 李颖哲的 Collection V2 extract_article_to_events。

7月9日：stub（返回 list []）→ 适配 main 的真实实现（返回 dict）。

返回结构（dict，不再是 list）：
    {
        "status": "ok" | "no_activity" | "not_an_event" | "text_too_short" | "parse_error",
        "events":   [{"title","summary","start_time","end_time","location","source_url"}, ...],
        "warnings": [...],
        "error":    None | str,
        "used_fallback": bool,
    }

auto_collector.extract_and_map 负责解包 dict 并把 status 映射到 fail_reasons。
本模块只做透传，保留函数名以兼容 auto_collector 的 import。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# 加载项目根 .env，让 extract_article 的 os.getenv("MAAS_API_KEY") 可见
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

from experiments.agent_maas_cli.extract_article import (
    extract_article_to_events as _real_extract,
)

# 保留旧符号供外部探测
REQUIRED_METADATA = ("source_url", "source_name", "title", "publish_time")


def extract_article_to_events(
    article_text: str,
    metadata: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """透传到 experiments.agent_maas_cli.extract_article.extract_article_to_events。

    返回 dict（见模块 docstring）。kwargs 透传 base_url/model/api_key/timeout/reference_date。
    """
    return _real_extract(article_text, metadata, **kwargs)
