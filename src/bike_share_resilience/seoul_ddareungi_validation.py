from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
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
from bike_share_resilience.seoul_ddareungi import (
    DEFAULT_OUTPUT_ROOT,
    SEOUL_SOURCE_NAME,
    build_rebalancing_priority,
)


KST = ZoneInfo("Asia/Seoul")
SNAPSHOT_RE = re.compile(r"(?P<stamp>\d{8}_\d{6})_inventory_snapshot\.csv$")
BIKE_TARGET = "bike_shortage_next_snapshot"
DOCK_TARGET = "dock_shortage_next_snapshot"


@dataclass(frozen=True)
class SeoulValidationConfig:
    shortage_ratio: float = 0.10
    max_label_gap_minutes: int = 90
    min_snapshots_for_validation: int = 24
    min_snapshots_for_model: int = 24
    min_label_rows_for_model: int = 500
    test_fraction: float = 0.25
    top_ks: tuple[int, ...] = (10, 50)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Seoul Ddareungi next-snapshot decision labels.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--shortage-ratio", type=float, default=0.10)
    parser.add_argument("--max-label-gap-minutes", type=int, default=90)
    parser.add_argument("--min-snapshots-for-validation", type=int, default=24)
    parser.add_argument("--min-snapshots-for-model", type=int, default=24)
    parser.add_argument("--min-label-rows-for-model", type=int, default=500)
    parser.add_argument("--test-fraction", type=float, default=0.25)
    return parser.parse_args()


def parse_snapshot_timestamp(path: Path) -> datetime | None:
    match = SNAPSHOT_RE.search(path.name)
    if not match:
        return None
    return datetime.strptime(match.group("stamp"), "%Y%m%d_%H%M%S").replace(tzinfo=KST)


