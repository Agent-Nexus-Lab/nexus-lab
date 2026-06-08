"""
集成脚本：通过 wechat-article-exporter 公网下载端点获取文章，转换后喂入 MaaS 管道。

用法:
    python fetch_via_exporter.py --url-file <urls.txt> [--output-dir <dir>] [--run-extraction]

输入: 每行一个微信文章 URL 的文本文件
流程: URL → 公网下载端点(HTML) → 提取元数据+正文 → 转管道文本 → MaaS 抽取(可选)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR.parent / "agent-maas-cli" / "texts"
EXPORTER_BASE = "http://localhost:3000"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    urls = read_urls(args)
    if not urls:
        print("error: no URLs provided", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] fetching: {url[:80]}...", file=sys.stderr)
        try:
            html = download_article(url)
            article = parse_article_html(html, url)
            text_path = write_pipeline_text(article, output_dir)
            results.append({"url": url, "status": "ok", "file": str(text_path)})
            print(f"  -> {text_path.name}", file=sys.stderr)
        except Exception as exc:
            results.append({"url": url, "status": "error", "error": str(exc)})
            print(f"  -> ERROR: {exc}", file=sys.stderr)

    ok = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] != "ok")
    print(f"\ndone: {ok} ok, {err} errors", file=sys.stderr)

    # optionally run MaaS extraction
    if args.run_extraction and ok > 0:
        print("\n--- running MaaS extraction ---", file=sys.stderr)
        run_maas_extraction(output_dir)

    return 0 if err == 0 else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch WeChat articles via exporter public API and prepare for MaaS pipeline."
    )
    parser.add_argument("--urls", nargs="*", help="Article URLs to fetch")
    parser.add_argument("--url-file", help="File with one URL per line")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--run-extraction",
        action="store_true",
        help="Run MaaS extraction after fetching",
    )
    return parser.parse_args(argv)


def read_urls(args: argparse.Namespace) -> list[str]:
    urls = []
    if args.urls:
        urls.extend(args.urls)
    if args.url_file:
        content = Path(args.url_file).read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


# ── download via exporter public API ────────────────────────────────────


def download_article(url: str, timeout: int = 30) -> str:
    """Fetch article HTML via exporter's public download endpoint (no auth needed)."""
    api_url = f"{EXPORTER_BASE}/api/public/v1/download?url={urllib.parse.quote(url, safe='')}&format=html"
    req = urllib.request.Request(api_url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ── parse article HTML ──────────────────────────────────────────────────


def parse_article_html(html: str, source_url: str) -> dict[str, str]:
    """Extract metadata and body text from the exporter's normalized HTML output."""
    soup = BeautifulSoup(html, "lxml")

    title = ""
    title_el = soup.select_one("h1.title")
    if title_el:
        title = title_el.get_text(strip=True)

    author = ""
    account = ""
    meta_el = soup.select_one(".__meta__")
    if meta_el:
        author_el = meta_el.select_one(".author")
        if author_el:
            author = author_el.get_text(strip=True)
        nick_el = meta_el.select_one(".nick_name")
        if nick_el:
            account = nick_el.get_text(strip=True)

    # body text from the content section
    body_parts = []
    content_el = soup.select_one(".text_content") or soup.select_one(".__page_content__")
    if content_el:
        # remove script/style tags
        for tag in content_el.find_all(["script", "style"]):
            tag.decompose()
        text = content_el.get_text(separator="\n", strip=True)
        body_parts.append(text)

    # also try item_show_type sections
    for section in soup.select("section[class*='item_show_type']"):
        for tag in section.find_all(["script", "style"]):
            tag.decompose()
        text = section.get_text(separator="\n", strip=True)
        if text:
            body_parts.append(text)

    body = "\n\n".join(body_parts)

    # fallback: extract all text from the page content
    if not body.strip():
        page = soup.select_one("#page-content") or soup.select_one(".__page_content__") or soup
        for tag in page.find_all(["script", "style"]):
            tag.decompose()
        body = page.get_text(separator="\n", strip=True)

    return {
        "title": title or "Untitled",
        "account": account or "",
        "author": author or account or "",
        "date": "",  # exporter HTML doesn't always include date
        "source_url": source_url,
        "body": body,
    }


# ── write pipeline text format ──────────────────────────────────────────


def write_pipeline_text(article: dict[str, str], output_dir: Path) -> Path:
    filename = slugify(article["title"]) + ".txt"
    path = output_dir / filename
    lines = [
        f"account: {article['account']}",
        f"title: {article['title']}",
        f"author: {article['author']}",
        f"date: {article['date']}",
        f"source_url: {article['source_url']}",
        "",
        article["body"],
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def slugify(text: str) -> str:
    text = text.strip().replace("/", "_").replace("\\", "_")
    text = re.sub(r"[^\w一-鿿\-]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text[:60].strip("_")


# ── MaaS extraction ────────────────────────────────────────────────────


def run_maas_extraction(texts_dir: Path) -> None:
    import subprocess

    cli_path = SCRIPT_DIR.parent / "agent-maas-cli" / "cli.py"
    result = subprocess.run(
        [sys.executable, str(cli_path), "--input-dir", str(texts_dir),
         "--write-output", "--incremental"],
        capture_output=False,
        timeout=300,
    )
    if result.returncode != 0:
        print("MaaS extraction failed", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
