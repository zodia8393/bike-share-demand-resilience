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


def to_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def to_int(value: Any) -> int | None:
    parsed = to_float(value)
    if parsed is None:
        return None
    return int(parsed)


def build_seoul_map_points(inventory: list[dict], priority: list[dict]) -> tuple[list[dict], dict]:
    priority_by_station = {
        str(row.get("station_id")): row
        for row in priority
        if row.get("station_id") not in {None, ""}
    }
    points: list[dict] = []
    excluded_missing_coordinates = 0
    for row in inventory:
        lat = to_float(row.get("station_lat"))
        lon = to_float(row.get("station_lon"))
        if lat is None or lon is None:
            excluded_missing_coordinates += 1
            continue
        station_id = str(row.get("station_id") or "")
        priority_row = priority_by_station.get(station_id, {})
        action = str(priority_row.get("recommended_action") or "monitor")
        issue = str(priority_row.get("issue_type") or "balanced")
        severity = to_float(priority_row.get("severity_score")) or 0.0
        marker_color = {
            "send_bikes": "#dc2626",
            "remove_bikes": "#2563eb",
            "monitor": "#0f766e",
        }.get(action, "#0f766e")
        points.append(
            {
                "station_id": station_id,
                "station_name": row.get("station_name"),
                "lat": lat,
                "lon": lon,
                "capacity": to_int(row.get("capacity")),
                "bikes_available": to_int(row.get("bikes_available")),
                "docks_available": to_int(row.get("docks_available")),
                "shared_rate": to_float(row.get("shared_rate")),
                "action": action,
                "issue_type": issue,
                "severity_score": severity,
                "priority_rank": to_int(priority_row.get("priority_rank")),
                "recommended_bikes_delta": to_int(priority_row.get("recommended_bikes_delta")) or 0,
                "marker_color": marker_color,
            }
        )
    summary = {
        "map_point_rows": len(points),
        "inventory_rows": len(inventory),
        "priority_rows": len(priority),
        "excluded_missing_coordinates": excluded_missing_coordinates,
        "action_counts": _count_by(points, "action"),
    }
    return clean_json(points), clean_json(summary)


