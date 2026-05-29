from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR.parent / "agent-maas-cli" / "texts"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = asyncio.run(fetch_article(args.url, timeout=args.timeout))
    except Exception as exc:
        print(f"scrape failed: {exc}", file=sys.stderr)
        return 2

    filename = slugify(result["title"]) + ".txt"
    output_path = output_dir / filename
    write_output(output_path, result)
    print(f"saved: {output_path}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a WeChat public account article and save as text."
    )
    parser.add_argument("url", help="WeChat article URL")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory (default: ../agent-maas-cli/texts)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="Page load timeout in seconds (default: 30)",
    )
    return parser.parse_args(argv)


async def fetch_article(url: str, timeout: float = 30) -> dict[str, str]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        page = await browser.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            await page.wait_for_selector("#js_content", timeout=timeout * 1000)
            html = await page.content()

            soup = BeautifulSoup(html, "lxml")

            title_el = soup.select_one("#activity-name")
            title = title_el.get_text(strip=True) if title_el else "Untitled"

            author_el = soup.select_one("#js_author_name")
            author = author_el.get_text(strip=True) if author_el else ""

            account_el = soup.select_one("#js_name")
            account = account_el.get_text(strip=True) if account_el else author

            pub_el = soup.select_one("#publish_time")
            pub_date = pub_el.get_text(strip=True) if pub_el else ""

            content_el = soup.select_one("#js_content")
            if content_el:
                for tag in content_el.find_all(["script", "style"]):
                    tag.decompose()
                body = content_el.get_text(separator="\n", strip=True)
            else:
                body = "[content extraction failed]"

            return {
                "title": title,
                "account": account,
                "author": author,
                "date": pub_date,
                "url": url,
                "body": body,
            }
        finally:
            await browser.close()


def write_output(path: Path, result: dict[str, str]) -> None:
    lines = [
        f"account: {result['account']}",
        f"title: {result['title']}",
        f"author: {result.get('author', '')}",
        f"date: {result['date']}",
        f"source_url: {result['url']}",
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
