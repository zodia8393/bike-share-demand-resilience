from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from bike_share_resilience.pipeline import markdown_table
from bike_share_resilience.station_prospective_validation import (
    population_stability_index,
    read_json,
)
from bike_share_resilience.station_snapshot_analysis import (
    DEFAULT_OUTPUT_ROOT,
    load_snapshot_history,
    parse_snapshot_cutoff,
)


KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class PostCutoffMonitoringConfig:
    snapshot_cutoff_at: datetime | None = None
    shortage_rate_max_diff: float = 0.05
    inventory_pressure_max_psi: float = 0.25
    hour_distribution_max_tv: float = 0.20
    station_coverage_min_ratio: float = 0.95


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor station distribution drift after the frozen validation cutoff."
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--snapshot-cutoff", type=parse_snapshot_cutoff)
    return parser.parse_args()


def resolve_cutoff(
    output_root: Path,
    configured_cutoff: datetime | None,
) -> datetime | None:
    if configured_cutoff is not None:
        return configured_cutoff.astimezone(KST)
    readiness = read_json(
        output_root / "station_level" / "reports" / "station_snapshot_readiness.json"
    )
    value = readiness.get("snapshot_cutoff_at")
    if not value:
        return None
    try:
        cutoff = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        return None
    return cutoff.astimezone(KST)


def monitoring_drift_rows(
    reference: pd.DataFrame,
    monitoring: pd.DataFrame,
    config: PostCutoffMonitoringConfig,
) -> list[dict]:
    station_key = (
        "gbfs_station_id" if "gbfs_station_id" in reference.columns else "station_short_name"
    )
    reference_hours = (
        reference["captured_at"]
        .drop_duplicates()
        .dt.hour.value_counts(normalize=True)
        .reindex(range(24), fill_value=0)
    )
    monitoring_hours = (
        monitoring["captured_at"]
        .drop_duplicates()
        .dt.hour.value_counts(normalize=True)
        .reindex(range(24), fill_value=0)
    )
    return [
        {
            "metric": "shortage_rate_abs_diff",
            "value": abs(
                float(reference["current_bike_shortage"].mean())
                - float(monitoring["current_bike_shortage"].mean())
            ),
            "threshold": config.shortage_rate_max_diff,
            "direction": "max",
        },
        {
            "metric": "inventory_pressure_psi",
            "value": population_stability_index(
                reference["inventory_pressure"],
                monitoring["inventory_pressure"],
            ),
            "threshold": config.inventory_pressure_max_psi,
            "direction": "max",
        },
        {
            "metric": "hour_distribution_tv",
            "value": float(0.5 * np.abs(reference_hours - monitoring_hours).sum()),
            "threshold": config.hour_distribution_max_tv,
            "direction": "max",
        },
        {
            "metric": "station_coverage_ratio",
            "value": float(
                monitoring[station_key].isin(set(reference[station_key])).mean()
            ),
            "threshold": config.station_coverage_min_ratio,
            "direction": "min",
        },
    ]


def monitoring_drift_checks(
    reference: pd.DataFrame,
    monitoring: pd.DataFrame,
    config: PostCutoffMonitoringConfig,
) -> pd.DataFrame:
    result = pd.DataFrame(monitoring_drift_rows(reference, monitoring, config))
    finite = np.isfinite(result["value"])
    passed = (
        ((result["direction"] == "max") & (result["value"] <= result["threshold"]))
        | ((result["direction"] == "min") & (result["value"] >= result["threshold"]))
    )
    result["status"] = np.where(finite & passed, "PASS", "REVIEW_REQUIRED")
    return result


def not_ready_payload(reason: str, cutoff: datetime | None = None) -> dict:
    return {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "NOT_READY",
        "decision": "NO_AUTOMATIC_MODEL_CHANGE",
        "reason": reason,
        "snapshot_cutoff_at": cutoff.isoformat() if cutoff else None,
    }


