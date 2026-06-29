from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bike_share_resilience.station_snapshot_analysis import DEFAULT_OUTPUT_ROOT


KST = ZoneInfo("Asia/Seoul")
TELEGRAM_SCRIPT = Path("/workspace/_codex/scripts/send-telegram-message.py")


Sender = Callable[[str], dict]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send one-time readiness notifications for station snapshots.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--phase", choices=["ready-start", "validation-result"], required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def report_dir(output_root: Path) -> Path:
    return output_root / "station_level" / "reports"


def state_path(output_root: Path) -> Path:
    return report_dir(output_root) / "station_readiness_notification_state.json"


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def readiness_event_id(readiness: dict) -> str:
    first = readiness.get("first_snapshot_at") or "unknown-first"
    target_days = readiness.get("target_days") or "unknown-days"
    minimum = readiness.get("min_required_snapshots") or readiness.get("target_snapshots") or "unknown-min"
    return f"{first}|target_days={target_days}|min_snapshots={minimum}"


def summarize_blockers(blockers: list | None) -> str:
    if not blockers:
        return "none"
    return "; ".join(str(item) for item in blockers[:4])


def send_telegram_message(message: str) -> dict:
    if not TELEGRAM_SCRIPT.is_file():
        raise RuntimeError(f"telegram sender missing: {TELEGRAM_SCRIPT}")
    result = subprocess.run(
        ["python3", str(TELEGRAM_SCRIPT), "--message", message],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "sent", "raw_stdout": result.stdout.strip()}


def dry_run_sender(message: str) -> dict:
    return {"status": "dry_run", "message_length": len(message)}


def build_start_message(readiness: dict) -> str:
    return "\n".join(
        [
            "Bike-share snapshot readiness READY",
            "",
            "2주 station_status snapshot이 검증 기준을 충족했습니다. 지금부터 prospective shortage validation을 시작합니다.",
            "",
            f"- snapshots: {readiness.get('snapshot_count')} / {readiness.get('target_snapshots')}",
            f"- minimum required: {readiness.get('min_required_snapshots')}",
            f"- span days: {readiness.get('span_days')}",
            f"- first snapshot: {readiness.get('first_snapshot_at')}",
            f"- latest snapshot: {readiness.get('latest_snapshot_at')}",
            f"- prospective label rows: {readiness.get('prospective_label_rows')}",
        ]
    )


def build_result_message(readiness: dict, validation: dict, deploy: dict) -> str:
    status = validation.get("validation_status", "UNKNOWN")
    decision = deploy.get("decision", "UNKNOWN")
    lines = [
        "Bike-share prospective validation result",
        "",
        f"- validation: {status}",
        f"- deploy readiness: {decision}",
        f"- snapshots: {readiness.get('snapshot_count')} / {readiness.get('target_snapshots')}",
        f"- label rows: {validation.get('label_rows', readiness.get('prospective_label_rows'))}",
    ]
    if validation.get("best_model"):
        lines.extend(
            [
                f"- best model: {validation.get('best_model')}",
                f"- best F1: {validation.get('best_f1')}",
                f"- best average precision: {validation.get('best_average_precision')}",
                f"- best brier: {validation.get('best_brier')}",
            ]
        )
    if deploy.get("blockers"):
        lines.append(f"- blockers: {summarize_blockers(deploy.get('blockers'))}")
    if status == "PASS" and decision == "GO":
        lines.append("- next: public deployment approval/release decision can be reviewed.")
    elif status == "PASS":
        lines.append("- next: validation passed; resolve deploy blockers before public release.")
    else:
        lines.append("- next: keep the project open and harden the validation/model before public release.")
    return "\n".join(lines)


def maybe_notify_ready_start(output_root: Path, sender: Sender = send_telegram_message, update_state: bool = True) -> dict:
    readiness = read_json(report_dir(output_root) / "station_snapshot_readiness.json")
    if not readiness.get("ready_for_prospective_validation"):
        return {"status": "skipped", "reason": "snapshot readiness is not READY"}

    event_id = readiness_event_id(readiness)
    state = read_json(state_path(output_root))
    if state.get("ready_start_event_id") == event_id:
        return {"status": "skipped", "reason": "ready-start notification already sent", "event_id": event_id}

    send_result = sender(build_start_message(readiness))
    if update_state:
        state.update(
            {
                "ready_start_event_id": event_id,
                "ready_start_notified_at_kst": now_kst(),
                "ready_start_send_result": send_result,
                "snapshot_count_at_ready_start": readiness.get("snapshot_count"),
            }
        )
        write_json(state_path(output_root), state)
    return {
        "status": "sent",
        "phase": "ready-start",
        "event_id": event_id,
        "send_result": send_result,
        "state_updated": update_state,
    }


def validation_result_key(event_id: str, validation: dict, deploy: dict) -> str:
    blockers = tuple(str(item) for item in deploy.get("blockers", []))
    blocker_digest = hashlib.sha256(json.dumps(blockers, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    return "|".join(
        [
            event_id,
            f"validation={validation.get('validation_status')}",
            f"deploy={deploy.get('decision')}",
            f"blockers={blocker_digest}",
        ]
    )


def maybe_notify_validation_result(output_root: Path, sender: Sender = send_telegram_message, update_state: bool = True) -> dict:
    paths = report_dir(output_root)
    readiness = read_json(paths / "station_snapshot_readiness.json")
    if not readiness.get("ready_for_prospective_validation"):
        return {"status": "skipped", "reason": "snapshot readiness is not READY"}

    validation = read_json(paths / "station_prospective_validation.json")
    if not validation:
        return {"status": "skipped", "reason": "prospective validation report is missing"}

    deploy = read_json(paths / "station_public_deploy_readiness.json")
    event_id = readiness_event_id(readiness)
    result_key = validation_result_key(event_id, validation, deploy)
    state = read_json(state_path(output_root))
    if state.get("validation_result_key") == result_key:
        return {"status": "skipped", "reason": "validation-result notification already sent", "event_id": event_id}

    send_result = sender(build_result_message(readiness, validation, deploy))
    if update_state:
        state.update(
            {
                "validation_result_key": result_key,
                "validation_result_event_id": event_id,
                "validation_result_notified_at_kst": now_kst(),
                "validation_result_send_result": send_result,
                "validation_status": validation.get("validation_status"),
                "deploy_decision": deploy.get("decision"),
            }
        )
        write_json(state_path(output_root), state)
    return {
        "status": "sent",
        "phase": "validation-result",
        "event_id": event_id,
        "send_result": send_result,
        "state_updated": update_state,
    }


def main() -> None:
    args = parse_args()
    sender = dry_run_sender if args.dry_run else send_telegram_message
    output_root = Path(args.output_root)
    if args.phase == "ready-start":
        payload = maybe_notify_ready_start(output_root, sender, update_state=not args.dry_run)
    else:
        payload = maybe_notify_validation_result(output_root, sender, update_state=not args.dry_run)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
