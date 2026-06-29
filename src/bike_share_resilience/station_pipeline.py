from __future__ import annotations

import argparse
import json
import math
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from bike_share_resilience.pipeline import conformal_intervals, evaluate_predictions, markdown_table


KST = ZoneInfo("Asia/Seoul")
TRIP_URL = "https://s3.amazonaws.com/tripdata/JC-202401-citibike-tripdata.csv.zip"
GBFS_STATION_INFO_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_information.json"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
JERSEY_CITY_LAT = 40.7178
JERSEY_CITY_LON = -74.0431
RANDOM_SEED = 20260629


@dataclass
class StationPaths:
    output_root: Path

    @property
    def station_root(self) -> Path:
        return self.output_root / "station_level"

    @property
    def raw_dir(self) -> Path:
        return self.station_root / "data" / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.station_root / "data" / "processed"

    @property
    def report_dir(self) -> Path:
        return self.station_root / "reports"

    def ensure(self) -> None:
        for path in [self.raw_dir, self.processed_dir, self.report_dir]:
            path.mkdir(parents=True, exist_ok=True)


def current_kst_date() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d KST")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        default="/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience",
    )
    parser.add_argument("--top-stations", type=int, default=35)
    parser.add_argument("--synthetic", action="store_true", help="Use deterministic synthetic station data")
    return parser.parse_args()


def download_bytes(url: str, target: Path, timeout: int = 45) -> bytes:
    if target.exists() and target.stat().st_size > 0:
        return target.read_bytes()
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = response.read()
    target.write_bytes(payload)
    return payload


def read_trip_zip(payload: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.endswith(".csv") and not name.startswith("__MACOSX/")
        ]
        if not names:
            raise ValueError("trip zip has no readable csv")
        with archive.open(names[0]) as handle:
            return pd.read_csv(handle)


def acquire_trips(paths: StationPaths, *, synthetic: bool) -> tuple[pd.DataFrame, dict]:
    if synthetic:
        trips = create_synthetic_trips()
        metadata = {
            "source_name": "synthetic station-level fallback",
            "source_url": "generated locally",
            "rows": int(len(trips)),
            "fallback_used": True,
        }
        return trips, metadata

    target = paths.raw_dir / "JC-202401-citibike-tripdata.csv.zip"
    payload = download_bytes(TRIP_URL, target)
    trips = read_trip_zip(payload)
    metadata = {
        "source_name": "Citi Bike Jersey City trip history 2024-01",
        "source_url": TRIP_URL,
        "raw_path": str(target),
        "zip_bytes": int(len(payload)),
        "rows": int(len(trips)),
        "columns": list(trips.columns),
        "fallback_used": False,
    }
    return trips, metadata


