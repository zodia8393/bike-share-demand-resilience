from __future__ import annotations

import argparse
import html
import json
import math
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


KST = ZoneInfo("Asia/Seoul")
DEFAULT_OUTPUT_ROOT = Path("/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve station-level bike-share decision artifacts.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check", action="store_true", help="Validate dashboard payload and exit")
    return parser.parse_args()


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_json(item) for item in value]
    if isinstance(value, tuple):
        return [clean_json(item) for item in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        try:
            return clean_json(value.item())
        except ValueError:
            return str(value)
    if pd.isna(value):
        return None
    return value


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return clean_json(json.loads(path.read_text(encoding="utf-8")))


def read_csv_records(path: Path, *, limit: int | None = None) -> list[dict]:
    if not path.exists():
        return []
    frame = pd.read_csv(path)
    if limit is not None:
        frame = frame.head(limit)
    return clean_json(frame.to_dict(orient="records"))


def resolve_inventory_path(station_root: Path) -> Path:
    processed_dir = station_root / "data" / "processed"
    primary = processed_dir / "station_inventory_snapshot.csv"
    if primary.exists():
        return primary
    return processed_dir / "latest_inventory_snapshot.csv"


def load_service_payload(output_root: Path) -> dict:
    station_root = output_root / "station_level"
    report_dir = station_root / "reports"
    inventory_path = resolve_inventory_path(station_root)
    summary = read_json(report_dir / "station_run_summary.json")
    snapshot_readiness = read_json(report_dir / "station_snapshot_readiness.json")
    deploy_readiness = read_json(report_dir / "station_public_deploy_readiness.json")
    priority = read_csv_records(report_dir / "station_rebalancing_priority.csv", limit=50)
    inventory = read_csv_records(inventory_path, limit=200)
    quality = read_csv_records(report_dir / "station_quality_gate_checks.csv")
    failed_quality_rows = [
        str(row.get("gate"))
        for row in quality
        if str(row.get("passed")).lower() not in {"true", "1", "yes"}
    ]
    failed_gates = failed_quality_rows or summary.get("failed_quality_gates", [])
    quality_gate_passed = bool(summary.get("quality_gate_passed"))
    payload = {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "artifact_root": str(output_root),
        "summary": summary,
        "rebalancing_priority": priority,
        "inventory_snapshot": inventory,
        "snapshot_readiness": snapshot_readiness,
        "deploy_readiness": deploy_readiness,
        "quality_gates": quality,
        "health": {
            "status": "ok" if summary and priority and inventory and quality_gate_passed and not failed_gates else "degraded",
            "summary_available": bool(summary),
            "priority_rows": len(priority),
            "inventory_rows": len(inventory),
            "failed_gates": failed_gates,
            "quality_gate_passed": quality_gate_passed,
            "snapshot_ready": bool(snapshot_readiness.get("ready_for_prospective_validation")),
            "snapshot_count": snapshot_readiness.get("snapshot_count"),
            "snapshot_span_days": snapshot_readiness.get("span_days"),
            "deploy_decision": deploy_readiness.get("decision"),
            "inventory_path": str(inventory_path) if inventory_path.exists() else None,
        },
    }
    return clean_json(payload)


def validate_service_payload(payload: dict) -> list[str]:
    errors = []
    health = payload.get("health", {})
    if not health.get("summary_available"):
        errors.append("station_run_summary.json is missing")
    if health.get("priority_rows", 0) <= 0:
        errors.append("station_rebalancing_priority.csv has no rows")
    if health.get("inventory_rows", 0) <= 0:
        errors.append("station inventory snapshot has no rows")
    if health.get("summary_available") and not health.get("quality_gate_passed"):
        errors.append("station quality gate is not passed")
    if health.get("failed_gates"):
        errors.append(f"quality gates failed: {health['failed_gates']}")
    return errors


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,.{digits}f}"
    return str(value)


def render_rows(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return '<tr><td colspan="99">No rows</td></tr>'
    rendered = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(fmt(row.get(col)))}</td>" for col in columns)
        rendered.append(f"<tr>{cells}</tr>")
    return "\n".join(rendered)


