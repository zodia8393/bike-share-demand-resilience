from pathlib import Path

import pandas as pd

from bike_share_resilience.seoul_ddareungi_validation import (
    SeoulValidationConfig,
    analyze_seoul_snapshots,
    build_next_snapshot_label_panel,
    evaluate_model_baseline,
    evaluate_rule_priority,
    load_snapshot_history,
    temporal_split,
)


def write_snapshot(root: Path, stamp: str, rows: list[dict]) -> None:
    snapshot_dir = root / "seoul_ddareungi" / "data" / "status_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(snapshot_dir / f"{stamp}_inventory_snapshot.csv", index=False)


def station_rows(captured_at: str, a_bikes: int, b_bikes: int) -> list[dict]:
    return [
        {
            "station_id": "A",
            "station_name": "Alpha",
            "capacity": 10,
            "bikes_available": a_bikes,
            "docks_available": 10 - a_bikes,
            "shared_rate": a_bikes * 10,
            "station_lat": 37.5,
            "station_lon": 127.0,
            "captured_at_kst": captured_at,
            "source": "fixture",
        },
        {
            "station_id": "B",
            "station_name": "Beta",
            "capacity": 10,
            "bikes_available": b_bikes,
            "docks_available": 10 - b_bikes,
            "shared_rate": b_bikes * 10,
            "station_lat": 37.6,
            "station_lon": 127.1,
            "captured_at_kst": captured_at,
            "source": "fixture",
        },
    ]


def write_three_snapshots(root: Path) -> None:
    write_snapshot(root, "20260702_190000", station_rows("2026-07-02T19:00:00+09:00", 5, 10))
    write_snapshot(root, "20260702_191000", station_rows("2026-07-02T19:10:00+09:00", 0, 9))
    write_snapshot(root, "20260702_192000", station_rows("2026-07-02T19:20:00+09:00", 5, 5))


def write_ml_ready_snapshots(root: Path) -> None:
    bike_patterns = {
        "A": [5, 0, 5, 0, 5, 0],
        "B": [5, 5, 5, 5, 5, 5],
        "C": [0, 0, 0, 0, 0, 0],
        "D": [10, 10, 10, 10, 10, 10],
    }
    names = {"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"}
    for idx, minute in enumerate([0, 10, 20, 30, 40, 50]):
        stamp = f"20260702_19{minute:02d}00"
        captured = f"2026-07-02T19:{minute:02d}:00+09:00"
        rows = []
        for station_id, values in bike_patterns.items():
            bikes = values[idx]
            rows.append(
                {
                    "station_id": station_id,
                    "station_name": names[station_id],
                    "capacity": 10,
                    "bikes_available": bikes,
                    "docks_available": 10 - bikes,
                    "shared_rate": bikes * 10,
                    "station_lat": 37.5,
                    "station_lon": 127.0,
                    "captured_at_kst": captured,
                    "source": "fixture",
                }
            )
        write_snapshot(root, stamp, rows)


def write_unbalanced_priority_snapshots(root: Path) -> None:
    first_rows = [
        {
            "station_id": "A",
            "station_name": "Dock A",
            "capacity": 10,
            "bikes_available": 10,
            "docks_available": 0,
            "shared_rate": 100,
            "station_lat": 37.5,
            "station_lon": 127.0,
            "captured_at_kst": "2026-07-02T19:00:00+09:00",
            "source": "fixture",
        },
        {
            "station_id": "B",
            "station_name": "Dock B",
            "capacity": 10,
            "bikes_available": 10,
            "docks_available": 0,
            "shared_rate": 100,
            "station_lat": 37.5,
            "station_lon": 127.0,
            "captured_at_kst": "2026-07-02T19:00:00+09:00",
            "source": "fixture",
        },
        {
            "station_id": "Z",
            "station_name": "Bike Z",
            "capacity": 10,
            "bikes_available": 0,
            "docks_available": 10,
            "shared_rate": 0,
            "station_lat": 37.5,
            "station_lon": 127.0,
            "captured_at_kst": "2026-07-02T19:00:00+09:00",
            "source": "fixture",
        },
    ]
    second_rows = [
        {**row, "captured_at_kst": "2026-07-02T19:10:00+09:00"}
        for row in first_rows
    ]
    write_snapshot(root, "20260702_190000", first_rows)
    write_snapshot(root, "20260702_191000", second_rows)


