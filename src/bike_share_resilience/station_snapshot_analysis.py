from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


KST = ZoneInfo("Asia/Seoul")
DEFAULT_OUTPUT_ROOT = Path("/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience")
SNAPSHOT_RE = re.compile(r"(?P<stamp>\d{8}_\d{6})_inventory_snapshot\.csv$")


@dataclass(frozen=True)
class SnapshotReadinessConfig:
    target_days: int = 14
    min_hourly_coverage: float = 0.80
    max_label_gap_minutes: int = 90
    snapshot_cutoff_at: datetime | None = None

    @property
    def target_snapshots(self) -> int:
        return self.target_days * 24

    @property
    def min_required_snapshots(self) -> int:
        return int(self.target_snapshots * self.min_hourly_coverage)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze accumulated station inventory snapshots.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--target-days", type=int, default=14)
    parser.add_argument("--min-hourly-coverage", type=float, default=0.80)
    parser.add_argument(
        "--snapshot-cutoff",
        type=parse_snapshot_cutoff,
        help="Inclusive ISO-8601 cutoff with timezone for a frozen snapshot cohort.",
    )
    parser.add_argument("--check-ready", action="store_true", help="Exit nonzero until the 2-week readiness gate passes")
    return parser.parse_args()


def parse_snapshot_cutoff(value: str) -> datetime:
    try:
        cutoff = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("snapshot cutoff must be an ISO-8601 datetime") from error
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise argparse.ArgumentTypeError("snapshot cutoff must include a timezone")
    return cutoff.astimezone(KST)


def parse_snapshot_timestamp(path: Path) -> datetime | None:
    match = SNAPSHOT_RE.search(path.name)
    if not match:
        return None
    return datetime.strptime(match.group("stamp"), "%Y%m%d_%H%M%S").replace(tzinfo=KST)


def list_inventory_snapshot_files(
    output_root: Path,
    snapshot_cutoff_at: datetime | None = None,
) -> list[Path]:
    snapshot_dir = output_root / "station_level" / "data" / "status_snapshots"
    if not snapshot_dir.exists():
        return []
    files = []
    for path in snapshot_dir.glob("*_inventory_snapshot.csv"):
        captured_at = parse_snapshot_timestamp(path)
        if captured_at is None:
            continue
        if snapshot_cutoff_at is not None and captured_at > snapshot_cutoff_at:
            continue
        files.append(path)
    return sorted(files, key=lambda path: parse_snapshot_timestamp(path) or datetime.min.replace(tzinfo=KST))


def normalize_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def load_snapshot_history(
    output_root: Path,
    snapshot_cutoff_at: datetime | None = None,
) -> pd.DataFrame:
    frames = []
    for path in list_inventory_snapshot_files(output_root, snapshot_cutoff_at):
        captured_at = parse_snapshot_timestamp(path)
        if captured_at is None:
            continue
        frame = pd.read_csv(path)
        frame["captured_at"] = captured_at.isoformat(timespec="seconds")
        frame["snapshot_path"] = str(path)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(
            columns=[
                "captured_at",
                "station_short_name",
                "gbfs_station_id",
                "num_bikes_available",
                "num_docks_available",
                "current_bike_shortage",
                "current_dock_shortage",
            ]
        )
    history = pd.concat(frames, ignore_index=True)
    history["captured_at"] = pd.to_datetime(history["captured_at"], utc=True).dt.tz_convert(KST)
    for col in ["num_bikes_available", "num_docks_available", "capacity", "inventory_pressure"]:
        if col in history.columns:
            history[col] = pd.to_numeric(history[col], errors="coerce")
    for col in ["current_bike_shortage", "current_dock_shortage", "inventory_joined"]:
        if col in history.columns:
            history[col] = normalize_bool(history[col])
    station_key = "gbfs_station_id" if "gbfs_station_id" in history.columns else "station_short_name"
    history = history.dropna(subset=["captured_at", station_key]).sort_values([station_key, "captured_at"])
    return history.reset_index(drop=True)


def build_shortage_label_panel(history: pd.DataFrame, config: SnapshotReadinessConfig) -> pd.DataFrame:
    if history.empty:
        return history.copy()
    station_key = "gbfs_station_id" if "gbfs_station_id" in history.columns else "station_short_name"
    panel = history.copy().sort_values([station_key, "captured_at"])
    grouped = panel.groupby(station_key, dropna=False)
    panel["next_captured_at"] = grouped["captured_at"].shift(-1)
    panel["next_gap_minutes"] = (panel["next_captured_at"] - panel["captured_at"]).dt.total_seconds() / 60
    if "current_bike_shortage" in panel.columns:
        panel["bike_shortage_next_snapshot"] = grouped["current_bike_shortage"].shift(-1)
        panel.loc[panel["next_gap_minutes"].gt(config.max_label_gap_minutes), "bike_shortage_next_snapshot"] = pd.NA
    if "current_dock_shortage" in panel.columns:
        panel["dock_shortage_next_snapshot"] = grouped["current_dock_shortage"].shift(-1)
        panel.loc[panel["next_gap_minutes"].gt(config.max_label_gap_minutes), "dock_shortage_next_snapshot"] = pd.NA
    return panel


