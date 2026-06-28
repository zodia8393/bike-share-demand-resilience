from pathlib import Path
import tempfile

from bike_share_resilience.pipeline import (
    build_features,
    conformal_intervals,
    create_synthetic_contract,
    chronological_split,
    evaluate_predictions,
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


if __name__ == "__main__":
    test_feature_builder_preserves_rows_after_lags()
    test_chronological_split_ordering()
    test_evaluate_predictions_contains_core_metrics()
    print("tests passed")