def build_monitoring_payload(
    reference: pd.DataFrame,
    monitoring: pd.DataFrame,
    cutoff: datetime,
    checks: pd.DataFrame,
) -> dict:
    status = "PASS" if checks["status"].eq("PASS").all() else "REVIEW_REQUIRED"
    reason = (
        "post-cutoff monitoring is within drift thresholds"
        if status == "PASS"
        else "one or more post-cutoff drift checks require review"
    )
    return {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": status,
        "decision": "NO_AUTOMATIC_MODEL_CHANGE",
        "reason": reason,
        "snapshot_cutoff_at": cutoff.isoformat(),
        "reference_snapshot_count": int(reference["captured_at"].nunique()),
        "monitoring_snapshot_count": int(monitoring["captured_at"].nunique()),
        "reference_rows": int(len(reference)),
        "monitoring_rows": int(len(monitoring)),
        "reference_shortage_rate": float(reference["current_bike_shortage"].mean()),
        "monitoring_shortage_rate": float(monitoring["current_bike_shortage"].mean()),
        "checks_passed": int(checks["status"].eq("PASS").sum()),
        "check_count": int(len(checks)),
    }


def evaluate_post_cutoff_monitoring(
    output_root: Path,
    config: PostCutoffMonitoringConfig,
) -> dict:
    cutoff = resolve_cutoff(output_root, config.snapshot_cutoff_at)
    if cutoff is None:
        payload = not_ready_payload("frozen snapshot cutoff is missing or invalid")
        write_reports(output_root, payload, pd.DataFrame())
        return payload
    history = load_snapshot_history(output_root)
    if history.empty:
        payload = not_ready_payload("no source snapshot history", cutoff)
        write_reports(output_root, payload, pd.DataFrame())
        return payload
    reference = history.loc[history["captured_at"].le(cutoff)].copy()
    monitoring = history.loc[history["captured_at"].gt(cutoff)].copy()
    if reference.empty:
        payload = not_ready_payload("no reference snapshots at or before cutoff", cutoff)
        write_reports(output_root, payload, pd.DataFrame())
        return payload
    if monitoring.empty:
        payload = not_ready_payload("no post-cutoff monitoring snapshots", cutoff)
        write_reports(output_root, payload, pd.DataFrame())
        return payload
    required = {"current_bike_shortage", "inventory_pressure"}
    if not required.issubset(history.columns):
        payload = not_ready_payload("snapshot history lacks required drift columns", cutoff)
        write_reports(output_root, payload, pd.DataFrame())
        return payload
    checks = monitoring_drift_checks(reference, monitoring, config)
    payload = build_monitoring_payload(reference, monitoring, cutoff, checks)
    report_dir = output_root / "station_level" / "reports"
    payload.update(
        {
            "checks_path": str(report_dir / "station_post_cutoff_drift.csv"),
            "report_path": str(report_dir / "station_post_cutoff_drift.md"),
        }
    )
    write_reports(output_root, payload, checks)
    return payload


def render_report(payload: dict, checks: pd.DataFrame) -> str:
    lines = [
        "# Station Post-Cutoff Drift Monitoring",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Decision: `{payload.get('decision')}`",
        f"- Reason: {payload.get('reason')}",
        f"- Frozen cutoff: `{payload.get('snapshot_cutoff_at') or '-'}`",
        "- Reference/monitoring snapshots: "
        f"`{payload.get('reference_snapshot_count', 0)}` / "
        f"`{payload.get('monitoring_snapshot_count', 0)}`",
        "",
    ]
    if not checks.empty:
        lines.extend(["## Drift Checks", "", markdown_table(checks, float_digits=4), ""])
    lines.extend(
        [
            "## Decision Boundary",
            "",
            "- Post-cutoff snapshots are monitoring-only and are never merged into the frozen validation cohort.",
            "- A threshold violation requires human review and does not trigger automatic threshold or model changes.",
            "- Metrics describe predictive input drift, not realized operational or causal impact.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(output_root: Path, payload: dict, checks: pd.DataFrame) -> None:
    report_dir = output_root / "station_level" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "station_post_cutoff_drift.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    checks.to_csv(report_dir / "station_post_cutoff_drift.csv", index=False)
    (report_dir / "station_post_cutoff_drift.md").write_text(
        render_report(payload, checks),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload = evaluate_post_cutoff_monitoring(
        Path(args.output_root),
        PostCutoffMonitoringConfig(snapshot_cutoff_at=args.snapshot_cutoff),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
