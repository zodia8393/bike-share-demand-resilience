#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bike_share_resilience.station_pipeline import (  # noqa: E402
    KST,
    StationPaths,
    acquire_station_info,
    acquire_station_status,
    build_inventory_snapshot,
    current_kst_stamp,
)


DEFAULT_OUTPUT_ROOT = "/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Citi Bike GBFS station_status and inventory snapshot.")
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--synthetic", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = StationPaths(Path(args.output_root))
    paths.ensure()
    station_info, station_info_meta = acquire_station_info(paths, synthetic=args.synthetic)
    station_status, station_status_meta = acquire_station_status(paths, synthetic=args.synthetic)
    inventory, inventory_meta = build_inventory_snapshot(station_info, station_status)

    stamp = current_kst_stamp()
    latest_path = paths.processed_dir / "latest_inventory_snapshot.csv"
    snapshot_path = paths.status_snapshot_dir / f"{stamp}_inventory_snapshot.csv"
    inventory.to_csv(latest_path, index=False)
    inventory.to_csv(snapshot_path, index=False)

    summary = {
        "captured_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "station_info": station_info_meta,
        "station_status": station_status_meta,
        "inventory": inventory_meta,
        "latest_inventory_path": str(latest_path),
        "snapshot_inventory_path": str(snapshot_path),
    }
    summary_path = paths.report_dir / "latest_inventory_snapshot_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
