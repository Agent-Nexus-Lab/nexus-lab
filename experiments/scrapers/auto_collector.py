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
import uuid
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
DEFAULT_ACCOUNTS = _HERE / "account_list.json"
EVENTS_JSON = _REPO_ROOT / "database" / "events.json"
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


SAMPLES_DIR = _HERE.parent / "agent_maas_cli" / "samples"


def load_sample_articles() -> list[dict]:
    """读 5 篇本地样例文章为 article dicts（含全文 body，供 extract 使用）。

    样例头部 `key: value` 行，空行后为正文。source_url 缺失时用 sample://<stem>。
    """
    articles: list[dict] = []
    for path in sorted(SAMPLES_DIR.glob("sample_*.txt")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        meta: dict[str, str] = {}
        i = 0
        for i, line in enumerate(lines):
            if not line.strip():
                break
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        body = "\n".join(lines[i + 1:]).strip()
        url = meta.get("source_url", f"sample://{path.stem}")
        articles.append({
            "title": meta.get("title", path.stem),
            "source_url": url,
            "url": url,
            "source_name": meta.get("account", "李颖哲样例"),
            "publish_time": meta.get("date", ""),
            "digest": body,  # 正文走 digest 字段，_get_article_text 会取到
        })
    return articles


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

    # Collection V2 返回 dict {status, events, warnings, error, used_fallback}
    try:
        result = extract_article_to_events(text, metadata)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"提取异常 {source_url}: {e}")
        return [], False, f"extract_error: {e}"

    if not isinstance(result, dict):
        # 兼容旧 list 返回（不应出现，但防御）
        events = result or []
        status, ext_warnings, error, used_fallback = "ok", [], None, False
    else:
        status = result.get("status", "ok")
        events = result.get("events") or []
        ext_warnings = result.get("warnings") or []
        error = result.get("error")
        used_fallback = result.get("used_fallback", False)

    # status → reason 映射。
    # no_activity / not_an_event / text_too_short 是正常业务结果，不是代码失败，
    # 只计入 fail_reasons，不进 warnings 当错误。
    if status == "parse_error":
        warnings.append(f"提取失败 {source_url}: {error or 'parse_error'}")
        return [], False, f"extract_error: {error or 'parse_error'}"
    if status == "text_too_short":
        return [], False, "text_too_short"
    if status == "not_an_event":
        return [], False, "not_an_event"
    if not events:
        # ok 但无 events，或 no_activity
        return [], False, "no_activity"

    drafts, map_warnings = map_wechat_article_to_drafts(article, events)
    if map_warnings:
        warnings.extend(map_warnings)
    if not drafts:
        return [], False, "mapper_produced_no_drafts"
    # 把抽取侧 warnings + used_fallback 透传到外层 debug（非错误）
    if ext_warnings:
        warnings.extend(f"[extract] {w}" for w in ext_warnings)
    if used_fallback:
        warnings.append(f"[extract] used_fallback {source_url or '?'}")

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


