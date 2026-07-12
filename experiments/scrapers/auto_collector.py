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
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
DEFAULT_ACCOUNTS = _HERE / "account_list.json"
ACCOUNT_CURSOR = _HERE / "account_cursor.json"
EVENTS_JSON = _REPO_ROOT / "database" / "events.json"
DEFAULT_LIMIT = 3  # 默认只扫前 3 个 enabled 账号，避免消耗 API 额度

# 账号分类值域（用于 category_breakdown 统计）
ACCOUNT_CATEGORIES = ("讲座", "文艺", "体育", "比赛", "就业", "志愿服务", "其他")

for _p in (str(_HERE.parent), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from experiments.scrapers.maas_extract import extract_article_to_events  # noqa: E402
from experiments.scrapers.schema_mapper import (  # noqa: E402
    map_wechat_article_to_drafts,
    map_xiaohongshu_note_to_drafts,
)
from experiments.agent_core.error_classify import (  # noqa: E402
    ErrorClass,
    classify_error,
    is_retryable,
    is_terminal_content,
)

# 文章级重试：对可重试临时错误（timeout/rate_limited/provider_error）退避重试。
# 注意：extract_article 内部已有 HTTP 层重试，此处是文章级分类重试，主要价值是
# 不重试内容结论（not_an_event/no_activity/text_too_short）和认证失败。
ARTICLE_MAX_RETRIES = 3
ARTICLE_RETRY_BACKOFF = 1.5  # sleep = BACKOFF * (attempt + 1)


def load_enabled_accounts(path: Path | None = None, limit: int = 0) -> list[dict]:
    p = path or DEFAULT_ACCOUNTS
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    enabled = [a for a in accounts if a.get("enabled") is True]
    if limit > 0:
        enabled = enabled[:limit]
    return enabled


def _read_cursor(cursor_path: Path) -> str | None:
    """读取上次写入的 next_account_cursor（即本轮应开始的账号 id）。"""
    try:
        data = json.loads(cursor_path.read_text(encoding="utf-8"))
        cid = data.get("cursor")
        return cid if isinstance(cid, str) and cid else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_cursor(cursor_path: Path, next_cursor: str | None) -> None:
    payload = {"cursor": next_cursor, "updated_at": datetime.now(timezone.utc).isoformat()}
    cursor_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_enabled_accounts_rotating(
    path: Path | None = None,
    limit: int = 0,
    cursor_path: Path | None = None,
) -> tuple[list[dict], str | None, str | None]:
    """环形轮换取 enabled 账号。

    返回 (selected, account_cursor_start, next_account_cursor)：
      - selected：本轮选中的账号列表（按环形顺序）
      - account_cursor_start：本轮起始账号 id（即游标指向的账号）
      - next_account_cursor：下轮应开始的账号 id（选中最后一个的下一个 enabled，环形）

    游标语义：cursor 文件存的是"下轮应开始的账号 id"。本轮从该 id 开始取 limit 个。
    """
    p = path or DEFAULT_ACCOUNTS
    cp = cursor_path or ACCOUNT_CURSOR
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    all_enabled = [a for a in accounts if a.get("enabled") is True]
    if not all_enabled:
        return [], None, None

    cursor_id = _read_cursor(cp)
    # 找到起始索引
    start_idx = 0
    if cursor_id:
        for i, a in enumerate(all_enabled):
            if a.get("id") == cursor_id:
                start_idx = i
                break
        # cursor 指向的账号若已禁用/删除，回退到 0

    n = len(all_enabled)
    take = limit if (limit and limit > 0) else n
    take = min(take, n)
    selected = [all_enabled[(start_idx + i) % n] for i in range(take)]

    account_cursor_start = selected[0].get("id") if selected else None
    # next_cursor = 选中最后一个的下一个 enabled（环形）
    last_idx = (start_idx + take - 1) % n
    next_idx = (last_idx + 1) % n
    next_account_cursor = all_enabled[next_idx].get("id") if selected else None
    return selected, account_cursor_start, next_account_cursor


def category_breakdown_of(accounts: list[dict]) -> dict[str, int]:
    bd = {c: 0 for c in ACCOUNT_CATEGORIES}
    for a in accounts:
        cat = a.get("category") or "其他"
        if cat not in bd:
            cat = "其他"
        bd[cat] += 1
    return bd


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


def _try_import_article_state() -> tuple[object | None, object | None, str | None]:
    """导入昕宇提供的文章状态层（database.article_state）+ SessionLocal。

    返回 (article_state_mod, session_local_factory, err)。未落地时 (None, None, err)，
    调用方降级到无跨轮去重行为。
    """
    try:
        import database.article_state as mod  # noqa: PLC0415
        from database.database import SessionLocal  # noqa: PLC0415
        for fn in ("is_article_processed", "mark_article_processing",
                   "mark_article_completed", "mark_article_failed"):
            if not hasattr(mod, fn):
                return None, None, f"database.article_state 缺 {fn}"
        return mod, SessionLocal, None
    except ImportError as e:
        return None, None, f"database.article_state 未落地: {e}"


def _content_hash(text: str) -> str:
    """与昕宇侧约定一致的 content_hash：sha256(text.strip().encode utf-8)。"""
    import hashlib  # noqa: PLC0415
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


# 业务 reason → RawDocument skipped_* status 映射（terminal 内容结论，不重试）
_REASON_TO_SKIPPED_STATUS = {
    "not_an_event": "skipped_not_an_event",
    "no_activity": "skipped_no_activity",
    "text_too_short": "skipped_text_too_short",
    "insufficient_evidence": "skipped_text_too_short",
    "no_text": "skipped_text_too_short",
}


def _to_skipped_status(reason: str) -> str | None:
    return _REASON_TO_SKIPPED_STATUS.get(reason)


_SKIPPED_TO_REASON = {v: k for k, v in _REASON_TO_SKIPPED_STATUS.items()}


def _skipped_to_reason(status: str) -> str:
    return _SKIPPED_TO_REASON.get(status, "already_processed")


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


def _text_quality(text: str | None, text_source: str) -> str:
    """判定正文质量：full / partial / insufficient / none。

    - none：无文本
    - insufficient：< 100 字
    - full：source ∈ {cn8n_detail, sample_fulltext} 且 ≥ 500 字
    - partial：其余（摘要或短正文）
    """
    if text is None:
        return "none"
    n = len(text)
    if n < 100:
        return "insufficient"
    if text_source in ("cn8n_detail", "sample_fulltext") and n >= 500:
        return "full"
    return "partial"


def _get_article_text(article_url: str, article: dict, cn8n_mod, *,
                      is_sample: bool = False) -> tuple[str | None, str, str]:
    """获取文章正文，返回 (text, text_source, text_quality)。

    优先级：cn8n detail_text > digest > None。
    text_source ∈ {cn8n_detail, cn8n_digest, sample_fulltext, none}。
    text_quality ∈ {full, partial, insufficient, none}。
    """
    # 1) try get_article_detail_text（样例模式跳过 cn8n）
    if not is_sample and cn8n_mod is not None and hasattr(cn8n_mod, "get_article_detail_text"):
        try:
            text = cn8n_mod.get_article_detail_text(article_url)
            if text:
                t = text.strip()
                return t, "cn8n_detail", _text_quality(t, "cn8n_detail")
        except NotImplementedError:
            pass
        except Exception:
            pass
    # 2) fallback to digest（样例模式的 digest 是本地全文）
    digest = (article.get("digest") or "").strip()
    if digest:
        src = "sample_fulltext" if is_sample else "cn8n_digest"
        return digest, src, _text_quality(digest, src)
    return None, "none", "none"


def extract_and_map(article: dict, *, cn8n_mod,
                    warnings: list[str], is_sample: bool = False,
                    db=None, article_state=None) -> tuple[list[dict], bool, str, dict]:
    """单篇文章：取正文 → MaaS 提取 → mapper → (drafts, succeeded, reason, info)。

    跨轮去重：当 db + article_state 可用时，调 LLM 前查 is_article_processed，
    completed+hash 同 / skipped_* → 跳过；处理后 mark_article_completed/failed。
    未落地时降级到单轮 seen_urls 去重。

    Returns:
        drafts: 6-field event drafts 列表（已附 text_source/text_quality）
        succeeded: True 如果成功产出至少 1 个 draft
        reason: 失败原因（成功时为空字符串）
        info: {text_source, text_quality, review_items, retry_count?, last_error?, auth_failed?}
    """
    info: dict = {"text_source": "none", "text_quality": "none", "review_items": []}
    metadata = {
        "source_name": article.get("source_name") or article.get("account"),
        "source_url": article.get("source_url") or article.get("url"),
        "title": article.get("title"),
        "publish_time": article.get("publish_time"),
    }
    source_url = metadata["source_url"]

    text, text_source, text_quality = _get_article_text(source_url, article, cn8n_mod, is_sample=is_sample)
    info["text_source"] = text_source
    info["text_quality"] = text_quality

    raw_document_id: str | None = None

    def _mark_processing() -> None:
        nonlocal raw_document_id
        if not (db and article_state and source_url):
            return
        try:
            pub = article.get("publish_time")
            pub_dt = None
            if pub:
                try:
                    pub_dt = datetime.fromisoformat(str(pub))
                except (TypeError, ValueError):
                    pub_dt = None
            raw_document_id = article_state.mark_article_processing(
                db, source_url, title=article.get("title") or "",
                content_hash=content_hash, published_at=pub_dt)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"mark_article_processing 失败 {source_url}: {e}")

    def _mark_outcome(succeeded: bool, reason: str, retry_count: int) -> None:
        if not (db and article_state and raw_document_id):
            return
        try:
            if succeeded:
                article_state.mark_article_completed(db, raw_document_id)
            else:
                skipped = _to_skipped_status(reason)
                is_terminal = skipped is not None or reason in ("authentication_failed",)
                article_state.mark_article_failed(
                    db, raw_document_id, error=reason,
                    retry_count=retry_count, is_terminal=is_terminal)
            db.commit()
        except Exception as e:  # noqa: BLE001
            warnings.append(f"mark_outcome 失败 {source_url}: {e}")

    if text is None:
        warnings.append(f"无正文可用: {source_url or '?'}")
        return [], False, "no_text", info
    content_hash = _content_hash(text)

    # --- 跨轮去重检查 ---
    if db and article_state and source_url:
        try:
            prev = article_state.is_article_processed(db, source_url, content_hash)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"is_article_processed 失败 {source_url}: {e}")
            prev = None
        if isinstance(prev, dict):
            prev_status = prev.get("status")
            if prev_status == "completed" and prev.get("content_hash") == content_hash:
                info["dedup"] = "already_processed"
                return [], False, "already_processed", info
            if prev_status and str(prev_status).startswith("skipped_"):
                info["dedup"] = prev_status
                return [], False, _skipped_to_reason(prev_status), info
            if prev_status == "failed":
                rc = int(prev.get("retry_count", 0) or 0)
                if rc >= ARTICLE_MAX_RETRIES:
                    info["dedup"] = "exhausted_retries"
                    return [], False, "exhausted_retries", info
                # 否则继续重试
        _mark_processing()

    # 证据不足：正文太短，不调 LLM 补猜
    if text_quality == "insufficient":
        _mark_outcome(False, "insufficient_evidence", 0)
        return [], False, "insufficient_evidence", info

    # Collection V2 返回 dict {status, events, warnings, error, used_fallback}
    # 文章级重试：对可重试临时错误退避重试，内容结论/认证失败不重试。
    result = None
    retry_count = 0
    last_error: str | None = None
    for attempt in range(ARTICLE_MAX_RETRIES + 1):
        try:
            result = extract_article_to_events(text, metadata)
            break  # 调用本身没抛异常，退出重试循环
        except Exception as e:  # noqa: BLE001
            err = classify_error(e)
            last_error = f"{err.value}: {e}"
            if err == ErrorClass.AUTH_FAILED:
                warnings.append(f"认证失败 {source_url}: {e}")
                info["retry_count"] = attempt
                info["last_error"] = last_error
                info["auth_failed"] = True
                _mark_outcome(False, "authentication_failed", attempt)
                return [], False, "authentication_failed", info
            if is_retryable(err) and attempt < ARTICLE_MAX_RETRIES:
                retry_count = attempt + 1
                time.sleep(ARTICLE_RETRY_BACKOFF * (attempt + 1))
                continue
            warnings.append(f"提取异常 {source_url}: {e}")
            info["retry_count"] = attempt
            info["last_error"] = last_error
            _mark_outcome(False, f"extract_error: {err.value}", attempt)
            return [], False, f"extract_error: {err.value}", info
    info["retry_count"] = retry_count
    if last_error:
        info["last_error"] = last_error

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
        _mark_outcome(False, f"extract_error: {error or 'parse_error'}", retry_count)
        return [], False, f"extract_error: {error or 'parse_error'}", info
    if status == "text_too_short":
        _mark_outcome(False, "text_too_short", retry_count)
        return [], False, "text_too_short", info
    if status == "not_an_event":
        _mark_outcome(False, "not_an_event", retry_count)
        return [], False, "not_an_event", info
    if not events:
        # ok 但无 events，或 no_activity
        _mark_outcome(False, "no_activity", retry_count)
        return [], False, "no_activity", info

    drafts, map_warnings = map_wechat_article_to_drafts(article, events)
    if map_warnings:
        warnings.extend(map_warnings)
    if not drafts:
        _mark_outcome(False, "mapper_produced_no_drafts", retry_count)
        return [], False, "mapper_produced_no_drafts", info
    # 把抽取侧 warnings + used_fallback 透传到外层 debug（非错误）
    if ext_warnings:
        warnings.extend(f"[extract] {w}" for w in ext_warnings)
    if used_fallback:
        warnings.append(f"[extract] used_fallback {source_url or '?'}")

    # 证据边界：每个 draft 必须有 title/start_time/location/source_url，缺任一进 review_queue
    kept: list[dict] = []
    for d in drafts:
        missing = [f for f in ("title", "start_time", "location", "source_url")
                   if not d.get(f)]
        if missing:
            info["review_items"].append({
                "source_url": source_url,
                "title": d.get("title") or article.get("title"),
                "missing_fields": missing,
                "reason": "insufficient_evidence" if text_quality == "insufficient" else "needs_review",
                "text_source": text_source,
                "text_quality": text_quality,
            })
        else:
            d["text_source"] = text_source
            d["text_quality"] = text_quality
            kept.append(d)
    if not kept:
        _mark_outcome(False, "insufficient_evidence", retry_count)
        return [], False, "insufficient_evidence", info
    _mark_outcome(True, "", retry_count)
    return kept, True, "", info


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
    # 跨轮去重：昕宇 article_state + SessionLocal（未落地则降级到单轮 seen_urls）
    article_state_mod, session_local, article_state_err = _try_import_article_state()
    if article_state_err:
        warnings.append(article_state_err)
    db = None
    if article_state_mod is not None and session_local is not None:
        try:
            db = session_local()
        except Exception as e:  # noqa: BLE001
            warnings.append(f"DB session 创建失败，跨轮去重降级: {e}")
            db = None

    seen_urls: set[str] = set()
    all_drafts: list[dict] = []
    total_articles = 0
    extracted_ok = 0
    extracted_fail = 0
    fail_reasons: dict[str, int] = {}
    per_account: list[dict] = []
    # 账号轮换游标
    account_cursor_start: str | None = None
    next_account_cursor: str | None = None
    scanned_account_ids: list[str] = []
    scanned_account_names: list[str] = []
    cat_breakdown: dict[str, int] = {}
    # 文本质量与证据边界
    text_quality_breakdown: dict[str, int] = {"full": 0, "partial": 0, "insufficient": 0, "none": 0}
    review_queue: list[dict] = []
    retry_summary = {"total_retried": 0, "max_retry_reached": 0, "auth_failures": 0}

    if samples:
        # 样例模式：读本地 5 篇全文文章，不走 cn8n
        articles = load_sample_articles()
        total_articles = len(articles)
        new_articles = dedupe_articles(articles, seen_urls)
        account_drafts: list[dict] = []
        ok = fail = 0
        for art in new_articles:
            drafts, succeeded, reason, ainfo = extract_and_map(
                art, cn8n_mod=cn8n_mod, warnings=warnings, is_sample=True,
                db=db, article_state=article_state_mod)
            account_drafts.extend(drafts)
            text_quality_breakdown[ainfo["text_quality"]] = text_quality_breakdown.get(ainfo["text_quality"], 0) + 1
            review_queue.extend(ainfo["review_items"])
            rc = ainfo.get("retry_count", 0)
            if rc:
                retry_summary["total_retried"] += 1
                retry_summary["max_retry_reached"] = max(retry_summary["max_retry_reached"], rc)
            if ainfo.get("auth_failed"):
                retry_summary["auth_failures"] += 1
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
        accounts, account_cursor_start, next_account_cursor = load_enabled_accounts_rotating(
            accounts_path, limit=limit)
        scanned_account_ids = [a.get("id") for a in accounts if a.get("id")]
        scanned_account_names = [a.get("name") for a in accounts if a.get("name")]
        cat_breakdown = category_breakdown_of(accounts)
        # 持久化游标（即使本轮无结果也推进，避免下次仍从同一位置）
        if next_account_cursor:
            try:
                _write_cursor(ACCOUNT_CURSOR, next_account_cursor)
            except OSError as e:  # noqa: BLE001
                warnings.append(f"游标写入失败: {e}")
        for acc in accounts:
            res = collect_account(acc, dry_run=dry_run, cn8n_mod=cn8n_mod,
                                  warnings=warnings)
            articles = res.get("articles", [])
            total_articles += len(articles)
            new_articles = dedupe_articles(articles, seen_urls)
            account_drafts = []
            ok = fail = 0
            for art in new_articles:
                drafts, succeeded, reason, ainfo = extract_and_map(
                    art, cn8n_mod=cn8n_mod, warnings=warnings,
                    db=db, article_state=article_state_mod)
                account_drafts.extend(drafts)
                text_quality_breakdown[ainfo["text_quality"]] = text_quality_breakdown.get(ainfo["text_quality"], 0) + 1
                review_queue.extend(ainfo["review_items"])
                rc = ainfo.get("retry_count", 0)
                if rc:
                    retry_summary["total_retried"] += 1
                    retry_summary["max_retry_reached"] = max(retry_summary["max_retry_reached"], rc)
                if ainfo.get("auth_failed"):
                    retry_summary["auth_failures"] += 1
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

    if db is not None:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass

    return {
        "dry_run": dry_run,
        "commit": commit,
        "commit_json": commit_json,
        "commit_target": commit_target,
        "limit_accounts": limit,
        "scanned_accounts": len(per_account),
        "scanned_account_ids": scanned_account_ids,
        "scanned_account_names": scanned_account_names,
        "account_cursor_start": account_cursor_start,
        "next_account_cursor": next_account_cursor,
        "category_breakdown": cat_breakdown,
        "total_articles": total_articles,
        "new_articles": sum(p["new_articles"] for p in per_account),
        "extraction_summary": {
            "total_articles_processed": extracted_ok + extracted_fail,
            "extracted_ok": extracted_ok,
            "extracted_fail": extracted_fail,
            "fail_reasons": fail_reasons,
            "retry_summary": retry_summary,
        },
        "text_quality_breakdown": text_quality_breakdown,
        "review_queue": review_queue,
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
                    "scanned_accounts", "scanned_account_ids", "scanned_account_names",
                    "account_cursor_start", "next_account_cursor", "category_breakdown",
                    "total_articles", "new_articles",
                    "extraction_summary", "text_quality_breakdown",
                    "extracted_event_drafts",
                    "commit_summary", "warnings")
    summary = {k: result[k] for k in summary_keys}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[written] {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