def list_snapshot_files(output_root: Path) -> list[Path]:
    snapshot_dir = output_root / "seoul_ddareungi" / "data" / "status_snapshots"
    if not snapshot_dir.exists():
        return []
    files = [path for path in snapshot_dir.glob("*_inventory_snapshot.csv") if parse_snapshot_timestamp(path)]
    return sorted(files, key=lambda path: parse_snapshot_timestamp(path) or datetime.min.replace(tzinfo=KST))


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_json(item) for item in value]
    if isinstance(value, tuple):
        return [clean_json(item) for item in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        try:
            return clean_json(value.item())
        except ValueError:
            return str(value)
    if pd.isna(value):
        return None
    return value


def load_snapshot_history(output_root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in list_snapshot_files(output_root):
        captured_at = parse_snapshot_timestamp(path)
        if captured_at is None:
            continue
        frame = pd.read_csv(path)
        frame["snapshot_captured_at"] = captured_at.isoformat(timespec="seconds")
        frame["snapshot_path"] = str(path)
        frames.append(frame)

    columns = [
        "station_id",
        "station_name",
        "capacity",
        "bikes_available",
        "docks_available",
        "shared_rate",
        "station_lat",
        "station_lon",
        "captured_at_kst",
        "source",
        "snapshot_captured_at",
        "snapshot_path",
    ]
    if not frames:
        return pd.DataFrame(columns=columns)

    history = pd.concat(frames, ignore_index=True)
    for col in columns:
        if col not in history.columns:
            history[col] = np.nan
    history["snapshot_captured_at"] = pd.to_datetime(
        history["snapshot_captured_at"], utc=True, errors="coerce"
    ).dt.tz_convert(KST)
    if "captured_at_kst" in history.columns:
        history["captured_at_kst"] = history["captured_at_kst"].astype(str)
    numeric_cols = [
        "capacity",
        "bikes_available",
        "docks_available",
        "shared_rate",
        "station_lat",
        "station_lon",
    ]
    for col in numeric_cols:
        history[col] = pd.to_numeric(history[col], errors="coerce")
    history["station_id"] = history["station_id"].astype(str)
    history = history.dropna(subset=["station_id", "snapshot_captured_at"])
    return history.sort_values(["station_id", "snapshot_captured_at"]).reset_index(drop=True)


def add_current_shortage_flags(history: pd.DataFrame, config: SeoulValidationConfig) -> pd.DataFrame:
    if history.empty:
        return history.copy()
    panel = history.copy()
    panel["bike_shortage_threshold"] = np.maximum(
        1,
        np.ceil(panel["capacity"].fillna(0) * config.shortage_ratio).astype(int),
    )
    panel["dock_shortage_threshold"] = panel["bike_shortage_threshold"]
    panel["bike_fill_rate"] = panel["bikes_available"] / panel["capacity"].replace({0: np.nan})
    panel["dock_fill_rate"] = panel["docks_available"] / panel["capacity"].replace({0: np.nan})
    panel["bike_shortage_current"] = panel["bikes_available"].le(panel["bike_shortage_threshold"]).astype("boolean")
    panel["dock_shortage_current"] = panel["docks_available"].le(panel["dock_shortage_threshold"]).astype("boolean")
    panel.loc[panel["capacity"].isna() | panel["capacity"].le(0), ["bike_shortage_current", "dock_shortage_current"]] = pd.NA
    return panel


def build_next_snapshot_label_panel(history: pd.DataFrame, config: SeoulValidationConfig) -> pd.DataFrame:
    if history.empty:
        return add_current_shortage_flags(history, config)
    panel = add_current_shortage_flags(history, config).sort_values(["station_id", "snapshot_captured_at"])
    grouped = panel.groupby("station_id", dropna=False)
    panel["next_snapshot_captured_at"] = grouped["snapshot_captured_at"].shift(-1)
    panel["next_gap_minutes"] = (
        panel["next_snapshot_captured_at"] - panel["snapshot_captured_at"]
    ).dt.total_seconds() / 60
    panel[BIKE_TARGET] = grouped["bike_shortage_current"].shift(-1)
    panel[DOCK_TARGET] = grouped["dock_shortage_current"].shift(-1)
    invalid_gap = panel["next_gap_minutes"].isna() | panel["next_gap_minutes"].gt(config.max_label_gap_minutes)
    panel.loc[invalid_gap, [BIKE_TARGET, DOCK_TARGET]] = pd.NA
    return panel.reset_index(drop=True)


def summarize_label_panel(history: pd.DataFrame, label_panel: pd.DataFrame, config: SeoulValidationConfig) -> dict:
    if history.empty:
        return {
            "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
            "snapshot_status": "NOT_READY",
            "reason": "no Seoul Ddareungi snapshot files",
            "snapshot_count": 0,
            "station_count": 0,
            "history_rows": 0,
            "label_rows": 0,
            "max_label_gap_minutes": config.max_label_gap_minutes,
        }

    captured = pd.Series(pd.to_datetime(history["snapshot_captured_at"]).dropna().unique()).sort_values()
    label_rows = int(label_panel[BIKE_TARGET].notna().sum()) if BIKE_TARGET in label_panel.columns else 0
    first = captured.iloc[0]
    latest = captured.iloc[-1]
    span_minutes = (latest - first).total_seconds() / 60
    return {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "snapshot_status": "READY" if label_rows > 0 else "NOT_READY",
        "reason": "next-snapshot labels available" if label_rows > 0 else "not enough paired snapshots",
        "source": SEOUL_SOURCE_NAME,
        "snapshot_count": int(len(captured)),
        "station_count": int(history["station_id"].nunique()),
        "history_rows": int(len(history)),
        "label_rows": label_rows,
        "first_snapshot_at": first.isoformat(),
        "latest_snapshot_at": latest.isoformat(),
        "span_minutes": float(span_minutes),
        "max_label_gap_minutes": config.max_label_gap_minutes,
        "shortage_ratio": config.shortage_ratio,
        "bike_shortage_current_rate": float(label_panel["bike_shortage_current"].mean()),
        "dock_shortage_current_rate": float(label_panel["dock_shortage_current"].mean()),
        "bike_shortage_next_rate": float(_nullable_bool_series(label_panel[BIKE_TARGET]).mean())
        if label_rows
        else None,
        "dock_shortage_next_rate": float(_nullable_bool_series(label_panel[DOCK_TARGET]).mean())
        if label_rows
        else None,
    }


def evaluate_rule_priority(label_panel: pd.DataFrame, config: SeoulValidationConfig) -> tuple[dict, pd.DataFrame]:
    if label_panel.empty or BIKE_TARGET not in label_panel.columns:
        return _rule_not_ready("no next-snapshot label panel", label_panel), pd.DataFrame()

    valid_panel = label_panel.loc[label_panel[BIKE_TARGET].notna() | label_panel[DOCK_TARGET].notna()].copy()
    if valid_panel.empty:
        return _rule_not_ready("no valid next-snapshot labels", label_panel), pd.DataFrame()

    max_k = max(config.top_ks)
    metric_rows: list[dict[str, Any]] = []
    total_label_snapshots = int(valid_panel["snapshot_captured_at"].nunique())
    for captured_at, group in valid_panel.groupby("snapshot_captured_at", sort=True):
        current_rows = _records_for_priority(group)
        priority_rows, _ = build_rebalancing_priority(current_rows, top_n=max_k)
        if not priority_rows:
            continue
        labels_by_station = group.set_index("station_id", drop=False)
        for top_k in config.top_ks:
            top_rows = priority_rows[:top_k]
            row = _score_priority_rows(captured_at, top_k, top_rows, labels_by_station)
            metric_rows.append(row)

    metrics = pd.DataFrame(metric_rows)
    if metrics.empty:
        return _rule_not_ready("priority rule produced no evaluated predictions", label_panel), metrics

    snapshot_count = int(label_panel["snapshot_captured_at"].nunique())
    meets_snapshot_floor = snapshot_count >= config.min_snapshots_for_validation
    summary: dict[str, Any] = {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "validation_status": "READY" if meets_snapshot_floor else "NOT_READY",
        "evaluation_status": "EVALUATED",
        "reason": "rule priority evaluated against next-snapshot labels"
        if meets_snapshot_floor
        else f"snapshot count below minimum {config.min_snapshots_for_validation}; metrics are preliminary",
        "source": SEOUL_SOURCE_NAME,
        "snapshot_count": snapshot_count,
        "min_snapshots_for_validation": config.min_snapshots_for_validation,
        "total_label_snapshots": total_label_snapshots,
        "evaluated_snapshots": int(metrics["snapshot_captured_at"].nunique()),
        "label_rows": int(valid_panel[BIKE_TARGET].notna().sum()),
        "coverage": float(metrics["snapshot_captured_at"].nunique() / max(total_label_snapshots, 1)),
        "top_ks": list(config.top_ks),
    }
    for top_k in config.top_ks:
        subset = metrics.loc[metrics["top_k"].eq(top_k)]
        predictions = int(subset["prediction_count"].sum())
        hits = int(subset["hit_count"].sum())
        summary[f"precision_at_{top_k}"] = float(hits / predictions) if predictions else None
        summary[f"predictions_at_{top_k}"] = predictions
        summary[f"hits_at_{top_k}"] = hits
    top_max = metrics.loc[metrics["top_k"].eq(max_k)]
    for action in ["send_bikes", "remove_bikes"]:
        count = int(top_max[f"{action}_count"].sum())
        hits = int(top_max[f"{action}_hits"].sum())
        summary[f"{action}_precision"] = float(hits / count) if count else None
        summary[f"{action}_count"] = count
        summary[f"{action}_hits"] = hits
    top_predictions = int(top_max["prediction_count"].sum())
    top_hits = int(top_max["hit_count"].sum())
    summary["issue_hit_rate"] = float(top_hits / top_predictions) if top_predictions else None
    return clean_json(summary), metrics


def evaluate_model_baseline(label_panel: pd.DataFrame, config: SeoulValidationConfig) -> tuple[dict, pd.DataFrame]:
    snapshot_count = int(label_panel["snapshot_captured_at"].nunique()) if "snapshot_captured_at" in label_panel.columns else 0
    frame = prepare_model_frame(label_panel)
    if snapshot_count < config.min_snapshots_for_model:
        return _model_not_ready(
            f"snapshot count below minimum {config.min_snapshots_for_model}",
            snapshot_count=snapshot_count,
            label_rows=len(frame),
        ), pd.DataFrame()
    if len(frame) < config.min_label_rows_for_model:
        return _model_not_ready(
            f"label rows below minimum {config.min_label_rows_for_model}",
            snapshot_count=snapshot_count,
            label_rows=len(frame),
        ), pd.DataFrame()

    train, test = temporal_split(frame, config.test_fraction)
    if train.empty or test.empty:
        return _model_not_ready("chronological split produced empty train or test", snapshot_count, len(frame)), pd.DataFrame()

    metric_rows: list[dict[str, Any]] = []
    for target in [BIKE_TARGET, DOCK_TARGET]:
        target_train = train.dropna(subset=[target]).copy()
        target_test = test.dropna(subset=[target]).copy()
        if target_train.empty or target_test.empty:
            continue
        target_train[target] = _nullable_bool_series(target_train[target]).astype(int)
        target_test[target] = _nullable_bool_series(target_test[target]).astype(int)
        if target_train[target].nunique() < 2 or target_test[target].nunique() < 2:
            continue
        for model_name, builder in [
            ("persistence_baseline", lambda: persistence_baseline(target, target_test)),
            ("station_hour_profile", lambda: profile_baseline(target, target_train, target_test)),
            ("logistic_inventory_model", lambda: logistic_model(target, target_train, target_test)),
        ]:
            y_pred, y_prob = builder()
            metric_rows.append(metric_row(target, model_name, target_test[target], y_pred, y_prob))

    metrics = pd.DataFrame(metric_rows)
    if metrics.empty:
        return _model_not_ready("chronological split lacks both target classes", snapshot_count, len(frame)), metrics

    metrics = metrics.sort_values(["target", "f1", "average_precision"], ascending=[True, False, False]).reset_index(drop=True)
    best = metrics.sort_values(["f1", "average_precision"], ascending=False).iloc[0].to_dict()
    payload = {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "model_status": "READY",
        "reason": "baseline models evaluated with chronological split",
        "source": SEOUL_SOURCE_NAME,
        "split": "chronological",
        "snapshot_count": snapshot_count,
        "label_rows": int(len(frame)),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "best_target": best["target"],
        "best_model": best["model"],
        "best_f1": float(best["f1"]),
        "best_average_precision": float(best["average_precision"]),
        "best_brier": float(best["brier"]),
    }
    return clean_json(payload), metrics


def prepare_model_frame(label_panel: pd.DataFrame) -> pd.DataFrame:
    if label_panel.empty or BIKE_TARGET not in label_panel.columns:
        return pd.DataFrame()
    frame = label_panel.loc[label_panel[BIKE_TARGET].notna() | label_panel[DOCK_TARGET].notna()].copy()
    if frame.empty:
        return frame
    frame["snapshot_captured_at"] = pd.to_datetime(
        frame["snapshot_captured_at"], utc=True, errors="coerce"
    ).dt.tz_convert(KST)
    frame = frame.dropna(subset=["snapshot_captured_at", "station_id"]).copy()
    for col in ["capacity", "bikes_available", "docks_available", "bike_fill_rate", "dock_fill_rate", "shared_rate"]:
        if col not in frame.columns:
            frame[col] = np.nan
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame[col] = frame[col].fillna(frame[col].median() if frame[col].notna().any() else 0)
    frame["bike_shortage_current_int"] = _nullable_bool_series(frame.get("bike_shortage_current", pd.Series(False, index=frame.index))).astype(int)
    frame["dock_shortage_current_int"] = _nullable_bool_series(frame.get("dock_shortage_current", pd.Series(False, index=frame.index))).astype(int)
    frame["hour"] = frame["snapshot_captured_at"].dt.hour
    frame["dayofweek"] = frame["snapshot_captured_at"].dt.dayofweek
    frame["is_weekend"] = frame["dayofweek"].isin([5, 6]).astype(int)
    frame["station_id"] = frame["station_id"].astype(str)
    return frame.sort_values("snapshot_captured_at").reset_index(drop=True)


def temporal_split(frame: pd.DataFrame, test_fraction: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    timestamps = pd.Series(frame["snapshot_captured_at"].dropna().unique()).sort_values()
    if len(timestamps) < 4:
        return frame.iloc[0:0].copy(), frame.iloc[0:0].copy()
    split_idx = max(1, int(len(timestamps) * (1 - test_fraction)))
    split_idx = min(split_idx, len(timestamps) - 1)
    cutoff = timestamps.iloc[split_idx - 1]
    train = frame.loc[frame["snapshot_captured_at"].le(cutoff)].copy()
    test = frame.loc[frame["snapshot_captured_at"].gt(cutoff)].copy()
    return train, test


def persistence_baseline(target: str, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    source_col = "bike_shortage_current_int" if target == BIKE_TARGET else "dock_shortage_current_int"
    prob = test[source_col].astype(float).to_numpy()
    return (prob >= 0.5).astype(int), prob


def profile_baseline(target: str, train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    global_rate = float(train[target].mean())
    profile = train.groupby(["station_id", "hour"])[target].mean().rename("profile_rate").reset_index()
    scored = test.merge(profile, on=["station_id", "hour"], how="left")
    prob = scored["profile_rate"].fillna(global_rate).to_numpy()
    threshold = min(0.5, max(0.1, global_rate))
    return (prob >= threshold).astype(int), prob


def logistic_model(target: str, train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    features = [
        "capacity",
        "bikes_available",
        "docks_available",
        "bike_fill_rate",
        "dock_fill_rate",
        "shared_rate",
        "bike_shortage_current_int",
        "dock_shortage_current_int",
        "hour",
        "dayofweek",
        "is_weekend",
    ]
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=500, class_weight="balanced", random_state=42),
    )
    model.fit(train[features], train[target])
    prob = model.predict_proba(test[features])[:, 1]
    threshold = min(0.5, max(0.1, float(train[target].mean())))
    return (prob >= threshold).astype(int), prob


def metric_row(target: str, model: str, y_true: pd.Series, y_pred: np.ndarray, y_prob: np.ndarray) -> dict:
    return {
        "target": target,
        "model": model,
        "rows": int(len(y_true)),
        "positive_rate": float(y_true.mean()),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "average_precision": float(average_precision_score(y_true, y_prob)) if y_true.nunique() > 1 else 0.0,
        "brier": float(brier_score_loss(y_true, y_prob)) if y_true.nunique() > 1 else 1.0,
    }


def analyze_seoul_snapshots(output_root: Path, config: SeoulValidationConfig) -> dict:
    seoul_root = output_root / "seoul_ddareungi"
    processed_dir = seoul_root / "data" / "processed"
    report_dir = seoul_root / "reports"
    processed_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    history = load_snapshot_history(output_root)
    label_panel = build_next_snapshot_label_panel(history, config)
    label_summary = summarize_label_panel(history, label_panel, config)
    validation_summary, validation_metrics = evaluate_rule_priority(label_panel, config)
    model_summary, model_metrics = evaluate_model_baseline(label_panel, config)

    history_path = processed_dir / "snapshot_history.csv"
    label_path = processed_dir / "next_snapshot_label_panel.csv"
    validation_summary_path = report_dir / "validation_summary.json"
    validation_metrics_path = report_dir / "validation_metrics.csv"
    validation_report_path = report_dir / "validation_report.md"
    model_summary_path = report_dir / "model_metrics.json"
    model_metrics_path = report_dir / "model_metrics.csv"

    history.to_csv(history_path, index=False)
    label_panel.to_csv(label_path, index=False)
    validation_metrics.to_csv(validation_metrics_path, index=False)
    model_metrics.to_csv(model_metrics_path, index=False)

    validation_summary = {
        **validation_summary,
        "snapshot": label_summary,
        "history_path": str(history_path),
        "label_panel_path": str(label_path),
        "metrics_path": str(validation_metrics_path),
        "report_path": str(validation_report_path),
    }
    model_summary = {
        **model_summary,
        "label_panel_path": str(label_path),
        "metrics_path": str(model_metrics_path),
    }
    validation_summary_path.write_text(json.dumps(clean_json(validation_summary), ensure_ascii=False, indent=2), encoding="utf-8")
    model_summary_path.write_text(json.dumps(clean_json(model_summary), ensure_ascii=False, indent=2), encoding="utf-8")
    validation_report_path.write_text(render_validation_report(validation_summary, validation_metrics, model_summary, model_metrics), encoding="utf-8")

    return clean_json({"validation": validation_summary, "model": model_summary})


def render_validation_report(
    validation_summary: dict,
    validation_metrics: pd.DataFrame,
    model_summary: dict,
    model_metrics: pd.DataFrame,
) -> str:
    lines = [
        "# Seoul Ddareungi Prospective Decision Validation",
        "",
        f"- Rule validation status: `{validation_summary.get('validation_status')}`",
        f"- Rule reason: {validation_summary.get('reason')}",
        f"- Snapshot count: {validation_summary.get('snapshot', {}).get('snapshot_count')}",
        f"- Label rows: {validation_summary.get('snapshot', {}).get('label_rows')}",
        f"- Precision@10: {validation_summary.get('precision_at_10')}",
        f"- Precision@50: {validation_summary.get('precision_at_50')}",
        f"- ML baseline status: `{model_summary.get('model_status')}`",
        f"- ML reason: {model_summary.get('reason')}",
        "",
        "## Rule Metrics",
        "",
        render_markdown_table(validation_metrics.head(20)) if not validation_metrics.empty else "Rule metrics are not ready.",
        "",
        "## ML Baseline Metrics",
        "",
        render_markdown_table(model_metrics) if not model_metrics.empty else "ML baseline is not ready.",
        "",
        "## Decision",
        "",
        "- Public deployment remains `NO_GO` until prospective validation has enough coverage and passes the deploy gate.",
        "- Current live map and priority table can be used as a local product prototype, not as a verified production claim.",
        "",
    ]
    return "\n".join(lines)


def render_markdown_table(frame: pd.DataFrame, float_digits: int = 3) -> str:
    copy = frame.copy()
    for col in copy.columns:
        copy[col] = copy[col].map(lambda value: _format_table_value(value, float_digits))
    return markdown_table(copy, float_digits=float_digits)


def _format_table_value(value: Any, float_digits: int) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{float_digits}f}"
    return str(value)


def _records_for_priority(group: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in group.to_dict(orient="records"):
        rows.append(
            {
                "station_id": row.get("station_id"),
                "station_name": row.get("station_name"),
                "capacity": row.get("capacity"),
                "bikes_available": row.get("bikes_available"),
                "docks_available": row.get("docks_available"),
                "shared_rate": row.get("shared_rate"),
                "captured_at_kst": row.get("captured_at_kst"),
                "station_lat": row.get("station_lat"),
                "station_lon": row.get("station_lon"),
                "source": row.get("source") or SEOUL_SOURCE_NAME,
            }
        )
    return rows


def _score_priority_rows(
    captured_at: Any,
    top_k: int,
    priority_rows: list[dict[str, Any]],
    labels_by_station: pd.DataFrame,
) -> dict[str, Any]:
    hits = 0
    send_count = 0
    send_hits = 0
    remove_count = 0
    remove_hits = 0
    for row in priority_rows:
        station_id = str(row.get("station_id"))
        if station_id not in labels_by_station.index:
            continue
        label_row = labels_by_station.loc[station_id]
        if isinstance(label_row, pd.DataFrame):
            label_row = label_row.iloc[0]
        action = row.get("recommended_action")
        if action == "send_bikes":
            send_count += 1
            hit = _bool_value(label_row.get(BIKE_TARGET)) is True
            send_hits += int(hit)
        elif action == "remove_bikes":
            remove_count += 1
            hit = _bool_value(label_row.get(DOCK_TARGET)) is True
            remove_hits += int(hit)
        else:
            hit = False
        hits += int(hit)
    prediction_count = int(len(priority_rows))
    return {
        "snapshot_captured_at": captured_at.isoformat() if hasattr(captured_at, "isoformat") else str(captured_at),
        "top_k": int(top_k),
        "prediction_count": prediction_count,
        "hit_count": int(hits),
        "precision": float(hits / prediction_count) if prediction_count else None,
        "send_bikes_count": int(send_count),
        "send_bikes_hits": int(send_hits),
        "send_bikes_precision": float(send_hits / send_count) if send_count else None,
        "remove_bikes_count": int(remove_count),
        "remove_bikes_hits": int(remove_hits),
        "remove_bikes_precision": float(remove_hits / remove_count) if remove_count else None,
    }


def _nullable_bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.astype("boolean")
    return series.map(_bool_value).astype("boolean")


def _bool_value(value: Any) -> bool | pd._libs.missing.NAType:
    if pd.isna(value):
        return pd.NA
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _rule_not_ready(reason: str, label_panel: pd.DataFrame) -> dict:
    return {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "validation_status": "NOT_READY",
        "reason": reason,
        "source": SEOUL_SOURCE_NAME,
        "snapshot_count": int(label_panel["snapshot_captured_at"].nunique()) if "snapshot_captured_at" in label_panel.columns else 0,
        "label_rows": int(label_panel[BIKE_TARGET].notna().sum()) if BIKE_TARGET in label_panel.columns else 0,
        "precision_at_10": None,
        "precision_at_50": None,
        "coverage": 0.0,
    }


def _model_not_ready(reason: str, snapshot_count: int = 0, label_rows: int = 0) -> dict:
    return {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "model_status": "NOT_READY",
        "reason": reason,
        "source": SEOUL_SOURCE_NAME,
        "split": "chronological",
        "snapshot_count": int(snapshot_count),
        "label_rows": int(label_rows),
        "best_model": None,
        "best_f1": None,
        "best_average_precision": None,
        "best_brier": None,
    }


def main() -> None:
    args = parse_args()
    config = SeoulValidationConfig(
        shortage_ratio=args.shortage_ratio,
        max_label_gap_minutes=args.max_label_gap_minutes,
        min_snapshots_for_validation=args.min_snapshots_for_validation,
        min_snapshots_for_model=args.min_snapshots_for_model,
        min_label_rows_for_model=args.min_label_rows_for_model,
        test_fraction=args.test_fraction,
    )
    payload = analyze_seoul_snapshots(Path(args.output_root), config)
    print(json.dumps(clean_json(payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
