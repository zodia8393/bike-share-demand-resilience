from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd

from bike_share_resilience.station_pipeline import (
    acquire_station_info,
    acquire_trips,
    acquire_weather,
    chronological_split,
    prepare_station_hour_frame,
    run_pipeline,
    station_hour_profile_predict,
    StationPaths,
)


def test_station_hour_frame_joins_sources(tmp_path):
    paths = StationPaths(tmp_path)
    paths.ensure()
    trips, trip_meta = acquire_trips(paths, synthetic=True)
    stations, station_meta = acquire_station_info(paths, synthetic=True)
    start_date = str(pd.to_datetime(trips["started_at"]).min().date())
    end_date = str(pd.to_datetime(trips["started_at"]).max().date())
    weather, weather_meta = acquire_weather(paths, start_date, end_date, synthetic=True)
    frame, meta = prepare_station_hour_frame(trips, stations, weather, top_stations=8)

    assert trip_meta["fallback_used"] is True
    assert station_meta["fallback_used"] is True
    assert weather_meta["fallback_used"] is True
    assert meta["station_count"] == 8
    assert meta["row_count"] > 24 * 20
    assert meta["gbfs_join_rate"] == 1.0
    assert {"start_count", "capacity", "temperature_2m", "lag_24"}.issubset(frame.columns)


def test_station_profile_baseline_and_split(tmp_path):
    paths = StationPaths(tmp_path)
    paths.ensure()
    trips, _ = acquire_trips(paths, synthetic=True)
    stations, _ = acquire_station_info(paths, synthetic=True)
    weather, _ = acquire_weather(paths, "2024-01-01", "2024-02-11", synthetic=True)
    frame, _ = prepare_station_hour_frame(trips, stations, weather, top_stations=8)
    train, valid, test = chronological_split(frame)
    pred = station_hour_profile_predict(train, valid)

    assert train["hour"].max() < valid["hour"].min()
    assert valid["hour"].max() < test["hour"].min()
    assert len(pred) == len(valid)
    assert (pred >= 0).all()


def test_station_pipeline_synthetic_smoke(tmp_path):
    payload = run_pipeline(tmp_path, top_stations=10, synthetic=True)
    report_dir = tmp_path / "station_level" / "reports"

    assert payload["quality_gate_passed"] is True
    assert payload["metadata"]["frame"]["station_count"] == 10
    assert (report_dir / "station_level_report.md").exists()
    assert (report_dir / "station_quality_gate_checks.csv").exists()
