# -*- coding: utf-8 -*-
"""自动采集骨架：遍历 enabled 公众号 → cn8n 取文章 → 去重 → 待处理队列。

今天只做 dry-run（不调 cn8n、不写 DB、不依赖本地 wechat-article-exporter）。
7月5日 cn8n_client 落地后，dry_run=False 即可真实抓取。

CLI:
  python experiments/scrapers/auto_collector.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
DEFAULT_ACCOUNTS = _HERE / "account_list.json"


def load_enabled_accounts(path: Path | None = None) -> list[dict]:
    """读 account_list.json，过滤 enabled is True。"""
    p = path or DEFAULT_ACCOUNTS
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    return [a for a in accounts if a.get("enabled") is True]


def collect_account(account: dict, *, dry_run: bool = True) -> dict:
    """抓取单个账号文章列表。

    dry_run=True：不调 cn8n，返回空文章列表 + would_fetch 标记。
    dry_run=False：调 cn8n_client.get_wechat_history；cn8n 未落地时抛清晰错误。
    """
    if dry_run:
        return {"account": account.get("name"), "account_id": account.get("id"),
                "would_fetch": True, "articles": []}
    try:
        from experiments.scrapers.cn8n_client import get_wechat_history  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError(
            "cn8n_client 未实现（曹昕宇 7月4日 task 6），请用 --dry-run"
        ) from e
    articles = get_wechat_history(account.get("name"), page=1)
    return {"account": account.get("name"), "account_id": account.get("id"),
            "would_fetch": False, "articles": articles or []}


def dedupe_articles(articles: list[dict], seen_urls: set[str]) -> list[dict]:
    """按 url 去重，返回新文章（seen_urls 会被原地更新）。"""
    new: list[dict] = []
    for a in articles:
        url = a.get("url") or a.get("source_url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        new.append(a)
    return new


def run(dry_run: bool = True, accounts_path: Path | None = None) -> dict:
    """遍历 enabled 账号 → collect → dedupe → 累积待处理队列。"""
    accounts = load_enabled_accounts(accounts_path)
    seen_urls: set[str] = set()
    queue: list[dict] = []
    total_articles = 0
    per_account: list[dict] = []
    for acc in accounts:
        res = collect_account(acc, dry_run=dry_run)
        articles = res.get("articles", [])
        total_articles += len(articles)
        new = dedupe_articles(articles, seen_urls)
        queue.extend(new)
        per_account.append({
            "account": res.get("account"),
            "fetched": len(articles),
            "new": len(new),
        })
    return {
        "dry_run": dry_run,
        "scanned_accounts": len(accounts),
        "total_articles": total_articles,
        "new_articles": len(queue),
        "per_account": per_account,
        "queue": queue,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="自动采集骨架（dry-run 默认）")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="不调 cn8n，只统计账号")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                        help="真实抓取（需 cn8n_client 已落地）")
    parser.add_argument("--accounts", type=Path, default=None,
                        help="account_list.json 路径")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, accounts_path=args.accounts)

    out_path = _HERE / "auto_collector_dryrun.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    summary = {k: result[k] for k in
               ("dry_run", "scanned_accounts", "total_articles", "new_articles")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[written] {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
