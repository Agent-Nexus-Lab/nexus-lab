# -*- coding: utf-8 -*-
"""查询向量生成（OpenAI 兼容 /embeddings 端点）。

供 plan_service 在 parse_intent 后生成 query_embedding，写入 Intent.query_embedding，
使 scoring.score_interest_match 走语义路径。昕宇侧 Event.summary_embedding 须用同模型生成。

env 配置：
  EMBEDDING_BASE_URL  默认读 MAAS_BASE_URL
  EMBEDDING_API_KEY   默认读 MAAS_API_KEY
  EMBEDDING_MODEL     模型名（如 bge-m3、text-embedding-3-small），需与 Event.summary_embedding 同模型

未配置或调用失败时返回 []，上层自动降级到 keyword_fallback（见 scoring.py）。
"""
from __future__ import annotations

import os
from typing import Any

try:
    import requests  # noqa: F401
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]


DEFAULT_TIMEOUT = 15.0


def _resolve_config(base_url: str | None, api_key: str | None, model: str | None) -> tuple[str | None, str | None, str | None]:
    base = (base_url or os.getenv("EMBEDDING_BASE_URL") or os.getenv("MAAS_BASE_URL"))
    key = (api_key or os.getenv("EMBEDDING_API_KEY") or os.getenv("MAAS_API_KEY"))
    mdl = (model or os.getenv("EMBEDDING_MODEL"))
    return (base or None), (key or None), (mdl or None)


def generate_query_embedding(
    intent_text: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
) -> tuple[list[float], str | None]:
    """把 intent_text 编码为向量。

    Returns (embedding, model_name)：
      - 成功：(vector, model)
      - 未配置/失败/requests 缺失：([], None)，上层走 keyword fallback
    """
    if not intent_text or requests is None:
        return [], None
    base, key, mdl = _resolve_config(base_url, api_key, model)
    if not (base and key and mdl):
        return [], None
    url = f"{base.rstrip('/')}/embeddings"
    try:
        resp = requests.post(
            url,
            json={"input": intent_text, "model": mdl},
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            timeout=timeout or DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            return [], mdl
        data: Any = resp.json()
        emb = (data.get("data") or [{}])[0].get("embedding")
        if isinstance(emb, list) and emb:
            return [float(x) for x in emb], mdl
        return [], mdl
    except Exception:  # noqa: BLE001
        return [], mdl
