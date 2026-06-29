#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_ROOT="${OUTPUT_ROOT:-/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience}"
SYNTHETIC_FLAG="${SYNTHETIC_FLAG:-}"

if [ -z "${LOG_DIR:-}" ]; then
  if mkdir -p /workspace/_codex/scripts/logs 2>/dev/null; then
    LOG_DIR="/workspace/_codex/scripts/logs"
  else
    LOG_DIR="$OUTPUT_ROOT/station_level/reports"
  fi
fi
mkdir -p "$LOG_DIR"

cd "$PROJECT_ROOT"
python3 scripts/capture_station_status_snapshot.py \
  --output-root "$OUTPUT_ROOT" \
  $SYNTHETIC_FLAG

PYTHONPATH=src python3 -m bike_share_resilience.station_snapshot_analysis \
  --output-root "$OUTPUT_ROOT"

PYTHONPATH=src python3 -m bike_share_resilience.station_prospective_validation \
  --output-root "$OUTPUT_ROOT"

python3 scripts/check_public_deploy_readiness.py \
  --output-root "$OUTPUT_ROOT" \
  --report-only

printf 'ok %s output_root=%s\n' "$(date '+%F %T')" "$OUTPUT_ROOT" > "$LOG_DIR/bike-share-station-snapshot-ok"
printf 'ok %s output_root=%s\n' "$(date '+%F %T')" "$OUTPUT_ROOT" > "$LOG_DIR/bike-share-station-snapshot-ok-$(date '+%Y%m%d')"
