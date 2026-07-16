from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from bike_share_resilience.station_prospective_validation import (
    ProspectiveValidationConfig,
    TARGET_COL,
    drift_audit,
    evaluate_prospective_validation,
    load_label_panel,
    prepare_model_frame,
    rolling_origin_splits,
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


def append_unlabeled_latest_snapshot(root: Path) -> None:
    path = root / "station_level" / "data" / "processed" / "station_shortage_label_panel.csv"
    panel = pd.read_csv(path)
    latest = panel.groupby("gbfs_station_id", sort=False).tail(1).copy()
    latest["captured_at"] = (pd.to_datetime(latest["captured_at"], utc=True) + pd.Timedelta(hours=1)).map(
        lambda value: value.isoformat()
    )
    latest["bike_shortage_next_snapshot"] = pd.NA
    pd.concat([panel, latest], ignore_index=True).to_csv(path, index=False)


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
    assert payload["label_rows"] == 360
    assert payload["test_rows"] > 0
    assert payload["rolling_origin_fold_count"] == 3
    assert payload["rolling_origin_model_rows"] == 9
    assert payload["feature_ablation_rows"] == 3
    assert payload["drift_checks_passed"] == payload["drift_check_count"]
    assert payload["failure_audit_segments"] >= 5
    assert payload["advanced_validation_ready"] is True
    for artifact in [
        "station_prospective_rolling_origin_metrics.csv",
        "station_prospective_feature_ablation.csv",
        "station_prospective_drift_audit.csv",
        "station_prospective_failure_audit.csv",
    ]:
        assert (tmp_path / "station_level" / "reports" / artifact).exists()


def test_label_panel_preserves_station_identifiers_as_strings(tmp_path):
    write_label_panel(tmp_path, hours=2)
    path = tmp_path / "station_level" / "data" / "processed" / "station_shortage_label_panel.csv"
    panel = pd.read_csv(path)
    panel.loc[0, "station_short_name"] = "6879.04"
    panel.to_csv(path, index=False)

    loaded = load_label_panel(tmp_path)

    assert str(loaded["station_short_name"].dtype) == "string"
    assert str(loaded["gbfs_station_id"].dtype) == "string"
    assert loaded.loc[0, "station_short_name"] == "6879.04"


def test_prospective_validation_excludes_unlabeled_latest_snapshot(tmp_path):
    write_readiness(tmp_path, ready=True)
    write_label_panel(tmp_path)
    append_unlabeled_latest_snapshot(tmp_path)

    payload = evaluate_prospective_validation(tmp_path, ProspectiveValidationConfig(min_label_rows=50))

    assert payload["validation_status"] == "PASS"
    assert payload["label_rows"] == 360
    assert payload["train_rows"] + payload["test_rows"] == 360


def test_prospective_validation_applies_minimum_to_labeled_rows(tmp_path):
    write_readiness(tmp_path, ready=True)
    write_label_panel(tmp_path)
    append_unlabeled_latest_snapshot(tmp_path)

    payload = evaluate_prospective_validation(tmp_path, ProspectiveValidationConfig(min_label_rows=361))

    assert payload["validation_status"] == "NOT_READY"
    assert payload["reason"] == "label rows below minimum 361"
    assert payload["label_rows"] == 360


def test_rolling_origin_splits_are_expanding_and_non_overlapping(tmp_path):
    write_label_panel(tmp_path)
    frame = prepare_model_frame(load_label_panel(tmp_path))

    splits = rolling_origin_splits(frame, n_folds=3, min_train_fraction=0.5)

    assert len(splits) == 3
    previous_train_rows = 0
    for fold, train, test in splits:
        assert fold in {1, 2, 3}
        assert len(train) > previous_train_rows
        assert train["captured_at"].max() < test["captured_at"].min()
        previous_train_rows = len(train)


def test_drift_audit_flags_large_target_shift(tmp_path):
    write_label_panel(tmp_path)
    frame = prepare_model_frame(load_label_panel(tmp_path))
    train = frame.iloc[:180].copy()
    test = frame.iloc[180:].copy()
    train[TARGET_COL] = 0
    test[TARGET_COL] = 1

    audit = drift_audit(train, test)

    target_row = audit.loc[audit["metric"].eq("shortage_rate_abs_diff")].iloc[0]
    assert target_row["status"] == "FAIL"
    assert target_row["value"] == 1.0
