#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bike_share_resilience.station_service import load_service_payload, validate_service_payload  # noqa: E402
from bike_share_resilience.station_snapshot_analysis import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT,
    SnapshotReadinessConfig,
    analyze_snapshots,
    parse_snapshot_cutoff,
)


KST = ZoneInfo("Asia/Seoul")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check whether the station dashboard is ready for public deployment.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument(
        "--snapshot-cutoff",
        type=parse_snapshot_cutoff,
        help="Inclusive ISO-8601 cutoff with timezone for a frozen snapshot cohort.",
    )
    parser.add_argument("--report-only", action="store_true", help="Write the decision report but do not fail on NO_GO")
    return parser.parse_args()


def tracked_publication_risks() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    risky_suffixes = (".zip", ".parquet", ".pkl", ".sqlite", ".db")
    risky_parts = ("/data/raw/", "/status_snapshots/", ".env")
    risks = []
    for line in result.stdout.splitlines():
        lowered = line.lower()
        if lowered.endswith(risky_suffixes) or any(part in lowered for part in risky_parts):
            risks.append(line)
    return risks


def build_decision(output_root: Path, snapshot_cutoff_at: datetime | None = None) -> dict:
    snapshot_summary = analyze_snapshots(
        output_root,
        SnapshotReadinessConfig(snapshot_cutoff_at=snapshot_cutoff_at),
    )
    service_payload = load_service_payload(output_root)
    service_errors = validate_service_payload(service_payload)
    prospective_path = output_root / "station_level" / "reports" / "station_prospective_validation.json"
    if prospective_path.is_file():
        prospective_validation = json.loads(prospective_path.read_text(encoding="utf-8"))
    else:
        prospective_validation = {}
    publication_risks = tracked_publication_risks()
    blockers = []
    if service_errors:
        blockers.extend(f"service: {error}" for error in service_errors)
    if not snapshot_summary.get("ready_for_prospective_validation"):
        blockers.append("snapshot: two-week prospective validation coverage is not ready")
    elif prospective_validation.get("validation_status") != "PASS":
        blockers.append("prospective_validation: true shortage validation is not PASS")
    if publication_risks:
        blockers.append("repo: raw/private artifact paths are tracked")
    decision = "GO" if not blockers else "NO_GO"
    service_health = dict(service_payload.get("health", {}))
    service_health["deploy_decision"] = decision
    return {
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "decision": decision,
        "blockers": blockers,
        "cleanup_required_before_public_deploy": [
            "Keep raw trip/status/weather artifacts under /DATA only.",
            "Serve aggregate JSON/CSV-derived dashboard payloads only.",
            "Bind local preview to 127.0.0.1 unless an explicit public deploy target is approved.",
            "Re-run station_service --check and this deploy readiness check before exposing any endpoint.",
        ],
        "service_health": service_health,
        "snapshot_readiness": snapshot_summary,
        "prospective_validation": prospective_validation,
        "tracked_publication_risks": publication_risks,
    }


def main() -> None:
    args = parse_args()
    output_root = Path(args.output_root)
    report_dir = output_root / "station_level" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    decision = build_decision(output_root, snapshot_cutoff_at=args.snapshot_cutoff)
    report_path = report_dir / "station_public_deploy_readiness.json"
    report_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    if decision["decision"] != "GO" and not args.report_only:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
