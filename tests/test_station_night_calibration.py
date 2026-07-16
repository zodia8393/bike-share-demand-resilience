from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from bike_share_resilience.station_night_calibration import (
    NightCalibrationConfig,
    build_calibration_result,
    evaluate_night_calibration,
)
from bike_share_resilience.station_prospective_validation import (
    TARGET_COL,
    load_label_panel,
    prepare_model_frame,
    temporal_split,
)


KST = ZoneInfo("Asia/Seoul")


def write_frozen_readiness(root: Path, include_cutoff: bool = True) -> None:
    report_dir = root / "station_level" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "ready_for_prospective_validation": True,
        "snapshot_cutoff_at": "2026-07-13T14:15:03+09:00" if include_cutoff else None,
    }
    (report_dir / "station_snapshot_readiness.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def write_label_panel(root: Path, hours: int = 160) -> None:
    processed_dir = root / "station_level" / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 6, 1, tzinfo=KST)
    rows = []
    for station_index in range(3):
        for hour_index in range(hours):
            captured_at = start + timedelta(hours=hour_index)
            current_shortage = (hour_index + station_index) % 7 in {0, 1}
            next_shortage = (hour_index + station_index + 1) % 7 in {0, 1}
            bikes = 1 if current_shortage else 10
            rows.append(
                {
                    "gbfs_station_id": f"station-{station_index}",
                    "station_short_name": f"S{station_index}",
                    "captured_at": captured_at.isoformat(),
                    "capacity": 20,
                    "num_bikes_available": bikes,
                    "num_docks_available": 20 - bikes,
                    "inventory_pressure": 1 - bikes / 20,
                    "current_bike_shortage": current_shortage,
                    "current_dock_shortage": False,
                    TARGET_COL: next_shortage,
                }
            )
    pd.DataFrame(rows).to_csv(
        processed_dir / "station_shortage_label_panel.csv",
        index=False,
    )


def test_night_calibration_writes_leakage_safe_comparison(tmp_path):
    write_frozen_readiness(tmp_path)
    write_label_panel(tmp_path)

    payload = evaluate_night_calibration(
        tmp_path,
        NightCalibrationConfig(min_label_rows=100),
    )
    comparison = pd.read_csv(
        tmp_path / "station_level" / "reports" / "station_night_threshold_comparison.csv"
    )

    assert payload["status"] == "PASS"
    assert payload["fit_end"] < payload["calibration_start"]
    assert payload["calibration_end"] < payload["test_start"]
    assert payload["decision"] in {
        "KEEP_PERSISTENCE_BASELINE",
        "USE_LOGISTIC_NIGHT_CALIBRATED",
    }
    assert {"all", "night", "non_night"} == set(comparison["segment"])
    assert {"calibration", "test"} == set(comparison["split"])
    assert {"f1", "precision", "recall", "average_precision", "brier"}.issubset(
        comparison.columns
    )


def test_night_thresholds_do_not_change_when_only_test_targets_change(tmp_path):
    write_label_panel(tmp_path)
    frame = prepare_model_frame(load_label_panel(tmp_path))
    config = NightCalibrationConfig(min_label_rows=100)
    original, _, _, _ = build_calibration_result(frame, config)
    train, test = temporal_split(frame, config.test_fraction)
    changed = frame.copy()
    changed.loc[test.index, TARGET_COL] = 1 - changed.loc[test.index, TARGET_COL]

    modified, _, _, _ = build_calibration_result(changed, config)

    assert len(train) + len(test) == len(frame)
    assert modified["global_threshold"] == original["global_threshold"]
    assert modified["night_threshold"] == original["night_threshold"]


def test_night_calibration_requires_frozen_cutoff(tmp_path):
    write_frozen_readiness(tmp_path, include_cutoff=False)
    write_label_panel(tmp_path)

    payload = evaluate_night_calibration(
        tmp_path,
        NightCalibrationConfig(min_label_rows=100),
    )

    assert payload["status"] == "NOT_READY"
    assert payload["decision"] == "KEEP_PERSISTENCE_BASELINE"
    assert "cutoff" in payload["reason"]


def test_night_calibration_rejects_split_without_night_rows():
    rows = []
    for day in range(20):
        for station in range(2):
            rows.append(
                {
                    "captured_at": datetime(2026, 6, 1, 12, tzinfo=KST)
                    + timedelta(days=day),
                    "hour": 12,
                    TARGET_COL: (day + station) % 2,
                    "current_bike_shortage_int": day % 2,
                    "current_dock_shortage_int": 0,
                    "capacity": 20,
                    "num_bikes_available": 10,
                    "num_docks_available": 10,
                    "inventory_pressure": 0.5,
                    "dayofweek": day % 7,
                    "is_weekend": int(day % 7 in {5, 6}),
                    "gbfs_station_id": str(station),
                }
            )

    with pytest.raises(ValueError, match="no night rows"):
        build_calibration_result(
            pd.DataFrame(rows),
            NightCalibrationConfig(min_label_rows=10),
        )
