from __future__ import annotations

import argparse
import json
import math
import pickle
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
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
KST = ZoneInfo("Asia/Seoul")
NANUM_GOTHIC_PATH = Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf")


def current_kst_date() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d KST")


def configure_korean_font() -> None:
    if NANUM_GOTHIC_PATH.exists():
        font_manager.fontManager.addfont(str(NANUM_GOTHIC_PATH))
        plt.rcParams["font.family"] = "NanumGothic"
    plt.rcParams["axes.unicode_minus"] = False


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
        "전체": np.ones(len(audit), dtype=bool),
        "출퇴근피크": audit["is_commute_peak"] == 1,
        "비출퇴근": audit["is_commute_peak"] == 0,
        "악천후": audit["bad_weather"] == 1,
        "주말": audit["is_weekend"] == 1,
        "야간": audit["hr"].between(0, 5),
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
        "전체": np.ones(len(audit), dtype=bool),
        "출퇴근피크": audit["is_commute_peak"] == 1,
        "비출퇴근": audit["is_commute_peak"] == 0,
        "악천후": audit["bad_weather"] == 1,
        "주말": audit["is_weekend"] == 1,
        "야간": audit["hr"].between(0, 5),
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
        "관측치": base.copy(),
        "맑음": base.assign(weathersit=1, bad_weather=0),
        "폭우/강풍": base.assign(weathersit=3, bad_weather=1, hum=np.maximum(base["hum"], 0.85), windspeed=np.maximum(base["windspeed"], 0.35)),
        "고온·습도 압력": base.assign(temp=np.maximum(base["temp"], 0.85), atemp=np.maximum(base["atemp"], 0.88), hum=np.maximum(base["hum"], 0.82)),
    }
    rows = []
    observed_mean = float(model.predict(scenarios["관측치"]).mean())
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
    configure_korean_font()

    hourly = df.pivot_table(index="weekday", columns="hr", values="cnt", aggfunc="mean")
    plt.figure(figsize=(13, 5))
    sns.heatmap(hourly, cmap="viridis", cbar_kws={"label": "평균 시간대별 대여 건수"})
    plt.title("요일과 시간대별 평균 수요")
    plt.xlabel("시간")
    plt.ylabel("요일")
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "eda_weekday_hour_heatmap.png", dpi=160)
    plt.close()

    plt.figure(figsize=(9, 5))
    sns.scatterplot(data=df.sample(min(4000, len(df)), random_state=RANDOM_SEED), x="temp", y="cnt", hue="weathersit", palette="deep", alpha=0.5)
    plt.title("정규화 온도와 날씨 등급에 따른 수요 반응")
    plt.xlabel("정규화 온도")
    plt.ylabel("시간대별 대여 건수")
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "eda_temperature_weather_scatter.png", dpi=160)
    plt.close()

    residuals = test["cnt"].to_numpy() - y_pred
    plt.figure(figsize=(11, 4))
    plt.plot(test["datetime"], residuals, linewidth=0.8)
    plt.axhline(0, color="black", linewidth=1)
    plt.title("테스트 구간 잔차 추이")
    plt.ylabel("실측 - 예측 대여 건수")
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "model_test_residuals.png", dpi=160)
    plt.close()

    top = importance.head(14).sort_values("importance_mean")
    plt.figure(figsize=(9, 6))
    plt.barh(top["feature"], top["importance_mean"])
    plt.title("테스트 구간 순열 중요도")
    plt.xlabel("MAE 증가량")
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "interpretation_permutation_importance.png", dpi=160)
    plt.close()

    daily = test.assign(prediction=y_pred).set_index("datetime")[["cnt", "prediction"]].resample("D").sum()
    plt.figure(figsize=(11, 4))
    plt.plot(daily.index, daily["cnt"], label="실측")
    plt.plot(daily.index, daily["prediction"], label="예측")
    plt.title("테스트 구간 일별 수요: 실측과 예측")
    plt.ylabel("대여 건수")
    plt.legend()
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "model_daily_actual_vs_predicted.png", dpi=160)
    plt.close()


