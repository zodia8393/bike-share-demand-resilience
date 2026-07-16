from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from bike_share_resilience.pipeline import markdown_table
from bike_share_resilience.station_snapshot_analysis import DEFAULT_OUTPUT_ROOT


KST = ZoneInfo("Asia/Seoul")
TARGET_COL = "bike_shortage_next_snapshot"
MODEL_FEATURES = [
    "capacity",
    "num_bikes_available",
    "num_docks_available",
    "inventory_pressure",
    "current_bike_shortage_int",
    "current_dock_shortage_int",
    "hour",
    "dayofweek",
    "is_weekend",
]
ABLATION_FEATURES = {
    "full": MODEL_FEATURES,
    "no_current_state_flags": [
        feature
        for feature in MODEL_FEATURES
        if feature not in {"current_bike_shortage_int", "current_dock_shortage_int"}
    ],
    "temporal_only": ["hour", "dayofweek", "is_weekend"],
}


@dataclass(frozen=True)
class ProspectiveValidationConfig:
    min_label_rows: int = 500
    test_fraction: float = 0.25
    require_readiness: bool = True
    rolling_folds: int = 3
    rolling_min_train_fraction: float = 0.5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate prospective station shortage labels.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--min-label-rows", type=int, default=500)
    parser.add_argument("--test-fraction", type=float, default=0.25)
    parser.add_argument("--rolling-folds", type=int, default=3)
    parser.add_argument("--rolling-min-train-fraction", type=float, default=0.5)
    parser.add_argument(
        "--allow-not-ready-evaluation",
        action="store_true",
        help="Evaluate labels even if the two-week readiness gate is not ready; intended for tests only.",
    )
    parser.add_argument("--check-pass", action="store_true", help="Exit nonzero unless prospective validation passes")
    return parser.parse_args()


def read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def load_label_panel(output_root: Path) -> pd.DataFrame:
    path = output_root / "station_level" / "data" / "processed" / "station_shortage_label_panel.csv"
    if not path.is_file():
        return pd.DataFrame()
    frame = pd.read_csv(
        path,
        dtype={"station_short_name": "string", "gbfs_station_id": "string"},
        low_memory=False,
    )
    if "captured_at" in frame.columns:
        frame["captured_at"] = pd.to_datetime(frame["captured_at"], utc=True, errors="coerce").dt.tz_convert(KST)
    for col in ["current_bike_shortage", "current_dock_shortage", "inventory_joined"]:
        if col in frame.columns:
            frame[col] = normalize_bool(frame[col])
    numeric_cols = [
        "capacity",
        "num_bikes_available",
        "num_docks_available",
        "inventory_pressure",
        "next_gap_minutes",
    ]
    for col in numeric_cols:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def prepare_model_frame(label_panel: pd.DataFrame) -> pd.DataFrame:
    if label_panel.empty or TARGET_COL not in label_panel.columns:
        return pd.DataFrame()
    frame = label_panel.dropna(subset=["captured_at", TARGET_COL]).copy()
    frame[TARGET_COL] = normalize_bool(frame[TARGET_COL]).astype(int)
    frame["current_bike_shortage_int"] = normalize_bool(frame.get("current_bike_shortage", pd.Series(False, index=frame.index))).astype(int)
    frame["current_dock_shortage_int"] = normalize_bool(frame.get("current_dock_shortage", pd.Series(False, index=frame.index))).astype(int)
    frame["hour"] = frame["captured_at"].dt.hour
    frame["dayofweek"] = frame["captured_at"].dt.dayofweek
    frame["is_weekend"] = frame["dayofweek"].isin([5, 6]).astype(int)
    for col in ["capacity", "num_bikes_available", "num_docks_available", "inventory_pressure"]:
        if col not in frame.columns:
            frame[col] = np.nan
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(frame[col].median() if frame[col].notna().any() else 0)
    station_key = "gbfs_station_id" if "gbfs_station_id" in frame.columns else "station_short_name"
    frame[station_key] = frame[station_key].astype(str)
    return frame.sort_values("captured_at").reset_index(drop=True)


