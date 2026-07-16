# -*- coding: utf-8 -*-
"""cn8n API 客户端：微信公众号文章正文 + 小红书搜索。

API key 从环境变量 CN8N_API_KEY 读取。
Base URL: http://api.cn8n.com
认证方式: Authorization: Bearer <API-KEY>

已实现：
  - get_wechat_history(account, page)    → 公众号历史文章（分页）
  - get_wechat_today(account)            → 公众号今日文章
  - get_article_detail_text(article_url) → 文章详情正文（HTML 转纯文本）
  - search_wechat_articles(keyword, page)→ 搜索公众号文章（待 cn8n 补充文档）
  - search_xiaohongshu(keyword, page)    → 小红书搜索笔记
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

# 自动加载项目根目录的 .env
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass

CN8N_BASE_URL = os.getenv("CN8N_BASE_URL", "http://api.cn8n.com").rstrip("/")
TIMEOUT = 30
MAX_RETRIES = 2


def _api_key() -> str:
    key = os.getenv("CN8N_API_KEY")
    if not key:
        raise RuntimeError(
            "CN8N_API_KEY 未设置。请在 .env 中添加 CN8N_API_KEY=your-key "
            "或设置环境变量。"
        )
    return key


class Cn8nError(RuntimeError):
    """cn8n API 统一错误。"""

    def __init__(self, message: str, *, code: str | None = None,
                 cn8n_message: str | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.cn8n_message = cn8n_message
        self.retryable = retryable


def _post(path: str, body: dict[str, Any], timeout: int = TIMEOUT) -> dict[str, Any]:
    """统一 POST 请求封装：超时 + 重试 + 统一错误格式。"""
    url = f"{CN8N_BASE_URL}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    last_err: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={
                    "Authorization": f"Bearer {_api_key()}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            if e.code in {408, 429, 500, 502, 503, 504} and attempt < MAX_RETRIES:
                last_err = e
                time.sleep(1.0 * (attempt + 1))
                continue
            raise Cn8nError(
                f"cn8n HTTP {e.code}: {body_text[:300]}",
                code=str(e.code),
                cn8n_message=body_text[:300],
                retryable=e.code in {408, 429, 500, 502, 503, 504},
            ) from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise Cn8nError(
                f"cn8n 网络错误（已重试 {MAX_RETRIES} 次）: {e}",
                retryable=True,
            ) from e

    if result.get("code") is not None and result.get("code") != 0:
        raise Cn8nError(
            f"cn8n 业务错误 code={result['code']}: {result.get('message', '')}",
            code=str(result["code"]),
            cn8n_message=str(result.get("message", "")),
        )
    return result


def _normalize_article(raw: dict[str, Any]) -> dict[str, Any]:
    """将 cn8n 返回的文章原始字段标准化为 auto_collector 期望的格式。"""
    return {
        "title": raw.get("title", ""),
        "url": raw.get("url") or raw.get("ContentUrl", ""),
        "publish_time": raw.get("post_time_str", ""),
        "publish_timestamp": raw.get("post_time") or raw.get("send_time"),
        "digest": raw.get("digest", ""),
        "cover_url": raw.get("cover_url", ""),
        "appmsgid": raw.get("appmsgid"),
        "source_name": raw.get("source_name", ""),
    }


def _extract_articles(result: dict[str, Any]) -> list[dict[str, Any]]:
    """从 cn8n 响应中提取文章列表（兼容 post_history 和 post_condition）。"""
    data = result.get("data", {})
    inner = data.get("result", {})
    articles_raw = inner.get("data", [])
    if not isinstance(articles_raw, list):
        return []
    return [_normalize_article(a) for a in articles_raw]


# ---------------------------------------------------------------------------
# 微信公众号
# ---------------------------------------------------------------------------

def get_wechat_history(account: str, page: int = 1) -> list[dict[str, Any]]:
    """获取公众号历史文章（分页，每页 5 次发文）。

    Args:
        account: 公众号名称或微信号。
        page: 页码，默认 1。

    Returns:
        标准化文章列表 [{title, url, publish_time, digest, cover_url, ...}]。
    """
    result = _post("/p4/fbmain/monitor/v3/post_history", {
        "name": account,
        "page": str(page),
    })
    return _extract_articles(result)


def get_wechat_today(account: str) -> list[dict[str, Any]]:
    """获取公众号今日文章（无分页，最多 20 次发文）。

    Args:
        account: 公众号名称或微信号。

    Returns:
        标准化文章列表。如果当天未发文，返回空列表（不报错）。
    """
    result = _post("/p4/fbmain/monitor/v3/post_condition", {
        "name": account,
    })
    return _extract_articles(result)


def get_article_detail_text(article_url: str) -> str:
    """获取微信公众号文章正文内容。

    cn8n 的 article_html 接口返回完整文章 HTML；这里在采集边界统一转成
    纯文本，避免把 HTML 标签直接交给 MaaS。正文接口失败时由
    auto_collector 继续按现有契约回退到 digest。

    Args:
        article_url: 文章链接。

    Returns:
        文章正文纯文本。
    """
    result = _post("/p4/fbmain/monitor/v3/article_html", {"url": article_url})
    data = result.get("data", {})
    payload = data.get("result", {}) if isinstance(data, dict) else {}
    html = payload.get("html", "") if isinstance(payload, dict) else ""
    if not isinstance(html, str) or not html.strip():
        raise Cn8nError("cn8n article_html 响应不含正文 html")

    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "noscript", "svg"]):
        tag.decompose()
    candidates = [soup.select_one("#js_content"), soup.select_one("article"), soup.body, soup]
    for content in candidates:
        if content is None:
            continue
        text = content.get_text(separator="\n", strip=True)
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if text:
            return text
    return ""


def search_wechat_articles(keyword: str, page: int = 1) -> list[dict[str, Any]]:
    """搜索微信公众号文章。

    当前 cn8n Apifox 文档未覆盖此接口。待补充后实现。

    Args:
        keyword: 搜索关键词。
        page: 页码，默认 1。
    """
    raise NotImplementedError(
        "cn8n 微信文章搜索接口待文档补充。"
        "当前 Apifox 文档（xzudd7pp08）中未见此端点。"
    )


# ---------------------------------------------------------------------------
# 小红书
# ---------------------------------------------------------------------------

def search_xiaohongshu(
    keyword: str,
    page: int = 1,
    sort: str = "最新",
    note_time: str = "一周内",
    note_type: str = "不限",
) -> list[dict[str, Any]]:
    """小红书搜索笔记。

    Args:
        keyword: 搜索关键词。
        page: 页码。
        sort: 排序方式（综合/最新/最多点赞/最多评论/最多收藏）。
        note_time: 时间范围（不限/一天内/一周内/一个月内/半年内）。
        note_type: 笔记类型（不限/视频笔记/普通笔记）。

    Returns:
        笔记列表，每项含 id/title/desc/user/timestamp/images_list 等。
    """
    result = _post("/p2/xhs/search_note_app", {
        "keyword": keyword,
        "page": page,
        "sort": sort,
        "note_time": note_time,
        "note_type": note_type,
    })
    data = result.get("data", {})
    items = data.get("result", [])
    if not isinstance(items, list):
        return []
    notes: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and "note" in item:
            notes.append(item["note"])
        elif isinstance(item, dict):
            notes.append(item)
    return notes
