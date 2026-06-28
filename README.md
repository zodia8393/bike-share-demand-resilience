# Bike-Share Demand Resilience Forecasting

Portfolio-grade data science project for mobility operations forecasting.

This project builds an end-to-end hourly bike-share demand forecasting and resilience analysis pipeline using the UCI Bike Sharing Dataset, with a deterministic synthetic fallback that preserves the public data contract when network access is unavailable.

## Problem

Bike-share operators need reliable short-horizon demand forecasts and interpretable stress diagnostics for weather, seasonality, and commute peaks. The portfolio objective is to demonstrate practical forecasting rigor, model comparison, residual auditing, and decision-oriented interpretation.

## Reproducible Run

```bash
cd /workspace/prj/data-scientist-career/bike-share-demand-resilience
scripts/run_all.sh
```

If `pytest` is not installed, run:

```bash
python3 tests/test_pipeline.py
```

## Outputs

All generated artifacts are written outside source control under:

- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/models`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports`
- `/DATA/HJ/prj/data-scientist-career/reports`

## Methods

- Public/open data acquisition with source metadata and fallback contract.
- Time-aware train/validation/test split.
- Feature engineering for calendar, seasonality, weather stress, lagged demand, rolling demand, commute windows, and interaction terms.
- Baselines: historical median profile and ridge regression.
- Strong model: gradient boosting regression.
- Validation: holdout test metrics, WAPE/sMAPE/MAPE, time-series cross-validation, bootstrap confidence interval for MAE, split-conformal prediction intervals, segment residual audit.
- Interpretation: permutation importance, weather shock sensitivity, interval coverage diagnostics, and operational recommendations.
- Decision layer: constrained rebalancing allocation demo using demand buckets, forecast uncertainty, priority weights, and a limited fleet budget.

## Portfolio Artifacts

- Final report: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/final_report.md`
- Model card: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/model_card.md`
- Experiment tracker: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/experiment_tracker.csv`
- Conformal intervals: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/conformal_prediction_intervals.csv`
- Rebalancing optimization: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/rebalancing_optimization.csv`
- Key figures:
  - `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures/uncertainty_conformal_intervals.png`
  - `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures/optimization_rebalancing_allocation.png`
  - `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures/interpretation_permutation_importance.png`

## Quality Gate

The generated final report includes the 10-category automation quality score table required by the weekend career-project schedule. The project is not considered complete unless every category scores at least 90.
