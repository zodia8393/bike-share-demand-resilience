#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bike_share_resilience.seoul_ddareungi import (  # noqa: E402
    DEFAULT_ENV_PATH,
    DEFAULT_OUTPUT_ROOT,
    SEOUL_OPEN_DATA_API_KEY_ENV,
    SeoulDdareungiError,
    build_redacted_bike_list_url,
    fetch_bike_list,
    resolve_api_key,
    validate_bike_list_schema,
    write_schema_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Seoul Ddareungi bikeList response schema.")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=5)
    parser.add_argument("--full-scan", action="store_true", help="Validate paged 1000-row ranges until the last partial page.")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--min-rows", type=int, default=1)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.full_scan:
            return _run_full_scan(args)

        return _run_single_range(args, args.start, args.end)
    except ValueError as exc:
        summary = {
            "ok": False,
            "status": "invalid_args",
            "dataset": "seoul_ddareungi_bikeList",
            "required_env": SEOUL_OPEN_DATA_API_KEY_ENV,
            "message": str(exc),
        }
        _emit(summary, args)
        return 2


def _run_single_range(args: argparse.Namespace, start: int, end: int) -> int:
    summary = {
        "ok": False,
        "status": "not_started",
        "dataset": "seoul_ddareungi_bikeList",
        "required_env": SEOUL_OPEN_DATA_API_KEY_ENV,
        "request_url": build_redacted_bike_list_url(start, end),
        "checked_range": {"start": start, "end": end},
    }

    api_key = resolve_api_key(env_file=args.env_file)
    if not api_key:
        summary["status"] = "missing_api_key"
        summary["message"] = f"set {SEOUL_OPEN_DATA_API_KEY_ENV} in environment or env file"
        _emit(summary, args)
        return 2

    try:
        payload = fetch_bike_list(api_key, start=start, end=end, timeout=args.timeout)
        schema_summary = validate_bike_list_schema(payload, min_rows=args.min_rows)
    except SeoulDdareungiError as exc:
        summary["status"] = "fetch_or_parse_failed"
        summary["error_type"] = exc.__class__.__name__
        summary["message"] = str(exc)
        _emit(summary, args)
        return 1

    schema_summary.update(
        {
            "status": "schema_ok" if schema_summary["ok"] else "schema_failed",
            "request_url": build_redacted_bike_list_url(start, end),
            "checked_range": {"start": start, "end": end},
        }
    )
    _emit(schema_summary, args)
    return 0 if schema_summary["ok"] else 1


def _run_full_scan(args: argparse.Namespace) -> int:
    api_key = resolve_api_key(env_file=args.env_file)
    summary = {
        "ok": False,
        "status": "not_started",
        "dataset": "seoul_ddareungi_bikeList",
        "required_env": SEOUL_OPEN_DATA_API_KEY_ENV,
        "page_size": args.page_size,
        "max_pages": args.max_pages,
        "pages_checked": 0,
        "total_rows_checked": 0,
        "stopped_reason": None,
        "pages": [],
    }
    if not api_key:
        summary["status"] = "missing_api_key"
        summary["message"] = f"set {SEOUL_OPEN_DATA_API_KEY_ENV} in environment or env file"
        _emit(summary, args)
        return 2
    if args.max_pages < 1:
        summary["status"] = "invalid_args"
        summary["message"] = "max_pages must be >= 1"
        _emit(summary, args)
        return 2
    if not 1 <= args.page_size <= 1000:
        summary["status"] = "invalid_args"
        summary["message"] = "page_size must be between 1 and 1000"
        _emit(summary, args)
        return 2

    all_ok = True
    for page_index in range(args.max_pages):
        start = args.start + page_index * args.page_size
        end = start + args.page_size - 1
        page_summary = {
            "ok": False,
            "status": "not_started",
            "request_url": build_redacted_bike_list_url(start, end),
            "checked_range": {"start": start, "end": end},
        }
        try:
            payload = fetch_bike_list(api_key, start=start, end=end, timeout=args.timeout)
            page_summary.update(validate_bike_list_schema(payload, min_rows=args.min_rows))
            page_summary["status"] = "schema_ok" if page_summary["ok"] else "schema_failed"
        except SeoulDdareungiError as exc:
            page_summary["status"] = "fetch_or_parse_failed"
            page_summary["error_type"] = exc.__class__.__name__
            page_summary["message"] = str(exc)

        summary["pages"].append(page_summary)
        summary["pages_checked"] += 1
        summary["total_rows_checked"] += int(page_summary.get("row_count") or 0)
        all_ok = all_ok and bool(page_summary["ok"])

        if not page_summary["ok"]:
            summary["stopped_reason"] = "page_failed"
            break
        if int(page_summary.get("row_count") or 0) < args.page_size:
            summary["stopped_reason"] = "last_partial_page"
            break
    else:
        summary["stopped_reason"] = "max_pages_reached"
        all_ok = False

    summary["ok"] = all_ok
    summary["status"] = "schema_ok" if all_ok else "schema_incomplete_or_failed"
    _emit(summary, args)
    return 0 if all_ok else 1


def _emit(summary: dict, args: argparse.Namespace) -> None:
    if not args.no_write_report:
        report_path = write_schema_report(summary, args.output_root)
        summary["report_path"] = str(report_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
