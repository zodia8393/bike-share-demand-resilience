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
    capture_realtime_inventory,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Seoul Ddareungi live inventory snapshot.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--min-rows", type=int, default=2000)
    parser.add_argument("--priority-top-n", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = capture_realtime_inventory(
            args.output_root,
            env_file=args.env_file,
            page_size=args.page_size,
            max_pages=args.max_pages,
            timeout=args.timeout,
            min_rows=args.min_rows,
            priority_top_n=args.priority_top_n,
        )
    except (SeoulDdareungiError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": "capture_failed",
                    "required_env": SEOUL_OPEN_DATA_API_KEY_ENV,
                    "message": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
