import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bike_share_resilience.pipeline import (
    _read_pytest_evidence,
    build_quality_gate_checks,
    build_quality_gate_scores,
    build_features,
    conformal_intervals,
    create_synthetic_contract,
    chronological_split,
    evaluate_predictions,
    render_model_card,
    rebalancing_optimization,
)


def test_feature_builder_preserves_rows_after_lags():
    df = create_synthetic_contract(days=45, seed=7)
    features = build_features(df)
    assert len(features) > 24 * 30
    assert "lag_24" in features.columns
    assert "rolling_24_mean" in features.columns
    assert features["cnt"].isna().sum() == 0


def test_chronological_split_ordering():
    df = build_features(create_synthetic_contract(days=60, seed=11))
    train, valid, test = chronological_split(df)
    assert train["dteday"].max() < valid["dteday"].min()
    assert valid["dteday"].max() < test["dteday"].min()
    assert len(train) > len(valid) > 0
    assert len(test) > 0


def test_evaluate_predictions_contains_core_metrics():
    metrics = evaluate_predictions([10, 20, 30], [12, 18, 33])
    assert {"mae", "rmse", "mape", "smape", "wape", "r2"}.issubset(metrics)
    assert metrics["mae"] > 0
    assert metrics["wape"] > 0


def test_conformal_intervals_cover_expected_columns():
    intervals, summary = conformal_intervals([10, 20, 30, 40], [11, 19, 29, 42], [15, 25], [14, 30])
    assert {"lower_90", "upper_90", "covered", "interval_width"}.issubset(intervals.columns)
    assert summary["conformal_radius"] >= 0
    assert 0 <= summary["conformal_test_coverage"] <= 1


def test_rebalancing_optimization_returns_bucket_allocations():
    df = build_features(create_synthetic_contract(days=45, seed=13)).tail(240)
    y_pred = df["cnt"].to_numpy(dtype=float)
    result = rebalancing_optimization(df, y_pred, conformal_radius=20.0)
    assert {"demand_bucket", "allocated_bikes", "target_bikes", "optimization_status"}.issubset(result.columns)
    assert result["allocated_bikes"].sum() > 0


def test_quality_gate_checks_use_observable_thresholds():
    metadata = {
        "effective_rows": 17379,
        "effective_columns": ["cnt", "datetime"],
    }
    metrics = {
        "wape": 15.0,
        "r2": 0.93,
        "conformal_test_coverage": 0.92,
        "conformal_mean_width": 175.0,
        "mae": 36.0,
        "mae_ci_low": 34.0,
        "mae_ci_high": 38.0,
    }
    rows = {"train_rows": 12000, "valid_rows": 2500, "test_rows": 2500}
    checks = build_quality_gate_checks(metrics, metadata, rows)
    scores = build_quality_gate_scores(metrics, metadata, rows)
    assert checks["passed"].all()
    assert {"gate", "passed", "evidence", "threshold"}.issubset(checks.columns)
    assert scores["score"].min() >= 90
    assert {"category", "score", "evidence"}.issubset(scores.columns)


def test_quality_scores_only_cross_active_floor_with_complete_advanced_evidence(tmp_path):
    metadata = {
        "effective_rows": 17379,
        "effective_columns": ["cnt", "datetime"],
        "fallback_used": False,
    }
    metrics = {
        "wape": 15.0,
        "r2": 0.93,
        "conformal_test_coverage": 0.92,
        "mae": 36.0,
        "mae_ci_low": 34.0,
        "mae_ci_high": 38.0,
    }
    row_counts = {"train_rows": 12000, "valid_rows": 2500, "test_rows": 2500}
    advanced = {
        "prospective_pass": True,
        "advanced_validation_ready": True,
        "advanced_artifacts_present": True,
        "label_rows": 817668,
        "rolling_origin_fold_count": 3,
        "rolling_origin_model_rows": 9,
        "feature_ablation_rows": 3,
        "drift_checks_passed": 4,
        "drift_check_count": 4,
        "failure_audit_segments": 6,
        "frozen_cohort_ready": True,
        "public_evidence_go": True,
        "presentation_ready": True,
        "tests_passed": True,
    }

    advanced["tests_passed"] = False
    unverified = build_quality_gate_scores(
        metrics,
        metadata,
        row_counts,
        advanced,
    )
    advanced["tests_passed"] = True
    verified = build_quality_gate_scores(
        metrics,
        metadata,
        row_counts,
        advanced,
    )

    assert unverified["score"].min() == 93
    assert verified["score"].min() == 96.0
    assert verified["evidence"].str.contains("rolling|prospective|drift|ablation|tests_passed|README").all()

    source_file = tmp_path / "src" / "module.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("VALUE = 1\n", encoding="utf-8")
    pytest_report = tmp_path / "reports" / "pytest.xml"
    pytest_report.parent.mkdir()
    pytest_report.write_text(
        '<testsuites><testsuite tests="55" failures="0" errors="0" /></testsuites>',
        encoding="utf-8",
    )
    fresh = _read_pytest_evidence(pytest_report, tmp_path)
    assert fresh["tests_passed"] is True
    assert fresh["test_count"] == 55

    newer_mtime = pytest_report.stat().st_mtime + 2
    os.utime(source_file, (newer_mtime, newer_mtime))
    stale = _read_pytest_evidence(pytest_report, tmp_path)
    assert stale["tests_passed"] is False
    assert stale["test_evidence_fresh"] is False

    pytest_report.write_text("<not-valid", encoding="utf-8")
    malformed = _read_pytest_evidence(pytest_report, tmp_path)
    assert malformed["tests_passed"] is False
    assert malformed["test_count"] == 0


def test_model_card_is_korean_template():
    metadata = {
        "source_name": "UCI Machine Learning Repository Bike Sharing Dataset",
        "preferred_source": "https://example.com/data.zip",
        "effective_rows": 17379,
        "fallback_used": False,
    }
    metrics = {
        "mae": 35.95,
        "rmse": 55.13,
        "wape": 15.36,
        "smape": 27.85,
        "r2": 0.933,
        "mae_ci_low": 34.31,
        "mae_ci_high": 37.61,
        "conformal_test_coverage": 0.923,
        "conformal_mean_width": 175.19,
    }
    coverage = create_synthetic_contract(days=8).head(1)[["cnt"]].rename(columns={"cnt": "rows"})
    coverage["segment"] = "전체"
    coverage["coverage_90"] = 0.92
    coverage["mean_interval_width"] = 175.0
    rebalancing = coverage.rename(columns={"segment": "demand_bucket"})
    rebalancing["allocated_bikes"] = 10.0
    card = render_model_card(metadata, "gradient_boosting", metrics, coverage, rebalancing)
    assert "# 모델 카드" in card
    assert "## 사용 목적" in card
    assert "Intended Use" not in card


if __name__ == "__main__":
    test_feature_builder_preserves_rows_after_lags()
    test_chronological_split_ordering()
    test_evaluate_predictions_contains_core_metrics()
    test_conformal_intervals_cover_expected_columns()
    test_rebalancing_optimization_returns_bucket_allocations()
    test_quality_gate_checks_use_observable_thresholds()
    test_model_card_is_korean_template()
    print("tests passed")
