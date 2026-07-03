#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_ROOT="${OUTPUT_ROOT:-/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience}"
ENV_FILE="${ENV_FILE:-/workspace/.env}"
PAGE_SIZE="${PAGE_SIZE:-1000}"
MAX_PAGES="${MAX_PAGES:-5}"
TIMEOUT="${TIMEOUT:-15}"
MIN_ROWS="${MIN_ROWS:-2000}"
PRIORITY_TOP_N="${PRIORITY_TOP_N:-50}"

if [ -z "${LOG_DIR:-}" ]; then
  if mkdir -p /workspace/_codex/scripts/logs 2>/dev/null; then
    LOG_DIR="/workspace/_codex/scripts/logs"
  else
    LOG_DIR="$OUTPUT_ROOT/seoul_ddareungi/reports"
  fi
fi
mkdir -p "$LOG_DIR"

cd "$PROJECT_ROOT"
python3 scripts/capture_seoul_ddareungi_snapshot.py \
  --output-root "$OUTPUT_ROOT" \
  --env-file "$ENV_FILE" \
  --page-size "$PAGE_SIZE" \
  --max-pages "$MAX_PAGES" \
  --timeout "$TIMEOUT" \
  --min-rows "$MIN_ROWS" \
  --priority-top-n "$PRIORITY_TOP_N"

PYTHONPATH=src python3 scripts/run_seoul_ddareungi_validation.py \
  --output-root "$OUTPUT_ROOT"

printf 'ok %s output_root=%s\n' "$(date '+%F %T')" "$OUTPUT_ROOT" > "$LOG_DIR/seoul-ddareungi-snapshot-ok"
printf 'ok %s output_root=%s\n' "$(date '+%F %T')" "$OUTPUT_ROOT" > "$LOG_DIR/seoul-ddareungi-snapshot-ok-$(date '+%Y%m%d')"