def test_next_snapshot_label_panel_marks_future_shortage(tmp_path):
    write_three_snapshots(tmp_path)
    history = load_snapshot_history(tmp_path)
    panel = build_next_snapshot_label_panel(history, SeoulValidationConfig())

    first_alpha = panel.loc[
        panel["station_id"].eq("A") & panel["snapshot_captured_at"].dt.strftime("%H:%M:%S").eq("19:00:00")
    ].iloc[0]
    first_beta = panel.loc[
        panel["station_id"].eq("B") & panel["snapshot_captured_at"].dt.strftime("%H:%M:%S").eq("19:00:00")
    ].iloc[0]

    assert len(history) == 6
    assert bool(first_alpha["bike_shortage_next_snapshot"]) is True
    assert bool(first_beta["dock_shortage_next_snapshot"]) is True
    assert first_alpha["next_gap_minutes"] == 10


def test_rule_priority_validation_scores_send_and_remove_actions(tmp_path):
    write_three_snapshots(tmp_path)
    history = load_snapshot_history(tmp_path)
    config = SeoulValidationConfig(min_snapshots_for_validation=2)
    panel = build_next_snapshot_label_panel(history, config)

    summary, metrics = evaluate_rule_priority(panel, SeoulValidationConfig(min_snapshots_for_validation=2, top_ks=(10, 50)))

    assert summary["validation_status"] == "READY"
    assert summary["precision_at_10"] is not None
    assert summary["send_bikes_count"] > 0
    assert summary["remove_bikes_count"] > 0
    assert not metrics.empty


def test_balanced_action_metrics_keep_send_bikes_visible_when_global_topk_is_remove_heavy(tmp_path):
    write_unbalanced_priority_snapshots(tmp_path)
    history = load_snapshot_history(tmp_path)
    config = SeoulValidationConfig(min_snapshots_for_validation=2, top_ks=(2,))
    panel = build_next_snapshot_label_panel(history, config)

    summary, metrics = evaluate_rule_priority(panel, config)
    global_top2 = metrics.loc[metrics["metric_mode"].eq("global_topk") & metrics["top_k"].eq(2)].iloc[0]
    balanced_top2 = metrics.loc[metrics["metric_mode"].eq("balanced_action") & metrics["top_k"].eq(2)].iloc[0]

    assert summary["validation_status"] == "READY"
    assert global_top2["send_bikes_count"] == 0
    assert global_top2["remove_bikes_count"] == 2
    assert balanced_top2["send_bikes_count"] == 1
    assert balanced_top2["remove_bikes_count"] == 1
    assert summary["balanced_send_bikes_count"] == 1
    assert summary["balanced_remove_bikes_count"] == 1


def test_analyze_seoul_snapshots_writes_reports_and_not_ready_model(tmp_path):
    write_three_snapshots(tmp_path)

    payload = analyze_seoul_snapshots(tmp_path, SeoulValidationConfig())

    report_dir = tmp_path / "seoul_ddareungi" / "reports"
    processed_dir = tmp_path / "seoul_ddareungi" / "data" / "processed"
    assert payload["validation"]["validation_status"] == "NOT_READY"
    assert payload["validation"]["evaluation_status"] == "EVALUATED"
    assert payload["model"]["model_status"] == "NOT_READY"
    assert (processed_dir / "snapshot_history.csv").exists()
    assert (processed_dir / "next_snapshot_label_panel.csv").exists()
    assert (report_dir / "validation_summary.json").exists()
    assert (report_dir / "validation_metrics.csv").exists()
    assert (report_dir / "validation_report.md").exists()
    assert (report_dir / "model_metrics.json").exists()
    assert (report_dir / "model_metrics.csv").exists()


def test_model_baseline_evaluates_when_snapshot_history_is_sufficient(tmp_path):
    write_ml_ready_snapshots(tmp_path)
    history = load_snapshot_history(tmp_path)
    config = SeoulValidationConfig(
        min_snapshots_for_validation=4,
        min_snapshots_for_model=4,
        min_label_rows_for_model=8,
        test_fraction=0.34,
    )
    panel = build_next_snapshot_label_panel(history, config)

    summary, metrics = evaluate_model_baseline(panel, config)

    assert summary["model_status"] == "READY"
    assert summary["split"] == "chronological"
    assert summary["best_model"] in set(metrics["model"])
    assert {"persistence_baseline", "station_hour_profile", "logistic_inventory_model"}.issubset(set(metrics["model"]))


def test_temporal_split_uses_chronological_boundary():
    frame = pd.DataFrame(
        {
            "snapshot_captured_at": pd.to_datetime(
                [
                    "2026-07-02T19:00:00+09:00",
                    "2026-07-02T19:10:00+09:00",
                    "2026-07-02T19:20:00+09:00",
                    "2026-07-02T19:30:00+09:00",
                ],
                utc=True,
            ),
            "value": [1, 2, 3, 4],
        }
    )

    train, test = temporal_split(frame, 0.25)

    assert train["value"].tolist() == [1, 2, 3]
    assert test["value"].tolist() == [4]