def _count_by(rows: list[dict], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def load_service_payload(output_root: Path) -> dict:
    station_root = output_root / "station_level"
    report_dir = station_root / "reports"
    seoul_root = output_root / "seoul_ddareungi"
    seoul_report_dir = seoul_root / "reports"
    seoul_processed_dir = seoul_root / "data" / "processed"
    inventory_path = resolve_inventory_path(station_root)
    summary = read_json(report_dir / "station_run_summary.json")
    snapshot_readiness = read_json(report_dir / "station_snapshot_readiness.json")
    deploy_readiness = read_json(report_dir / "station_public_deploy_readiness.json")
    priority = read_csv_records(report_dir / "station_rebalancing_priority.csv", limit=50)
    inventory = read_csv_records(inventory_path, limit=200)
    quality = read_csv_records(report_dir / "station_quality_gate_checks.csv")
    seoul_priority = read_csv_records(seoul_report_dir / "rebalancing_priority.csv", limit=100)
    seoul_inventory = read_csv_records(seoul_processed_dir / "latest_inventory_snapshot.csv")
    seoul_inventory_summary = read_json(seoul_report_dir / "latest_inventory_snapshot_summary.json")
    seoul_priority_summary = read_json(seoul_report_dir / "rebalancing_priority_summary.json")
    seoul_validation_summary = read_json(seoul_report_dir / "validation_summary.json")
    seoul_model_metrics = read_json(seoul_report_dir / "model_metrics.json")
    seoul_map_points, seoul_map_summary = build_seoul_map_points(seoul_inventory, seoul_priority)
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
        "seoul_ddareungi": {
            "inventory_summary": seoul_inventory_summary,
            "priority_summary": seoul_priority_summary,
            "rebalancing_priority": seoul_priority,
            "inventory_snapshot": seoul_inventory,
            "map_points": seoul_map_points,
            "map_summary": seoul_map_summary,
            "validation_summary": seoul_validation_summary,
            "model_metrics": seoul_model_metrics,
        },
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
            "seoul_priority_rows": len(seoul_priority),
            "seoul_inventory_rows": len(seoul_inventory),
            "seoul_map_points": len(seoul_map_points),
            "seoul_map_excluded_missing_coordinates": seoul_map_summary.get("excluded_missing_coordinates"),
            "seoul_status": seoul_inventory_summary.get("status") or "missing",
            "seoul_priority_status": seoul_priority_summary.get("status") or "missing",
            "seoul_validation_status": seoul_validation_summary.get("validation_status") or "missing",
            "seoul_model_status": seoul_model_metrics.get("model_status") or "missing",
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
    seoul_priority_cols = [
        "priority_rank",
        "station_name",
        "issue_type",
        "recommended_action",
        "recommended_bikes_delta",
        "capacity",
        "bikes_available",
        "docks_available",
        "severity_score",
    ]
    seoul = payload.get("seoul_ddareungi", {})
    seoul_priority_summary = seoul.get("priority_summary", {})
    seoul_map_summary = seoul.get("map_summary", {})
    seoul_validation = seoul.get("validation_summary", {})
    seoul_model = seoul.get("model_metrics", {})
    quality_cols = ["gate", "passed", "evidence", "threshold"]
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bike-share Station Operations</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
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
    .map-panel {{ border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: white; }}
    #seoul-map {{ height: 520px; min-height: 360px; width: 100%; }}
    .map-fallback {{ display: grid; place-items: center; height: 100%; min-height: 360px; padding: 24px; color: var(--muted); text-align: center; }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 14px; padding: 10px 12px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }}
    .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
    .swatch {{ width: 10px; height: 10px; border-radius: 99px; display: inline-block; }}
    @media (max-width: 900px) {{
      header, main {{ padding-left: 18px; padding-right: 18px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(120px, 1fr)); }}
      #seoul-map {{ height: 420px; }}
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
      <div class="metric"><span>Seoul priority</span><strong>{html.escape(fmt(health.get("seoul_priority_rows"), 0))}</strong></div>
      <div class="metric"><span>Seoul map points</span><strong>{html.escape(fmt(seoul_map_summary.get("map_point_rows"), 0))}</strong></div>
      <div class="metric"><span>Seoul validation</span><strong>{html.escape(fmt(seoul_validation.get("validation_status") or health.get("seoul_validation_status")))}</strong></div>
      <div class="metric"><span>Seoul model</span><strong>{html.escape(fmt(seoul_model.get("model_status") or health.get("seoul_model_status")))}</strong></div>
      <div class="metric"><span>Seoul action</span><strong>{html.escape(fmt(seoul_priority_summary.get("action_counts")))}</strong></div>
    </section>
  </header>
  <main>
    <h2>Seoul Ddareungi Live Map</h2>
    <div class="map-panel">
      <div id="seoul-map" data-point-count="{html.escape(fmt(seoul_map_summary.get("map_point_rows"), 0))}">
        <div class="map-fallback">Map is loading. Priority table remains available below.</div>
      </div>
      <div class="legend">
        <span><i class="swatch" style="background:#dc2626"></i>send_bikes</span>
        <span><i class="swatch" style="background:#2563eb"></i>remove_bikes</span>
        <span><i class="swatch" style="background:#0f766e"></i>monitor</span>
      </div>
    </div>
    <h2>Seoul Validation Readiness</h2>
    <section class="metrics">
      <div class="metric"><span>Rule status</span><strong>{html.escape(fmt(seoul_validation.get("validation_status")))}</strong></div>
      <div class="metric"><span>Precision@10</span><strong>{html.escape(fmt(seoul_validation.get("precision_at_10"), 3))}</strong></div>
      <div class="metric"><span>Precision@50</span><strong>{html.escape(fmt(seoul_validation.get("precision_at_50"), 3))}</strong></div>
      <div class="metric"><span>Rule coverage</span><strong>{html.escape(fmt(seoul_validation.get("coverage"), 3))}</strong></div>
      <div class="metric"><span>Label rows</span><strong>{html.escape(fmt((seoul_validation.get("snapshot") or {}).get("label_rows"), 0))}</strong></div>
      <div class="metric"><span>ML status</span><strong>{html.escape(fmt(seoul_model.get("model_status")))}</strong></div>
      <div class="metric"><span>Best model</span><strong>{html.escape(fmt(seoul_model.get("best_model")))}</strong></div>
      <div class="metric"><span>Best F1</span><strong>{html.escape(fmt(seoul_model.get("best_f1"), 3))}</strong></div>
    </section>
    <h2>Seoul Ddareungi Live Priority</h2>
    <div class="wide">
      <table>
        <thead><tr>{"".join(f"<th>{html.escape(col)}</th>" for col in seoul_priority_cols)}</tr></thead>
        <tbody>{render_rows(seoul.get("rebalancing_priority", []), seoul_priority_cols)}</tbody>
      </table>
    </div>
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
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    (() => {{
      const mapEl = document.getElementById("seoul-map");
      if (!mapEl) return;
      const fallback = (message) => {{
        mapEl.innerHTML = `<div class="map-fallback">${{message}}</div>`;
      }};
      const esc = (value) => String(value ?? "-").replace(/[&<>"']/g, (ch) => ({{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }}[ch]));
      const colorFor = (point) => point.marker_color || {{
        send_bikes: "#dc2626",
        remove_bikes: "#2563eb",
        monitor: "#0f766e"
      }}[point.action] || "#0f766e";

      if (!window.L) {{
        fallback("Map library is unavailable. Priority table remains available below.");
        return;
      }}

      fetch("/api/seoul-ddareungi-map-points")
        .then((response) => {{
          if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
          return response.json();
        }})
        .then((points) => {{
          if (!Array.isArray(points) || points.length === 0) {{
            fallback("No Seoul map points are available.");
            return;
          }}
          mapEl.innerHTML = "";
          const map = L.map(mapEl, {{ scrollWheelZoom: false }}).setView([37.5665, 126.9780], 11);
          L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap contributors"
          }}).addTo(map);
          const bounds = [];
          points.forEach((point) => {{
            if (typeof point.lat !== "number" || typeof point.lon !== "number") return;
            const color = colorFor(point);
            const radius = point.action === "monitor" ? 4 : 7;
            const marker = L.circleMarker([point.lat, point.lon], {{
              radius,
              color,
              fillColor: color,
              fillOpacity: point.action === "monitor" ? 0.55 : 0.82,
              weight: point.action === "monitor" ? 1 : 2
            }}).addTo(map);
            marker.bindPopup(`
              <strong>${{esc(point.station_name)}}</strong><br>
              capacity: ${{esc(point.capacity)}}<br>
              bikes: ${{esc(point.bikes_available)}} / docks: ${{esc(point.docks_available)}}<br>
              action: ${{esc(point.action)}}<br>
              severity: ${{esc(point.severity_score)}}<br>
              rank: ${{esc(point.priority_rank)}}
            `);
            bounds.push([point.lat, point.lon]);
          }});
          if (bounds.length > 0) {{
            map.fitBounds(bounds, {{ padding: [22, 22], maxZoom: 14 }});
          }}
        }})
        .catch(() => fallback("Map data failed to load. Priority table remains available below."));
    }})();
  </script>
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
        if self.path == "/api/seoul-ddareungi-priority":
            self.send_json(payload["seoul_ddareungi"]["rebalancing_priority"])
            return
        if self.path == "/api/seoul-ddareungi-map-points":
            self.send_json(payload["seoul_ddareungi"]["map_points"])
            return
        if self.path == "/api/seoul-ddareungi-inventory":
            self.send_json(payload["seoul_ddareungi"]["inventory_snapshot"])
            return
        if self.path == "/api/seoul-ddareungi-summary":
            self.send_json(
                {
                    "inventory": payload["seoul_ddareungi"]["inventory_summary"],
                    "priority": payload["seoul_ddareungi"]["priority_summary"],
                }
            )
            return
        if self.path == "/api/seoul-ddareungi-validation":
            self.send_json(payload["seoul_ddareungi"]["validation_summary"])
            return
        if self.path == "/api/seoul-ddareungi-model-metrics":
            self.send_json(payload["seoul_ddareungi"]["model_metrics"])
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
                "/api/seoul-ddareungi-priority",
                "/api/seoul-ddareungi-map-points",
                "/api/seoul-ddareungi-inventory",
                "/api/seoul-ddareungi-summary",
                "/api/seoul-ddareungi-validation",
                "/api/seoul-ddareungi-model-metrics",
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
