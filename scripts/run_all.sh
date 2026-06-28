#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_ROOT="${OUTPUT_ROOT:-/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience}"
REPORT_DIR="${REPORT_DIR:-/DATA/HJ/prj/data-scientist-career/reports}"

cd "$PROJECT_ROOT"
PYTHONPATH=src python3 -m bike_share_resilience.pipeline \
  --output-root "$OUTPUT_ROOT" \
  --report-dir "$REPORT_DIR"
python3 -m pytest tests