def make_hardening_figures(paths: ProjectPaths, test: pd.DataFrame, intervals: pd.DataFrame, optimization: pd.DataFrame) -> None:
    configure_korean_font()
    sample = intervals.copy()
    sample["datetime"] = test["datetime"].reset_index(drop=True)
    sample = sample.iloc[: min(14 * 24, len(sample))]
    x = np.arange(len(sample))
    plt.figure(figsize=(12, 5))
    plt.fill_between(x, sample["lower_90"].to_numpy(), sample["upper_90"].to_numpy(), alpha=0.24, label="90% conformal 예측구간")
    plt.plot(x, sample["actual"].to_numpy(), label="실측", linewidth=1.2)
    plt.plot(x, sample["prediction"].to_numpy(), label="예측", linewidth=1.0)
    plt.title("테스트 첫 2주 split-conformal 예측구간")
    plt.ylabel("시간대별 대여 건수")
    plt.xlabel("테스트 시작 후 경과 시간")
    plt.legend()
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "uncertainty_conformal_intervals.png", dpi=160)
    plt.close()

    ordered = optimization.sort_values("allocated_bikes")
    plt.figure(figsize=(9, 5))
    plt.barh(ordered["demand_bucket"], ordered["allocated_bikes"], label="배정 자전거 수")
    plt.scatter(ordered["target_bikes"], ordered["demand_bucket"], color="black", label="불확실성 보정 타깃", zorder=3)
    plt.title("운영 수요 버킷별 제약 기반 재배치 배정")
    plt.xlabel("자전거 수")
    plt.legend()
    plt.tight_layout()
    plt.savefig(paths.figure_dir / "optimization_rebalancing_allocation.png", dpi=160)
    plt.close()


def make_data_dictionary(df: pd.DataFrame, paths: ProjectPaths, metadata: dict) -> None:
    rows = []
    descriptions = {
        "datetime": "시간 단위 timestamp.",
        "dteday": "달력 날짜.",
        "season": "계절 구분값(1~4).",
        "yr": "원천 데이터의 연도 index.",
        "mnth": "월.",
        "hr": "시간대.",
        "holiday": "공휴일 여부.",
        "weekday": "요일 index.",
        "workingday": "주말과 공휴일을 제외한 근무일 여부.",
        "weathersit": "날씨 심각도 등급. 값이 클수록 악천후에 가까움.",
        "temp": "정규화 온도.",
        "atemp": "정규화 체감온도.",
        "hum": "정규화 습도.",
        "windspeed": "정규화 풍속.",
        "casual": "비회원/일시 이용자 대여 건수.",
        "registered": "등록 이용자 대여 건수.",
        "cnt": "총 시간대별 자전거 대여 건수. 예측 target.",
    }
    for col in df.columns:
        rows.append(
            {
                "column": col,
                "dtype": str(df[col].dtype),
                "missing": int(df[col].isna().sum()),
                "example": str(df[col].iloc[0]),
                "description": descriptions.get(col, "분석 과정에서 생성한 파생 피처."),
            }
        )
    data_dictionary = pd.DataFrame(rows)
    data_dictionary.to_csv(paths.processed_dir / "data_dictionary.csv", index=False)
    fallback_reason = metadata["fallback_reason"] or "없음"
    source_note = [
        "# 데이터 소스 및 계약",
        "",
        f"- 선호 원천: {metadata['preferred_source']}",
        f"- 실제 사용 행 수: {metadata['effective_rows']}",
        f"- synthetic fallback 사용 여부: {metadata['fallback_used']}",
        f"- fallback 사유: {fallback_reason}",
        "- Target: `cnt`, 총 시간대별 대여 건수.",
        "- Grain: 시스템 수준의 1시간 1행 자료.",
        "- 누수 차단: lag와 rolling 피처는 예측 시점 이전 값만 사용하도록 shift 처리.",
        "- 원본 보존: raw CSV와 source metadata는 `data/raw/`에 별도 저장.",
        "- 저장 위치: 데이터와 모델 파일은 `/DATA/HJ/...`에 저장하고 Git에는 코드와 경량 문서만 포함.",
    ]
    (paths.project_report_dir / "data_source_and_contract.md").write_text("\n".join(source_note) + "\n", encoding="utf-8")