def summarize_history(history: pd.DataFrame, label_panel: pd.DataFrame, config: SnapshotReadinessConfig) -> dict:
    if history.empty:
        return {
            "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
            "ready_for_prospective_validation": False,
            "reason": "no inventory snapshot files",
            "snapshot_count": 0,
            "target_days": config.target_days,
            "target_snapshots": config.target_snapshots,
            "min_required_snapshots": config.min_required_snapshots,
        }

    captured = pd.Series(pd.to_datetime(history["captured_at"]).dropna().unique()).sort_values()
    first = captured.iloc[0]
    latest = captured.iloc[-1]
    span_hours = (latest - first).total_seconds() / 3600
    span_days = span_hours / 24
    snapshot_count = int(len(captured))
    station_key = "gbfs_station_id" if "gbfs_station_id" in history.columns else "station_short_name"
    label_rows = 0
    if "bike_shortage_next_snapshot" in label_panel.columns:
        label_rows = int(label_panel["bike_shortage_next_snapshot"].notna().sum())
    ready = (
        span_days >= config.target_days
        and snapshot_count >= config.min_required_snapshots
        and label_rows > 0
    )
    earliest_ready_at = first + timedelta(days=config.target_days)
    remaining_snapshots = max(config.min_required_snapshots - snapshot_count, 0)
    reason = "ready" if ready else "waiting for 2-week hourly snapshot coverage"
    return {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "ready_for_prospective_validation": bool(ready),
        "reason": reason,
        "target_days": config.target_days,
        "target_snapshots": config.target_snapshots,
        "min_hourly_coverage": config.min_hourly_coverage,
        "min_required_snapshots": config.min_required_snapshots,
        "snapshot_count": snapshot_count,
        "remaining_snapshots": remaining_snapshots,
        "coverage_ratio": float(min(snapshot_count / max(config.target_snapshots, 1), 1.0)),
        "first_snapshot_at": first.isoformat(),
        "latest_snapshot_at": latest.isoformat(),
        "earliest_ready_at": earliest_ready_at.isoformat(),
        "span_hours": float(span_hours),
        "span_days": float(span_days),
        "station_count": int(history[station_key].nunique()),
        "history_rows": int(len(history)),
        "prospective_label_rows": label_rows,
        "bike_shortage_rate": float(history.get("current_bike_shortage", pd.Series(dtype=bool)).mean())
        if "current_bike_shortage" in history.columns
        else None,
        "dock_shortage_rate": float(history.get("current_dock_shortage", pd.Series(dtype=bool)).mean())
        if "current_dock_shortage" in history.columns
        else None,
    }


def render_readiness_report(summary: dict) -> str:
    ready = "READY" if summary.get("ready_for_prospective_validation") else "NOT_READY"
    return "\n".join(
        [
            "# Station Snapshot Readiness",
            "",
            f"- Status: {ready}",
            f"- Generated: {summary.get('generated_at_kst')}",
            f"- Reason: {summary.get('reason')}",
            f"- Snapshot count: {summary.get('snapshot_count', 0)} / {summary.get('target_snapshots', 0)}",
            f"- Snapshot cutoff: {summary.get('snapshot_cutoff_at') or '-'}",
            f"- Source snapshots: {summary.get('source_snapshot_count', summary.get('snapshot_count', 0))}",
            f"- Excluded after cutoff: {summary.get('excluded_snapshot_count', 0)}",
            f"- Minimum required snapshots: {summary.get('min_required_snapshots', 0)}",
            f"- Remaining snapshots: {summary.get('remaining_snapshots', 0)}",
            f"- Span days: {summary.get('span_days', 0):.2f}",
            f"- Earliest ready at: {summary.get('earliest_ready_at', '-')}",
            f"- Station count: {summary.get('station_count', 0)}",
            f"- Prospective label rows: {summary.get('prospective_label_rows', 0)}",
            "",
            "## Decision",
            "",
            "- Public deployment remains gated until this report is READY and the public deployment readiness check passes.",
            "- Before READY, the project can be shown as a local research/product prototype with automated prospective data collection.",
            "",
        ]
    )


def analyze_snapshots(output_root: Path, config: SnapshotReadinessConfig) -> dict:
    paths = {
        "processed_dir": output_root / "station_level" / "data" / "processed",
        "report_dir": output_root / "station_level" / "reports",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    source_snapshot_count = len(list_inventory_snapshot_files(output_root))
    history = load_snapshot_history(output_root, config.snapshot_cutoff_at)
    label_panel = build_shortage_label_panel(history, config)
    summary = summarize_history(history, label_panel, config)

    history_path = paths["processed_dir"] / "station_inventory_history.csv"
    label_path = paths["processed_dir"] / "station_shortage_label_panel.csv"
    summary_path = paths["report_dir"] / "station_snapshot_readiness.json"
    report_path = paths["report_dir"] / "station_snapshot_readiness.md"

    history.to_csv(history_path, index=False)
    label_panel.to_csv(label_path, index=False)
    summary.update(
        {
            "snapshot_cutoff_at": config.snapshot_cutoff_at.isoformat()
            if config.snapshot_cutoff_at is not None
            else None,
            "source_snapshot_count": source_snapshot_count,
            "excluded_snapshot_count": max(source_snapshot_count - int(summary.get("snapshot_count", 0)), 0),
            "history_path": str(history_path),
            "label_panel_path": str(label_path),
            "report_path": str(report_path),
        }
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_readiness_report(summary), encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    config = SnapshotReadinessConfig(
        target_days=args.target_days,
        min_hourly_coverage=args.min_hourly_coverage,
        snapshot_cutoff_at=args.snapshot_cutoff,
    )
    summary = analyze_snapshots(Path(args.output_root), config)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.check_ready and not summary["ready_for_prospective_validation"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
