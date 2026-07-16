from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from bike_share_resilience.pipeline import markdown_table
from bike_share_resilience.station_prospective_validation import (
    TARGET_COL,
    load_label_panel,
    logistic_model,
    metric_row,
    persistence_baseline,
    prepare_model_frame,
    read_json,
    temporal_split,
)
from bike_share_resilience.station_snapshot_analysis import DEFAULT_OUTPUT_ROOT


KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class NightCalibrationConfig:
    test_fraction: float = 0.25
    calibration_fraction: float = 0.20
    threshold_min: float = 0.05
    threshold_max: float = 0.95
    threshold_step: float = 0.025
    minimum_night_f1_gain: float = 0.001
    maximum_overall_f1_drop: float = 0.0
    min_label_rows: int = 500


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calibrate and audit the station shortage night-segment threshold."
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--min-label-rows", type=int, default=500)
    parser.add_argument("--test-fraction", type=float, default=0.25)
    parser.add_argument("--calibration-fraction", type=float, default=0.20)
    return parser.parse_args()


def threshold_grid(config: NightCalibrationConfig) -> np.ndarray:
    count = int(round((config.threshold_max - config.threshold_min) / config.threshold_step))
    return np.round(
        np.linspace(config.threshold_min, config.threshold_max, count + 1),
        6,
    )


def select_f1_threshold(
    y_true: pd.Series,
    probabilities: np.ndarray,
    config: NightCalibrationConfig,
) -> float:
    rows = []
    for threshold in threshold_grid(config):
        metrics = metric_row(
            "candidate",
            y_true,
            (probabilities >= threshold).astype(int),
            probabilities,
        )
        rows.append(
            {
                "threshold": float(threshold),
                "f1": metrics["f1"],
                "precision": metrics["precision"],
            }
        )
    ranked = sorted(
        rows,
        key=lambda row: (
            -row["f1"],
            -row["precision"],
            abs(row["threshold"] - 0.5),
        ),
    )
    return float(ranked[0]["threshold"])


