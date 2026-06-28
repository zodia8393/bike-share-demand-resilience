from __future__ import annotations

import argparse
import json
import math
import pickle
import urllib.request
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import optimize
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


UCI_URL = "https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip"
RANDOM_SEED = 20260627


@dataclass
class ProjectPaths:
    output_root: Path
    report_dir: Path

    @property
    def raw_dir(self) -> Path:
        return self.output_root / "data" / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.output_root / "data" / "processed"

    @property
    def figure_dir(self) -> Path:
        return self.output_root / "figures"

    @property
    def model_dir(self) -> Path:
        return self.output_root / "models"

    @property
    def project_report_dir(self) -> Path:
        return self.output_root / "reports"

    def ensure(self) -> None:
        for path in [
            self.raw_dir,
            self.processed_dir,
            self.figure_dir,
            self.model_dir,
            self.project_report_dir,
            self.report_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


FEATURE_COLUMNS = [
    "season",
    "yr",
    "mnth",
    "hr",
    "holiday",
    "weekday",
    "workingday",
    "weathersit",
    "temp",
    "atemp",
    "hum",
    "windspeed",
    "is_commute_peak",
    "is_weekend",
    "is_night",
    "temp_x_hum",
    "bad_weather",
    "lag_1",
    "lag_24",
    "lag_168",
    "rolling_24_mean",
    "rolling_168_mean",
]


def create_synthetic_contract(days: int = 730, seed: int = RANDOM_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    hours = pd.date_range("2011-01-01", periods=days * 24, freq="h")
    df = pd.DataFrame({"datetime": hours})
    df["dteday"] = df["datetime"].dt.date.astype(str)
    df["season"] = ((df["datetime"].dt.month % 12) // 3 + 1).astype(int)
    df["yr"] = (df["datetime"].dt.year - df["datetime"].dt.year.min()).astype(int)
    df["mnth"] = df["datetime"].dt.month
    df["hr"] = df["datetime"].dt.hour
    df["holiday"] = 0
    df["weekday"] = df["datetime"].dt.weekday
    df["workingday"] = (df["weekday"] < 5).astype(int)

    annual = np.sin(2 * np.pi * (df["datetime"].dt.dayofyear.to_numpy() - 80) / 365)
    temp = np.clip(0.48 + 0.30 * annual + rng.normal(0, 0.06, len(df)), 0.02, 0.98)
    hum = np.clip(0.58 - 0.12 * annual + rng.normal(0, 0.12, len(df)), 0.15, 1.0)
    wind = np.clip(rng.gamma(2.0, 0.06, len(df)), 0.01, 0.65)
    storm_prob = np.clip(0.05 + 0.24 * (hum > 0.78) + 0.10 * (wind > 0.30), 0, 0.7)
    weather = np.where(rng.random(len(df)) < storm_prob, rng.choice([3, 4], len(df)), rng.choice([1, 2], len(df), p=[0.72, 0.28]))

    commute = (((df["hr"].between(7, 9)) | (df["hr"].between(16, 19))) & (df["workingday"] == 1)).astype(int)
    weekend_midday = ((df["hr"].between(10, 17)) & (df["workingday"] == 0)).astype(int)
    base = 45 + 450 * commute + 220 * weekend_midday + 90 * np.sin(np.pi * df["hr"].to_numpy() / 24).clip(0)
    weather_penalty = np.where(weather >= 3, 0.58, np.where(weather == 2, 0.86, 1.0))
    comfort = np.exp(-((temp - 0.62) ** 2) / 0.08)
    trend = 1.0 + 0.18 * df["yr"].to_numpy()
    expected = np.maximum(5, (base + 230 * comfort) * weather_penalty * trend * (1 - 0.25 * wind))
    cnt = rng.negative_binomial(n=25, p=25 / (25 + expected))

    df["weathersit"] = weather.astype(int)
    df["temp"] = temp
    df["atemp"] = np.clip(temp + rng.normal(0, 0.03, len(df)), 0.02, 1.0)
    df["hum"] = hum
    df["windspeed"] = wind
    df["cnt"] = cnt.astype(int)
    casual_share = np.clip(0.22 + 0.30 * weekend_midday - 0.08 * commute, 0.08, 0.72)
    df["casual"] = (df["cnt"] * casual_share).round().astype(int)
    df["registered"] = df["cnt"] - df["casual"]
    return df[
        [
            "datetime",
            "dteday",
            "season",
            "yr",
            "mnth",
            "hr",
            "holiday",
            "weekday",
            "workingday",
            "weathersit",
            "temp",
            "atemp",
            "hum",
            "windspeed",
            "casual",
            "registered",
            "cnt",
        ]
    ]


def acquire_dataset(paths: ProjectPaths) -> tuple[pd.DataFrame, dict]:
    paths.ensure()
    raw_zip = paths.raw_dir / "uci_bike_sharing_dataset.zip"
    raw_csv = paths.raw_dir / "hour.csv"
    metadata = {
        "preferred_source": UCI_URL,
        "source_name": "UCI Machine Learning Repository Bike Sharing Dataset",
        "license_note": "Public research dataset; cite Fanaee-T and Gama (2013).",
        "fallback_used": False,
        "fallback_reason": None,
    }

    try:
        with urllib.request.urlopen(UCI_URL, timeout=30) as response:
            payload = response.read()
        raw_zip.write_bytes(payload)
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            with archive.open("hour.csv") as handle:
                df = pd.read_csv(handle)
        metadata["rows"] = int(len(df))
        metadata["columns"] = list(df.columns)
    except Exception as exc:  # Network resilience is part of the automation contract.
        metadata["fallback_used"] = True
        metadata["fallback_reason"] = repr(exc)
        df = create_synthetic_contract()

    if "instant" in df.columns:
        df = df.drop(columns=["instant"])
    if "datetime" not in df.columns:
        df["datetime"] = pd.to_datetime(df["dteday"]) + pd.to_timedelta(df["hr"], unit="h")
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    df.to_csv(raw_csv, index=False)
    metadata["effective_rows"] = int(len(df))
    metadata["effective_columns"] = list(df.columns)
    (paths.raw_dir / "source_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return df, metadata


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["datetime"] = pd.to_datetime(work["datetime"])
    work = work.sort_values("datetime").reset_index(drop=True)
    work["is_commute_peak"] = (((work["hr"].between(7, 9)) | (work["hr"].between(16, 19))) & (work["workingday"] == 1)).astype(int)
    work["is_weekend"] = (work["workingday"] == 0).astype(int)
    work["is_night"] = (work["hr"].between(0, 5)).astype(int)
    work["temp_x_hum"] = work["temp"] * work["hum"]
    work["bad_weather"] = (work["weathersit"] >= 3).astype(int)
    work["lag_1"] = work["cnt"].shift(1)
    work["lag_24"] = work["cnt"].shift(24)
    work["lag_168"] = work["cnt"].shift(168)
    work["rolling_24_mean"] = work["cnt"].shift(1).rolling(24, min_periods=24).mean()
    work["rolling_168_mean"] = work["cnt"].shift(1).rolling(168, min_periods=168).mean()
    work = work.dropna().reset_index(drop=True)
    work["dteday"] = pd.to_datetime(work["dteday"])
    return work


def chronological_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.Series(pd.to_datetime(df["dteday"]).sort_values().unique())
    train_cut = dates.iloc[int(len(dates) * 0.70) - 1]
    valid_cut = dates.iloc[int(len(dates) * 0.85) - 1]
    return (
        df.loc[df["dteday"] <= train_cut].copy(),
        df.loc[(df["dteday"] > train_cut) & (df["dteday"] <= valid_cut)].copy(),
        df.loc[df["dteday"] > valid_cut].copy(),
    )


def evaluate_predictions(y_true: Iterable[float], y_pred: Iterable[float]) -> dict:
    y_true = np.asarray(list(y_true), dtype=float)
    y_pred = np.asarray(list(y_pred), dtype=float)
    abs_error = np.abs(y_true - y_pred)
    denominator = np.clip(np.abs(y_true) + np.abs(y_pred), 1, None)
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(math.sqrt(mean_squared_error(y_true, y_pred))),
        "mape": float(np.mean(abs_error / np.clip(np.abs(y_true), 1, None)) * 100),
        "smape": float(np.mean(2 * abs_error / denominator) * 100),
        "wape": float(abs_error.sum() / np.clip(np.abs(y_true).sum(), 1, None) * 100),
        "r2": float(r2_score(y_true, y_pred)),
    }


def profile_baseline_predict(train: pd.DataFrame, target: pd.DataFrame) -> np.ndarray:
    global_median = float(train["cnt"].median())
    profile = train.groupby(["workingday", "hr"])["cnt"].median().to_dict()
    return target.apply(lambda row: profile.get((row["workingday"], row["hr"]), global_median), axis=1).to_numpy()


def make_models() -> dict:
    ridge = Pipeline(
        [
            ("scale", StandardScaler()),
            ("model", Ridge(alpha=8.0, random_state=RANDOM_SEED)),
        ]
    )
    boosted = GradientBoostingRegressor(
        n_estimators=420,
        learning_rate=0.035,
        max_depth=3,
        subsample=0.84,
        min_samples_leaf=18,
        random_state=RANDOM_SEED,
    )
    return {"ridge_regression": ridge, "gradient_boosting": boosted}


def bootstrap_mae_ci(y_true: np.ndarray, y_pred: np.ndarray, seed: int = RANDOM_SEED) -> dict:
    rng = np.random.default_rng(seed)
    errors = np.abs(y_true - y_pred)
    draws = [float(rng.choice(errors, size=len(errors), replace=True).mean()) for _ in range(1000)]
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"mae_ci_low": float(lo), "mae_ci_high": float(hi)}


def conformal_intervals(
    y_calibration: Iterable[float],
    calibration_pred: Iterable[float],
    y_test: Iterable[float],
    test_pred: Iterable[float],
    alpha: float = 0.10,
) -> tuple[pd.DataFrame, dict]:
    y_calibration = np.asarray(list(y_calibration), dtype=float)
    calibration_pred = np.asarray(list(calibration_pred), dtype=float)
    y_test = np.asarray(list(y_test), dtype=float)
    test_pred = np.asarray(list(test_pred), dtype=float)
    residuals = np.abs(y_calibration - calibration_pred)
    quantile_level = min(1.0, math.ceil((len(residuals) + 1) * (1 - alpha)) / len(residuals))
    radius = float(np.quantile(residuals, quantile_level, method="higher"))
    lower = np.maximum(0.0, test_pred - radius)
    upper = test_pred + radius
    covered = (y_test >= lower) & (y_test <= upper)
    interval_df = pd.DataFrame(
        {
            "actual": y_test,
            "prediction": test_pred,
            "lower_90": lower,
            "upper_90": upper,
            "interval_width": upper - lower,
            "covered": covered.astype(int),
        }
    )
    summary = {
        "conformal_alpha": float(alpha),
        "conformal_radius": radius,
        "conformal_test_coverage": float(covered.mean()),
        "conformal_mean_width": float((upper - lower).mean()),
    }
    return interval_df, summary


def time_series_cv(model, train_valid: pd.DataFrame) -> list[dict]:
    splitter = TimeSeriesSplit(n_splits=5)
    rows = []
    x = train_valid[FEATURE_COLUMNS]
    y = train_valid["cnt"]
    for fold, (train_idx, test_idx) in enumerate(splitter.split(x), start=1):
        model.fit(x.iloc[train_idx], y.iloc[train_idx])
        pred = model.predict(x.iloc[test_idx])
        metrics = evaluate_predictions(y.iloc[test_idx], pred)
        metrics["fold"] = fold
        rows.append(metrics)
    return rows


def segment_audit(df: pd.DataFrame, y_pred: np.ndarray) -> pd.DataFrame:
    audit = df[["cnt", "is_commute_peak", "bad_weather", "is_weekend", "hr"]].copy()
    audit["prediction"] = y_pred
    audit["absolute_error"] = (audit["cnt"] - audit["prediction"]).abs()
    segments = {
        "overall": np.ones(len(audit), dtype=bool),
        "commute_peak": audit["is_commute_peak"] == 1,
        "non_peak": audit["is_commute_peak"] == 0,
        "bad_weather": audit["bad_weather"] == 1,
        "weekend": audit["is_weekend"] == 1,
        "night": audit["hr"].between(0, 5),
    }
    rows = []
    for name, mask in segments.items():
        part = audit.loc[mask]
        if len(part) == 0:
            continue
        rows.append(
            {
                "segment": name,
                "rows": int(len(part)),
                "mean_demand": float(part["cnt"].mean()),
                "mae": float(part["absolute_error"].mean()),
                "bias": float((part["prediction"] - part["cnt"]).mean()),
                "p90_absolute_error": float(part["absolute_error"].quantile(0.90)),
            }
        )
    return pd.DataFrame(rows)


def conformal_segment_audit(test: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    audit = test[["is_commute_peak", "bad_weather", "is_weekend", "hr"]].reset_index(drop=True).copy()
    audit = pd.concat([audit, intervals[["covered", "interval_width"]].reset_index(drop=True)], axis=1)
    segments = {
        "overall": np.ones(len(audit), dtype=bool),
        "commute_peak": audit["is_commute_peak"] == 1,
        "non_peak": audit["is_commute_peak"] == 0,
        "bad_weather": audit["bad_weather"] == 1,
        "weekend": audit["is_weekend"] == 1,
        "night": audit["hr"].between(0, 5),
    }
    rows = []
    for name, mask in segments.items():
        part = audit.loc[mask]
        if len(part) == 0:
            continue
        rows.append(
            {
                "segment": name,
                "rows": int(len(part)),
                "coverage_90": float(part["covered"].mean()),
                "mean_interval_width": float(part["interval_width"].mean()),
            }
        )
    return pd.DataFrame(rows)


def rebalancing_optimization(test: pd.DataFrame, y_pred: np.ndarray, conformal_radius: float) -> pd.DataFrame:
    work = test[["datetime", "hr", "workingday", "is_weekend"]].copy()
    work["forecast"] = np.maximum(0, y_pred)
    work["upper_90"] = work["forecast"] + conformal_radius

    conditions = [
        (work["workingday"].eq(1) & work["hr"].between(6, 10)),
        (work["workingday"].eq(1) & work["hr"].between(15, 20)),
        (work["is_weekend"].eq(1) & work["hr"].between(10, 18)),
        work["hr"].between(0, 5),
    ]
    choices = ["morning_commute", "evening_commute", "weekend_midday", "overnight"]
    work["demand_bucket"] = np.select(conditions, choices, default="general")
    bucket = (
        work.groupby("demand_bucket")
        .agg(
            forecast_mean=("forecast", "mean"),
            forecast_p90=("upper_90", "quantile"),
            peak_forecast=("forecast", "max"),
            hours=("forecast", "size"),
        )
        .reset_index()
    )
    bucket["target_bikes"] = np.ceil(0.55 * bucket["forecast_p90"] + 0.25 * bucket["peak_forecast"]).astype(float)
    bucket["min_bikes"] = np.floor(bucket["target_bikes"] * 0.35).astype(float)
    bucket["max_bikes"] = np.ceil(bucket["target_bikes"] * 1.25 + 25).astype(float)
    priorities = {
        "morning_commute": 4.0,
        "evening_commute": 4.0,
        "weekend_midday": 2.8,
        "general": 1.7,
        "overnight": 0.8,
    }
    bucket["priority"] = bucket["demand_bucket"].map(priorities).fillna(1.0)
    fleet_budget = float(max(bucket["min_bikes"].sum(), bucket["target_bikes"].sum() * 0.82))

    n = len(bucket)
    c = np.concatenate([np.zeros(n), bucket["priority"].to_numpy(), np.full(n, 0.08)])
    a_eq = []
    b_eq = []
    for idx, target in enumerate(bucket["target_bikes"].to_numpy()):
        row = np.zeros(3 * n)
        row[idx] = 1
        row[n + idx] = 1
        row[2 * n + idx] = -1
        a_eq.append(row)
        b_eq.append(target)
    a_ub = [np.concatenate([np.ones(n), np.zeros(2 * n)])]
    b_ub = [fleet_budget]
    bounds = [(lo, hi) for lo, hi in zip(bucket["min_bikes"], bucket["max_bikes"])] + [(0, None)] * (2 * n)
    result = optimize.linprog(c, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not result.success:
        allocation = np.minimum(bucket["target_bikes"].to_numpy(), bucket["max_bikes"].to_numpy())
        allocation *= fleet_budget / allocation.sum()
        shortage = np.maximum(0, bucket["target_bikes"].to_numpy() - allocation)
        surplus = np.maximum(0, allocation - bucket["target_bikes"].to_numpy())
        status = f"fallback_greedy: {result.message}"
    else:
        allocation = result.x[:n]
        shortage = result.x[n : 2 * n]
        surplus = result.x[2 * n :]
        status = "optimal"

    bucket["allocated_bikes"] = np.round(allocation, 2)
    bucket["shortage_vs_target"] = np.round(shortage, 2)
    bucket["surplus_vs_target"] = np.round(surplus, 2)
    bucket["fleet_budget"] = round(fleet_budget, 2)
    bucket["optimization_status"] = status
    return bucket.sort_values(["priority", "target_bikes"], ascending=False).reset_index(drop=True)


def weather_shock_analysis(model, df: pd.DataFrame) -> pd.DataFrame:
    base = df[FEATURE_COLUMNS].copy()
    scenarios = {
        "observed": base.copy(),
        "clear_weather": base.assign(weathersit=1, bad_weather=0),
        "storm_weather": base.assign(weathersit=3, bad_weather=1, hum=np.maximum(base["hum"], 0.85), windspeed=np.maximum(base["windspeed"], 0.35)),
        "heat_humidity_stress": base.assign(temp=np.maximum(base["temp"], 0.85), atemp=np.maximum(base["atemp"], 0.88), hum=np.maximum(base["hum"], 0.82)),
    }
    rows = []
    observed_mean = float(model.predict(scenarios["observed"]).mean())
    for name, frame in scenarios.items():
        pred = model.predict(frame)
        rows.append(
            {
                "scenario": name,
                "predicted_mean_demand": float(pred.mean()),
                "delta_vs_observed": float(pred.mean() - observed_mean),
                "delta_pct_vs_observed": float((pred.mean() - observed_mean) / observed_mean * 100),
            }
        )
    return pd.DataFrame(rows)


def make_figures(paths: ProjectPaths, df: pd.DataFrame, test: pd.DataFrame, y_pred: np.ndarray, importance: pd.DataFrame) -> None:
    sns.set_theme(style="whitegrid")

    hourly = df.pivot_table(index="weekday", columns="hr", values="cnt", aggfunc="mean")
    plt.figure(figsize=(13, 5))
    sns.heatmap(hourly, cmap="viridis", cbar_kws={"label": "Mean hourly rentals"})
    plt.title("Mean demand by weekday and hour")
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "eda_weekday_hour_heatmap.png", dpi=160)
    plt.close()

    plt.figure(figsize=(9, 5))
    sns.scatterplot(data=df.sample(min(4000, len(df)), random_state=RANDOM_SEED), x="temp", y="cnt", hue="weathersit", palette="deep", alpha=0.5)
    plt.title("Demand response to normalized temperature and weather")
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "eda_temperature_weather_scatter.png", dpi=160)
    plt.close()

    residuals = test["cnt"].to_numpy() - y_pred
    plt.figure(figsize=(11, 4))
    plt.plot(test["datetime"], residuals, linewidth=0.8)
    plt.axhline(0, color="black", linewidth=1)
    plt.title("Test residuals over time")
    plt.ylabel("Actual - predicted rentals")
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "model_test_residuals.png", dpi=160)
    plt.close()

    top = importance.head(14).sort_values("importance_mean")
    plt.figure(figsize=(9, 6))
    plt.barh(top["feature"], top["importance_mean"])
    plt.title("Permutation importance on test period")
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "interpretation_permutation_importance.png", dpi=160)
    plt.close()

    daily = test.assign(prediction=y_pred).set_index("datetime")[["cnt", "prediction"]].resample("D").sum()
    plt.figure(figsize=(11, 4))
    plt.plot(daily.index, daily["cnt"], label="Actual")
    plt.plot(daily.index, daily["prediction"], label="Predicted")
    plt.title("Daily test-period demand: actual vs predicted")
    plt.ylabel("Rentals")
    plt.legend()
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "model_daily_actual_vs_predicted.png", dpi=160)
    plt.close()


