# -*- coding: utf-8 -*-
"""自动采集：遍历 enabled 账号 → cn8n 取文章 → MaaS 提取 → schema_mapper → 入库。

三段接线，每段缺依赖则降级 + 记 warning：
  - 抓取段：cn8n_client 未落地 → 跳过真实抓取，articles=[]
  - 提取段：maas_extract 仍为 stub → extracted_events=[]（李颖哲替换后自动生效）
  - 入库段：database/import_events EventImportService 未落地 → 只输出 drafts 不写库

CLI：
  python experiments/scrapers/auto_collector.py --dry-run     # 默认，不写库
  python experiments/scrapers/auto_collector.py --commit      # 写库（需 EventImportService）
  python experiments/scrapers/auto_collector.py --no-dry-run  # 真实抓取（需 cn8n_client）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
DEFAULT_ACCOUNTS = _HERE / "account_list.json"

for _p in (str(_HERE.parent), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from experiments.scrapers.maas_extract import extract_article_to_events  # noqa: E402
from experiments.scrapers.schema_mapper import map_wechat_article_to_drafts  # noqa: E402


def load_enabled_accounts(path: Path | None = None) -> list[dict]:
    p = path or DEFAULT_ACCOUNTS
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    return [a for a in accounts if a.get("enabled") is True]


def _try_import_cn8n() -> tuple[object | None, str | None]:
    """返回 (module, error)；落地则 error=None。"""
    try:
        import experiments.scrapers.cn8n_client as mod  # noqa: PLC0415
        return mod, None
    except ImportError as e:
        return None, f"cn8n_client 未落地（曹昕宇 step 1）：{e}"


def _try_import_import_service() -> tuple[object | None, str | None]:
    """返回 (module, error)；EventImportService 落地则 error=None。"""
    try:
        import database.import_events as mod  # noqa: PLC0415
        # 检查是否有真正的批量入库函数（import_many / upsert_event）
        if hasattr(mod, "import_many") or hasattr(mod, "upsert_event"):
            return mod, None
        return None, "database.import_events 只有 import_events_from_json，缺 import_many/upsert_event（曹昕宇 step 4 未完成）"
    except ImportError as e:
        return None, f"database.import_events 未落地（曹昕宇 step 4）：{e}"


def collect_account(account: dict, *, dry_run: bool, cn8n_mod, warnings: list[str]) -> dict:
    """抓取单个账号文章列表。dry_run 或 cn8n 缺失 → articles=[]。"""
    if dry_run:
        return {"account": account.get("name"), "account_id": account.get("id"),
                "would_fetch": True, "articles": []}
    if cn8n_mod is None:
        return {"account": account.get("name"), "account_id": account.get("id"),
                "would_fetch": False, "articles": []}
    try:
        articles = cn8n_mod.get_wechat_history(account.get("name"), page=1) or []
    except Exception as e:  # noqa: BLE001
        warnings.append(f"抓取 {account.get('name')} 失败：{e}")
        articles = []
    return {"account": account.get("name"), "account_id": account.get("id"),
            "would_fetch": False, "articles": articles}


def extract_and_map(article: dict, *, cn8n_mod, warnings: list[str]) -> list[dict]:
    """对单篇文章：取正文 → MaaS 提取 → mapper → event drafts。

    cn8n 缺失则 text=None；maas_extract stub 返回 [] → drafts=[]。
    """
    metadata = {
        "source_platform": "wechat",
        "source_name": article.get("source_name") or article.get("account"),
        "source_url": article.get("source_url") or article.get("url"),
        "title": article.get("title"),
        "publish_time": article.get("publish_time"),
    }
    text = None
    if cn8n_mod is not None and hasattr(cn8n_mod, "get_article_detail_text"):
        try:
            text = cn8n_mod.get_article_detail_text(metadata["source_url"])
        except Exception as e:  # noqa: BLE001
            warnings.append(f"取正文失败 {metadata['source_url']}：{e}")
    try:
        events = extract_article_to_events(text or "", metadata) or []
    except Exception as e:  # noqa: BLE001
        warnings.append(f"提取失败 {metadata['source_url']}：{e}")
        events = []
    return map_wechat_article_to_drafts(article, events)


def dedupe_articles(articles: list[dict], seen_urls: set[str]) -> list[dict]:
    new: list[dict] = []
    for a in articles:
        url = a.get("url") or a.get("source_url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        new.append(a)
    return new


def run(dry_run: bool = True, commit: bool = False,
        accounts_path: Path | None = None) -> dict:
    accounts = load_enabled_accounts(accounts_path)
    warnings: list[str] = []

    cn8n_mod, cn8n_err = _try_import_cn8n()
    if cn8n_err and not dry_run:
        warnings.append(cn8n_err)
    import_mod, import_err = _try_import_import_service()
    if import_err and commit:
        warnings.append(import_err)

    seen_urls: set[str] = set()
    all_drafts: list[dict] = []
    total_articles = 0
    per_account: list[dict] = []
    for acc in accounts:
        res = collect_account(acc, dry_run=dry_run, cn8n_mod=cn8n_mod, warnings=warnings)
        articles = res.get("articles", [])
        total_articles += len(articles)
        new_articles = dedupe_articles(articles, seen_urls)
        account_drafts: list[dict] = []
        for art in new_articles:
            drafts = extract_and_map(art, cn8n_mod=cn8n_mod, warnings=warnings)
            account_drafts.extend(drafts)
        all_drafts.extend(account_drafts)
        per_account.append({
            "account": res.get("account"),
            "fetched": len(articles),
            "new_articles": len(new_articles),
            "event_drafts": len(account_drafts),
        })

    imported = 0
    if commit and import_mod is not None:
        try:
            if hasattr(import_mod, "import_many"):
                result = import_mod.import_many(all_drafts)
                imported = result.get("imported", 0) if isinstance(result, dict) else 0
            else:
                warnings.append("EventImportService 无 import_many，跳过写库")
        except Exception as e:  # noqa: BLE001
            warnings.append(f"入库失败：{e}")

    return {
        "dry_run": dry_run,
        "commit": commit,
        "scanned_accounts": len(accounts),
        "total_articles": total_articles,
        "new_articles": sum(p["new_articles"] for p in per_account),
        "extracted_event_drafts": len(all_drafts),
        "imported": imported,
        "per_account": per_account,
        "event_drafts": all_drafts,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="自动采集（dry-run 默认）")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="不抓取、不写库，只统计账号")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                        help="真实抓取（需 cn8n_client）")
    parser.add_argument("--commit", action="store_true", default=False,
                        help="写库（需 EventImportService）；默认只输出 drafts")
    parser.add_argument("--accounts", type=Path, default=None)
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, commit=args.commit, accounts_path=args.accounts)

    suffix = "commit" if args.commit else "dryrun"
    out_path = _HERE / f"auto_collector_{suffix}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    summary = {k: result[k] for k in
               ("dry_run", "commit", "scanned_accounts", "total_articles",
                "new_articles", "extracted_event_drafts", "imported", "warnings")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[written] {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