def render_dashboard_html(payload: dict) -> str:
    health = payload["health"]
    summary = payload.get("summary", {})
    metadata = summary.get("metadata", {})
    frame = metadata.get("frame", {})
    model = summary.get("best_model", "-")
    mae = summary.get("best_test_mae")
    baseline = summary.get("baseline_test_mae")
    coverage = summary.get("conformal_summary", {}).get("conformal_test_coverage")
    status_class = "ok" if health["status"] == "ok" else "degraded"
    priority_cols = [
        "station_short_name",
        "station_name",
        "forecast_24h",
        "num_bikes_available",
        "current_bike_shortage",
        "risk_score",
        "recommended_buffer_bikes",
    ]
    inventory_cols = [
        "station_short_name",
        "station_name",
        "num_bikes_available",
        "num_docks_available",
        "current_bike_shortage",
        "current_dock_shortage",
        "inventory_pressure",
    ]
    quality_cols = ["gate", "passed", "evidence", "threshold"]
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bike-share Station Operations</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172026;
      --muted: #5b6770;
      --line: #d8dee4;
      --paper: #f7f8f9;
      --accent: #0f766e;
      --warn: #a15c07;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; color: var(--ink); font: 14px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: white; }}
    header {{ padding: 28px 32px 20px; border-bottom: 1px solid var(--line); background: var(--paper); }}
    main {{ padding: 24px 32px 40px; max-width: 1440px; margin: 0 auto; }}
    h1 {{ margin: 0 0 10px; font-size: 28px; font-weight: 700; letter-spacing: 0; }}
    h2 {{ margin: 30px 0 12px; font-size: 18px; letter-spacing: 0; }}
    .status {{ display: inline-flex; align-items: center; gap: 8px; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--line); background: white; }}
    .dot {{ width: 9px; height: 9px; border-radius: 99px; background: var(--warn); }}
    .status.ok .dot {{ background: var(--accent); }}
    .metrics {{ display: grid; grid-template-columns: repeat(8, minmax(120px, 1fr)); gap: 12px; margin-top: 20px; }}
    .metric {{ border-top: 3px solid var(--accent); background: white; padding: 12px 0; }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ display: block; margin-top: 2px; font-size: 20px; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }}
    th {{ background: var(--paper); color: var(--muted); font-size: 12px; font-weight: 650; }}
    .wide {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }}
    .wide table {{ min-width: 980px; }}
    @media (max-width: 900px) {{
      header, main {{ padding-left: 18px; padding-right: 18px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(120px, 1fr)); }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Bike-share Station Operations</h1>
    <div class="status {status_class}"><span class="dot"></span><span>{html.escape(health["status"])}</span></div>
    <section class="metrics">
      <div class="metric"><span>Best model</span><strong>{html.escape(fmt(model))}</strong></div>
      <div class="metric"><span>Test MAE</span><strong>{html.escape(fmt(mae, 3))}</strong></div>
      <div class="metric"><span>Baseline MAE</span><strong>{html.escape(fmt(baseline, 3))}</strong></div>
      <div class="metric"><span>Conformal coverage</span><strong>{html.escape(fmt(coverage, 3))}</strong></div>
      <div class="metric"><span>Stations</span><strong>{html.escape(fmt(frame.get("station_count"), 0))}</strong></div>
      <div class="metric"><span>Inventory rows</span><strong>{html.escape(fmt(health.get("inventory_rows"), 0))}</strong></div>
      <div class="metric"><span>Snapshot count</span><strong>{html.escape(fmt(health.get("snapshot_count"), 0))}</strong></div>
      <div class="metric"><span>Deploy decision</span><strong>{html.escape(fmt(health.get("deploy_decision")))}</strong></div>
    </section>
  </header>
  <main>
    <h2>Rebalancing Priority</h2>
    <div class="wide">
      <table>
        <thead><tr>{"".join(f"<th>{html.escape(col)}</th>" for col in priority_cols)}</tr></thead>
        <tbody>{render_rows(payload["rebalancing_priority"], priority_cols)}</tbody>
      </table>
    </div>
    <h2>Inventory Snapshot</h2>
    <div class="wide">
      <table>
        <thead><tr>{"".join(f"<th>{html.escape(col)}</th>" for col in inventory_cols)}</tr></thead>
        <tbody>{render_rows(payload["inventory_snapshot"][:50], inventory_cols)}</tbody>
      </table>
    </div>
    <h2>Quality Gates</h2>
    <div class="wide">
      <table>
        <thead><tr>{"".join(f"<th>{html.escape(col)}</th>" for col in quality_cols)}</tr></thead>
        <tbody>{render_rows(payload["quality_gates"], quality_cols)}</tbody>
      </table>
    </div>
  </main>
</body>
</html>"""


class StationServiceHandler(BaseHTTPRequestHandler):
    output_root = DEFAULT_OUTPUT_ROOT

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_payload(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(clean_json(payload), ensure_ascii=False, indent=2).encode("utf-8")
        self.send_payload(status, "application/json; charset=utf-8", body)

    def do_GET(self) -> None:
        payload = load_service_payload(self.output_root)
        if self.path in {"/", "/dashboard"}:
            body = render_dashboard_html(payload).encode("utf-8")
            self.send_payload(200, "text/html; charset=utf-8", body)
            return
        if self.path == "/health":
            self.send_json(payload["health"], status=200 if payload["health"]["status"] == "ok" else 503)
            return
        if self.path == "/api/summary":
            self.send_json(payload["summary"])
            return
        if self.path == "/api/rebalancing-priority":
            self.send_json(payload["rebalancing_priority"])
            return
        if self.path == "/api/inventory-snapshot":
            self.send_json(payload["inventory_snapshot"])
            return
        if self.path == "/api/snapshot-readiness":
            self.send_json(payload["snapshot_readiness"])
            return
        if self.path == "/api/deploy-readiness":
            self.send_json(payload["deploy_readiness"])
            return
        self.send_json({"error": "not found"}, status=404)


def main() -> None:
    args = parse_args()
    output_root = Path(args.output_root)
    payload = load_service_payload(output_root)
    if args.check:
        errors = validate_service_payload(payload)
        check = {
            "ok": not errors,
            "errors": errors,
            "health": payload["health"],
            "endpoints": [
                "/health",
                "/api/summary",
                "/api/rebalancing-priority",
                "/api/inventory-snapshot",
                "/api/snapshot-readiness",
                "/api/deploy-readiness",
                "/",
            ],
        }
        print(json.dumps(clean_json(check), ensure_ascii=False, indent=2))
        raise SystemExit(0 if not errors else 1)

    StationServiceHandler.output_root = output_root
    server = ThreadingHTTPServer((args.host, args.port), StationServiceHandler)
    print(f"Serving station dashboard at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
