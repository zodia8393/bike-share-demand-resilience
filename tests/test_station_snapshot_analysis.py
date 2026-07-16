import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from bike_share_resilience.station_snapshot_analysis import (
    SnapshotReadinessConfig,
    analyze_snapshots,
    load_snapshot_history,
    parse_snapshot_cutoff,
)


def write_snapshot(root: Path, stamp: str, bikes: int) -> None:
    snapshot_dir = root / "station_level" / "data" / "status_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "station_short_name": "JC001",
                "station_name": "Station A",
                "gbfs_station_id": "gbfs-1",
                "capacity": 20,
                "num_bikes_available": bikes,
                "num_docks_available": 20 - bikes,
                "current_bike_shortage": bikes <= 2,
                "current_dock_shortage": 20 - bikes <= 2,
                "inventory_pressure": 1 - bikes / 20,
            }
        ]
    ).to_csv(snapshot_dir / f"{stamp}_inventory_snapshot.csv", index=False)


def test_snapshot_readiness_waits_for_two_week_coverage(tmp_path):
    write_snapshot(tmp_path, "20260629_010000", 1)
    write_snapshot(tmp_path, "20260629_020000", 5)

    summary = analyze_snapshots(tmp_path, SnapshotReadinessConfig(target_days=14, min_hourly_coverage=0.8))

    assert summary["ready_for_prospective_validation"] is False
    assert summary["snapshot_count"] == 2
    assert summary["remaining_snapshots"] > 0
    assert (tmp_path / "station_level" / "reports" / "station_snapshot_readiness.json").exists()


def test_snapshot_readiness_builds_prospective_label_panel(tmp_path):
    for hour in range(24):
        write_snapshot(tmp_path, f"20260629_{hour:02d}0000", 1 if hour % 3 == 0 else 8)

    summary = analyze_snapshots(tmp_path, SnapshotReadinessConfig(target_days=0, min_hourly_coverage=1.0))
    history = load_snapshot_history(tmp_path)
    label_path = tmp_path / "station_level" / "data" / "processed" / "station_shortage_label_panel.csv"
    labels = pd.read_csv(label_path)

    assert summary["ready_for_prospective_validation"] is True
    assert len(history) == 24
    assert labels["bike_shortage_next_snapshot"].notna().sum() == 23


def test_snapshot_cutoff_freezes_cohort_without_deleting_later_files(tmp_path):
    write_snapshot(tmp_path, "20260629_000000", 1)
    write_snapshot(tmp_path, "20260629_010000", 5)
    write_snapshot(tmp_path, "20260629_020000", 8)
    cutoff = datetime.fromisoformat("2026-06-29T01:00:00+09:00")

    summary = analyze_snapshots(
        tmp_path,
        SnapshotReadinessConfig(
            target_days=0,
            min_hourly_coverage=1.0,
            snapshot_cutoff_at=cutoff,
        ),
    )
    history = load_snapshot_history(tmp_path, cutoff)
    source_files = list((tmp_path / "station_level" / "data" / "status_snapshots").glob("*.csv"))
    report = (tmp_path / "station_level" / "reports" / "station_snapshot_readiness.md").read_text(encoding="utf-8")

    assert summary["snapshot_count"] == 2
    assert summary["source_snapshot_count"] == 3
    assert summary["excluded_snapshot_count"] == 1
    assert summary["snapshot_cutoff_at"] == "2026-06-29T01:00:00+09:00"
    assert len(history) == 2
    assert len(source_files) == 3
    assert "Snapshot cutoff: 2026-06-29T01:00:00+09:00" in report
    assert "Excluded after cutoff: 1" in report


def test_parse_snapshot_cutoff_rejects_timezone_naive_value():
    with pytest.raises(argparse.ArgumentTypeError, match="timezone"):
        parse_snapshot_cutoff("2026-07-13T14:15:03")
