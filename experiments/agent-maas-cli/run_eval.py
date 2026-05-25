from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from schema import build_aggregated_event, normalize_response, validate_events_file


SCRIPT_DIR = Path(__file__).resolve().parent
CLI_PATH = SCRIPT_DIR / "cli.py"
DEFAULT_INPUT_DIR = SCRIPT_DIR / "texts"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "outputs"
DEFAULT_REFERENCE_DATE = "2026-05-20"
SUPPORTED_SUFFIXES = {".txt", ".md", ".html"}


def main() -> int:
    args = parse_args()
    files = discover_files(args.input_dir)
    selected_files = select_files(files, args.range)
    if not selected_files:
        print("no matching eval files", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        return run_dry_run(args, selected_files)

    output_file = resolve_output_file(args)
    events: list[dict[str, Any]] = []
    failures = 0
    for index, input_file in enumerate(selected_files):
        extraction = run_extraction_with_retries(args, input_file)
        if extraction is None:
            failures += 1
            if args.stop_on_error:
                return 1
            continue

        if extraction["warnings"]:
            for warning in extraction["warnings"]:
                print(f"[eval] warning {input_file.name}: {warning}", file=sys.stderr)

        if not extraction["events"]:
            failures += 1
            print(f"[eval] {input_file.name} status=empty", file=sys.stderr)
            if args.stop_on_error:
                return 1

        for event in extraction["events"]:
            events.append(
                build_aggregated_event(
                    event,
                    event_id=str(uuid.uuid4()),
                    source_file=input_file.name,
                    source_name=extraction["source_name"],
                    source_url=extraction["source_url"],
                )
            )

        if args.delay_seconds > 0 and index < len(selected_files) - 1:
            time.sleep(args.delay_seconds)

    payload = {"events": events}
    try:
        validate_events_file(payload)
    except Exception as exc:
        print(f"[eval] aggregated events invalid: {exc}", file=sys.stderr)
        return 1
    write_json_output(output_file, payload)

    total = len(selected_files)
    ok = total - failures
    print(f"[eval] wrote {len(events)} events -> {output_file}")
    print(f"[eval] done: {ok}/{total} sources succeeded, {failures} failed")
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量运行 MaaS 活动信息抽取测评，默认处理 texts/ 下所有文件。"
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-file", type=Path, help="聚合输出 JSON 文件；默认 output-dir/events.json")
    parser.add_argument(
        "--range",
        dest="range",
        help="按文件序号筛选，如 1-3、2、1,3,5-7；默认全量",
    )
    parser.add_argument("--reference-date", default=DEFAULT_REFERENCE_DATE)
    parser.add_argument("--source-name")
    parser.add_argument("--source-url")
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--delay-seconds", type=float, default=0.0, help="每个输入文件之间的可选等待时间；默认不等待")
    parser.add_argument("--retries", type=int, default=0, help="单个输入为空结果或非法输出时的重试次数；默认不重试")
    parser.add_argument("--api-style", choices=["openai", "v2"])
    parser.add_argument("--thinking", choices=["default", "enabled", "disabled"], default="disabled")
    parser.add_argument("--reasoning-effort", choices=["high", "max"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-verify-ssl", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


def run_dry_run(args: argparse.Namespace, selected_files: list[Path]) -> int:
    request_dir = args.output_dir / "dry-run"
    request_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for input_file in selected_files:
        output_file = request_dir / f"{input_file.stem}.request.json"
        command = build_command(args, input_file)
        print(f"[eval] dry-run {input_file.name} -> {output_file}", flush=True)
        result = run_cli(command)
        if result.returncode != 0:
            failures += 1
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            if args.stop_on_error:
                return result.returncode
            continue
        try:
            payload = json.loads(result.stdout)
        except Exception as exc:
            failures += 1
            print(f"[eval] {input_file.name} invalid request output: {exc}", file=sys.stderr)
            if args.stop_on_error:
                return 1
            continue
        write_json_output(output_file, payload)

    total = len(selected_files)
    ok = total - failures
    print(f"[eval] dry-run done: {ok}/{total} sources succeeded, {failures} failed")
    return 1 if failures else 0


def discover_files(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        return []
    return sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def select_files(files: list[Path], range_expr: str | None) -> list[Path]:
    if not range_expr:
        return files

    selected_numbers = parse_range_expr(range_expr)
    selected: list[Path] = []
    for file in files:
        number = parse_numeric_stem(file)
        if number is not None and number in selected_numbers:
            selected.append(file)
    return selected


def parse_range_expr(range_expr: str) -> set[int]:
    numbers: set[int] = set()
    for part in range_expr.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                start, end = end, start
            numbers.update(range(start, end + 1))
        else:
            numbers.add(int(part))
    return numbers


def parse_numeric_stem(file: Path) -> int | None:
    try:
        return int(file.stem)
    except ValueError:
        return None


def build_command(args: argparse.Namespace, input_file: Path) -> list[str]:
    command = [
        sys.executable,
        str(CLI_PATH),
        "--input-file",
        str(input_file),
        "--reference-date",
        args.reference_date,
        "--thinking",
        args.thinking,
    ]

    optional_string_args = {
        "--base-url": args.base_url,
        "--model": args.model,
        "--api-style": args.api_style,
        "--reasoning-effort": args.reasoning_effort,
        "--source-name": args.source_name,
        "--source-url": args.source_url,
    }
    for flag, value in optional_string_args.items():
        if value:
            command.extend([flag, value])

    if args.temperature is not None:
        command.extend(["--temperature", str(args.temperature)])
    if args.timeout is not None:
        command.extend(["--timeout", str(args.timeout)])
    if args.max_tokens is not None:
        command.extend(["--max-tokens", str(args.max_tokens)])
    if args.dry_run:
        command.append("--dry-run")
    if args.strict:
        command.append("--strict")
    if args.no_verify_ssl:
        command.append("--no-verify-ssl")

    return command


def run_extraction_with_retries(args: argparse.Namespace, input_file: Path) -> dict[str, Any] | None:
    attempts = max(args.retries, 0) + 1
    for attempt in range(1, attempts + 1):
        if attempt > 1 and args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

        command = build_command(args, input_file)
        label = input_file.name if attempt == 1 else f"{input_file.name} retry {attempt - 1}/{attempts - 1}"
        print(f"[eval] {label}", flush=True)
        result = run_cli(command)
        if result.returncode != 0:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            if attempt < attempts:
                continue
            return None

        try:
            extraction = parse_extraction_stdout(result.stdout, args)
        except Exception as exc:
            print(f"[eval] {input_file.name} invalid output: {exc}", file=sys.stderr)
            if attempt < attempts:
                continue
            return None

        if extraction["events"] or attempt >= attempts:
            return extraction
        print(f"[eval] {input_file.name} status=empty", file=sys.stderr)

    return None


def run_cli(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=SCRIPT_DIR.parent.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def parse_extraction_stdout(stdout: str, args: argparse.Namespace) -> dict[str, Any]:
    payload = json.loads(stdout)
    fallback = {
        "source_name": args.source_name,
        "source_url": args.source_url,
    }
    return normalize_response(payload, fallback)


def resolve_output_file(args: argparse.Namespace) -> Path:
    return args.output_file if args.output_file is not None else args.output_dir / "events.json"


def write_json_output(output_file: Path, payload: dict[str, Any]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
