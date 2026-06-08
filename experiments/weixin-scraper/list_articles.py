from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

SCRIPT_DIR = Path(__file__).resolve().parent

WECHAT_UA = (
    "Mozilla/5.0 (Linux; Android 12; Pixel 6) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.5359.128 "
    "Mobile Safari/537.36 MicroMessenger/8.0.42"
)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        result = asyncio.run(
            run(
                args.url,
                max_articles=args.max_articles,
                album_ids=args.album_ids,
                seed_urls=args.seed_urls,
                list_albums_only=args.list_albums,
                deep=args.deep,
                delay=args.delay,
            )
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.list_albums:
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for a in result:
                print(f"{a['album_name']}")
                print(f"  id={a['album_id']}  articles={a['article_count']}")
                if a.get("description"):
                    print(f"  {a['description']}")
                print()
        return 0

    articles = result
    if args.format == "json":
        print(json.dumps(articles, ensure_ascii=False, indent=2))
    elif args.format == "urls":
        for a in articles:
            print(a["url"])
    else:
        for a in articles:
            ct = a.get("create_time", 0)
            if ct > 10000000000:
                ct //= 1000
            if ct:
                try:
                    ts = datetime.fromtimestamp(ct, tz=timezone.utc).astimezone()
                    label = f"{ts:%Y-%m-%d}"
                except (OSError, ValueError):
                    label = str(a.get("create_time", ""))
            else:
                label = str(a.get("create_time", ""))
            print(f"{label}  {a['title']}")
            print(f"  {a['url']}")
            print()

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List articles from a WeChat public account via album discovery."
    )
    parser.add_argument("url", help="Any article URL from the target public account")
    parser.add_argument(
        "--max", type=int, default=0, dest="max_articles",
        help="Max articles to return (0 = unlimited)",
    )
    parser.add_argument(
        "--format", choices=["json", "text", "urls"], default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--album-ids", nargs="*", default=None,
        help="Specific album IDs to fetch (default: discover from article)",
    )
    parser.add_argument(
        "--list-albums", action="store_true",
        help="Only list album metadata, not articles",
    )
    parser.add_argument(
        "--seed-urls", nargs="*", default=None,
        help="Additional seed article URLs for multi-entry album discovery",
    )
    parser.add_argument(
        "--deep", action="store_true",
        help="Recursively discover albums across the full account",
    )
    parser.add_argument(
        "--delay", type=float, default=3.0,
        help="Delay between requests in deep mode (default: 3s)",
    )
    return parser.parse_args(argv)


async def run(
    article_url: str,
    max_articles: int = 0,
    album_ids: list[str] | None = None,
    seed_urls: list[str] | None = None,
    list_albums_only: bool = False,
    deep: bool = False,
    delay: float = 3.0,
) -> list[dict[str, Any]]:
    all_seeds = [article_url]
    if seed_urls:
        all_seeds.extend(seed_urls)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        context = await browser.new_context(user_agent=WECHAT_UA)
        page = await context.new_page()

        # Step 1: load first seed to extract __biz + account context
        await page.goto(all_seeds[0], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("#js_content", timeout=15000)
        html = await page.content()

        biz_match = re.search(r'var\s+biz\s*=\s*"([^"]+)"', html)
        if not biz_match:
            await browser.close()
            raise RuntimeError("could not extract __biz from article page")
        biz = biz_match.group(1)
        account_name = _account_name(html)

        # Step 2: discover album IDs from all seed articles
        if album_ids is None:
            album_ids = []
            for seed_url in all_seeds:
                if album_ids and seed_url == all_seeds[0]:
                    # Already loaded
                    ids = _discover_albums_from_html(html)
                else:
                    await asyncio.sleep(delay)
                    await page.goto(seed_url, wait_until="domcontentloaded", timeout=20000)
                    try:
                        await page.wait_for_selector("#js_content", timeout=10000)
                    except Exception:
                        pass
                    ids = _discover_albums_from_html(await page.content())

                for aid in ids:
                    if aid not in album_ids:
                        album_ids.append(aid)

            if not album_ids:
                await browser.close()
                raise RuntimeError("no album IDs found on any seed article")

        # Step 3: if deep, recursively discover more albums
        if deep:
            album_ids = await _deep_discover_albums(
                page, biz, album_ids, delay
            )

        # Step 4: fetch album metadata
        album_metas = await fetch_album_metas(page, biz, album_ids)

        if list_albums_only:
            await browser.close()
            return album_metas

        # Step 5: fetch articles from all albums
        all_articles: dict[str, dict[str, Any]] = {}
        album_name_map = {m["album_id"]: m["album_name"] for m in album_metas}

        for aid in album_ids:
            if max_articles and len(all_articles) >= max_articles:
                break
            for art in await fetch_album_articles(page, biz, aid):
                if max_articles and len(all_articles) >= max_articles:
                    break
                key = art.get("key", "") or f"{art.get('msgid','')}_{art.get('itemidx','')}"
                if key and key not in all_articles:
                    all_articles[key] = {
                        "title": art.get("title", ""),
                        "url": art.get("url", ""),
                        "create_time": int(art.get("create_time", "0")),
                        "msgid": art.get("msgid", ""),
                        "album_id": aid,
                        "album_name": album_name_map.get(aid, ""),
                    }

        name = _account_name(html)
        print(f"  {name}: {len(all_articles)} articles from {len(album_ids)} albums", file=sys.stderr)
        await browser.close()

    articles = sorted(all_articles.values(), key=lambda a: a.get("create_time", 0), reverse=True)
    if max_articles:
        articles = articles[:max_articles]
    return articles


# ── album discovery helpers ──────────────────────────────────────────

def _discover_albums_from_html(html: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"album_id[=/\"]+(\d+)", html)))