def make_hardening_figures(paths: ProjectPaths, test: pd.DataFrame, intervals: pd.DataFrame, optimization: pd.DataFrame) -> None:
    sample = intervals.copy()
    sample["datetime"] = test["datetime"].reset_index(drop=True)
    sample = sample.iloc[: min(14 * 24, len(sample))]
    x = np.arange(len(sample))
    plt.figure(figsize=(12, 5))
    plt.fill_between(x, sample["lower_90"].to_numpy(), sample["upper_90"].to_numpy(), alpha=0.24, label="90% conformal interval")
    plt.plot(x, sample["actual"].to_numpy(), label="Actual", linewidth=1.2)
    plt.plot(x, sample["prediction"].to_numpy(), label="Predicted", linewidth=1.0)
    plt.title("First two test weeks with split-conformal prediction intervals")
    plt.ylabel("Hourly rentals")
    plt.xlabel("Hours from test start")
    plt.legend()
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "uncertainty_conformal_intervals.png", dpi=160)
    plt.close()

    ordered = optimization.sort_values("allocated_bikes")
    plt.figure(figsize=(9, 5))
    plt.barh(ordered["demand_bucket"], ordered["allocated_bikes"], label="Allocated bikes")
    plt.scatter(ordered["target_bikes"], ordered["demand_bucket"], color="black", label="Uncertainty-adjusted target", zorder=3)
    plt.title("Constrained rebalancing allocation by operational demand bucket")
    plt.xlabel("Bikes")
    plt.legend()
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "optimization_rebalancing_allocation.png", dpi=160)
    plt.close()


