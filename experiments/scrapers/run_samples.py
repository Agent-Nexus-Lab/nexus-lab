# -*- coding: utf-8 -*-
"""样例抽取 harness：对 5 篇本地样例文章跑 Collection V2 抽取 → mapper → drafts。

不依赖 cn8n，直接读 experiments/agent_maas_cli/samples/*.txt。
样例文件头部为 `key: value` 行（account/title/author/date/source_url/source_platform），
空行后为正文。

Usage:
    python experiments/scrapers/run_samples.py
    python experiments/scrapers/run_samples.py --no-extract   # 只解析不调 MaaS
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
SAMPLES_DIR = _HERE.parent / "agent_maas_cli" / "samples"

for _p in (str(_HERE.parent), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from experiments.scrapers.maas_extract import extract_article_to_events  # noqa: E402
from experiments.scrapers.schema_mapper import map_wechat_article_to_drafts  # noqa: E402


def parse_sample(path: Path) -> tuple[dict, dict, str]:
    """解析样例文件 → (metadata, body_text)。"""
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
    metadata = {
        "title": meta.get("title", path.stem),
        "source_url": meta.get("source_url", f"sample://{path.stem}"),
        "source_name": meta.get("account", "李颖哲样例"),
        "publish_time": meta.get("date", ""),
    }
    article = {
        "title": metadata["title"],
        "source_url": metadata["source_url"],
        "url": metadata["source_url"],
        "source_name": metadata["source_name"],
        "publish_time": metadata["publish_time"],
    }
    return article, metadata, body


def main() -> int:
    parser = argparse.ArgumentParser(description="样例抽取 harness")
    parser.add_argument("--no-extract", action="store_true",
                        help="只解析样例，不调 MaaS")
    args = parser.parse_args()

    samples = sorted(SAMPLES_DIR.glob("sample_*.txt"))
    if not samples:
        print(f"未找到样例: {SAMPLES_DIR}", file=sys.stderr)
        return 1

    all_drafts: list[dict] = []
    per_sample: list[dict] = []
    fail_reasons: dict[str, int] = {}

    for path in samples:
        article, metadata, body = parse_sample(path)
        if args.no_extract:
            per_sample.append({"sample": path.name, "title": article["title"],
                               "body_len": len(body), "skipped": True})
            continue
        print(f"→ {path.name}  ({len(body)} 字)", file=sys.stderr)
        try:
            result = extract_article_to_events(body, metadata)
        except Exception as e:  # noqa: BLE001
            reason = f"extract_error: {e}"
            fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
            per_sample.append({"sample": path.name, "status": "exception",
                               "error": str(e), "drafts": 0})
            continue

        status = result.get("status")
        events = result.get("events") or []
        drafts, map_warnings = map_wechat_article_to_drafts(article, events)
        all_drafts.extend(drafts)

        if drafts:
            per_sample.append({"sample": path.name, "status": status,
                               "events": len(events), "drafts": len(drafts),
                               "warnings": result.get("warnings", [])})
        else:
            reason = {"no_activity": "no_activity",
                      "not_an_event": "not_an_event",
                      "text_too_short": "text_too_short",
                      "parse_error": f"extract_error: {result.get('error')}"}.get(
                status, f"unknown_status:{status}")
            fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
            per_sample.append({"sample": path.name, "status": status,
                               "events": 0, "drafts": 0,
                               "error": result.get("error"),
                               "warnings": result.get("warnings", [])})

    summary = {
        "samples_total": len(samples),
        "extracted_ok": sum(1 for p in per_sample if p.get("drafts", 0) > 0),
        "total_drafts": len(all_drafts),
        "fail_reasons": fail_reasons,
        "per_sample": per_sample,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if all_drafts:
        print("\n=== drafts ===", file=sys.stderr)
        print(json.dumps(all_drafts, ensure_ascii=False, indent=2), file=sys.stderr)
    print(f"\n[summary] {len(all_drafts)} drafts from {len(samples)} samples",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
