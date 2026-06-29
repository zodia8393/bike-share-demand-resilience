from __future__ import annotations

import json
from pathlib import Path

from bike_share_resilience.station_readiness_notifications import (
    maybe_notify_ready_start,
    maybe_notify_validation_result,
    state_path,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def ready_payload(ready: bool = True) -> dict:
    return {
        "ready_for_prospective_validation": ready,
        "snapshot_count": 336,
        "target_snapshots": 336,
        "min_required_snapshots": 268,
        "target_days": 14,
        "span_days": 14.0,
        "first_snapshot_at": "2026-06-29T14:04:57+09:00",
        "latest_snapshot_at": "2026-07-13T14:04:57+09:00",
        "prospective_label_rows": 24000,
    }


def test_ready_notification_waits_until_snapshot_readiness(tmp_path):
    report_dir = tmp_path / "station_level" / "reports"
    write_json(report_dir / "station_snapshot_readiness.json", ready_payload(ready=False))
    sent_messages = []

    payload = maybe_notify_ready_start(tmp_path, lambda message: sent_messages.append(message) or {"status": "fake"})

    assert payload["status"] == "skipped"
    assert sent_messages == []
    assert not state_path(tmp_path).exists()


def test_ready_notification_is_sent_once_per_readiness_event(tmp_path):
    report_dir = tmp_path / "station_level" / "reports"
    write_json(report_dir / "station_snapshot_readiness.json", ready_payload())
    sent_messages = []

    first = maybe_notify_ready_start(tmp_path, lambda message: sent_messages.append(message) or {"status": "fake"})
    second = maybe_notify_ready_start(tmp_path, lambda message: sent_messages.append(message) or {"status": "fake"})
    state = json.loads(state_path(tmp_path).read_text(encoding="utf-8"))

    assert first["status"] == "sent"
    assert second["status"] == "skipped"
    assert len(sent_messages) == 1
    assert state["ready_start_event_id"] == first["event_id"]


def test_ready_notification_dry_run_does_not_update_state(tmp_path):
    report_dir = tmp_path / "station_level" / "reports"
    write_json(report_dir / "station_snapshot_readiness.json", ready_payload())
    sent_messages = []

    payload = maybe_notify_ready_start(
        tmp_path,
        lambda message: sent_messages.append(message) or {"status": "fake"},
        update_state=False,
    )

    assert payload["status"] == "sent"
    assert payload["state_updated"] is False
    assert len(sent_messages) == 1
    assert not state_path(tmp_path).exists()


def test_validation_result_notification_is_sent_once_per_result_state(tmp_path):
    report_dir = tmp_path / "station_level" / "reports"
    write_json(report_dir / "station_snapshot_readiness.json", ready_payload())
    write_json(
        report_dir / "station_prospective_validation.json",
        {
            "validation_status": "PASS",
            "label_rows": 24000,
            "best_model": "logistic_inventory_model",
            "best_f1": 0.61,
            "best_average_precision": 0.73,
            "best_brier": 0.18,
        },
    )
    write_json(report_dir / "station_public_deploy_readiness.json", {"decision": "NO_GO", "blockers": ["auth pending"]})
    sent_messages = []

    first = maybe_notify_validation_result(tmp_path, lambda message: sent_messages.append(message) or {"status": "fake"})
    second = maybe_notify_validation_result(tmp_path, lambda message: sent_messages.append(message) or {"status": "fake"})
    write_json(report_dir / "station_public_deploy_readiness.json", {"decision": "GO", "blockers": []})
    third = maybe_notify_validation_result(tmp_path, lambda message: sent_messages.append(message) or {"status": "fake"})

    assert first["status"] == "sent"
    assert second["status"] == "skipped"
    assert third["status"] == "sent"
    assert len(sent_messages) == 2
