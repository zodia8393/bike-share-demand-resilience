from pathlib import Path
import json

import pandas as pd

from bike_share_resilience.station_service import (
    build_seoul_map_points,
    load_service_payload,
    render_dashboard_html,
    validate_service_payload,
)


def write_service_artifacts(root: Path) -> None:
    report_dir = root / "station_level" / "reports"
    processed_dir = root / "station_level" / "data" / "processed"
    seoul_report_dir = root / "seoul_ddareungi" / "reports"
    seoul_processed_dir = root / "seoul_ddareungi" / "data" / "processed"
    report_dir.mkdir(parents=True)
    processed_dir.mkdir(parents=True)
    seoul_report_dir.mkdir(parents=True)
    seoul_processed_dir.mkdir(parents=True)
    summary = {
        "best_model": "gradient_boosting",
        "baseline_test_mae": 1.2,
        "best_test_mae": 1.0,
        "conformal_summary": {"conformal_test_coverage": 0.9},
        "quality_gate_passed": True,
        "failed_quality_gates": [],
        "metadata": {"frame": {"station_count": 2}},
    }
    (report_dir / "station_run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (report_dir / "station_snapshot_readiness.json").write_text(
        json.dumps({"ready_for_prospective_validation": True, "snapshot_count": 400, "span_days": 14.1}),
        encoding="utf-8",
    )
    (report_dir / "station_public_deploy_readiness.json").write_text(
        json.dumps({"decision": "GO", "blockers": []}),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "station_short_name": "JC001",
                "station_name": "A",
                "forecast_24h": 20.0,
                "num_bikes_available": 1,
                "current_bike_shortage": True,
                "risk_score": 1.5,
                "recommended_buffer_bikes": 2,
            }
        ]
    ).to_csv(report_dir / "station_rebalancing_priority.csv", index=False)
    pd.DataFrame(
        [
            {
                "station_short_name": "JC001",
                "station_name": "A",
                "num_bikes_available": 1,
                "num_docks_available": 20,
                "current_bike_shortage": True,
                "current_dock_shortage": False,
                "inventory_pressure": 0.95,
            }
        ]
    ).to_csv(processed_dir / "station_inventory_snapshot.csv", index=False)
    pd.DataFrame(
        [
            {
                "gate": "inventory snapshot",
                "passed": True,
                "evidence": "inventory_join_rate=100.0%",
                "threshold": ">=80%",
            }
        ]
    ).to_csv(report_dir / "station_quality_gate_checks.csv", index=False)
    pd.DataFrame(
        [
            {
                "priority_rank": 1,
                "station_id": "ST-1",
                "station_name": "Seoul A",
                "issue_type": "dock_shortage",
                "recommended_action": "remove_bikes",
                "severity_score": 2.0,
                "recommended_bikes_delta": -5,
                "capacity": 10,
                "bikes_available": 10,
                "docks_available": 0,
                "station_lat": 37.566,
                "station_lon": 126.978,
            }
        ]
    ).to_csv(seoul_report_dir / "rebalancing_priority.csv", index=False)
    pd.DataFrame(
        [
            {
                "station_id": "ST-1",
                "station_name": "Seoul A",
                "capacity": 10,
                "bikes_available": 10,
                "docks_available": 0,
                "station_lat": 37.566,
                "station_lon": 126.978,
            }
        ]
    ).to_csv(seoul_processed_dir / "latest_inventory_snapshot.csv", index=False)
    (seoul_report_dir / "latest_inventory_snapshot_summary.json").write_text(
        json.dumps({"status": "inventory_ok", "row_count": 1}),
        encoding="utf-8",
    )
    (seoul_report_dir / "rebalancing_priority_summary.json").write_text(
        json.dumps({"status": "priority_ok", "priority_rows": 1, "action_counts": {"remove_bikes": 1}}),
        encoding="utf-8",
    )
    (seoul_report_dir / "validation_summary.json").write_text(
        json.dumps(
            {
                "validation_status": "READY",
                "precision_at_10": 0.5,
                "precision_at_50": 0.4,
                "coverage": 1.0,
                "snapshot": {"label_rows": 2},
            }
        ),
        encoding="utf-8",
    )
    (seoul_report_dir / "model_metrics.json").write_text(
        json.dumps({"model_status": "NOT_READY", "reason": "fixture"}),
        encoding="utf-8",
    )


def test_station_service_payload_and_dashboard(tmp_path):
    write_service_artifacts(tmp_path)

    payload = load_service_payload(tmp_path)
    errors = validate_service_payload(payload)
    html = render_dashboard_html(payload)

    assert errors == []
    assert payload["health"]["status"] == "ok"
    assert payload["health"]["priority_rows"] == 1
    assert payload["health"]["inventory_rows"] == 1
    assert payload["health"]["seoul_priority_rows"] == 1
    assert payload["health"]["seoul_inventory_rows"] == 1
    assert payload["health"]["seoul_map_points"] == 1
    assert payload["health"]["seoul_validation_status"] == "READY"
    assert payload["health"]["seoul_model_status"] == "NOT_READY"
    assert payload["health"]["snapshot_ready"] is True
    assert payload["health"]["deploy_decision"] == "GO"
    assert payload["seoul_ddareungi"]["rebalancing_priority"][0]["station_name"] == "Seoul A"
    assert payload["seoul_ddareungi"]["map_points"][0]["action"] == "remove_bikes"
    assert payload["seoul_ddareungi"]["map_points"][0]["lat"] == 37.566
    assert "Bike-share Station Operations" in html
    assert "Seoul Ddareungi Live Map" in html
    assert "seoul-ddareungi-map-points" in html
    assert "leaflet" in html.lower()
    assert "Seoul Ddareungi Live Priority" in html
    assert "Seoul Validation Readiness" in html
    assert "Seoul A" in html
    assert "JC001" in html


def test_build_seoul_map_points_excludes_missing_coordinates():
    points, summary = build_seoul_map_points(
        [
            {
                "station_id": "A",
                "station_name": "Valid",
                "capacity": 10,
                "bikes_available": 0,
                "docks_available": 10,
                "station_lat": 37.5,
                "station_lon": 127.0,
            },
            {
                "station_id": "B",
                "station_name": "No coordinate",
                "capacity": 10,
                "bikes_available": 5,
                "docks_available": 5,
            },
        ],
        [
            {
                "station_id": "A",
                "recommended_action": "send_bikes",
                "issue_type": "bike_shortage",
                "severity_score": 1.5,
                "priority_rank": 1,
                "recommended_bikes_delta": 2,
            }
        ],
    )

    assert len(points) == 1
    assert points[0]["action"] == "send_bikes"
    assert summary["excluded_missing_coordinates"] == 1
