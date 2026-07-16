from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from bike_share_resilience.station_post_cutoff_monitoring import (
    PostCutoffMonitoringConfig,
    evaluate_post_cutoff_monitoring,
)


def write_snapshot(
    root: Path,
    stamp: str,
    bikes: int,
    station_id: str = "station-1",
) -> None:
    snapshot_dir = root / "station_level" / "data" / "status_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "station_short_name": station_id,
                "gbfs_station_id": station_id,
                "capacity": 20,
                "num_bikes_available": bikes,
                "num_docks_available": 20 - bikes,
                "inventory_pressure": 1 - bikes / 20,
                "current_bike_shortage": bikes <= 2,
                "current_dock_shortage": 20 - bikes <= 2,
            }
        ]
    ).to_csv(snapshot_dir / f"{stamp}_inventory_snapshot.csv", index=False)


def write_cutoff(root: Path, cutoff: str | None) -> str:
    report_dir = root / "station_level" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    content = json.dumps({"snapshot_cutoff_at": cutoff})
    (report_dir / "station_snapshot_readiness.json").write_text(content, encoding="utf-8")
    return content


def test_post_cutoff_monitoring_passes_stable_separate_cohort(tmp_path):
    cutoff = "2026-06-01T03:00:00+09:00"
    readiness_before = write_cutoff(tmp_path, cutoff)
    for hour in range(4):
        write_snapshot(tmp_path, f"20260601_{hour:02d}0000", bikes=8)
        write_snapshot(tmp_path, f"20260602_{hour:02d}0000", bikes=8)

    payload = evaluate_post_cutoff_monitoring(
        tmp_path,
        PostCutoffMonitoringConfig(),
    )
    readiness_after = (
        tmp_path / "station_level" / "reports" / "station_snapshot_readiness.json"
    ).read_text(encoding="utf-8")

    assert payload["status"] == "PASS"
    assert payload["reference_snapshot_count"] == 4
    assert payload["monitoring_snapshot_count"] == 4
    assert payload["checks_passed"] == payload["check_count"] == 4
    assert readiness_after == readiness_before


def test_post_cutoff_monitoring_requires_review_for_shortage_shift(tmp_path):
    write_cutoff(tmp_path, "2026-06-01T03:00:00+09:00")
    for hour in range(4):
        write_snapshot(tmp_path, f"20260601_{hour:02d}0000", bikes=8)
        write_snapshot(tmp_path, f"20260602_{hour:02d}0000", bikes=1)

    payload = evaluate_post_cutoff_monitoring(
        tmp_path,
        PostCutoffMonitoringConfig(),
    )
    checks = pd.read_csv(
        tmp_path / "station_level" / "reports" / "station_post_cutoff_drift.csv"
    )

    assert payload["status"] == "REVIEW_REQUIRED"
    assert payload["decision"] == "NO_AUTOMATIC_MODEL_CHANGE"
    assert checks.loc[checks["metric"].eq("shortage_rate_abs_diff"), "status"].item() == (
        "REVIEW_REQUIRED"
    )


def test_post_cutoff_monitoring_waits_without_later_snapshots(tmp_path):
    write_cutoff(tmp_path, "2026-06-01T03:00:00+09:00")
    write_snapshot(tmp_path, "20260601_010000", bikes=8)

    payload = evaluate_post_cutoff_monitoring(
        tmp_path,
        PostCutoffMonitoringConfig(),
    )

    assert payload["status"] == "NOT_READY"
    assert "no post-cutoff" in payload["reason"]


def test_post_cutoff_monitoring_requires_valid_frozen_cutoff(tmp_path):
    write_cutoff(tmp_path, None)
    write_snapshot(tmp_path, "20260601_010000", bikes=8)

    payload = evaluate_post_cutoff_monitoring(
        tmp_path,
        PostCutoffMonitoringConfig(),
    )

    assert payload["status"] == "NOT_READY"
    assert "cutoff" in payload["reason"]
