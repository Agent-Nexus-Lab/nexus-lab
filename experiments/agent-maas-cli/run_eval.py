from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


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
    failures = 0
    for input_file in selected_files:
        suffix = ".request.json" if args.dry_run else ".json"
        output_file = args.output_dir / f"{input_file.stem}{suffix}"
        command = build_command(args, input_file, output_file)
        print(f"[eval] {input_file.name} -> {output_file.name}", flush=True)
        result = subprocess.run(command, cwd=SCRIPT_DIR.parent.parent, capture_output=True, text=True)
        if result.returncode != 0:
            failures += 1
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            if args.stop_on_error:
                return result.returncode
            continue

        status = read_output_status(output_file, args.dry_run)
        if status != "completed" and status != "dry_run":
            failures += 1
            print(f"[eval] {input_file.name} status={status}", file=sys.stderr)
            if args.stop_on_error:
                return 1

    total = len(selected_files)
    ok = total - failures
    print(f"[eval] done: {ok}/{total} succeeded, {failures} failed")
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量运行 MaaS 活动信息抽取测评，默认处理 texts/ 下所有文件。"
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
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
    parser.add_argument("--api-style", choices=["openai", "v2"])
    parser.add_argument("--thinking", choices=["default", "enabled", "disabled"], default="disabled")
    parser.add_argument("--reasoning-effort", choices=["high", "max"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-verify-ssl", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


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


def build_command(args: argparse.Namespace, input_file: Path, output_file: Path) -> list[str]:
    command = [
        sys.executable,
        str(CLI_PATH),
        "--input-file",
        str(input_file),
        "--output-file",
        str(output_file),
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


def read_output_status(output_file: Path, dry_run: bool) -> str:
    if dry_run:
        return "dry_run"
    try:
        payload = json.loads(output_file.read_text(encoding="utf-8"))
    except Exception:
        return "invalid_output"
    events = payload.get("events")
    if not isinstance(events, list):
        return "invalid_output"
    return "completed" if events else "empty"


if __name__ == "__main__":
    raise SystemExit(main())
