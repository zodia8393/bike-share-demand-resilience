# 연구 설계

## Research Questions

1. 시간순 holdout에서 공공자전거 시간대별 수요 예측은 baseline 대비 얼마나 개선되는가?
2. 출퇴근 피크, 악천후, 주말, 야간 segment에서 오차와 conformal coverage는 안정적으로 유지되는가?
3. 예측값과 불확실성 폭을 재배치 staging target으로 바꾸면 운영자가 쓸 수 있는 의사결정 단위가 되는가?
4. station-hour 수요와 station capacity, hourly weather를 결합하면 shortage-risk proxy 기반 human review queue를 만들 수 있는가?

## Evidence Plan

- 복합 데이터 결합: 현재 UCI 공개 데이터의 calendar/weather 변수를 활용했고, 외부 station/SNS/internal join은 공개성과 station grain 부재로 다음 확장으로 분리했다.
- Leakage-safe validation: 날짜 경계 기준 chronological train/valid/test split과 shifted lag/rolling feature를 사용한다.
- Baseline: 근무일 여부와 시간대별 median profile을 기준선으로 둔다.
- Main model: Ridge regression과 Gradient Boosting을 같은 split에서 비교한다.
- Ablation: baseline, linear model, nonlinear model, lag/rolling/weather feature contribution을 `experiment_tracker.csv`와 permutation importance로 추적한다.
- Uncertainty/robustness: bootstrap MAE confidence interval, split-conformal 90% interval, segment coverage, weather shock scenario를 산출한다.
- Failure audit: commute peak, bad weather, weekend, night segment의 residual과 coverage를 분리한다.
- Decision impact: conformal upper bound를 수요 bucket별 staging target으로 변환하고 fleet budget 제약 최적화를 실행한다.
- Station-level extension: Jersey City trip history, GBFS station metadata, Open-Meteo weather를 결합해 station-hour demand forecast와 rebalancing priority를 산출한다.

## 한계와 윤리

현재 프로젝트는 사용자·정류장·좌표 식별자를 포함하지 않는 공개 집계 데이터만 사용한다. station-level 운영 claim은 하지 않고, 실제 dispatch 적용 전 필요한 capacity, trip, station coordinate, real-time weather/event join을 `research_gap_report.md`에 명시한다.