def _commit_to_events_json(drafts: list[dict],
                           path: Path = EVENTS_JSON) -> dict:
    """停gap 入库：把 6-field drafts 合并进 database/events.json。

    曹昕宇的 EventImportService.import_many 落地后由生产路径取代。
    - source_url 相同 → 更新 summary/start_time/end_time/location（不重复 insert）
    - source_url 缺失 → 用 title+start_time+location 保底去重
    - 新条目生成 event_id (UUIDv4)、source_file="auto_collector_stopgap"、created_at
    - 写前备份 events.json.bak
    """
    if not drafts:
        return {"imported": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        return {"imported": 0, "updated": 0, "skipped": 0, "failed": len(drafts),
                "errors": [f"读 events.json 失败: {e}"]}
    events = data.get("events", []) if isinstance(data, dict) else []
    if not isinstance(events, list):
        events = []

    # 备份
    bak = path.with_suffix(path.suffix + ".bak")
    try:
        with open(bak, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass

    # 去重 key：(source_url, title) — 同一篇文章可含多个活动
    by_key = {(e.get("source_url"), e.get("title")): e for e in events
              if e.get("source_url") and e.get("title")}
    imported = skipped = 0
    errors: list[str] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for dr in drafts:
        url = dr.get("source_url")
        title = dr.get("title")
        if not title:
            skipped += 1
            continue
        dedup_key = (url, title)
        if url and title and dedup_key in by_key:
            # 停gap：已有 (source_url, title) → 跳过（不做更新）
            # 真正的 upsert 属于曹昕宇的 EventImportService
            skipped += 1
            continue
        # 保底去重：url 缺失时用 title + start_time + location
        if not url:
            alt_key = (title, dr.get("start_time"), dr.get("location"))
            if any(
                (e.get("title"), e.get("start_time"), e.get("location")) == alt_key
                for e in events
            ):
                skipped += 1
                continue
        new_event = {
            "event_id": str(uuid.uuid4()),
            "title": title,
            "summary": dr.get("summary"),
            "start_time": dr.get("start_time"),
            "end_time": dr.get("end_time"),
            "location": dr.get("location"),
            "source_url": url,
            "source_name": dr.get("source_name", ""),
            "source_file": "auto_collector_stopgap",
            "campus": None,
            "organizer": None,
            "tags": [],
            "evidence_text": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        events.append(new_event)
        if url and title:
            by_key[(url, title)] = new_event
        imported += 1

    data["events"] = events
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        return {"imported": imported, "updated": 0, "skipped": skipped,
                "failed": len(drafts) - imported - skipped,
                "errors": [f"写 events.json 失败: {e}"]}

    return {"imported": imported, "updated": 0, "skipped": skipped,
            "failed": 0, "errors": errors}


def run(dry_run: bool = True, commit: bool = False, commit_json: bool = False,
        samples: bool = False, accounts_path: Path | None = None,
        limit: int = DEFAULT_LIMIT) -> dict:
    warnings: list[str] = []

    cn8n_mod, cn8n_err = _try_import_cn8n()
    if cn8n_err and not dry_run and not samples:
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

    if samples:
        # 样例模式：读本地 5 篇全文文章，不走 cn8n
        articles = load_sample_articles()
        total_articles = len(articles)
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
        extracted_ok = ok
        extracted_fail = fail
        per_account.append({
            "account": "samples",
            "fetched": len(articles),
            "new_articles": len(new_articles),
            "extracted_ok": ok,
            "extracted_fail": fail,
            "event_drafts": len(account_drafts),
        })
    else:
        accounts = load_enabled_accounts(accounts_path, limit=limit)
        for acc in accounts:
            res = collect_account(acc, dry_run=dry_run, cn8n_mod=cn8n_mod,
                                  warnings=warnings)
            articles = res.get("articles", [])
            total_articles += len(articles)
            new_articles = dedupe_articles(articles, seen_urls)
            account_drafts = []
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

    imported = updated = skipped = failed = 0
    import_errors: list[str] = []
    commit_target = "none"
    if commit and import_mod is not None and hasattr(import_mod, "import_many"):
        commit_target = "import_many"
        try:
            import_fn = getattr(import_mod, "import_many_standalone", import_mod.import_many)
            result = import_fn(all_drafts)
            if isinstance(result, dict):
                imported = result.get("imported", 0)
                updated = result.get("updated", 0)
                skipped = result.get("skipped", 0)
                failed = result.get("failed", 0)
                import_errors = result.get("errors", [])
            else:
                imported = int(result) if isinstance(result, int) else 0
        except Exception as e:  # noqa: BLE001
            warnings.append(f"入库失败: {e}")
            failed = len(all_drafts)
            import_errors = [str(e)]
    elif commit and import_mod is not None:
        warnings.append("EventImportService 无 import_many，跳过写库")
    elif commit_json:
        # 停gap：写 database/events.json（曹昕宇 import_many 落地后取代）
        commit_target = "events_json_stopgap"
        res = _commit_to_events_json(all_drafts)
        imported = res["imported"]
        updated = res["updated"]
        skipped = res["skipped"]
        failed = res["failed"]
        import_errors = res["errors"]

    return {
        "dry_run": dry_run,
        "commit": commit,
        "commit_json": commit_json,
        "commit_target": commit_target,
        "limit_accounts": limit,
        "scanned_accounts": len(per_account),
        "total_articles": total_articles,
        "new_articles": sum(p["new_articles"] for p in per_account),
        "extraction_summary": {
            "total_articles_processed": extracted_ok + extracted_fail,
            "extracted_ok": extracted_ok,
            "extracted_fail": extracted_fail,
            "fail_reasons": fail_reasons,
        },
        "extracted_event_drafts": len(all_drafts),
        "commit_summary": {
            "fetched_count": total_articles,
            "extracted_count": extracted_ok,
            "imported_count": imported,
            "updated_count": updated,
            "skipped_count": skipped,
            "failed_count": failed,
            "errors": import_errors,
        },
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
    parser.add_argument("--commit-json", dest="commit_json", action="store_true",
                        default=False, help="停gap：写 database/events.json")
    parser.add_argument("--accounts", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"限制扫描账号数（默认 {DEFAULT_LIMIT}，0=不限）")
    parser.add_argument("--samples", action="store_true", default=False,
                        help="用本地 5 篇样例文章代替 cn8n 抓取")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, commit=args.commit,
                 commit_json=args.commit_json, samples=args.samples,
                 accounts_path=args.accounts, limit=args.limit)

    suffix = "commit" if (args.commit or args.commit_json) else "dryrun"
    out_path = _HERE / f"auto_collector_{suffix}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    summary_keys = ("dry_run", "commit", "commit_json", "commit_target",
                    "scanned_accounts", "total_articles", "new_articles",
                    "extraction_summary", "extracted_event_drafts",
                    "commit_summary", "warnings")
    summary = {k: result[k] for k in summary_keys}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[written] {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
