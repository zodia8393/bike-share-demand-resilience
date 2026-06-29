from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from bike_share_resilience.station_prospective_validation import (
    ProspectiveValidationConfig,
    evaluate_prospective_validation,
)


KST = ZoneInfo("Asia/Seoul")


def write_readiness(root: Path, ready: bool, snapshot_count: int = 400) -> None:
    report_dir = root / "station_level" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "ready_for_prospective_validation": ready,
        "snapshot_count": snapshot_count,
        "target_snapshots": 336,
        "span_days": 14.1 if ready else 0.5,
    }
    (report_dir / "station_snapshot_readiness.json").write_text(json.dumps(payload), encoding="utf-8")


def write_label_panel(root: Path, hours: int = 120) -> None:
    processed_dir = root / "station_level" / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 6, 1, 0, 0, tzinfo=KST)
    rows = []
    for station_idx, station in enumerate(["JC001", "JC002", "JC003"]):
        for hour in range(hours):
            captured_at = start + timedelta(hours=hour)
            shortage_block = (hour + station_idx) % 8 in {1, 2, 3}
            next_shortage = (hour + 1 + station_idx) % 8 in {1, 2, 3}
            bikes = 1 if shortage_block else 9
            rows.append(
                {
                    "station_short_name": station,
                    "gbfs_station_id": f"gbfs-{station_idx}",
                    "captured_at": captured_at.isoformat(),
                    "capacity": 20,
                    "num_bikes_available": bikes,
                    "num_docks_available": 20 - bikes,
                    "inventory_pressure": 1 - bikes / 20,
                    "current_bike_shortage": shortage_block,
                    "current_dock_shortage": False,
                    "bike_shortage_next_snapshot": next_shortage,
                    "next_gap_minutes": 60,
                }
            )
    pd.DataFrame(rows).to_csv(processed_dir / "station_shortage_label_panel.csv", index=False)


def test_prospective_validation_waits_for_snapshot_readiness(tmp_path):
    write_readiness(tmp_path, ready=False, snapshot_count=12)

    payload = evaluate_prospective_validation(tmp_path, ProspectiveValidationConfig(min_label_rows=10))

    assert payload["validation_status"] == "NOT_READY"
    assert payload["reason"] == "snapshot readiness gate is not ready"
    assert (tmp_path / "station_level" / "reports" / "station_prospective_validation.json").exists()


def test_prospective_validation_evaluates_ready_label_panel(tmp_path):
    write_readiness(tmp_path, ready=True)
    write_label_panel(tmp_path)

    payload = evaluate_prospective_validation(tmp_path, ProspectiveValidationConfig(min_label_rows=50))
    metrics = pd.read_csv(tmp_path / "station_level" / "reports" / "station_prospective_validation_metrics.csv")

    assert payload["validation_status"] == "PASS"
    assert payload["best_model"] in set(metrics["model"])
    assert {"persistence_baseline", "station_hour_profile", "logistic_inventory_model"}.issubset(set(metrics["model"]))
    assert payload["test_rows"] > 0
