from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runtime import load_events, load_profile, parse_now, plan_day


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_EVENTS_PATH = SCRIPT_DIR.parent / "agent-maas-cli" / "outputs" / "events.json"
DEFAULT_PROFILE_PATH = SCRIPT_DIR / "profile.sample.json"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        events = load_events(args.events)
        profile = load_profile(args.profile)
        now = parse_now(args.now)
        rewriter = build_rewriter(args)
        result = plan_day(
            events=events,
            profile=profile,
            request_text=args.request_text,
            date_scope=args.date_scope,
            now=now,
            include_debug=args.include_debug,
            rewriter=rewriter,
        )
    except Exception as exc:
        print(f"plan runtime failed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the MVP plan-day rule pipeline against an events.json file.",
    )
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS_PATH, help="events.json path")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH, help="profile JSON path")
    parser.add_argument("--request-text", required=True, help="用户自然语言日程请求")
    parser.add_argument(
        "--date-scope",
        choices=["today", "tomorrow", "this_week"],
        default="today",
        help="时间范围",
    )
    parser.add_argument(
        "--now",
        help="ISO 8601 reference time. Use this for deterministic demo runs with the sample data.",
    )
    parser.add_argument(
        "--llm-mode",
        choices=["template", "maas"],
        default="template",
        help="template uses deterministic reasons; maas only rewrites selected items.",
    )
    parser.add_argument("--maas-base-url", help="Override MAAS_BASE_URL for --llm-mode maas")
    parser.add_argument("--maas-model", help="Override MAAS_MODEL for --llm-mode maas")
    parser.add_argument("--maas-timeout", type=float, default=None, help="HTTP timeout for MaaS rewrite")
    parser.add_argument("--include-debug", action="store_true", help="Include filter reasons, scores, and evidence")
    return parser


def build_rewriter(args: argparse.Namespace):
    if args.llm_mode == "template":
        return None

    from llm import rewrite_with_maas

    def rewriter(result: dict[str, Any]) -> dict[str, Any]:
        return rewrite_with_maas(
            result,
            base_url=args.maas_base_url,
            model=args.maas_model,
            timeout=args.maas_timeout,
        )

    return rewriter


if __name__ == "__main__":
    raise SystemExit(main())