def temporal_split(frame: pd.DataFrame, test_fraction: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    timestamps = pd.Series(frame["captured_at"].dropna().unique()).sort_values()
    if len(timestamps) < 4:
        return frame.iloc[0:0].copy(), frame.iloc[0:0].copy()
    split_idx = max(1, int(len(timestamps) * (1 - test_fraction)))
    split_idx = min(split_idx, len(timestamps) - 1)
    cutoff = timestamps.iloc[split_idx - 1]
    train = frame.loc[frame["captured_at"].le(cutoff)].copy()
    test = frame.loc[frame["captured_at"].gt(cutoff)].copy()
    return train, test


def rolling_origin_splits(
    frame: pd.DataFrame,
    n_folds: int,
    min_train_fraction: float,
) -> list[tuple[int, pd.DataFrame, pd.DataFrame]]:
    timestamps = pd.Series(frame["captured_at"].dropna().unique()).sort_values().reset_index(drop=True)
    if n_folds < 1 or not 0 < min_train_fraction < 1 or len(timestamps) < n_folds + 4:
        return []
    min_train = max(2, int(len(timestamps) * min_train_fraction))
    test_window = (len(timestamps) - min_train) // n_folds
    if test_window < 1:
        return []
    splits = []
    for fold in range(n_folds):
        train_end = min_train + fold * test_window
        test_end = len(timestamps) if fold == n_folds - 1 else train_end + test_window
        train_cutoff = timestamps.iloc[train_end - 1]
        test_cutoff = timestamps.iloc[test_end - 1]
        train = frame.loc[frame["captured_at"].le(train_cutoff)].copy()
        test = frame.loc[
            frame["captured_at"].gt(train_cutoff) & frame["captured_at"].le(test_cutoff)
        ].copy()
        splits.append((fold + 1, train, test))
    return splits


def metric_row(model: str, y_true: pd.Series, y_pred: np.ndarray, y_prob: np.ndarray) -> dict:
    return {
        "model": model,
        "rows": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "average_precision": float(average_precision_score(y_true, y_prob)) if y_true.nunique() > 1 else 0.0,
        "brier": float(brier_score_loss(y_true, y_prob)) if y_true.nunique() > 1 else 1.0,
    }


def persistence_baseline(test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    prob = test["current_bike_shortage_int"].astype(float).to_numpy()
    return (prob >= 0.5).astype(int), prob


def profile_baseline(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    station_key = "gbfs_station_id" if "gbfs_station_id" in train.columns else "station_short_name"
    global_rate = float(train[TARGET_COL].mean())
    profile = train.groupby([station_key, "hour"])[TARGET_COL].mean().rename("profile_rate").reset_index()
    scored = test.merge(profile, on=[station_key, "hour"], how="left")
    prob = scored["profile_rate"].fillna(global_rate).to_numpy()
    threshold = min(0.5, max(0.1, global_rate))
    return (prob >= threshold).astype(int), prob


def logistic_model(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    selected_features = features or MODEL_FEATURES
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=500, class_weight="balanced", random_state=42),
    )
    model.fit(train[selected_features], train[TARGET_COL])
    prob = model.predict_proba(test[selected_features])[:, 1]
    threshold = min(0.5, max(0.1, float(train[TARGET_COL].mean())))
    return (prob >= threshold).astype(int), prob


def evaluate_model_suite(
    train: pd.DataFrame,
    test: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, tuple[np.ndarray, np.ndarray]]]:
    predictions = {}
    for name, builder in [
        ("persistence_baseline", lambda: persistence_baseline(test)),
        ("station_hour_profile", lambda: profile_baseline(train, test)),
        ("logistic_inventory_model", lambda: logistic_model(train, test)),
    ]:
        predictions[name] = builder()
    rows = [
        metric_row(name, test[TARGET_COL], y_pred, y_prob)
        for name, (y_pred, y_prob) in predictions.items()
    ]
    metrics = pd.DataFrame(rows).sort_values(
        ["f1", "average_precision"], ascending=False
    ).reset_index(drop=True)
    return metrics, predictions


def rolling_origin_audit(
    frame: pd.DataFrame,
    config: ProspectiveValidationConfig,
) -> pd.DataFrame:
    rows = []
    for fold, train, test in rolling_origin_splits(
        frame,
        n_folds=config.rolling_folds,
        min_train_fraction=config.rolling_min_train_fraction,
    ):
        if train[TARGET_COL].nunique() < 2 or test[TARGET_COL].nunique() < 2:
            continue
        metrics, _ = evaluate_model_suite(train, test)
        metrics.insert(0, "fold", fold)
        metrics.insert(1, "train_rows", len(train))
        metrics.insert(2, "train_end", train["captured_at"].max().isoformat())
        metrics.insert(3, "test_start", test["captured_at"].min().isoformat())
        metrics.insert(4, "test_end", test["captured_at"].max().isoformat())
        rows.extend(metrics.to_dict(orient="records"))
    return pd.DataFrame(rows)


def feature_ablation_audit(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, features in ABLATION_FEATURES.items():
        y_pred, y_prob = logistic_model(train, test, features)
        row = metric_row(name, test[TARGET_COL], y_pred, y_prob)
        row["feature_count"] = len(features)
        row["features"] = ",".join(features)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["average_precision", "f1"], ascending=False
    ).reset_index(drop=True)


def population_stability_index(train: pd.Series, test: pd.Series, bins: int = 10) -> float:
    train_values = pd.to_numeric(train, errors="coerce").dropna().to_numpy(dtype=float)
    test_values = pd.to_numeric(test, errors="coerce").dropna().to_numpy(dtype=float)
    if len(train_values) == 0 or len(test_values) == 0:
        return float("nan")
    quantiles = np.unique(np.quantile(train_values, np.linspace(0, 1, bins + 1)))
    if len(quantiles) < 3:
        return 0.0
    edges = np.concatenate(([-np.inf], quantiles[1:-1], [np.inf]))
    train_dist = np.histogram(train_values, bins=edges)[0] / len(train_values)
    test_dist = np.histogram(test_values, bins=edges)[0] / len(test_values)
    train_dist = np.clip(train_dist, 1e-6, None)
    test_dist = np.clip(test_dist, 1e-6, None)
    return float(np.sum((test_dist - train_dist) * np.log(test_dist / train_dist)))


def drift_audit(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    station_key = "gbfs_station_id" if "gbfs_station_id" in train.columns else "station_short_name"
    train_hours = train["hour"].value_counts(normalize=True).reindex(range(24), fill_value=0)
    test_hours = test["hour"].value_counts(normalize=True).reindex(range(24), fill_value=0)
    rows = [
        {
            "metric": "shortage_rate_abs_diff",
            "value": abs(float(train[TARGET_COL].mean()) - float(test[TARGET_COL].mean())),
            "threshold": 0.05,
            "direction": "max",
        },
        {
            "metric": "inventory_pressure_psi",
            "value": population_stability_index(train["inventory_pressure"], test["inventory_pressure"]),
            "threshold": 0.25,
            "direction": "max",
        },
        {
            "metric": "hour_distribution_tv",
            "value": float(0.5 * np.abs(train_hours - test_hours).sum()),
            "threshold": 0.2,
            "direction": "max",
        },
        {
            "metric": "station_coverage_ratio",
            "value": float(test[station_key].isin(set(train[station_key])).mean()),
            "threshold": 0.95,
            "direction": "min",
        },
    ]
    result = pd.DataFrame(rows)
    result["status"] = np.where(
        ((result["direction"] == "max") & (result["value"] <= result["threshold"]))
        | ((result["direction"] == "min") & (result["value"] >= result["threshold"])),
        "PASS",
        "FAIL",
    )
    return result


def failure_segment_audit(
    test: pd.DataFrame,
    model_name: str,
    y_pred: np.ndarray,
    y_prob: np.ndarray,
) -> pd.DataFrame:
    weekday = test["dayofweek"].lt(5)
    segments = {
        "all": np.ones(len(test), dtype=bool),
        "commute_peak": weekday & (test["hour"].between(7, 9) | test["hour"].between(16, 19)),
        "non_commute": ~(weekday & (test["hour"].between(7, 9) | test["hour"].between(16, 19))),
        "weekend": test["is_weekend"].eq(1),
        "night": test["hour"].between(0, 5),
        "high_inventory_pressure": test["inventory_pressure"].ge(0.8),
    }
    rows = []
    for segment, mask in segments.items():
        selected = np.asarray(mask, dtype=bool)
        if not selected.any():
            continue
        row = metric_row(
            model_name,
            test.loc[selected, TARGET_COL],
            y_pred[selected],
            y_prob[selected],
        )
        row["segment"] = segment
        row["shortage_rate"] = float(test.loc[selected, TARGET_COL].mean())
        rows.append(row)
    return pd.DataFrame(rows)


def not_ready_payload(output_root: Path, reason: str, readiness: dict | None = None, label_rows: int = 0) -> dict:
    if label_rows == 0 and readiness:
        label_rows = int(readiness.get("prospective_label_rows") or 0)
    return {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "validation_status": "NOT_READY",
        "reason": reason,
        "ready_for_prospective_validation": bool((readiness or {}).get("ready_for_prospective_validation")),
        "snapshot_count": (readiness or {}).get("snapshot_count"),
        "target_snapshots": (readiness or {}).get("target_snapshots"),
        "label_rows": int(label_rows),
        "metrics_path": str(output_root / "station_level" / "reports" / "station_prospective_validation_metrics.csv"),
        "rolling_origin_metrics_path": str(output_root / "station_level" / "reports" / "station_prospective_rolling_origin_metrics.csv"),
        "feature_ablation_path": str(output_root / "station_level" / "reports" / "station_prospective_feature_ablation.csv"),
        "drift_audit_path": str(output_root / "station_level" / "reports" / "station_prospective_drift_audit.csv"),
        "failure_audit_path": str(output_root / "station_level" / "reports" / "station_prospective_failure_audit.csv"),
        "report_path": str(output_root / "station_level" / "reports" / "station_prospective_validation.md"),
    }


def evaluate_prospective_validation(output_root: Path, config: ProspectiveValidationConfig) -> dict:
    report_dir = output_root / "station_level" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    readiness = read_json(report_dir / "station_snapshot_readiness.json")
    if config.require_readiness and not readiness.get("ready_for_prospective_validation"):
        payload = not_ready_payload(output_root, "snapshot readiness gate is not ready", readiness)
        write_reports(output_root, payload, pd.DataFrame())
        return payload

    label_panel = load_label_panel(output_root)
    frame = prepare_model_frame(label_panel)
    if frame.empty:
        payload = not_ready_payload(output_root, "no prospective label rows", readiness, 0)
        write_reports(output_root, payload, pd.DataFrame())
        return payload
    if len(frame) < config.min_label_rows:
        payload = not_ready_payload(output_root, f"label rows below minimum {config.min_label_rows}", readiness, len(frame))
        write_reports(output_root, payload, pd.DataFrame())
        return payload

    train, test = temporal_split(frame, config.test_fraction)
    if train.empty or test.empty or train[TARGET_COL].nunique() < 2 or test[TARGET_COL].nunique() < 2:
        payload = not_ready_payload(output_root, "temporal split lacks both shortage classes", readiness, len(frame))
        write_reports(output_root, payload, pd.DataFrame())
        return payload

    metrics, predictions = evaluate_model_suite(train, test)
    rolling_metrics = rolling_origin_audit(frame, config)
    ablation = feature_ablation_audit(train, test)
    drift = drift_audit(train, test)
    best = metrics.iloc[0].to_dict()
    best_prediction = predictions[str(best["model"])]
    failure_audit = failure_segment_audit(
        test,
        str(best["model"]),
        best_prediction[0],
        best_prediction[1],
    )
    fold_best = (
        rolling_metrics.groupby("fold", as_index=False)["f1"].max()
        if not rolling_metrics.empty
        else pd.DataFrame()
    )
    completed_folds = int(rolling_metrics["fold"].nunique()) if not rolling_metrics.empty else 0
    advanced_ready = bool(
        completed_folds == config.rolling_folds
        and len(ablation) == len(ABLATION_FEATURES)
        and len(failure_audit) >= 5
        and not drift.empty
        and drift["status"].eq("PASS").all()
    )
    payload = {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "validation_status": "PASS" if best["f1"] > 0 else "FAIL",
        "reason": "ready" if best["f1"] > 0 else "no useful shortage classifier",
        "ready_for_prospective_validation": bool(readiness.get("ready_for_prospective_validation")),
        "snapshot_count": readiness.get("snapshot_count"),
        "target_snapshots": readiness.get("target_snapshots"),
        "label_rows": int(len(frame)),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "test_shortage_rate": float(test[TARGET_COL].mean()),
        "best_model": best["model"],
        "best_f1": float(best["f1"]),
        "best_average_precision": float(best["average_precision"]),
        "best_brier": float(best["brier"]),
        "rolling_origin_fold_count": completed_folds,
        "rolling_origin_model_rows": int(len(rolling_metrics)),
        "rolling_origin_best_f1_mean": float(fold_best["f1"].mean()) if not fold_best.empty else None,
        "rolling_origin_best_f1_worst": float(fold_best["f1"].min()) if not fold_best.empty else None,
        "feature_ablation_rows": int(len(ablation)),
        "drift_checks_passed": int(drift["status"].eq("PASS").sum()),
        "drift_check_count": int(len(drift)),
        "failure_audit_segments": int(len(failure_audit)),
        "failure_worst_segment_f1": float(failure_audit["f1"].min()),
        "advanced_validation_ready": advanced_ready,
        "metrics_path": str(report_dir / "station_prospective_validation_metrics.csv"),
        "rolling_origin_metrics_path": str(report_dir / "station_prospective_rolling_origin_metrics.csv"),
        "feature_ablation_path": str(report_dir / "station_prospective_feature_ablation.csv"),
        "drift_audit_path": str(report_dir / "station_prospective_drift_audit.csv"),
        "failure_audit_path": str(report_dir / "station_prospective_failure_audit.csv"),
        "report_path": str(report_dir / "station_prospective_validation.md"),
    }
    write_reports(
        output_root,
        payload,
        metrics,
        rolling_metrics=rolling_metrics,
        ablation=ablation,
        drift=drift,
        failure_audit=failure_audit,
    )
    return payload


def render_report(
    payload: dict,
    metrics: pd.DataFrame,
    rolling_metrics: pd.DataFrame | None = None,
    ablation: pd.DataFrame | None = None,
    drift: pd.DataFrame | None = None,
    failure_audit: pd.DataFrame | None = None,
) -> str:
    status = payload.get("validation_status", "NOT_READY")
    lines = [
        "# Station Prospective Shortage Validation",
        "",
        f"- Status: `{status}`",
        f"- Generated: `{payload.get('generated_at_kst')}`",
        f"- Reason: {payload.get('reason')}",
        f"- Snapshot count: {payload.get('snapshot_count')} / {payload.get('target_snapshots')}",
        f"- Label rows: {payload.get('label_rows')}",
        "",
    ]
    if metrics.empty:
        lines.extend(
            [
                "## Decision",
                "",
                "- Prospective shortage validation is not ready. Do not claim true shortage prediction performance yet.",
                "- Keep collecting hourly station status snapshots and rerun the monitor.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Metrics",
                "",
                markdown_table(metrics, float_digits=3),
                "",
                "## Decision",
                "",
                f"- Best model: `{payload.get('best_model')}` with F1 `{payload.get('best_f1'):.3f}`.",
                "- Public deploy can only proceed if this report is `PASS` and the deploy readiness gate has no blockers.",
                "",
            ]
        )
        for title, frame in [
            ("Rolling-Origin Validation", rolling_metrics),
            ("Feature Ablation", ablation),
            ("Distribution Drift Audit", drift),
            ("Failure Segment Audit", failure_audit),
        ]:
            if frame is not None and not frame.empty:
                lines.extend([f"## {title}", "", markdown_table(frame, float_digits=3), ""])
        lines.extend(
            [
                "## Advanced Validation Decision",
                "",
                f"- Advanced evidence ready: `{payload.get('advanced_validation_ready')}`.",
                f"- Rolling-origin folds: `{payload.get('rolling_origin_fold_count')}`.",
                f"- Drift checks: `{payload.get('drift_checks_passed')}/{payload.get('drift_check_count')}` passed.",
                "- Candidate-unit metrics remain predictive decision-support evidence, not realized causal impact.",
                "",
            ]
        )
    return "\n".join(lines)


def write_reports(
    output_root: Path,
    payload: dict,
    metrics: pd.DataFrame,
    *,
    rolling_metrics: pd.DataFrame | None = None,
    ablation: pd.DataFrame | None = None,
    drift: pd.DataFrame | None = None,
    failure_audit: pd.DataFrame | None = None,
) -> None:
    report_dir = output_root / "station_level" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "station_prospective_validation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metrics.to_csv(report_dir / "station_prospective_validation_metrics.csv", index=False)
    (rolling_metrics if rolling_metrics is not None else pd.DataFrame()).to_csv(
        report_dir / "station_prospective_rolling_origin_metrics.csv", index=False
    )
    (ablation if ablation is not None else pd.DataFrame()).to_csv(
        report_dir / "station_prospective_feature_ablation.csv", index=False
    )
    (drift if drift is not None else pd.DataFrame()).to_csv(
        report_dir / "station_prospective_drift_audit.csv", index=False
    )
    (failure_audit if failure_audit is not None else pd.DataFrame()).to_csv(
        report_dir / "station_prospective_failure_audit.csv", index=False
    )
    report = render_report(
        payload,
        metrics,
        rolling_metrics=rolling_metrics,
        ablation=ablation,
        drift=drift,
        failure_audit=failure_audit,
    )
    (report_dir / "station_prospective_validation.md").write_text(report, encoding="utf-8")


def main() -> None:
    args = parse_args()
    config = ProspectiveValidationConfig(
        min_label_rows=args.min_label_rows,
        test_fraction=args.test_fraction,
        require_readiness=not args.allow_not_ready_evaluation,
        rolling_folds=args.rolling_folds,
        rolling_min_train_fraction=args.rolling_min_train_fraction,
    )
    payload = evaluate_prospective_validation(Path(args.output_root), config)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.check_pass and payload["validation_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