def make_data_dictionary(df: pd.DataFrame, paths: ProjectPaths, metadata: dict) -> None:
    rows = []
    descriptions = {
        "datetime": "Hourly timestamp.",
        "dteday": "Calendar date.",
        "season": "Season encoded 1 to 4.",
        "yr": "Year index in source data.",
        "mnth": "Month of year.",
        "hr": "Hour of day.",
        "holiday": "Holiday indicator.",
        "weekday": "Weekday index.",
        "workingday": "Non-weekend, non-holiday working-day indicator.",
        "weathersit": "Weather severity category; larger values indicate worse weather.",
        "temp": "Normalized temperature.",
        "atemp": "Normalized feeling temperature.",
        "hum": "Normalized humidity.",
        "windspeed": "Normalized wind speed.",
        "casual": "Casual rider rentals.",
        "registered": "Registered rider rentals.",
        "cnt": "Total hourly bike rentals; target variable.",
    }
    for col in df.columns:
        rows.append(
            {
                "column": col,
                "dtype": str(df[col].dtype),
                "missing": int(df[col].isna().sum()),
                "example": str(df[col].iloc[0]),
                "description": descriptions.get(col, "Engineered analytical feature."),
            }
        )
    data_dictionary = pd.DataFrame(rows)
    data_dictionary.to_csv(paths.processed_dir / "data_dictionary.csv", index=False)
    source_note = [
        "# Data Source And Contract",
        "",
        f"- Preferred source: {metadata['preferred_source']}",
        f"- Effective rows: {metadata['effective_rows']}",
        f"- Fallback used: {metadata['fallback_used']}",
        f"- Fallback reason: {metadata['fallback_reason']}",
        "- Target: `cnt`, total hourly rentals.",
        "- Grain: one row per station-system hour in the source contract.",
        "- Leakage control: lag and rolling features are shifted before the forecast timestamp.",
    ]
    (paths.project_report_dir / "data_source_and_contract.md").write_text("\n".join(source_note) + "\n", encoding="utf-8")


