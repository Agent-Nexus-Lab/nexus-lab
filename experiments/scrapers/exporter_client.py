"""HTTP client for wechat-article-exporter local server (localhost:3000).

Usage:
    client = ExporterClient()
    auth_key = client.get_auth_key()
    fakeid = client.search_account(auth_key, "复旦天协")
    articles = client.get_article_list(auth_key, fakeid)
    for a in articles:
        content = client.download_article(a["link"])
        client.convert_to_text(content, output_dir)
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup


class ExporterError(Exception):
    """Raised when the exporter API returns an error."""


class ExporterClient:
    """HTTP client for the wechat-article-exporter local server.

    All methods that require authentication need a valid auth_key, obtained
    via get_auth_key() after the user has logged in at http://localhost:3000.
    """

    BASE_URL = "http://localhost:3000"
    DEBUG_KEY = "nexus-lab-debug"

    def __init__(self, base_url: str = BASE_URL, debug_key: str = DEBUG_KEY):
        self.base_url = base_url.rstrip("/")
        self.debug_key = debug_key

    # ── auth ────────────────────────────────────────────────────────

    def get_auth_key(self) -> str | None:
        """Extract auth-key from the server's in-memory CookieStore.

        Returns None if no active session exists (user hasn't logged in).
        """
        url = f"{self.base_url}/api/_debug?key={self.debug_key}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
            if data:
                return next(iter(data.keys()))
        except Exception:
            pass
        return None

    # ── search ──────────────────────────────────────────────────────

    def search_account(self, auth_key: str, keyword: str) -> dict | None:
        """Search for a WeChat public account by name.

        Returns account info dict (with 'fakeid', 'nickname', etc.) or None.
        """
        url = f"{self.base_url}/api/web/mp/searchbiz?keyword={urllib.parse.quote(keyword)}"
        req = urllib.request.Request(url, headers={"X-Auth-Key": auth_key})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        if data.get("base_resp", {}).get("ret") != 0:
            return None
        accounts = data.get("list", [])
        return accounts[0] if accounts else None

    # ── article list ────────────────────────────────────────────────

    def get_article_list(self, auth_key: str, fakeid: str, max_articles: int = 5) -> list[dict]:
        """Get article metadata list from appmsgpublish API."""
        url = (
            f"{self.base_url}/api/web/mp/appmsgpublish"
            f"?fakeid={fakeid}&size={max_articles}"
        )
        req = urllib.request.Request(url, headers={"X-Auth-Key": auth_key})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        if data.get("base_resp", {}).get("ret") != 0:
            return []

        publish_page = json.loads(data["publish_page"])
        articles = []
        for item in publish_page.get("publish_list", []):
            publish_info = json.loads(item["publish_info"])
            for a in publish_info.get("appmsgex", []):
                articles.append(a)

        return articles[:max_articles]

    # ── download ───────────────────────────────────────────────────

    @staticmethod
    def download_article(url: str) -> dict:
        """Download article content as structured JSON via the public API.

        No authentication required — this endpoint fetches the WeChat article
        page directly and parses the CGI data.
        """
        api_url = (
            f"{ExporterClient.BASE_URL}/api/public/v1/download"
            f"?url={urllib.parse.quote(url, safe='')}&format=json"
        )
        req = urllib.request.Request(api_url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    # ── convert ────────────────────────────────────────────────────

    @staticmethod
    def convert_to_text(data: dict, output_dir: Path) -> Path:
        """Convert API JSON response to pipeline text format and write to disk."""
        title = (data.get("title") or "").strip()
        account = (data.get("nick_name") or "").strip()
        author = data.get("author_name") or account
        create_time = data.get("create_time", "")
        source_url = data.get("link", "")
        html_content = data.get("content_noencode", "")
        body = _html_to_text(html_content)

        if not body.strip():
            body = data.get("desc", "")

        filename = _slugify(title) + ".txt"
        path = output_dir / filename

        lines = [
            f"account: {account}",
            f"title: {title}",
            f"author: {author}",
            f"date: {create_time}",
            f"source_url: {source_url}",
            "",
            body,
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path


# ── internal helpers ──────────────────────────────────────────────────


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all(["script", "style"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", "", html)


def _slugify(text: str) -> str:
    text = text.strip().replace("/", "_").replace("\\", "_")
    text = re.sub(r"[^\w一-鿿\-]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text[:60].strip("_")
