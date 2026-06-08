from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 fallback
    ZoneInfo = None

from schema import build_aggregated_event, build_error_response, maas_tool_schema, normalize_response, validate_events_file


DEFAULT_OPENAI_BASE_URL = "https://api.modelarts-maas.com/openai/v1"
DEFAULT_V2_BASE_URL = "https://api-ap-southeast-1.modelarts-maas.com/v2"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_TIMEZONE = "Asia/Shanghai"
SCRIPT_DIR = Path(__file__).resolve().parent
PROMPT_PATH = SCRIPT_DIR / "prompt.md"
DEFAULT_INPUT_DIR = SCRIPT_DIR / "texts"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "outputs"
SUPPORTED_INPUT_SUFFIXES = {".txt", ".md", ".html"}


def main() -> int:
    preload_env_file()
    args = parse_args()

    if args.input_dir is not None:
        return run_batch(args)

    source_text = read_source_text(args)
    if not source_text.strip():
        print("source text is empty", file=sys.stderr)
        return 2

    if args.dry_run:
        payload = build_request_payload(args, source_text)
        if args.output_file is not None:
            write_json_output(args.output_file, payload)
        elif args.write_output:
            output_file = default_single_output_path(args, payload).with_suffix(".request.json")
            write_json_output(output_file, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    normalized = process_source_text(args, source_text, input_file=args.input_file)
    if args.output_file is not None:
        write_json_output(args.output_file, normalized)
    elif args.write_output:
        output_file = default_single_output_path(args, normalized)
        write_json_output(output_file, normalized)

    print(json.dumps(normalized, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="调用华为云 MaaS DeepSeek-V4-Pro，将信息源原文抽取为活动结构化 JSON。"
    )
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--text", help="直接传入信息源原文")
    input_group.add_argument("--input-file", type=Path, help="从文件读取信息源原文，使用 UTF-8")
    input_group.add_argument(
        "--input-dir",
        nargs="?",
        const=DEFAULT_INPUT_DIR,
        type=Path,
        help="批量读取目录下的 .txt/.md/.html 文件；不传目录时使用 experiments/agent-maas-cli/texts",
    )
    parser.add_argument("--env-file", type=Path, default=None, help="环境变量文件，默认自动查找 .env")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("AGENT_MAAS_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))),
        help="批量输出目录，默认 experiments/agent-maas-cli/outputs",
    )
    parser.add_argument("--output-file", type=Path, help="单文件模式下写入指定 JSON；批量模式下写入聚合 events.json")
    parser.add_argument("--write-output", action="store_true", help="单文件模式下同时写入标准输出目录")
    parser.add_argument(
        "--api-style",
        choices=["openai", "v2"],
        default=os.getenv("MAAS_API_STYLE", "openai"),
        help="openai 使用 /openai/v1 且启用 named tool；v2 使用华为示例接口和纯 JSON prompt",
    )
    parser.add_argument("--base-url", default=os.getenv("MAAS_BASE_URL"))
    parser.add_argument("--model", default=os.getenv("MAAS_MODEL", DEFAULT_MODEL))
    parser.add_argument("--api-key", default=os.getenv("MAAS_API_KEY"), help="默认读取 MAAS_API_KEY")
    parser.add_argument("--reference-date", default=os.getenv("REFERENCE_DATE"), help="解析相对日期的参考日期，如 2026-05-20")
    parser.add_argument("--timezone", default=os.getenv("TIMEZONE", DEFAULT_TIMEZONE))
    parser.add_argument("--source-name", default=os.getenv("SOURCE_NAME"), help="信息源名称，优先写入输出 source_name")
    parser.add_argument("--source-url", default=os.getenv("SOURCE_URL"), help="信息源 URL，优先写入输出 source_url")
    parser.add_argument("--temperature", type=float, default=float(os.getenv("MAAS_TEMPERATURE", "0.1")))
    parser.add_argument("--max-tokens", type=int, default=optional_int_env("MAAS_MAX_TOKENS"))
    parser.add_argument("--timeout", type=float, default=optional_float_env("MAAS_TIMEOUT"))
    parser.add_argument(
        "--thinking",
        choices=["default", "enabled", "disabled"],
        default=os.getenv("MAAS_THINKING", "disabled"),
        help="DeepSeek 深度思考开关；抽取任务默认 disabled",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=["high", "max"],
        default=os.getenv("MAAS_REASONING_EFFORT"),
        help="DeepSeek-V4 系列思考强度；仅在需要时传 high/max",
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        default=os.getenv("MAAS_VERIFY_SSL", "true").lower() in {"0", "false", "no"},
        help="调试 TLS 问题时关闭证书校验；默认校验证书",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印 MaaS 请求体，不发起网络请求")
    parser.add_argument("--strict", action="store_true", help="调用或校验失败时直接抛错")
    return parser.parse_args()


def run_batch(args: argparse.Namespace) -> int:
    input_dir = args.input_dir
    output_dir = args.output_dir
    files = discover_input_files(input_dir)
    if not files:
        print(f"no input files found in {input_dir}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = args.output_file or output_dir / "events.json"
    events: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for input_file in files:
        source_text = input_file.read_text(encoding="utf-8")

        if args.dry_run:
            request_file = output_dir / "dry-run" / f"{input_file.stem}.request.json"
            payload = build_request_payload(args, source_text)
            write_json_output(request_file, payload)
            status = "dry_run"
            event_count = 0
            result_output = str(request_file)
        else:
            normalized = process_source_text(args, source_text, input_file=input_file)
            status = "completed" if normalized["events"] else "empty"
            event_count = len(normalized["events"])
            result_output = str(output_file)
            for event in normalized["events"]:
                events.append(
                    build_aggregated_event(
                        event,
                        event_id=str(uuid.uuid4()),
                        source_file=input_file.name,
                        source_name=normalized["source_name"],
                        source_url=normalized["source_url"],
                    )
                )

        results.append(
            {
                "input_file": str(input_file),
                "output_file": result_output,
                "status": status,
                "events": event_count,
            }
        )

    if not args.dry_run:
        payload = {"events": events}
        validate_events_file(payload)
        write_json_output(output_file, payload)

    summary = {
        "code": 0,
        "data": {
            "input_dir": str(input_dir),
            "output_file": str(output_file),
            "total": len(results),
            "total_events": len(events),
            "sources": results,
        },
        "message": "ok",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def discover_input_files(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        return []
    return sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_SUFFIXES
    )


def process_source_text(
    args: argparse.Namespace,
    source_text: str,
    input_file: Path | None = None,
) -> dict[str, Any]:
    fallback = {
        "source_name": args.source_name,
        "source_url": args.source_url,
    }

    try:
        raw_response = call_maas(args, source_text)
        extracted = extract_payload(raw_response)
        return normalize_response(extracted, fallback)
    except Exception as exc:
        if args.strict:
            raise
        return build_error_response(f"结构化抽取失败：{exc}", fallback)


def default_single_output_path(args: argparse.Namespace, payload: dict[str, Any]) -> Path:
    if args.input_file is not None:
        stem = args.input_file.stem
    else:
        stem = "extraction"
    return args.output_dir / f"{stem}.json"


def write_json_output(output_file: Path, payload: dict[str, Any]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_env_file(explicit_path: Path | None) -> None:
    env_path = explicit_path or find_env_file()
    if env_path is None or not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def find_env_file() -> Path | None:
    candidates = [Path.cwd() / ".env", SCRIPT_DIR / ".env", SCRIPT_DIR.parent.parent / ".env"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def read_source_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.input_file is not None:
        return args.input_file.read_text(encoding="utf-8")
    return sys.stdin.read()


def call_maas(
    args: argparse.Namespace,
    source_text: str,
) -> dict[str, Any]:
    import requests

    api_key = args.api_key or os.getenv("MAAS_API_KEY")
    if not api_key:
        raise RuntimeError("MAAS_API_KEY is required. Put it in .env or export it in the shell.")

    base_url = resolve_base_url(args).rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = build_request_payload(args, source_text)
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=args.timeout,
        verify=not args.no_verify_ssl,
    )
    if not response.ok:
        detail = response.text[:1000].replace(api_key, "[REDACTED]")
        raise RuntimeError(f"MaaS HTTP {response.status_code}: {detail}")
    return response.json()


def resolve_timezone(timezone_name: str) -> timezone:
    if ZoneInfo is not None:
        try:
            return ZoneInfo(timezone_name)
        except Exception:
            pass
    if timezone_name == DEFAULT_TIMEZONE:
        return timezone(timedelta(hours=8))
    return datetime.now().astimezone().tzinfo or timezone.utc


def preload_env_file() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-file", type=Path, default=None)
    args, _ = parser.parse_known_args()
    load_env_file(args.env_file)


def optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    return int(value) if value else None


def optional_float_env(name: str) -> float | None:
    value = os.getenv(name)
    return float(value) if value else None


def build_request_payload(
    args: argparse.Namespace,
    source_text: str,
) -> dict[str, Any]:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    user_payload = {
        "source_name": args.source_name,
        "source_url": args.source_url,
        "reference_date": args.reference_date,
        "timezone": args.timezone,
        "source_text": source_text,
    }
    payload: dict[str, Any] = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": args.temperature,
    }
    if args.max_tokens is not None:
        payload["max_tokens"] = args.max_tokens
    if args.api_style == "openai":
        payload["tools"] = [maas_tool_schema()]
        payload["tool_choice"] = {
            "type": "function",
            "function": {"name": "emit_event_extraction_result"},
        }
    if args.thinking != "default":
        payload["thinking"] = {"type": args.thinking}
    if args.reasoning_effort:
        payload["reasoning_effort"] = args.reasoning_effort
    return payload


def resolve_base_url(args: argparse.Namespace) -> str:
    if args.base_url:
        return args.base_url
    if args.api_style == "v2":
        return DEFAULT_V2_BASE_URL
    return DEFAULT_OPENAI_BASE_URL


def extract_payload(raw_response: dict[str, Any]) -> dict[str, Any]:
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("MaaS response missing choices")

    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        function = tool_calls[0].get("function", {})
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            return json.loads(arguments)
        if isinstance(arguments, dict):
            return arguments

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return parse_json_content(content)

    raise ValueError("MaaS response did not contain tool arguments or JSON content")


def parse_json_content(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    return json.loads(stripped)


if __name__ == "__main__":
    raise SystemExit(main())