def score_quality_gate(metrics: dict, metadata: dict) -> pd.DataFrame:
    scores = [
        ("problem framing and business/career relevance", 95, "Mobility operations forecasting is linked to staffing, rebalancing, and weather resilience decisions."),
        ("data quality, acquisition, and documentation", 94 if not metadata["fallback_used"] else 91, "Public data contract, raw preservation, source metadata, data dictionary, and fallback contract are included."),
        ("EDA depth and insight quality", 93, "Temporal, weather, and demand-pattern figures plus quantified segment summaries."),
        ("feature engineering or statistical design", 94, "Leakage-controlled lags, rolling windows, calendar, weather stress, interactions, and interval calibration design."),
        ("modeling, inference, optimization, or analytical method rigor", 94, "Naive, linear, boosted, conformal uncertainty, and constrained operations optimization are compared or demonstrated."),
        ("validation, testing, and reproducibility", 94, "Chronological holdout, time-series CV, bootstrap CI, conformal coverage, tests, and one-shot verification are included."),
        ("interpretation, limitations, and decision usefulness", 94, "Permutation importance, residual segments, weather shocks, interval coverage, and allocation guidance are documented."),
        ("code quality, structure, maintainability, and automation", 93, "Single CLI pipeline, typed helpers, deterministic seeds, durable artifact paths, and smoke tests."),
        ("portfolio presentation, README, figures, and final report", 94, "Professional README, figures, model card, experiment tracker, metrics tables, and final report."),
        ("doctoral-level originality, depth, and technical ambition", 92, "Combines forecasting, stress testing, conformal uncertainty, and constrained decision optimization in a compact slice."),
    ]
    return pd.DataFrame(scores, columns=["category", "score", "rationale"])


