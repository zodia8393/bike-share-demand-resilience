from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from scripts import check_public_deploy_readiness as deploy_check


def write_snapshot(root: Path, stamp: str, bikes: int) -> None:
    snapshot_dir = root / "station_level" / "data" / "status_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "station_short_name": "JC001",
                "gbfs_station_id": "gbfs-1",
                "capacity": 20,
                "num_bikes_available": bikes,
                "num_docks_available": 20 - bikes,
                "current_bike_shortage": bikes <= 2,
                "current_dock_shortage": 20 - bikes <= 2,
            }
        ]
    ).to_csv(snapshot_dir / f"{stamp}_inventory_snapshot.csv", index=False)


def test_parse_args_accepts_timezone_aware_snapshot_cutoff(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_public_deploy_readiness.py", "--snapshot-cutoff", "2026-07-13T14:15:03+09:00"],
    )

    args = deploy_check.parse_args()

    assert args.snapshot_cutoff == datetime.fromisoformat("2026-07-13T14:15:03+09:00")


def test_build_decision_applies_snapshot_cutoff(tmp_path, monkeypatch):
    write_snapshot(tmp_path, "20260713_141503", 1)
    write_snapshot(tmp_path, "20260713_151503", 5)
    cutoff = datetime.fromisoformat("2026-07-13T14:15:03+09:00")
    monkeypatch.setattr(deploy_check, "load_service_payload", lambda _root: {"health": {}})
    monkeypatch.setattr(deploy_check, "validate_service_payload", lambda _payload: [])
    monkeypatch.setattr(deploy_check, "tracked_publication_risks", lambda: [])

    decision = deploy_check.build_decision(tmp_path, snapshot_cutoff_at=cutoff)

    readiness = decision["snapshot_readiness"]
    assert readiness["snapshot_count"] == 1
    assert readiness["source_snapshot_count"] == 2
    assert readiness["excluded_snapshot_count"] == 1
    assert readiness["latest_snapshot_at"] == "2026-07-13T14:15:03+09:00"
    assert readiness["snapshot_cutoff_at"] == "2026-07-13T14:15:03+09:00"


def test_main_passes_snapshot_cutoff_to_build_decision(tmp_path, monkeypatch):
    cutoff = datetime.fromisoformat("2026-07-13T14:15:03+09:00")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        deploy_check,
        "parse_args",
        lambda: argparse.Namespace(output_root=str(tmp_path), snapshot_cutoff=cutoff, report_only=False),
    )

    def fake_build_decision(output_root: Path, snapshot_cutoff_at: datetime | None = None) -> dict:
        captured["output_root"] = output_root
        captured["snapshot_cutoff_at"] = snapshot_cutoff_at
        return {"decision": "GO"}

    monkeypatch.setattr(deploy_check, "build_decision", fake_build_decision)

    deploy_check.main()

    assert captured == {"output_root": tmp_path, "snapshot_cutoff_at": cutoff}
    assert (tmp_path / "station_level" / "reports" / "station_public_deploy_readiness.json").is_file()