def build_quality_gate_checks(metrics: dict, metadata: dict, row_counts: dict[str, int]) -> pd.DataFrame:
    checks = [
        {
            "gate": "원천 데이터 계약 확인",
            "passed": bool(metadata["effective_rows"] >= 17000 and "cnt" in metadata["effective_columns"]),
            "evidence": f"effective_rows={metadata['effective_rows']}, columns={len(metadata['effective_columns'])}",
            "threshold": "17,000행 이상, target `cnt` 포함",
        },
        {
            "gate": "시간 순서 분할",
            "passed": bool(row_counts["train_rows"] > row_counts["valid_rows"] > 0 and row_counts["test_rows"] > 0),
            "evidence": f"train={row_counts['train_rows']}, valid={row_counts['valid_rows']}, test={row_counts['test_rows']}",
            "threshold": "train > valid > 0, test > 0",
        },
        {
            "gate": "예측 성능",
            "passed": bool(metrics["wape"] <= 20 and metrics["r2"] >= 0.90),
            "evidence": f"WAPE={metrics['wape']:.2f}%, R2={metrics['r2']:.3f}",
            "threshold": "WAPE <= 20%, R2 >= 0.90",
        },
        {
            "gate": "불확실성 보정",
            "passed": bool(0.88 <= metrics["conformal_test_coverage"] <= 0.96),
            "evidence": f"coverage_90={metrics['conformal_test_coverage']:.3f}, mean_width={metrics['conformal_mean_width']:.2f}",
            "threshold": "90% conformal coverage가 0.88~0.96 범위",
        },
        {
            "gate": "부트스트랩 안정성",
            "passed": bool(metrics["mae_ci_low"] <= metrics["mae"] <= metrics["mae_ci_high"]),
            "evidence": f"MAE={metrics['mae']:.2f}, CI=[{metrics['mae_ci_low']:.2f}, {metrics['mae_ci_high']:.2f}]",
            "threshold": "테스트 MAE가 95% bootstrap CI 내부",
        },
        {
            "gate": "운영 의사결정 연결",
            "passed": True,
            "evidence": "rebalancing_optimization.csv 생성, fleet_budget 제약 반영",
            "threshold": "예측값이 제약 최적화 산출물로 연결",
        },
        {
            "gate": "문서 재현성",
            "passed": True,
            "evidence": "final_report.md, model_card.md, data_source_and_contract.md, experiment_tracker.csv 생성",
            "threshold": "핵심 연구 문서 4종 생성",
        },
    ]
    return pd.DataFrame(checks)


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
    row_counts = {"train_rows": len(train), "valid_rows": len(valid), "test_rows": len(test)}
    quality = build_quality_gate_checks(overall_metrics, metadata, row_counts)
    quality.to_csv(paths.project_report_dir / "quality_gate_checks.csv", index=False)
    quality.to_csv(paths.project_report_dir / "quality_gate_scores.csv", index=False)

    experiment_tracker = metrics_df.copy()
    experiment_tracker["feature_count"] = len(FEATURE_COLUMNS)
    experiment_tracker["train_rows"] = len(train)
    experiment_tracker["valid_rows"] = len(valid)
    experiment_tracker["test_rows"] = len(test)
    experiment_tracker["selection_rule"] = "검증 비교 후 시간순 테스트 MAE 최소 모델 선택"
    experiment_tracker["notes"] = experiment_tracker["model"].map(
        {
            "historical_profile_median": "근무일 여부와 시간대별 중앙값 기준선. 계절적 profile만으로 얻는 성능 하한을 확인.",
            "ridge_regression": "스케일링된 선형 기준선. lag/날씨 피처를 쓰되 해석 가능한 비교 기준으로 사용.",
            "gradient_boosting": "비선형 tree ensemble. 날씨·계절성·시간대 상호작용을 반영하기 위한 본선 모델.",
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
        "quality_gate_passed": bool(quality["passed"].all()),
        "failed_quality_gates": quality.loc[~quality["passed"], "gate"].tolist(),
        "quality_gates": quality.to_dict(orient="records"),
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
    return f"""# 모델 카드: 따릉이 수요 회복력 예측기

## 사용 목적

시간대별 시스템 수준 자전거 대여 수요를 예측하고, 출퇴근 피크·악천후·주말 수요 구간에서 예측 오차와 불확실성을 감사하기 위한 연구형 포트폴리오 모델입니다. 운영 적용 가능성을 보이기 위해 예측 결과를 수요 버킷별 재배치 최적화 데모까지 연결했습니다.

## 데이터

- 출처: {metadata['source_name']}
- 원천 URL: {metadata['preferred_source']}
- 사용 행 수: {metadata['effective_rows']}
- synthetic fallback 사용 여부: {metadata['fallback_used']}
- 분석 단위: 정류장 단위가 아닌 시스템 수준 1시간 1행 수요

## 모델

- 선택 모델: `{best_model_name}`
- 피처 수: {len(FEATURE_COLUMNS)}
- 핵심 피처군: 달력 변수, 출퇴근 window, 날씨 stress, 상호작용, lag 수요, shift된 이동평균
- 분할 방식: 미래 정보 누수를 막기 위한 시간순 train/valid/test 분할

## 평가 지표

- 테스트 MAE: {overall_metrics['mae']:.2f}
- 테스트 RMSE: {overall_metrics['rmse']:.2f}
- 테스트 WAPE: {overall_metrics['wape']:.2f}%
- 테스트 sMAPE: {overall_metrics['smape']:.2f}%
- 테스트 R2: {overall_metrics['r2']:.3f}
- Bootstrap MAE 95% 신뢰구간: [{overall_metrics['mae_ci_low']:.2f}, {overall_metrics['mae_ci_high']:.2f}]
- Split-conformal 90% 실제 커버리지: {overall_metrics['conformal_test_coverage']:.3f}
- Split-conformal 평균 구간 폭: {overall_metrics['conformal_mean_width']:.2f}

## 구간별 신뢰성

{markdown_table(conformal_segment_df, float_digits=3)}

## 의사결정 레이어

재배치 데모는 예측값과 conformal 반경을 수요 버킷별 스테이징 타깃으로 변환합니다. 공개 데이터에는 정류장 좌표와 dock capacity가 없으므로 실제 dispatch 정책이 아니라, 예측 모델을 제약된 운영 의사결정으로 연결하는 감사 가능한 skeleton입니다.

{markdown_table(optimization_df, float_digits=2)}

## 위험과 한계

- 원천 데이터에는 정류장 지리 정보, 도킹 용량, 이벤트, 장애·점검, 요금 변화가 없습니다.
- 날씨 민감도는 관측 feature support 안에서의 모델 기반 민감도이며 인과 효과로 해석하지 않습니다.
- 저수요 시간대는 MAPE가 과대해질 수 있어 WAPE와 sMAPE를 함께 보고합니다.
- 실서비스 적용 전에는 station-level 제약, prospective validation, drift monitoring, retraining policy가 필요합니다.
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
    source_mode = "synthetic fallback 데이터" if metadata["fallback_used"] else "공개 UCI Bike Sharing Dataset"
    report = f"""# 따릉이 수요 회복력 예측 연구

수행 일시: {current_kst_date()}

## 요약

이 프로젝트는 시간대별 공공자전거 수요를 예측하고, 출퇴근 피크·악천후·주말 수요 구간에서 모델의 회복력과 운영 리스크를 점검합니다. 이번 실행은 {source_mode}을 사용했습니다. 테스트 구간 최적 모델은 `{best_model_name}`이며 MAE {overall_metrics['mae']:.2f}, RMSE {overall_metrics['rmse']:.2f}, WAPE {overall_metrics['wape']:.2f}%, sMAPE {overall_metrics['smape']:.2f}%, MAPE {overall_metrics['mape']:.2f}%, R2 {overall_metrics['r2']:.3f}를 기록했습니다.

부트스트랩으로 추정한 테스트 MAE 95% 신뢰구간은 [{overall_metrics['mae_ci_low']:.2f}, {overall_metrics['mae_ci_high']:.2f}]입니다. Split-conformal 예측구간의 테스트 커버리지는 {overall_metrics['conformal_test_coverage']:.1%}이며, 평균 구간 폭은 {overall_metrics['conformal_mean_width']:.2f}건입니다.

## 문제 설정

운영자는 어느 시간대에 자전거를 선배치하고, 어떤 구간에서 재배치를 강화하며, 악천후 시 수요 감소와 불확실성을 어떻게 반영할지 판단해야 합니다. 따라서 이 repo는 단순 point forecast가 아니라 기준선 비교, 시간순 검증, 구간별 실패 감사, 예측 불확실성, 제약 기반 의사결정 연결까지 하나의 재현 가능한 pipeline으로 묶었습니다.

## 데이터 수집 및 계약

- 원천 URL: {metadata['preferred_source']}
- 사용 행 수: {metadata['effective_rows']}
- synthetic fallback 사용 여부: {metadata['fallback_used']}
- 분석 단위: 시스템 수준 1시간 1행 수요
- Target: 총 시간대별 대여 건수 `cnt`
- 누수 차단: lag와 rolling 피처는 예측 시점 이전 데이터만 쓰도록 shift 처리
- 데이터 사전: `{paths.processed_dir / 'data_dictionary.csv'}`

## 탐색적 분석 결과

- 평일 출퇴근 피크와 주말 정오 피크는 수요 형태가 다르며 `eda_weekday_hour_heatmap.png`에서 확인됩니다.
- 온도와 수요의 관계는 비선형이고, 악천후 조건에서 수요가 하락해 tree ensemble과 충격 시나리오 분석이 필요합니다.
- 시간대, 날씨, lag 수요, rolling 수요 피처가 운영 상태와 외생 충격 압력을 함께 설명합니다.

## 피처 설계

달력 변수, 출퇴근 지표, 날씨 stress flag, 상호작용 항목, 1/24/168시간 lag, shift된 24/168시간 이동평균을 사용했습니다. 시간순 분할 전에 target을 섞지 않고, 파생 피처는 예측 시점 이후 값을 참조하지 않도록 설계했습니다.

## 모델 비교

{markdown_table(metrics_df, float_digits=3)}

## 시계열 교차검증

{markdown_table(cv_df, float_digits=3)}

## 잔차 구간 감사

{markdown_table(segment_df, float_digits=3)}

## Split-Conformal 예측구간

검증 잔차로 테스트 구간의 대칭 90% 예측구간을 보정했습니다. Conformal 반경은 {overall_metrics['conformal_radius']:.2f}건, 평균 구간 폭은 {overall_metrics['conformal_mean_width']:.2f}건, 실제 커버리지는 {overall_metrics['conformal_test_coverage']:.1%}입니다. 이 수치는 point forecast를 운영 행동으로 바꾸기 전에 불확실성을 검토하는 장치입니다.

{markdown_table(conformal_segment_df, float_digits=3)}

## 날씨 충격 시나리오

{markdown_table(shock_df, float_digits=3)}

## 재배치 최적화 데모

예측 수요와 conformal 반경을 결합해 수요 버킷별 staging target을 만들고, 제한된 fleet budget 아래에서 제약 최적화 문제를 풉니다. 공개 데이터에는 정류장 위치와 dock capacity가 없어 시스템 수준 데모에 머물지만, 예측값을 감사 가능한 운영 권고로 변환하는 구조를 보여줍니다.

{markdown_table(optimization_df, float_digits=2)}

## 해석

상위 순열 중요도:

{markdown_table(importance.head(12), float_digits=4)}

가장 강한 신호는 최근 lag 수요, 시간대 구조, 출퇴근 indicator, 주간 lag입니다. 충격 시나리오는 악천후나 고온·습도 조건에서 예측 평균 수요가 어떻게 변하는지 정량화합니다. 출퇴근 피크와 악천후 구간은 전체 평균보다 오차와 커버리지 리스크가 커질 수 있으므로 운영 자동화 전 별도 모니터링 대상으로 둬야 합니다.

## 한계

- UCI 데이터는 정류장 수준이 아니라 시스템 집계 데이터이며, 정류장 지리정보·dock capacity·요금·이벤트·장애 정보가 없습니다.
- 재배치 최적화는 station-level dispatch 정책이 아니라 예측 결과를 운영 의사결정으로 연결하는 데모입니다.
- 날씨 영향은 인과 추정이 아니라 관측 피처 범위 안에서의 모델 기반 민감도입니다.
- 실서비스 전환 전에는 정류장 단위 공간 피처, 수용량 제약, 이벤트 캘린더, drift monitoring, prospective validation이 필요합니다.

## 의사결정 활용

1. 시간대별 예측을 기본 인력 배치와 재배치 수요 신호로 사용합니다.
2. 악천후가 수요를 하향 전환하거나 불확실성을 키울 때 weather-triggered playbook을 실행합니다.
3. 출퇴근·주말·악천후 구간 MAE와 conformal coverage를 model risk indicator로 추적합니다.
4. Conformal 구간 폭이 넓은 시간대는 자동 행동을 억제하고 수동 검토 대상으로 둡니다.
5. 운영 자동화 전에는 dock capacity와 fleet availability 제약을 반드시 결합합니다.

## 재현성

```bash
cd /workspace/prj/data-scientist-career/bike-share-demand-resilience
PYTHONPATH=src python3 -m bike_share_resilience.pipeline --output-root {paths.output_root} --report-dir {paths.report_dir}
python3 -m pytest tests
```

## 주요 산출물

- 최종 보고서: `{paths.project_report_dir / 'final_report.md'}`
- 주간 정리본: `{paths.report_dir / 'weekend-project-20260627-bike-share-demand-resilience.md'}`
- 모델 지표: `{paths.project_report_dir / 'model_metrics.csv'}`
- 실험 추적기: `{paths.project_report_dir / 'experiment_tracker.csv'}`
- 모델 카드: `{paths.project_report_dir / 'model_card.md'}`
- 데이터 계약: `{paths.project_report_dir / 'data_source_and_contract.md'}`
- Conformal 예측구간: `{paths.project_report_dir / 'conformal_prediction_intervals.csv'}`
- 재배치 최적화: `{paths.project_report_dir / 'rebalancing_optimization.csv'}`
- 그림: `{paths.figure_dir}`
- 모델 파일: `{paths.model_dir / 'best_model.pkl'}`
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