def acquire_station_info(paths: StationPaths, *, synthetic: bool) -> tuple[pd.DataFrame, dict]:
    if synthetic:
        rows = []
        for idx in range(12):
            rows.append(
                {
                    "station_short_name": f"JC{idx:03d}",
                    "station_name": f"Synthetic Station {idx}",
                    "gbfs_station_id": f"synthetic-{idx}",
                    "station_lat": JERSEY_CITY_LAT + (idx % 4 - 1.5) * 0.01,
                    "station_lon": JERSEY_CITY_LON + (idx // 4 - 1) * 0.01,
                    "capacity": 14 + idx,
                }
            )
        stations = pd.DataFrame(rows)
        metadata = {"source_name": "synthetic station metadata", "rows": int(len(stations)), "fallback_used": True}
        return stations, metadata

    target = paths.raw_dir / "citibike_gbfs_station_information.json"
    payload = download_bytes(GBFS_STATION_INFO_URL, target)
    data = json.loads(payload.decode("utf-8"))
    rows = []
    for station in data.get("data", {}).get("stations", []):
        rows.append(
            {
                "station_short_name": station.get("short_name"),
                "station_name": station.get("name"),
                "gbfs_station_id": station.get("station_id"),
                "station_lat": station.get("lat"),
                "station_lon": station.get("lon"),
                "capacity": station.get("capacity"),
            }
        )
    stations = pd.DataFrame(rows)
    metadata = {
        "source_name": "Citi Bike GBFS station_information",
        "source_url": GBFS_STATION_INFO_URL,
        "raw_path": str(target),
        "rows": int(len(stations)),
        "columns": list(stations.columns),
        "fallback_used": False,
    }
    return stations, metadata


def acquire_weather(paths: StationPaths, start_date: str, end_date: str, *, synthetic: bool) -> tuple[pd.DataFrame, dict]:
    if synthetic:
        hours = pd.date_range(start_date, end_date, freq="h")
        weather = pd.DataFrame(
            {
                "hour": hours,
                "temperature_2m": 2 + 6 * np.sin(np.arange(len(hours)) / 24),
                "relative_humidity_2m": 68,
                "precipitation": 0.0,
                "wind_speed_10m": 12,
            }
        )
        return weather, {"source_name": "synthetic hourly weather", "rows": int(len(weather)), "fallback_used": True}

    params = {
        "latitude": JERSEY_CITY_LAT,
        "longitude": JERSEY_CITY_LON,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
        "timezone": "America/New_York",
    }
    url = f"{OPEN_METEO_ARCHIVE_URL}?{urllib.parse.urlencode(params)}"
    target = paths.raw_dir / f"open_meteo_hourly_{start_date}_{end_date}.json"
    payload = download_bytes(url, target)
    data = json.loads(payload.decode("utf-8"))
    hourly = data["hourly"]
    weather = pd.DataFrame(hourly).rename(columns={"time": "hour"})
    weather["hour"] = pd.to_datetime(weather["hour"])
    metadata = {
        "source_name": "Open-Meteo historical hourly weather",
        "source_url": url,
        "raw_path": str(target),
        "rows": int(len(weather)),
        "columns": list(weather.columns),
        "fallback_used": False,
    }
    return weather, metadata


def create_synthetic_trips(days: int = 42, stations: int = 12, seed: int = RANDOM_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    start = pd.Timestamp("2024-01-01 00:00:00")
    for hour_offset in range(days * 24):
        hour = start + pd.Timedelta(hours=hour_offset)
        for station_idx in range(stations):
            commute = hour.hour in {7, 8, 17, 18}
            weekend = hour.weekday() >= 5
            lam = 0.6 + 1.8 * commute + 0.7 * weekend + station_idx * 0.05
            count = rng.poisson(lam)
            for ride_idx in range(count):
                rows.append(
                    {
                        "ride_id": f"synthetic-{hour_offset}-{station_idx}-{ride_idx}",
                        "started_at": hour + pd.Timedelta(minutes=int(rng.integers(0, 60))),
                        "ended_at": hour + pd.Timedelta(minutes=int(rng.integers(8, 35))),
                        "start_station_name": f"Synthetic Station {station_idx}",
                        "start_station_id": f"JC{station_idx:03d}",
                        "end_station_name": f"Synthetic Station {(station_idx + 1) % stations}",
                        "end_station_id": f"JC{(station_idx + 1) % stations:03d}",
                        "start_lat": JERSEY_CITY_LAT + (station_idx % 4 - 1.5) * 0.01,
                        "start_lng": JERSEY_CITY_LON + (station_idx // 4 - 1) * 0.01,
                        "end_lat": JERSEY_CITY_LAT,
                        "end_lng": JERSEY_CITY_LON,
                        "member_casual": "member",
                    }
                )
    return pd.DataFrame(rows)


def haversine_km(lat: pd.Series, lon: pd.Series, center_lat: float = JERSEY_CITY_LAT, center_lon: float = JERSEY_CITY_LON) -> pd.Series:
    radius = 6371.0
    lat1 = np.radians(lat.astype(float))
    lon1 = np.radians(lon.astype(float))
    lat2 = math.radians(center_lat)
    lon2 = math.radians(center_lon)
    dlat = lat1 - lat2
    dlon = lon1 - lon2
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * math.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * radius * np.arcsin(np.sqrt(a))


def prepare_station_hour_frame(
    trips: pd.DataFrame,
    station_info: pd.DataFrame,
    weather: pd.DataFrame,
    *,
    top_stations: int,
) -> tuple[pd.DataFrame, dict]:
    trips = trips.copy()
    trips["started_at"] = pd.to_datetime(trips["started_at"], errors="coerce")
    trips["ended_at"] = pd.to_datetime(trips["ended_at"], errors="coerce")
    trips = trips.dropna(subset=["started_at", "start_station_id", "start_station_name"])
    trips["hour"] = trips["started_at"].dt.floor("h")
    station_counts = trips["start_station_id"].value_counts().head(top_stations)
    selected = sorted(station_counts.index.astype(str))
    trips = trips.loc[trips["start_station_id"].astype(str).isin(selected)].copy()
    trips["start_station_id"] = trips["start_station_id"].astype(str)

    starts = (
        trips.groupby(["start_station_id", "hour"], as_index=False)
        .size()
        .rename(columns={"start_station_id": "station_short_name", "size": "start_count"})
    )
    ends = (
        trips.dropna(subset=["end_station_id"])
        .assign(end_station_id=lambda df: df["end_station_id"].astype(str), end_hour=lambda df: df["ended_at"].dt.floor("h"))
        .query("end_station_id in @selected")
        .groupby(["end_station_id", "end_hour"], as_index=False)
        .size()
        .rename(columns={"end_station_id": "station_short_name", "end_hour": "hour", "size": "end_count"})
    )
    trip_station = (
        trips.groupby("start_station_id", as_index=False)
        .agg(
            station_name=("start_station_name", "first"),
            trip_lat=("start_lat", "median"),
            trip_lon=("start_lng", "median"),
        )
        .rename(columns={"start_station_id": "station_short_name"})
    )
    station_info = station_info.copy()
    station_info["station_short_name"] = station_info["station_short_name"].astype(str)
    station_meta = trip_station.merge(station_info, on="station_short_name", how="left", suffixes=("_trip", "_gbfs"))
    station_meta["station_name"] = station_meta["station_name_gbfs"].combine_first(station_meta["station_name_trip"])
    station_meta["station_lat"] = station_meta["station_lat"].fillna(station_meta["trip_lat"])
    station_meta["station_lon"] = station_meta["station_lon"].fillna(station_meta["trip_lon"])
    capacity_median = station_meta["capacity"].dropna().median()
    station_meta["capacity"] = station_meta["capacity"].fillna(capacity_median if not np.isnan(capacity_median) else 20)
    station_meta = station_meta[
        ["station_short_name", "station_name", "gbfs_station_id", "station_lat", "station_lon", "capacity"]
    ]
    station_meta["distance_to_center_km"] = haversine_km(station_meta["station_lat"], station_meta["station_lon"])
    station_meta["station_code"] = pd.factorize(station_meta["station_short_name"])[0]

    min_hour = starts["hour"].min()
    max_hour = starts["hour"].max()
    hours = pd.date_range(min_hour, max_hour, freq="h")
    grid = pd.MultiIndex.from_product([selected, hours], names=["station_short_name", "hour"]).to_frame(index=False)
    frame = grid.merge(starts, on=["station_short_name", "hour"], how="left")
    frame = frame.merge(ends, on=["station_short_name", "hour"], how="left")
    frame[["start_count", "end_count"]] = frame[["start_count", "end_count"]].fillna(0).astype(int)
    frame = frame.merge(station_meta, on="station_short_name", how="left")
    weather = weather.copy()
    weather["hour"] = pd.to_datetime(weather["hour"]).dt.floor("h")
    frame = frame.merge(weather, on="hour", how="left")
    for col in ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m"]:
        frame[col] = frame[col].ffill().bfill()
    frame["weekday"] = frame["hour"].dt.weekday
    frame["hr"] = frame["hour"].dt.hour
    frame["is_weekend"] = (frame["weekday"] >= 5).astype(int)
    frame["is_commute_peak"] = frame["hr"].isin([7, 8, 9, 16, 17, 18, 19]).astype(int)
    frame["is_night"] = frame["hr"].between(0, 5).astype(int)
    frame["precipitation_flag"] = (frame["precipitation"] > 0).astype(int)
    frame = frame.sort_values(["station_short_name", "hour"]).reset_index(drop=True)
    grouped = frame.groupby("station_short_name")["start_count"]
    frame["lag_1"] = grouped.shift(1)
    frame["lag_24"] = grouped.shift(24)
    frame["rolling_24_mean"] = grouped.shift(1).rolling(24, min_periods=12).mean().reset_index(level=0, drop=True)
    frame = frame.dropna(subset=["lag_1", "lag_24", "rolling_24_mean"]).reset_index(drop=True)
    metadata = {
        "station_count": int(frame["station_short_name"].nunique()),
        "row_count": int(len(frame)),
        "hour_min": str(frame["hour"].min()),
        "hour_max": str(frame["hour"].max()),
        "gbfs_join_rate": float(station_meta["gbfs_station_id"].notna().mean()),
    }
    return frame, metadata


def chronological_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    hours = pd.Series(pd.to_datetime(df["hour"]).sort_values().unique())
    train_cut = hours.iloc[int(len(hours) * 0.70) - 1]
    valid_cut = hours.iloc[int(len(hours) * 0.85) - 1]
    return (
        df.loc[df["hour"] <= train_cut].copy(),
        df.loc[(df["hour"] > train_cut) & (df["hour"] <= valid_cut)].copy(),
        df.loc[df["hour"] > valid_cut].copy(),
    )


FEATURE_COLUMNS = [
    "station_code",
    "capacity",
    "distance_to_center_km",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "weekday",
    "hr",
    "is_weekend",
    "is_commute_peak",
    "is_night",
    "precipitation_flag",
    "end_count",
    "lag_1",
    "lag_24",
    "rolling_24_mean",
]


def station_hour_profile_predict(train: pd.DataFrame, target: pd.DataFrame) -> np.ndarray:
    profile = train.groupby(["station_short_name", "weekday", "hr"])["start_count"].median()
    station_profile = train.groupby(["station_short_name", "hr"])["start_count"].median()
    global_profile = train.groupby("hr")["start_count"].median()
    global_default = float(train["start_count"].median())
    values = []
    for row in target.itertuples(index=False):
        key = (row.station_short_name, row.weekday, row.hr)
        fallback_key = (row.station_short_name, row.hr)
        if key in profile:
            values.append(float(profile.loc[key]))
        elif fallback_key in station_profile:
            values.append(float(station_profile.loc[fallback_key]))
        elif row.hr in global_profile:
            values.append(float(global_profile.loc[row.hr]))
        else:
            values.append(global_default)
    return np.asarray(values)


def make_models() -> dict[str, object]:
    return {
        "ridge_regression": Pipeline(
            [("scaler", StandardScaler()), ("model", Ridge(alpha=5.0, random_state=RANDOM_SEED))]
        ),
        "gradient_boosting": GradientBoostingRegressor(
            random_state=RANDOM_SEED,
            n_estimators=160,
            learning_rate=0.045,
            max_depth=3,
        ),
    }


def segment_metrics(df: pd.DataFrame, pred: np.ndarray) -> pd.DataFrame:
    work = df[["station_short_name", "start_count", "is_commute_peak", "precipitation_flag", "capacity"]].copy()
    work["pred"] = pred
    work["abs_error"] = (work["start_count"] - work["pred"]).abs()
    capacity_cut = work["capacity"].median()
    segments = {
        "overall": pd.Series(True, index=work.index),
        "commute_peak": work["is_commute_peak"].eq(1),
        "precipitation": work["precipitation_flag"].eq(1),
        "low_capacity": work["capacity"].le(capacity_cut),
        "high_capacity": work["capacity"].gt(capacity_cut),
    }
    rows = []
    for name, mask in segments.items():
        part = work.loc[mask]
        if part.empty:
            continue
        metrics = evaluate_predictions(part["start_count"], part["pred"])
        rows.append(
            {
                "segment": name,
                "rows": int(len(part)),
                "station_count": int(part["station_short_name"].nunique()),
                "mae": metrics["mae"],
                "wape": metrics["wape"],
                "bias": float((part["pred"] - part["start_count"]).mean()),
                "p90_abs_error": float(part["abs_error"].quantile(0.90)),
            }
        )
    return pd.DataFrame(rows)


def make_rebalancing_priority(test: pd.DataFrame, pred: np.ndarray, conformal_radius: float) -> pd.DataFrame:
    latest_hour = test["hour"].max()
    window = test.loc[test["hour"] >= latest_hour - pd.Timedelta(hours=23)].copy()
    if window.empty:
        window = test.tail(24).copy()
    window["forecast"] = pred[-len(window) :]
    summary = (
        window.groupby(["station_short_name", "station_name"], as_index=False)
        .agg(
            forecast_24h=("forecast", "sum"),
            observed_24h=("start_count", "sum"),
            capacity=("capacity", "first"),
            lat=("station_lat", "first"),
            lon=("station_lon", "first"),
        )
    )
    summary["upper_demand_24h"] = summary["forecast_24h"] + conformal_radius * math.sqrt(24)
    summary["risk_score"] = summary["upper_demand_24h"] / summary["capacity"].clip(lower=1)
    summary["recommended_buffer_bikes"] = np.ceil((summary["risk_score"] - 1).clip(lower=0) * summary["capacity"] * 0.25)
    return summary.sort_values("risk_score", ascending=False).head(12)


def render_station_report(
    metadata: dict,
    metrics_df: pd.DataFrame,
    segment_df: pd.DataFrame,
    priority_df: pd.DataFrame,
    quality_df: pd.DataFrame,
) -> str:
    return "\n".join(
        [
            "# Station-Level 수요 회복력 확장 보고서",
            "",
            f"- 생성일: {current_kst_date()}",
            "- 목적: 시스템 집계 UCI slice를 넘어 station-hour 수요, station capacity, 날씨를 결합한 운영 의사결정 slice를 검증한다.",
            "",
            "## 데이터 원천",
            "",
            f"- Trip history: {metadata['sources']['trips']['source_name']} ({metadata['sources']['trips'].get('rows')} rows)",
            f"- Station metadata: {metadata['sources']['station_info']['source_name']} ({metadata['sources']['station_info'].get('rows')} stations)",
            f"- Weather: {metadata['sources']['weather']['source_name']} ({metadata['sources']['weather'].get('rows')} hours)",
            f"- Station-hour rows: {metadata['frame']['row_count']}",
            f"- Station count: {metadata['frame']['station_count']}",
            f"- GBFS join rate: {metadata['frame']['gbfs_join_rate']:.1%}",
            "",
            "## 모델 비교",
            "",
            markdown_table(metrics_df, float_digits=3),
            "",
            "## Segment Failure Audit",
            "",
            markdown_table(segment_df, float_digits=3),
            "",
            "## 운영 우선순위",
            "",
            "최근 24시간 test window에서 forecast와 conformal radius를 station capacity로 나누어 shortage-risk proxy를 만들었다.",
            "",
            markdown_table(
                priority_df[
                    [
                        "station_short_name",
                        "station_name",
                        "forecast_24h",
                        "upper_demand_24h",
                        "capacity",
                        "risk_score",
                        "recommended_buffer_bikes",
                    ]
                ],
                float_digits=2,
            ),
            "",
            "## Quality Gate",
            "",
            markdown_table(quality_df, float_digits=3),
            "",
            "## 해석 제한",
            "",
            "- GBFS station capacity는 현재 metadata이므로 2024년 1월 당시 capacity와 다를 수 있다.",
            "- Trip history에는 실시간 재고와 장애 상태가 없어서 실제 shortage label이 아니라 demand pressure proxy를 사용했다.",
            "- raw ride_id는 `/DATA` raw artifact에만 두고 공개 repo에는 aggregate/report/schema만 둔다.",
            "",
        ]
    )


def build_quality_gate(metrics: dict, metadata: dict) -> pd.DataFrame:
    checks = [
        {
            "gate": "multi-source join",
            "passed": metadata["frame"]["station_count"] >= 10 and metadata["frame"]["gbfs_join_rate"] >= 0.80,
            "evidence": f"stations={metadata['frame']['station_count']}, gbfs_join_rate={metadata['frame']['gbfs_join_rate']:.1%}",
            "threshold": ">=10 stations and >=80% station metadata join",
        },
        {
            "gate": "weather join",
            "passed": metadata["sources"]["weather"].get("rows", 0) >= 24 * 20,
            "evidence": f"weather_hours={metadata['sources']['weather'].get('rows')}",
            "threshold": ">=20 days of hourly weather",
        },
        {
            "gate": "baseline comparison",
            "passed": metrics["best_test_mae"] <= metrics["baseline_test_mae"],
            "evidence": f"best_mae={metrics['best_test_mae']:.3f}, baseline_mae={metrics['baseline_test_mae']:.3f}",
            "threshold": "model MAE <= station-hour profile baseline MAE",
        },
        {
            "gate": "conformal coverage",
            "passed": 0.82 <= metrics["conformal_test_coverage"] <= 0.99,
            "evidence": f"coverage={metrics['conformal_test_coverage']:.3f}",
            "threshold": "coverage in [0.82, 0.99]",
        },
        {
            "gate": "decision output",
            "passed": metrics["priority_rows"] >= 5,
            "evidence": f"priority_rows={metrics['priority_rows']}",
            "threshold": ">=5 station-level rebalancing priority rows",
        },
    ]
    return pd.DataFrame(checks)


def run_pipeline(output_root: Path, *, top_stations: int = 35, synthetic: bool = False) -> dict:
    paths = StationPaths(output_root=output_root)
    paths.ensure()
    trips, trip_meta = acquire_trips(paths, synthetic=synthetic)
    station_info, station_meta = acquire_station_info(paths, synthetic=synthetic)
    start_date = str(pd.to_datetime(trips["started_at"]).min().date())
    end_date = str(pd.to_datetime(trips["started_at"]).max().date())
    weather, weather_meta = acquire_weather(paths, start_date, end_date, synthetic=synthetic)
    frame, frame_meta = prepare_station_hour_frame(trips, station_info, weather, top_stations=top_stations)
    train, valid, test = chronological_split(frame)
    train_valid = pd.concat([train, valid], ignore_index=True)

    paths.processed_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(paths.processed_dir / "station_hour_features.parquet", index=False)
    frame.head(200).to_csv(paths.processed_dir / "station_hour_sample.csv", index=False)

    rows = []
    valid_predictions: dict[str, np.ndarray] = {}
    baseline_valid = station_hour_profile_predict(train, valid)
    baseline_test = station_hour_profile_predict(train_valid, test)
    valid_predictions["station_hour_profile"] = baseline_valid
    rows.append({"model": "station_hour_profile", "split": "valid", **evaluate_predictions(valid["start_count"], baseline_valid)})
    rows.append({"model": "station_hour_profile", "split": "test", **evaluate_predictions(test["start_count"], baseline_test)})
    models = make_models()
    fitted = {}
    for name, model in models.items():
        model.fit(train[FEATURE_COLUMNS], train["start_count"])
        valid_pred = model.predict(valid[FEATURE_COLUMNS]).clip(min=0)
        valid_predictions[name] = valid_pred
        rows.append({"model": name, "split": "valid", **evaluate_predictions(valid["start_count"], valid_pred)})
        model.fit(train_valid[FEATURE_COLUMNS], train_valid["start_count"])
        test_pred = model.predict(test[FEATURE_COLUMNS]).clip(min=0)
        rows.append({"model": name, "split": "test", **evaluate_predictions(test["start_count"], test_pred)})
        fitted[name] = model
    metrics_df = pd.DataFrame(rows).sort_values(["split", "mae"])
    metrics_df.to_csv(paths.report_dir / "station_model_metrics.csv", index=False)
    best_name = metrics_df.loc[metrics_df["split"].eq("test")].sort_values("mae").iloc[0]["model"]
    if best_name == "station_hour_profile":
        best_test_pred = baseline_test
        best_valid_pred = baseline_valid
    else:
        best_test_pred = fitted[best_name].predict(test[FEATURE_COLUMNS]).clip(min=0)
        best_valid_pred = valid_predictions[best_name]
    intervals, conformal_summary = conformal_intervals(valid["start_count"], best_valid_pred, test["start_count"], best_test_pred)
    intervals.insert(0, "hour", test["hour"].reset_index(drop=True))
    intervals.insert(1, "station_short_name", test["station_short_name"].reset_index(drop=True))
    intervals.to_csv(paths.report_dir / "station_conformal_intervals.csv", index=False)
    segment_df = segment_metrics(test, best_test_pred)
    segment_df.to_csv(paths.report_dir / "station_segment_audit.csv", index=False)
    priority_df = make_rebalancing_priority(test, best_test_pred, conformal_summary["conformal_radius"])
    priority_df.to_csv(paths.report_dir / "station_rebalancing_priority.csv", index=False)

    baseline_mae = float(
        metrics_df.loc[(metrics_df["model"] == "station_hour_profile") & (metrics_df["split"] == "test"), "mae"].iloc[0]
    )
    best_mae = float(metrics_df.loc[(metrics_df["model"] == best_name) & (metrics_df["split"] == "test"), "mae"].iloc[0])
    metadata = {
        "created_at_kst": current_kst_date(),
        "top_stations": top_stations,
        "sources": {
            "trips": trip_meta,
            "station_info": station_meta,
            "weather": weather_meta,
        },
        "frame": frame_meta,
        "splits": {
            "train_rows": int(len(train)),
            "valid_rows": int(len(valid)),
            "test_rows": int(len(test)),
        },
    }
    quality_inputs = {
        "baseline_test_mae": baseline_mae,
        "best_test_mae": best_mae,
        "conformal_test_coverage": float(conformal_summary["conformal_test_coverage"]),
        "priority_rows": int(len(priority_df)),
    }
    quality_df = build_quality_gate(quality_inputs, metadata)
    quality_df.to_csv(paths.report_dir / "station_quality_gate_checks.csv", index=False)
    report = render_station_report(metadata, metrics_df, segment_df, priority_df, quality_df)
    (paths.report_dir / "station_level_report.md").write_text(report, encoding="utf-8")
    payload = {
        "best_model": best_name,
        "baseline_test_mae": baseline_mae,
        "best_test_mae": best_mae,
        "conformal_summary": conformal_summary,
        "metadata": metadata,
        "quality_gate_passed": bool(quality_df["passed"].all()),
        "failed_quality_gates": quality_df.loc[~quality_df["passed"], "gate"].tolist(),
    }
    (paths.report_dir / "station_run_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    args = parse_args()
    payload = run_pipeline(Path(args.output_root), top_stations=args.top_stations, synthetic=args.synthetic)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
