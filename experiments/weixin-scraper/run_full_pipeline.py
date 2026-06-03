"""
端到端自动化脚本：wechat-article-exporter → 文本转换 → MaaS 抽取 → 验证

用法:
    python run_full_pipeline.py --keyword "复旦天协" [--max-articles 5] [--run-extraction]

流程:
    1. 通过 exporter 认证 API 搜索公众号 → 获取文章列表
    2. 下载每篇文章的 JSON 内容
    3. 转换为管道文本格式
    4. (可选) 运行 MaaS 抽取管道
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
TEXTS_DIR = SCRIPT_DIR.parent / "agent-maas-cli" / "texts"
OUTPUT_DIR = SCRIPT_DIR.parent / "agent-maas-cli" / "outputs"
EXPORTER_BASE = "http://localhost:3000"
DEBUG_KEY = "nexus-lab-debug"


def main() -> int:
    args = parse_args()

    # 1. 获取 auth-key
    auth_key = get_auth_key()
    if not auth_key:
        print("ERROR: No active session. Please login at http://localhost:3000 first.", file=sys.stderr)
        return 2
    print(f"[1/5] Auth key: {auth_key[:12]}...", file=sys.stderr)

    # 2. 搜索公众号
    fakeid = search_account(auth_key, args.keyword)
    if not fakeid:
        print(f"ERROR: Account '{args.keyword}' not found", file=sys.stderr)
        return 2
    print(f"[2/5] Found account: {args.keyword} (fakeid={fakeid})", file=sys.stderr)

    # 3. 获取文章列表
    articles = get_article_list(auth_key, fakeid, max_articles=args.max_articles)
    if not articles:
        print("ERROR: No articles found", file=sys.stderr)
        return 2
    print(f"[3/5] Got {len(articles)} articles", file=sys.stderr)

    # 4. 下载内容并转换为管道文本
    TEXTS_DIR.mkdir(parents=True, exist_ok=True)
    converted = 0
    for i, article in enumerate(articles, 1):
        url = article["link"]
        title = article.get("title", "Untitled")
        try:
            if args.skip_existing and any(
                (TEXTS_DIR / (slugify(title) + ext)).exists()
                for ext in (".txt", ".md")
            ):
                print(f"  [{i}/{len(articles)}] SKIP (exists): {title[:50]}", file=sys.stderr)
                converted += 1
                continue

            print(f"  [{i}/{len(articles)}] downloading: {title[:50]}...", file=sys.stderr)
            content_json = download_article_json(url)
            text_path = convert_to_text(content_json, TEXTS_DIR)
            print(f"    -> {text_path.name}", file=sys.stderr)
            converted += 1
            time.sleep(1)  # polite delay
        except Exception as exc:
            print(f"    -> ERROR: {exc}", file=sys.stderr)

    print(f"[4/5] Converted {converted}/{len(articles)} articles", file=sys.stderr)

    # 5. 运行 MaaS 抽取
    if args.run_extraction and converted > 0:
        print(f"[5/5] Running MaaS extraction...", file=sys.stderr)
        run_maas_extraction()
    else:
        print(f"[5/5] MaaS extraction skipped (use --run-extraction to enable)", file=sys.stderr)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Full pipeline: exporter → text → MaaS extraction")
    parser.add_argument("--keyword", default="复旦天协", help="Account name to search (default: 复旦天协)")
    parser.add_argument("--max-articles", type=int, default=5, help="Max articles to fetch (default: 5)")
    parser.add_argument("--run-extraction", action="store_true", help="Run MaaS extraction after conversion")
    parser.add_argument("--skip-existing", action="store_true", default=True, help="Skip already-converted files")
    return parser.parse_args()


# ── auth ─────────────────────────────────────────────────────────────────


def get_auth_key() -> str | None:
    """Extract auth-key from CookieStore via debug endpoint."""
    try:
        url = f"{EXPORTER_BASE}/api/_debug?key={DEBUG_KEY}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        if data:
            return next(iter(data.keys()))
    except Exception:
        pass
    return None


# ── search ───────────────────────────────────────────────────────────────


def search_account(auth_key: str, keyword: str) -> str | None:
    """Search for a WeChat public account by name. Returns fakeid."""
    encoded = urllib.parse.quote(keyword)
    url = f"{EXPORTER_BASE}/api/web/mp/searchbiz?keyword={encoded}"
    req = urllib.request.Request(url, headers={"X-Auth-Key": auth_key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    if data.get("base_resp", {}).get("ret") == 0:
        accounts = data.get("list", [])
        if accounts:
            return accounts[0]["fakeid"]
    return None


# ── article list ────────────────────────────────────────────────────────


def get_article_list(auth_key: str, fakeid: str, max_articles: int = 5) -> list[dict]:
    """Get article list from appmsgpublish API."""
    url = f"{EXPORTER_BASE}/api/web/mp/appmsgpublish?fakeid={fakeid}&size={max_articles}"
    req = urllib.request.Request(url, headers={"X-Auth-Key": auth_key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    if data.get("base_resp", {}).get("ret") != 0:
        return []

    # Parse nested publish_page JSON
    publish_page = json.loads(data["publish_page"])
    articles = []
    for item in publish_page.get("publish_list", []):
        publish_info = json.loads(item["publish_info"])
        for a in publish_info.get("appmsgex", []):
            articles.append(a)

    return articles[:max_articles]


# ── download ────────────────────────────────────────────────────────────


def download_article_json(url: str) -> dict:
    """Download article content as JSON via public API endpoint."""
    api_url = f"{EXPORTER_BASE}/api/public/v1/download?url={urllib.parse.quote(url, safe='')}&format=json"
    req = urllib.request.Request(api_url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# ── convert ─────────────────────────────────────────────────────────────


def convert_to_text(data: dict, output_dir: Path) -> Path:
    """Convert API JSON response to pipeline text format."""
    title = data.get("title", "").strip()
    account = data.get("nick_name", "").strip()
    author = data.get("author_name", "") or account
    create_time = data.get("create_time", "")
    source_url = data.get("link", "")

    # Extract plain text from content_noencode (HTML)
    html_content = data.get("content_noencode", "")
    body = html_to_text(html_content)

    # If no content, try description
    if not body.strip():
        body = data.get("desc", "")

    filename = slugify(title) + ".txt"
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


def html_to_text(html: str) -> str:
    """Convert HTML content to plain text."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text
    except Exception:
        return re.sub(r"<[^>]+>", "", html)


def slugify(text: str) -> str:
    text = text.strip().replace("/", "_").replace("\\", "_")
    text = re.sub(r"[^\w一-鿿\-]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text[:60].strip("_")


# ── MaaS extraction ─────────────────────────────────────────────────────


def run_maas_extraction() -> None:
    """Run the MaaS CLI batch extraction."""
    cli_path = SCRIPT_DIR.parent / "agent-maas-cli" / "cli.py"
    result = subprocess.run(
        [sys.executable, str(cli_path), "--input-dir", str(TEXTS_DIR),
         "--write-output", "--incremental"],
        cwd=str(cli_path.parent),
        timeout=300,
    )
    if result.returncode != 0:
        print("MaaS extraction returned non-zero exit code", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
