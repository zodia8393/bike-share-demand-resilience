from pathlib import Path
import json

import pandas as pd

from bike_share_resilience.station_service import (
    load_service_payload,
    render_dashboard_html,
    validate_service_payload,
)


def write_service_artifacts(root: Path) -> None:
    report_dir = root / "station_level" / "reports"
    processed_dir = root / "station_level" / "data" / "processed"
    report_dir.mkdir(parents=True)
    processed_dir.mkdir(parents=True)
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


def test_station_service_payload_and_dashboard(tmp_path):
    write_service_artifacts(tmp_path)

    payload = load_service_payload(tmp_path)
    errors = validate_service_payload(payload)
    html = render_dashboard_html(payload)

    assert errors == []
    assert payload["health"]["status"] == "ok"
    assert payload["health"]["priority_rows"] == 1
    assert payload["health"]["inventory_rows"] == 1
    assert "Bike-share Station Operations" in html
    assert "JC001" in html
