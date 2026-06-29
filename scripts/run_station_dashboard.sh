#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_ROOT="${OUTPUT_ROOT:-/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"

cd "$PROJECT_ROOT"
PYTHONPATH=src python3 -m bike_share_resilience.station_service \
  --output-root "$OUTPUT_ROOT" \
  --host "$HOST" \
  --port "$PORT"
