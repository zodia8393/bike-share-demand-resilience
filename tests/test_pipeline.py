from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bike_share_resilience.pipeline import (
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