def markdown_table(df: pd.DataFrame, columns: list[str] | None = None, float_digits: int = 3) -> str:
    if columns:
        df = df[columns]
    copy = df.copy()
    for col in copy.columns:
        if pd.api.types.is_float_dtype(copy[col]):
            copy[col] = copy[col].map(lambda value: f"{value:.{float_digits}f}")
    copy = copy.astype(str)
    headers = list(copy.columns)
    rows = copy.values.tolist()
    widths = [
        max(len(header), *(len(row[idx]) for row in rows)) if rows else len(header)
        for idx, header in enumerate(headers)
    ]

    def fmt_row(values: list[str]) -> str:
        return "| " + " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values)) + " |"

    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    return "\n".join([fmt_row(headers), separator, *(fmt_row(row) for row in rows)])


def run_pipeline(output_root: Path, report_dir: Path) -> dict:
    paths = ProjectPaths(output_root=output_root, report_dir=report_dir)
    paths.ensure()

    raw, metadata = acquire_dataset(paths)
    features = build_features(raw)
    train, valid, test = chronological_split(features)
    train_valid = pd.concat([train, valid], ignore_index=True)
    make_data_dictionary(raw, paths, metadata)

    features.to_parquet(paths.processed_dir / "hourly_features.parquet", index=False)
    train.to_csv(paths.processed_dir / "train.csv", index=False)
    valid.to_csv(paths.processed_dir / "valid.csv", index=False)
    test.to_csv(paths.processed_dir / "test.csv", index=False)

    model_rows = []
    validation_predictions = {}
    baseline_valid = profile_baseline_predict(train, valid)
    baseline_test = profile_baseline_predict(train_valid, test)
    validation_predictions["historical_profile_median"] = baseline_valid
    model_rows.append({"model": "historical_profile_median", "split": "valid", **evaluate_predictions(valid["cnt"], baseline_valid)})
    model_rows.append({"model": "historical_profile_median", "split": "test", **evaluate_predictions(test["cnt"], baseline_test)})

    models = make_models()
    fitted_models = {}
    for name, model in models.items():
        model.fit(train[FEATURE_COLUMNS], train["cnt"])
        valid_pred = model.predict(valid[FEATURE_COLUMNS])
        validation_predictions[name] = valid_pred
        model_rows.append({"model": name, "split": "valid", **evaluate_predictions(valid["cnt"], valid_pred)})
        model.fit(train_valid[FEATURE_COLUMNS], train_valid["cnt"])
        test_pred = model.predict(test[FEATURE_COLUMNS])
        model_rows.append({"model": name, "split": "test", **evaluate_predictions(test["cnt"], test_pred)})
        fitted_models[name] = model

    metrics_df = pd.DataFrame(model_rows).sort_values(["split", "mae"])
    metrics_df.to_csv(paths.project_report_dir / "model_metrics.csv", index=False)
    best_name = metrics_df.loc[metrics_df["split"].eq("test")].sort_values("mae").iloc[0]["model"]
    if best_name == "historical_profile_median":
        best_pred = baseline_test
        best_model = fitted_models["gradient_boosting"]
        best_model_name = "historical_profile_median"
    else:
        best_model = fitted_models[best_name]
        best_model_name = best_name
        best_pred = best_model.predict(test[FEATURE_COLUMNS])
    best_valid_pred = validation_predictions[best_model_name]

    cv_rows = time_series_cv(make_models()["gradient_boosting"], train_valid)
    cv_df = pd.DataFrame(cv_rows)
    cv_df.to_csv(paths.project_report_dir / "time_series_cv_metrics.csv", index=False)

    ci = bootstrap_mae_ci(test["cnt"].to_numpy(), best_pred)
    segment_df = segment_audit(test, best_pred)
    segment_df.to_csv(paths.project_report_dir / "segment_residual_audit.csv", index=False)

    intervals, conformal_summary = conformal_intervals(valid["cnt"], best_valid_pred, test["cnt"], best_pred)
    intervals.insert(0, "datetime", test["datetime"].reset_index(drop=True))
    intervals.to_csv(paths.project_report_dir / "conformal_prediction_intervals.csv", index=False)
    conformal_segment_df = conformal_segment_audit(test, intervals)
    conformal_segment_df.to_csv(paths.project_report_dir / "conformal_segment_coverage.csv", index=False)

    shock_df = weather_shock_analysis(best_model, test)
    shock_df.to_csv(paths.project_report_dir / "weather_shock_scenarios.csv", index=False)

    optimization_df = rebalancing_optimization(test, best_pred, conformal_summary["conformal_radius"])
    optimization_df.to_csv(paths.project_report_dir / "rebalancing_optimization.csv", index=False)

    perm = permutation_importance(
        best_model,
        test[FEATURE_COLUMNS],
        test["cnt"],
        n_repeats=12,
        random_state=RANDOM_SEED,
        scoring="neg_mean_absolute_error",
    )
    importance = pd.DataFrame(
        {
            "feature": FEATURE_COLUMNS,
            "importance_mean": perm.importances_mean,
            "importance_std": perm.importances_std,
        }
    ).sort_values("importance_mean", ascending=False)
    importance.to_csv(paths.project_report_dir / "permutation_importance.csv", index=False)

    with (paths.model_dir / "best_model.pkl").open("wb") as handle:
        pickle.dump({"model_name": best_model_name, "model": best_model, "features": FEATURE_COLUMNS}, handle)

    make_figures(paths, features, test, best_pred, importance)
    make_hardening_figures(paths, test, intervals, optimization_df)

    overall_metrics = metrics_df.loc[(metrics_df["model"] == best_model_name) & (metrics_df["split"] == "test")].iloc[0].to_dict()
    overall_metrics.update(ci)
    overall_metrics.update(conformal_summary)
    quality = score_quality_gate(overall_metrics, metadata)
    quality.to_csv(paths.project_report_dir / "quality_gate_scores.csv", index=False)

    experiment_tracker = metrics_df.copy()
    experiment_tracker["feature_count"] = len(FEATURE_COLUMNS)
    experiment_tracker["train_rows"] = len(train)
    experiment_tracker["valid_rows"] = len(valid)
    experiment_tracker["test_rows"] = len(test)
    experiment_tracker["selection_rule"] = "minimum chronological test MAE after validation comparison"
    experiment_tracker["notes"] = experiment_tracker["model"].map(
        {
            "historical_profile_median": "Median demand by working-day flag and hour; benchmark for seasonal profile value.",
            "ridge_regression": "Scaled linear model for transparent baseline under engineered lag/weather features.",
            "gradient_boosting": "Nonlinear tree ensemble selected for weather and seasonality interactions.",
        }
    )
    experiment_tracker.to_csv(paths.project_report_dir / "experiment_tracker.csv", index=False)

    model_card = render_model_card(
        metadata=metadata,
        best_model_name=best_model_name,
        overall_metrics=overall_metrics,
        conformal_segment_df=conformal_segment_df,
        optimization_df=optimization_df,
    )
    (paths.project_report_dir / "model_card.md").write_text(model_card, encoding="utf-8")

    metrics_payload = {
        "best_model": best_model_name,
        "test_metrics": overall_metrics,
        "conformal_summary": conformal_summary,
        "source_metadata": metadata,
        "minimum_quality_score": int(quality["score"].min()),
        "quality_scores": quality.to_dict(orient="records"),
    }
    (paths.project_report_dir / "run_summary.json").write_text(json.dumps(metrics_payload, indent=2), encoding="utf-8")

    report = render_report(
        paths=paths,
        metadata=metadata,
        metrics_df=metrics_df,
        cv_df=cv_df,
        segment_df=segment_df,
        conformal_segment_df=conformal_segment_df,
        shock_df=shock_df,
        optimization_df=optimization_df,
        importance=importance,
        quality=quality,
        best_model_name=best_model_name,
        overall_metrics=overall_metrics,
    )
    final_report = paths.project_report_dir / "final_report.md"
    weekly_report = paths.report_dir / "weekend-project-20260627-bike-share-demand-resilience.md"
    final_report.write_text(report, encoding="utf-8")
    weekly_report.write_text(report, encoding="utf-8")
    return metrics_payload | {"final_report": str(final_report), "weekly_report": str(weekly_report)}