async def _deep_discover_albums(
    page, biz: str, seed_ids: list[str], delay: float,
) -> list[str]:
    """Recursively discover albums: get articles from known albums,
    visit their pages, check for new album IDs, repeat until no new albums."""
    all_ids = list(seed_ids)
    checked_albums: set[str] = set()
    round_num = 0

    while round_num < 5:
        round_num += 1
        # Find albums we haven't sampled from yet
        unchecked = [a for a in all_ids if a not in checked_albums]
        if not unchecked:
            break

        new_found_this_round = 0
        for aid in unchecked[:3]:  # sample up to 3 albums per round
            checked_albums.add(aid)
            # Get a few article URLs from this album
            sample_urls = await _sample_album_articles(page, biz, aid, count=5)
            for art_url in sample_urls:
                await asyncio.sleep(delay)
                try:
                    resp = await page.goto(art_url, wait_until="domcontentloaded", timeout=15000)
                    if not resp or resp.status != 200:
                        continue
                    await page.wait_for_timeout(1000)
                    html = await page.content()
                except Exception:
                    continue

                # Check this article for album IDs we haven't seen
                aids = _discover_albums_from_html(html)
                for new_aid in aids:
                    if new_aid not in all_ids:
                        all_ids.append(new_aid)
                        new_found_this_round += 1

        if new_found_this_round > 0:
            print(
                f"  deep round {round_num}: +{new_found_this_round} albums "
                f"(total {len(all_ids)})",
                file=sys.stderr,
            )
        else:
            break  # no new albums, done

    return all_ids


async def _sample_album_articles(
    page, biz: str, album_id: str, count: int = 5,
) -> list[str]:
    """Get a few article URLs from an album (first page)."""
    url = (
        f"https://mp.weixin.qq.com/mp/appmsgalbum?"
        f"action=getalbum&__biz={biz}&album_id={album_id}"
        f"&count={count}&f=json"
    )
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=10000)
        if resp and resp.status == 200:
            data = json.loads((await resp.body()).decode("utf-8", errors="replace"))
            return [
                a.get("url", "")
                for a in data.get("getalbum_resp", {}).get("article_list", [])
                if a.get("url")
            ]
    except Exception:
        pass
    return []


# ── album API helpers ─────────────────────────────────────────────────

async def fetch_album_metas(page, biz: str, album_ids: list[str]) -> list[dict[str, Any]]:
    metas = []
    for aid in album_ids:
        url = (
            f"https://mp.weixin.qq.com/mp/appmsgalbum?"
            f"action=getalbum&__biz={biz}&album_id={aid}&count=1&f=json"
        )
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        if not resp or resp.status != 200:
            continue
        data = json.loads((await resp.body()).decode("utf-8", errors="replace"))
        base = data.get("getalbum_resp", {}).get("base_info", {})
        metas.append({
            "album_id": aid,
            "album_name": base.get("title", ""),
            "article_count": base.get("article_count", ""),
            "description": base.get("description", ""),
        })
    return metas


async def fetch_album_articles(page, biz: str, album_id: str) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    begin_msgid = ""
    begin_itemidx = ""

    while True:
        url = (
            f"https://mp.weixin.qq.com/mp/appmsgalbum?"
            f"action=getalbum&__biz={biz}&album_id={album_id}"
            f"&count=10&begin_msgid={begin_msgid}&begin_itemidx={begin_itemidx}"
            f"&uin=&key=&pass_ticket=&wxtoken=&devicetype=&clientversion=&x5=0&f=json"
        )
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        if not resp or resp.status != 200:
            break

        data = json.loads((await resp.body()).decode("utf-8", errors="replace"))
        articles = data.get("getalbum_resp", {}).get("article_list", [])
        if not articles:
            break

        all_items.extend(articles)

        last = articles[-1]
        begin_msgid = str(last.get("msgid", ""))
        begin_itemidx = str(last.get("itemidx", ""))

        if len(articles) < 10:
            break

    return all_items


# ── simple helpers ────────────────────────────────────────────────────

def _account_name(html: str) -> str:
    m = re.search(r'var\s+user_name\s*=\s*"([^"]+)"', html)
    if m:
        return m.group(1)
    # Try the title element
    m = re.search(r"<title>([^<]+)</title>", html)
    return m.group(1).strip() if m else "?"


if __name__ == "__main__":
    raise SystemExit(main())
