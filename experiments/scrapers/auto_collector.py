# -*- coding: utf-8 -*-
"""自动采集：遍历 enabled 账号 → cn8n 取文章 → MaaS 提取 → mapper → event drafts。

三段接线，每段缺依赖则降级 + 记 warning：
  - 抓取段：cn8n_client 未落地 → 跳过真实抓取
  - 提取段：maas_extract 仍为 stub → extracted_events=[]（李颖哲替换后自动生效）
  - 入库段：EventImportService 未落地 → 只输出 drafts 不写库

正文 fallback：
  - get_article_detail_text 不可用 → 用 cn8n 返回的 digest 作为 article_text
  - digest 也为空 → 标记 "无正文可用"

CLI：
  python experiments/scrapers/auto_collector.py --dry-run     # 默认
  python experiments/scrapers/auto_collector.py --no-dry-run  # 真实抓取
  python experiments/scrapers/auto_collector.py --commit      # 写库（需 EventImportService）
  python experiments/scrapers/auto_collector.py --limit 3     # 只扫前 3 个账号

=== collection_cron 接线边界（7月7日确认，7月8日实现） ===

cron 触发路径：
    cron → auto_collector.run(dry_run=False, commit=True)
    与手动采集共用同一条 run()，不另写采集逻辑。

最小配置字段（需曹昕宇确认后端持久化）：
    enabled: bool              # 是否启用定时采集
    schedule: str              # cron 表达式，默认 "0 8,18 * * *"
    sources: list[str]         # 账号 id 列表，默认全部 enabled
    max_articles_per_source: int  # 单次每个账号最大文章数，默认 5
    timeout_seconds: int       # 单次采集总超时，默认 600

曹昕宇需提供：
    - 后端 cron 触发入口（如 APScheduler / Celery beat）
    - collection_logs 写入（batch_id / 触发时间 / 触发方式 / sources / 统计）
    - 入库时 collection_logs 更新（imported / skipped / error）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
DEFAULT_ACCOUNTS = _HERE / "account_list.json"
DEFAULT_LIMIT = 3  # 默认只扫前 3 个 enabled 账号，避免消耗 API 额度

for _p in (str(_HERE.parent), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from experiments.scrapers.maas_extract import extract_article_to_events  # noqa: E402
from experiments.scrapers.schema_mapper import (  # noqa: E402
    map_wechat_article_to_drafts,
    map_xiaohongshu_note_to_drafts,
)


def load_enabled_accounts(path: Path | None = None, limit: int = 0) -> list[dict]:
    p = path or DEFAULT_ACCOUNTS
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    enabled = [a for a in accounts if a.get("enabled") is True]
    if limit > 0:
        enabled = enabled[:limit]
    return enabled


def _try_import_cn8n() -> tuple[object | None, str | None]:
    try:
        import experiments.scrapers.cn8n_client as mod  # noqa: PLC0415
        return mod, None
    except ImportError as e:
        return None, f"cn8n_client 未落地: {e}"


def _try_import_import_service() -> tuple[object | None, str | None]:
    try:
        import database.import_events as mod  # noqa: PLC0415
        if hasattr(mod, "import_many") or hasattr(mod, "upsert_event"):
            return mod, None
        return None, "database.import_events 缺 import_many/upsert_event"
    except ImportError as e:
        return None, f"database.import_events 未落地: {e}"


def collect_account(account: dict, *, dry_run: bool, cn8n_mod,
                    warnings: list[str]) -> dict:
    if dry_run:
        return {"account": account.get("name"), "account_id": account.get("id"),
                "would_fetch": True, "articles": []}
    if cn8n_mod is None:
        return {"account": account.get("name"), "account_id": account.get("id"),
                "would_fetch": False, "articles": []}
    try:
        articles = cn8n_mod.get_wechat_history(account.get("name"), page=1) or []
    except Exception as e:  # noqa: BLE001
        warnings.append(f"抓取 {account.get('name')} 失败: {e}")
        articles = []
    # 注入 source_name（cn8n 返回的文章里不包含公众号名，但后续 MaaS 提取需要）
    acc_name = account.get("name", "")
    for a in articles:
        if not a.get("source_name"):
            a["source_name"] = acc_name
    return {"account": account.get("name"), "account_id": account.get("id"),
            "would_fetch": False, "articles": articles}


def _get_article_text(article_url: str, article: dict, cn8n_mod) -> tuple[str | None, str]:
    """获取文章正文，返回 (text, text_source)。

    优先级：cn8n detail_text > cn8n digest > None。
    text_source 为 "cn8n_detail" / "cn8n_digest" / "none"。
    """
    # 1) try get_article_detail_text
    if cn8n_mod is not None and hasattr(cn8n_mod, "get_article_detail_text"):
        try:
            text = cn8n_mod.get_article_detail_text(article_url)
            if text:
                return text, "cn8n_detail"
        except NotImplementedError:
            pass
        except Exception:
            pass
    # 2) fallback to digest
    digest = article.get("digest", "").strip()
    if digest:
        return digest, "cn8n_digest"
    return None, "none"


def extract_and_map(article: dict, *, cn8n_mod,
                    warnings: list[str]) -> tuple[list[dict], bool, str]:
    """单篇文章：取正文 → MaaS 提取 → mapper → (drafts, succeeded, reason)。

    Returns:
        drafts: 6-field event drafts 列表
        succeeded: True 如果成功产出至少 1 个 draft
        reason: 失败原因（成功时为空字符串）
    """
    metadata = {
        "source_name": article.get("source_name") or article.get("account"),
        "source_url": article.get("source_url") or article.get("url"),
        "title": article.get("title"),
        "publish_time": article.get("publish_time"),
    }
    source_url = metadata["source_url"]

    text, text_source = _get_article_text(source_url, article, cn8n_mod)
    if text is None:
        warnings.append(f"无正文可用: {source_url or '?'}")
        return [], False, "no_text"

    try:
        events = extract_article_to_events(text, metadata) or []
    except Exception as e:  # noqa: BLE001
        warnings.append(f"提取失败 {source_url}: {e}")
        return [], False, f"extract_error: {e}"

    if not events:
        return [], False, "no_events_extracted"

    drafts, map_warnings = map_wechat_article_to_drafts(article, events)
    if map_warnings:
        warnings.extend(map_warnings)
    if not drafts:
        return [], False, "mapper_produced_no_drafts"

    return drafts, True, ""


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
        accounts_path: Path | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    accounts = load_enabled_accounts(accounts_path, limit=limit)
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
    extracted_ok = 0
    extracted_fail = 0
    fail_reasons: dict[str, int] = {}
    per_account: list[dict] = []

    for acc in accounts:
        res = collect_account(acc, dry_run=dry_run, cn8n_mod=cn8n_mod,
                              warnings=warnings)
        articles = res.get("articles", [])
        total_articles += len(articles)
        new_articles = dedupe_articles(articles, seen_urls)
        account_drafts: list[dict] = []
        ok = fail = 0
        for art in new_articles:
            drafts, succeeded, reason = extract_and_map(
                art, cn8n_mod=cn8n_mod, warnings=warnings)
            account_drafts.extend(drafts)
            if succeeded:
                ok += 1
            else:
                fail += 1
                fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
        all_drafts.extend(account_drafts)
        extracted_ok += ok
        extracted_fail += fail
        per_account.append({
            "account": res.get("account"),
            "fetched": len(articles),
            "new_articles": len(new_articles),
            "extracted_ok": ok,
            "extracted_fail": fail,
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
            warnings.append(f"入库失败: {e}")

    return {
        "dry_run": dry_run,
        "commit": commit,
        "limit_accounts": limit,
        "scanned_accounts": len(accounts),
        "total_articles": total_articles,
        "new_articles": sum(p["new_articles"] for p in per_account),
        "extraction_summary": {
            "total_articles_processed": extracted_ok + extracted_fail,
            "extracted_ok": extracted_ok,
            "extracted_fail": extracted_fail,
            "fail_reasons": fail_reasons,
        },
        "extracted_event_drafts": len(all_drafts),
        "imported": imported,
        "per_account": per_account,
        "event_drafts": all_drafts,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="自动采集（dry-run 默认）")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    parser.add_argument("--commit", action="store_true", default=False)
    parser.add_argument("--accounts", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"限制扫描账号数（默认 {DEFAULT_LIMIT}，0=不限）")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, commit=args.commit,
                 accounts_path=args.accounts, limit=args.limit)

    suffix = "commit" if args.commit else "dryrun"
    out_path = _HERE / f"auto_collector_{suffix}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    summary_keys = ("dry_run", "commit", "scanned_accounts", "total_articles",
                    "new_articles", "extraction_summary",
                    "extracted_event_drafts", "imported", "warnings")
    summary = {k: result[k] for k in summary_keys}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[written] {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
