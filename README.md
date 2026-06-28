# Bike-Share Demand Resilience Forecasting

서울시 따릉이 대여량의 수요를 시간 단위로 예측하고, 수요 급변(날씨 충격, 계절/휴일/출퇴근 피크)에 대한 복원력을 측정하는 포트폴리오형 데이터 과학 프로젝트입니다.

이 프로젝트는 UCI Bike Sharing 공개 데이터셋을 기반으로 시계열 누수 방지 분할, 피처 엔지니어링(달력/계절성/날씨 스트레스/라그/이동평균/상호작용), 모델 비교, 잔차 감사, 신뢰구간/운영 의사결정 레이어를 end-to-end로 구성했습니다.

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