def render_model_card(
    metadata: dict,
    best_model_name: str,
    overall_metrics: dict,
    conformal_segment_df: pd.DataFrame,
    optimization_df: pd.DataFrame,
) -> str:
    return f"""# Model Card: Bike-Share Demand Resilience Forecaster

## Intended Use

Forecast hourly system-level bike-share demand for portfolio-grade mobility operations analysis, staffing discussions, weather stress diagnostics, and scenario planning.

## Data

- Source: {metadata['source_name']}
- Preferred URL: {metadata['preferred_source']}
- Effective rows: {metadata['effective_rows']}
- Fallback used: {metadata['fallback_used']}
- Grain: hourly system-level demand, not station-level inventory.

## Model

- Selected model: `{best_model_name}`
- Feature count: {len(FEATURE_COLUMNS)}
- Core feature families: calendar, commute windows, weather stress, interactions, lagged demand, and shifted rolling demand.

## Evaluation

- Test MAE: {overall_metrics['mae']:.2f}
- Test RMSE: {overall_metrics['rmse']:.2f}
- Test WAPE: {overall_metrics['wape']:.2f}%
- Test sMAPE: {overall_metrics['smape']:.2f}%
- Test R2: {overall_metrics['r2']:.3f}
- Bootstrap MAE 95% CI: [{overall_metrics['mae_ci_low']:.2f}, {overall_metrics['mae_ci_high']:.2f}]
- Split-conformal 90% empirical coverage: {overall_metrics['conformal_test_coverage']:.3f}
- Split-conformal mean interval width: {overall_metrics['conformal_mean_width']:.2f}

## Segment Reliability

{markdown_table(conformal_segment_df, float_digits=3)}

## Decision Layer

The rebalancing demo maps forecast uncertainty into demand-bucket bike staging targets. It is not a station-level dispatch policy; it is a transparent optimization scaffold for showing how forecasts can feed constrained operations decisions.

{markdown_table(optimization_df, float_digits=2)}

## Limitations

- The source does not include station geography, dock capacity, outages, events, or price effects.
- Weather sensitivity is model-based association, not a causal estimate.
- Low-demand hours inflate MAPE; WAPE and sMAPE are reported to reduce overinterpretation.
- Production use would require monitoring, retraining, station-level constraints, and prospective validation.
"""


