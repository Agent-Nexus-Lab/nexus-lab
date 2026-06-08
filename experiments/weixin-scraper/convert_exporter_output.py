"""
将 wechat-article-exporter 导出的 JSON 文件转换为 MaaS 管道期望的文本格式。

用法:
    python convert_exporter_output.py <exported.json> [--output-dir <dir>] [--dry-run]

输入: wechat-article-exporter Web UI 导出的 JSON 文件（需勾选"包含正文内容"）
      JSON 结构: Array<ExcelExportEntity>

输出: 每篇文章一个 .txt 文件，格式:
    account: <公众号名称>
    title: <文章标题>
    author: <作者>
    date: <发布日期>
    source_url: <文章URL>

    <正文纯文本>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR.parent / "agent_maas_cli" / "texts"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw = json.loads(Path(args.input_file).read_text(encoding="utf-8"))
    articles = raw if isinstance(raw, list) else raw.get("articles", raw.get("data", []))

    if not articles:
        print("error: no articles found in input file", file=sys.stderr)
        return 2

    converted = 0
    skipped = 0
    for article in articles:
        result = convert_article(article)
        if result is None:
            skipped += 1
            continue

        filename = slugify(result["title"]) + ".txt"
        output_path = output_dir / filename

        if args.dry_run:
            print(f"[dry-run] would write: {output_path}")
            print(f"  account={result['account']}, title={result['title']}")
            converted += 1
            continue

        write_output(output_path, result)
        print(f"wrote: {output_path}")
        converted += 1

    print(f"\nconverted: {converted}, skipped: {skipped}, total: {len(articles)}", file=sys.stderr)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert wechat-article-exporter JSON export to pipeline text format."
    )
    parser.add_argument("input_file", help="Path to the exported JSON file")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview conversion without writing files",
    )
    return parser.parse_args(argv)


def convert_article(article: dict) -> dict[str, str] | None:
    """Convert a single exporter article dict to pipeline text dict.

    Returns None if the article should be skipped (e.g., no title).
    """
    # ── extract fields from exporter JSON ──────────────────────────
    title = (article.get("title") or "").strip()
    if not title:
        return None

    account = (
        article.get("_accountName")
        or article.get("nick_name")
        or article.get("nickname")
        or ""
    ).strip()

    author = (article.get("author_name") or account or "").strip()

    source_url = (article.get("link") or article.get("url") or "").strip()

    # date: prefer create_time (unix timestamp), fallback to update_time
    ts = article.get("create_time") or article.get("update_time") or 0
    date_str = format_timestamp(ts)

    # content: rendered plain text from the exporter
    content = article.get("content") or article.get("digest") or ""

    # If content comes from renderTextFromCgiDataNew, it's "title\n\ntext"
    # Strip the leading title line if it duplicates the article title
    content = strip_leading_title(content, title)

    # If content is HTML (from digest or fallback), convert to plain text
    if looks_like_html(content):
        content = html_to_text(content)

    if not content.strip():
        content = "(正文为空或未勾选导出时包含正文内容)"

    return {
        "title": title,
        "account": account,
        "author": author,
        "date": date_str,
        "source_url": source_url,
        "body": content,
    }


# ── helpers ─────────────────────────────────────────────────────────────


def format_timestamp(ts: int) -> str:
    """Convert unix timestamp to human-readable date string."""
    if not ts:
        return ""
    try:
        if ts > 10000000000:  # milliseconds
            ts //= 1000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        return f"{dt.year}年{dt.month}月{dt.day}日 {dt.hour:02d}:{dt.minute:02d}"
    except (OSError, ValueError):
        return str(ts)


def strip_leading_title(content: str, title: str) -> str:
    """Remove the leading title line if it matches the article title.

    The exporter's renderTextFromCgiDataNew() prepends "title\n\n" to content.
    """
    if not content or not title:
        return content
    lines = content.splitlines()
    if lines and lines[0].strip() == title.strip():
        return "\n".join(lines[1:]).strip()
    return content


def looks_like_html(text: str) -> bool:
    """Heuristic check if text looks like HTML."""
    return bool(re.search(r"<\s*(p|div|span|section|br|img|a|h\d)\b", text, re.IGNORECASE))


def html_to_text(html: str) -> str:
    """Convert HTML to plain text using BeautifulSoup."""
    try:
        soup = BeautifulSoup(html, "lxml")
        # Remove script and style elements
        for tag in soup.find_all(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text
    except Exception:
        # If parsing fails, do a simple tag strip
        return re.sub(r"<[^>]+>", "", html)


def write_output(path: Path, result: dict[str, str]) -> None:
    lines = [
        f"account: {result['account']}",
        f"title: {result['title']}",
        f"author: {result['author']}",
        f"date: {result['date']}",
        f"source_url: {result['source_url']}",
        "",
        result["body"],
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def slugify(text: str) -> str:
    text = text.strip().replace("/", "_").replace("\\", "_")
    text = re.sub(r"[^\w一-鿿\-]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text[:60].strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
