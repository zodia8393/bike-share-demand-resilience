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


@dataclass(frozen=True)
class ProspectiveValidationConfig:
    min_label_rows: int = 500
    test_fraction: float = 0.25
    require_readiness: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate prospective station shortage labels.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--min-label-rows", type=int, default=500)
    parser.add_argument("--test-fraction", type=float, default=0.25)
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
    frame = pd.read_csv(path)
    if "captured_at" in frame.columns:
        frame["captured_at"] = pd.to_datetime(frame["captured_at"], utc=True, errors="coerce").dt.tz_convert(KST)
    for col in [TARGET_COL, "current_bike_shortage", "current_dock_shortage", "inventory_joined"]:
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


def logistic_model(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    features = [
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
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=500, class_weight="balanced", random_state=42),
    )
    model.fit(train[features], train[TARGET_COL])
    prob = model.predict_proba(test[features])[:, 1]
    threshold = min(0.5, max(0.1, float(train[TARGET_COL].mean())))
    return (prob >= threshold).astype(int), prob


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

    metric_rows = []
    for name, builder in [
        ("persistence_baseline", lambda: persistence_baseline(test)),
        ("station_hour_profile", lambda: profile_baseline(train, test)),
        ("logistic_inventory_model", lambda: logistic_model(train, test)),
    ]:
        y_pred, y_prob = builder()
        metric_rows.append(metric_row(name, test[TARGET_COL], y_pred, y_prob))

    metrics = pd.DataFrame(metric_rows).sort_values(["f1", "average_precision"], ascending=False).reset_index(drop=True)
    best = metrics.iloc[0].to_dict()
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
        "metrics_path": str(report_dir / "station_prospective_validation_metrics.csv"),
        "report_path": str(report_dir / "station_prospective_validation.md"),
    }
    write_reports(output_root, payload, metrics)
    return payload


def render_report(payload: dict, metrics: pd.DataFrame) -> str:
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
    return "\n".join(lines)


def write_reports(output_root: Path, payload: dict, metrics: pd.DataFrame) -> None:
    report_dir = output_root / "station_level" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "station_prospective_validation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metrics.to_csv(report_dir / "station_prospective_validation_metrics.csv", index=False)
    (report_dir / "station_prospective_validation.md").write_text(render_report(payload, metrics), encoding="utf-8")


def main() -> None:
    args = parse_args()
    config = ProspectiveValidationConfig(
        min_label_rows=args.min_label_rows,
        test_fraction=args.test_fraction,
        require_readiness=not args.allow_not_ready_evaluation,
    )
    payload = evaluate_prospective_validation(Path(args.output_root), config)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.check_pass and payload["validation_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