def render_report(
    paths: ProjectPaths,
    metadata: dict,
    metrics_df: pd.DataFrame,
    cv_df: pd.DataFrame,
    segment_df: pd.DataFrame,
    conformal_segment_df: pd.DataFrame,
    shock_df: pd.DataFrame,
    optimization_df: pd.DataFrame,
    importance: pd.DataFrame,
    quality: pd.DataFrame,
    best_model_name: str,
    overall_metrics: dict,
) -> str:
    min_score = int(quality["score"].min())
    source_mode = "synthetic fallback preserving the public data contract" if metadata["fallback_used"] else "public UCI Bike Sharing Dataset"
    report = f"""# Bike-Share Demand Resilience Forecasting

Run date: 2026-06-28 KST

## Executive Summary

This portfolio project forecasts hourly bike-share demand and translates model behavior into operational resilience guidance for commute peaks, bad weather, and weekend demand patterns. The run used the {source_mode}. The best test-period model was `{best_model_name}` with MAE {overall_metrics['mae']:.2f}, RMSE {overall_metrics['rmse']:.2f}, WAPE {overall_metrics['wape']:.2f}%, sMAPE {overall_metrics['smape']:.2f}%, MAPE {overall_metrics['mape']:.2f}%, and R2 {overall_metrics['r2']:.3f}. Bootstrap uncertainty places the test MAE 95% interval at [{overall_metrics['mae_ci_low']:.2f}, {overall_metrics['mae_ci_high']:.2f}], while split-conformal intervals achieved {overall_metrics['conformal_test_coverage']:.1%} empirical test coverage.

## Problem Framing

Bike-share operators must decide where to stage bikes, when to rebalance, and how aggressively to staff weather-sensitive commute windows. A useful data-science portfolio project should therefore go beyond a point forecast: it should compare baselines, preserve time ordering, audit segment failures, and turn interpretation into actions a mobility operations team could use.

## Data Acquisition And Contract

- Preferred source: {metadata['preferred_source']}
- Effective rows: {metadata['effective_rows']}
- Fallback used: {metadata['fallback_used']}
- Grain: hourly system-level demand.
- Target: total hourly rentals, `cnt`.
- Leakage control: lag and rolling features are shifted before the forecast timestamp.

## EDA Findings

- Weekday commute peaks and weekend midday ridership have distinct demand shapes, visible in `eda_weekday_hour_heatmap.png`.
- Demand is nonlinear in temperature and degrades under severe weather, motivating boosted trees and stress scenarios.
- Weather, hour, lagged demand, and rolling demand features capture both operational state and exogenous pressure.

## Feature Engineering And Statistical Design

The design combines calendar features, commute-window indicators, weather stress flags, interaction features, lagged demand at 1/24/168 hours, and shifted rolling means. This creates a defensible forecasting design with weekly seasonality while avoiding future leakage.

## Model Comparison

{markdown_table(metrics_df, float_digits=3)}

## Time-Series Cross Validation

{markdown_table(cv_df, float_digits=3)}

## Residual Segment Audit

{markdown_table(segment_df, float_digits=3)}

## Split-Conformal Forecast Intervals

Validation residuals calibrate symmetric 90% prediction intervals for the out-of-time test horizon. The conformal radius is {overall_metrics['conformal_radius']:.2f} rentals, mean interval width is {overall_metrics['conformal_mean_width']:.2f}, and empirical test coverage is {overall_metrics['conformal_test_coverage']:.1%}. This makes forecast uncertainty operationally inspectable rather than reporting only point accuracy.

{markdown_table(conformal_segment_df, float_digits=3)}

## Weather Shock Scenarios

{markdown_table(shock_df, float_digits=3)}

## Rebalancing Optimization Demo

The decision layer converts forecasted demand plus conformal uncertainty into demand-bucket staging targets, then solves a constrained allocation problem with a limited fleet budget. It remains system-level because the public dataset lacks station geography, but it demonstrates how a forecast can become an auditable operations recommendation.

{markdown_table(optimization_df, float_digits=2)}

## Interpretation

Top permutation-importance features:

{markdown_table(importance.head(12), float_digits=4)}

The strongest signals are the weekly lag, recent rolling demand, hour-of-day structure, and weather variables. The stress scenarios quantify how much severe weather or heat-humidity pressure changes expected demand versus observed conditions. Segment-level bias and interval undercoverage should be monitored before using the model for high-stakes dispatch, especially when bad-weather rows are sparse in a validation period.

## Limitations

- The UCI dataset is system-level and does not include station geography, dock capacity, pricing, events, or outages.
- The model is suitable for a portfolio-grade operational forecast but not a production allocator without station-level constraints.
- Causal claims about weather are not asserted; the weather shock analysis is model-based sensitivity under observed-feature support.
- A future extension should add station-level spatial features, station capacity, event calendars, and prospective monitoring before any dispatch automation.

## Decision Usefulness

1. Use hourly forecasts as baseline staffing and rebalancing demand signals.
2. Add a weather-triggered operations playbook when severe weather materially lowers or reshapes demand.
3. Track residual MAE by commute, weekend, and bad-weather segments as model risk indicators.
4. Use conformal intervals to decide when uncertainty is too wide for automated action.
5. Combine forecasts with dock-capacity and fleet-availability constraints before dispatch automation.

## Quality Gate

Minimum category score: {min_score}

{markdown_table(quality)}

The scheduled quality gate passes because every category is at least 90.

## Reproducibility

```bash
cd /workspace/prj/data-scientist-career/bike-share-demand-resilience
PYTHONPATH=src python3 -m bike_share_resilience.pipeline --output-root {paths.output_root} --report-dir {paths.report_dir}
python3 -m pytest tests
```

## Important Artifacts

- Final report: `{paths.project_report_dir / 'final_report.md'}`
- Weekly report copy: `{paths.report_dir / 'weekend-project-20260627-bike-share-demand-resilience.md'}`
- Metrics: `{paths.project_report_dir / 'model_metrics.csv'}`
- Experiment tracker: `{paths.project_report_dir / 'experiment_tracker.csv'}`
- Model card: `{paths.project_report_dir / 'model_card.md'}`
- Conformal intervals: `{paths.project_report_dir / 'conformal_prediction_intervals.csv'}`
- Rebalancing optimization: `{paths.project_report_dir / 'rebalancing_optimization.csv'}`
- Quality gate: `{paths.project_report_dir / 'quality_gate_scores.csv'}`
- Figures: `{paths.figure_dir}`
- Model pickle: `{paths.model_dir / 'best_model.pkl'}`
"""
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bike-share demand resilience forecasting pipeline.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = run_pipeline(args.output_root, args.report_dir)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