def segment_masks(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    night = frame["hour"].between(0, 5).to_numpy()
    return {
        "all": np.ones(len(frame), dtype=bool),
        "night": night,
        "non_night": ~night,
    }


def policy_metric_rows(
    split: str,
    frame: pd.DataFrame,
    policy: str,
    predictions: np.ndarray,
    probabilities: np.ndarray,
    global_threshold: float,
    night_threshold: float,
) -> list[dict]:
    rows = []
    for segment, mask in segment_masks(frame).items():
        if not mask.any():
            continue
        row = metric_row(
            policy,
            frame.loc[mask, TARGET_COL],
            predictions[mask],
            probabilities[mask],
        )
        row.update(
            {
                "split": split,
                "policy": row.pop("model"),
                "segment": segment,
                "shortage_rate": float(frame.loc[mask, TARGET_COL].mean()),
                "global_threshold": global_threshold,
                "night_threshold": night_threshold,
            }
        )
        rows.append(row)
    return rows


def class_balance_audit(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for split, frame in splits.items():
        for segment, mask in segment_masks(frame).items():
            target = frame.loc[mask, TARGET_COL]
            positives = int(target.sum())
            negatives = int(len(target) - positives)
            rows.append(
                {
                    "split": split,
                    "segment": segment,
                    "rows": int(len(target)),
                    "positives": positives,
                    "negatives": negatives,
                    "shortage_rate": float(target.mean()),
                    "positive_to_negative_ratio": positives / max(negatives, 1),
                }
            )
    return pd.DataFrame(rows)


def hour_diagnostics(
    test: pd.DataFrame,
    baseline_predictions: np.ndarray,
    candidate_predictions: np.ndarray,
) -> pd.DataFrame:
    rows = []
    current = test["current_bike_shortage_int"].to_numpy()
    for hour in range(24):
        mask = test["hour"].eq(hour).to_numpy()
        if not mask.any():
            continue
        target = test.loc[mask, TARGET_COL]
        baseline = metric_row("persistence", target, baseline_predictions[mask], current[mask])
        candidate = metric_row(
            "candidate",
            target,
            candidate_predictions[mask],
            candidate_predictions[mask].astype(float),
        )
        rows.append(
            {
                "hour": hour,
                "is_night": hour <= 5,
                "rows": int(mask.sum()),
                "shortage_rate": float(target.mean()),
                "state_transition_rate": float((current[mask] != target.to_numpy()).mean()),
                "persistence_f1": baseline["f1"],
                "candidate_f1": candidate["f1"],
                "persistence_precision": baseline["precision"],
                "candidate_precision": candidate["precision"],
                "persistence_recall": baseline["recall"],
                "candidate_recall": candidate["recall"],
            }
        )
    return pd.DataFrame(rows)


def metric_value(
    comparison: pd.DataFrame,
    split: str,
    policy: str,
    segment: str,
    metric: str,
) -> float:
    row = comparison.loc[
        comparison["split"].eq(split)
        & comparison["policy"].eq(policy)
        & comparison["segment"].eq(segment)
    ]
    return float(row.iloc[0][metric])


def deployment_decision(
    comparison: pd.DataFrame,
    config: NightCalibrationConfig,
) -> tuple[str, str]:
    checks = {}
    for split in ["calibration", "test"]:
        baseline_all = metric_value(comparison, split, "persistence_baseline", "all", "f1")
        candidate_all = metric_value(comparison, split, "logistic_night_calibrated", "all", "f1")
        baseline_night = metric_value(comparison, split, "persistence_baseline", "night", "f1")
        candidate_night = metric_value(comparison, split, "logistic_night_calibrated", "night", "f1")
        checks[f"{split}_overall"] = (
            candidate_all >= baseline_all - config.maximum_overall_f1_drop
        )
        checks[f"{split}_night"] = (
            candidate_night - baseline_night >= config.minimum_night_f1_gain
        )
    if all(checks.values()):
        return "USE_LOGISTIC_NIGHT_CALIBRATED", "candidate passed calibration and final holdout gates"
    failed = ", ".join(name for name, passed in checks.items() if not passed)
    return "KEEP_PERSISTENCE_BASELINE", f"candidate did not pass: {failed}"


def calibration_splits(
    frame: pd.DataFrame,
    config: NightCalibrationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train, test = temporal_split(frame, config.test_fraction)
    fit, calibration = temporal_split(train, config.calibration_fraction)
    if any(part.empty for part in [fit, calibration, test]):
        raise ValueError("temporal fit/calibration/test split is empty")
    if any(part[TARGET_COL].nunique() < 2 for part in [fit, calibration, test]):
        raise ValueError("temporal split lacks both target classes")
    if not calibration["hour"].between(0, 5).any() or not test["hour"].between(0, 5).any():
        raise ValueError("calibration or test split has no night rows")
    return train, fit, calibration, test


def calibrated_probabilities(
    train: pd.DataFrame,
    fit: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    config: NightCalibrationConfig,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    _, calibration_prob = logistic_model(fit, calibration)
    _, test_prob = logistic_model(train, test)
    global_threshold = select_f1_threshold(calibration[TARGET_COL], calibration_prob, config)
    night_mask = calibration["hour"].between(0, 5).to_numpy()
    night_threshold = select_f1_threshold(
        calibration.loc[night_mask, TARGET_COL],
        calibration_prob[night_mask],
        config,
    )
    return calibration_prob, test_prob, global_threshold, night_threshold


def build_policy_comparison(
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    calibration_prob: np.ndarray,
    test_prob: np.ndarray,
    global_threshold: float,
    night_threshold: float,
) -> tuple[pd.DataFrame, tuple[np.ndarray, np.ndarray]]:
    rows = []
    test_predictions: tuple[np.ndarray, np.ndarray] | None = None
    for split, part, candidate_prob in [
        ("calibration", calibration, calibration_prob),
        ("test", test, test_prob),
    ]:
        baseline_pred, baseline_prob = persistence_baseline(part)
        night = part["hour"].between(0, 5).to_numpy()
        candidate_pred = np.where(
            night,
            candidate_prob >= night_threshold,
            candidate_prob >= global_threshold,
        ).astype(int)
        rows.extend(
            policy_metric_rows(
                split,
                part,
                "persistence_baseline",
                baseline_pred,
                baseline_prob,
                0.5,
                0.5,
            )
        )
        rows.extend(
            policy_metric_rows(
                split,
                part,
                "logistic_night_calibrated",
                candidate_pred,
                candidate_prob,
                global_threshold,
                night_threshold,
            )
        )
        if split == "test":
            test_predictions = baseline_pred, candidate_pred
    if test_predictions is None:
        raise ValueError("test policy predictions are missing")
    return pd.DataFrame(rows), test_predictions


def calibration_payload(
    frame: pd.DataFrame,
    fit: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    global_threshold: float,
    night_threshold: float,
    decision: str,
    reason: str,
    config: NightCalibrationConfig,
) -> dict:
    return {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "PASS",
        "decision": decision,
        "reason": reason,
        "label_rows": int(len(frame)),
        "fit_rows": int(len(fit)),
        "calibration_rows": int(len(calibration)),
        "test_rows": int(len(test)),
        "fit_end": fit["captured_at"].max().isoformat(),
        "calibration_start": calibration["captured_at"].min().isoformat(),
        "calibration_end": calibration["captured_at"].max().isoformat(),
        "test_start": test["captured_at"].min().isoformat(),
        "global_threshold": global_threshold,
        "night_threshold": night_threshold,
        "config": asdict(config),
    }


def build_calibration_result(
    frame: pd.DataFrame,
    config: NightCalibrationConfig,
) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train, fit, calibration, test = calibration_splits(frame, config)
    calibration_prob, test_prob, global_threshold, night_threshold = calibrated_probabilities(
        train,
        fit,
        calibration,
        test,
        config,
    )
    comparison, test_predictions = build_policy_comparison(
        calibration,
        test,
        calibration_prob,
        test_prob,
        global_threshold,
        night_threshold,
    )
    decision, reason = deployment_decision(comparison, config)
    balance = class_balance_audit({"fit": fit, "calibration": calibration, "test": test})
    hourly = hour_diagnostics(test, test_predictions[0], test_predictions[1])
    payload = calibration_payload(
        frame,
        fit,
        calibration,
        test,
        global_threshold,
        night_threshold,
        decision,
        reason,
        config,
    )
    return payload, comparison, balance, hourly


def not_ready_payload(reason: str) -> dict:
    return {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "NOT_READY",
        "decision": "KEEP_PERSISTENCE_BASELINE",
        "reason": reason,
    }


def evaluate_night_calibration(
    output_root: Path,
    config: NightCalibrationConfig,
) -> dict:
    readiness = read_json(
        output_root / "station_level" / "reports" / "station_snapshot_readiness.json"
    )
    frame = prepare_model_frame(load_label_panel(output_root))
    if not readiness.get("snapshot_cutoff_at"):
        payload = not_ready_payload("frozen snapshot cutoff is missing")
        write_reports(output_root, payload, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        return payload
    if len(frame) < config.min_label_rows:
        payload = not_ready_payload(f"label rows below minimum {config.min_label_rows}")
        write_reports(output_root, payload, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        return payload
    try:
        payload, comparison, balance, hourly = build_calibration_result(frame, config)
    except ValueError as error:
        payload = not_ready_payload(str(error))
        write_reports(output_root, payload, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        return payload
    payload["snapshot_cutoff_at"] = readiness["snapshot_cutoff_at"]
    report_dir = output_root / "station_level" / "reports"
    payload.update(
        {
            "comparison_path": str(report_dir / "station_night_threshold_comparison.csv"),
            "class_balance_path": str(report_dir / "station_night_class_balance.csv"),
            "hour_diagnostics_path": str(report_dir / "station_night_hour_diagnostics.csv"),
            "report_path": str(report_dir / "station_night_calibration.md"),
        }
    )
    write_reports(output_root, payload, comparison, balance, hourly)
    return payload


def render_report(
    payload: dict,
    comparison: pd.DataFrame,
    balance: pd.DataFrame,
    hourly: pd.DataFrame,
) -> str:
    lines = [
        "# Station Night Threshold Calibration",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Decision: `{payload.get('decision')}`",
        f"- Reason: {payload.get('reason')}",
        f"- Frozen cutoff: `{payload.get('snapshot_cutoff_at', '-')}`",
        "- Global/night threshold: "
        f"`{payload.get('global_threshold', '-')}` / `{payload.get('night_threshold', '-')}`",
        "",
    ]
    for title, frame in [
        ("Policy Comparison", comparison),
        ("Class Balance", balance),
        ("Hour Diagnostics", hourly),
    ]:
        if not frame.empty:
            lines.extend([f"## {title}", "", markdown_table(frame, float_digits=4), ""])
    lines.extend(
        [
            "## Boundary",
            "",
            "- Thresholds are selected only on the chronological calibration split inside the training period.",
            "- Final holdout is used only as a non-degradation acceptance gate; it is not used to retune thresholds.",
            "- The recommendation is predictive decision-support evidence, not realized causal impact.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(
    output_root: Path,
    payload: dict,
    comparison: pd.DataFrame,
    balance: pd.DataFrame,
    hourly: pd.DataFrame,
) -> None:
    report_dir = output_root / "station_level" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "station_night_calibration.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    comparison.to_csv(report_dir / "station_night_threshold_comparison.csv", index=False)
    balance.to_csv(report_dir / "station_night_class_balance.csv", index=False)
    hourly.to_csv(report_dir / "station_night_hour_diagnostics.csv", index=False)
    (report_dir / "station_night_calibration.md").write_text(
        render_report(payload, comparison, balance, hourly),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    config = NightCalibrationConfig(
        min_label_rows=args.min_label_rows,
        test_fraction=args.test_fraction,
        calibration_fraction=args.calibration_fraction,
    )
    payload = evaluate_night_calibration(Path(args.output_root), config)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
