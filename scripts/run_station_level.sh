#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_ROOT="${OUTPUT_ROOT:-/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience}"
TOP_STATIONS="${TOP_STATIONS:-35}"
SYNTHETIC_FLAG="${SYNTHETIC_FLAG:-}"

cd "$PROJECT_ROOT"
PYTHONPATH=src python3 -m bike_share_resilience.station_pipeline \
  --output-root "$OUTPUT_ROOT" \
  --top-stations "$TOP_STATIONS" \
  $SYNTHETIC_FLAG
