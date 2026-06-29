# Research Gap Report

현재 slice는 portfolio-ready이며 quality gate를 통과했다. 2026-06-29에 station-level multi-source extension, live inventory snapshot, local API/dashboard check를 추가해 가장 큰 gap이던 station/capacity/weather/inventory/product surface를 1차 해소했다. 다만 true shortage outcome은 시간별 station_status snapshot이 누적된 이후 prospective validation으로 검증해야 한다.

| Gate | 현재 상태 | 미달 근거 | 다음 작업 |
|---|---|---|---|
| topic candidates >= 5 | PASS | `docs/topic_selection.md`에 5개 후보 평가 기록 | 다음 후보는 SNS/물류/에너지 중 하나로 확장 |
| data sources explored >= 3 | PASS | UCI, Citi Bike JC trip history, Citi Bike GBFS station metadata/status, Open-Meteo weather, SNS/event 후보를 분리 기록 | 이벤트/장애/요금 source 추가 시 decision feature 확장 |
| data sources joined >= 2 or documented exception | PASS | station-level extension에서 trip history + GBFS station metadata/status + Open-Meteo weather를 station-hour grain과 inventory surface로 결합 | historical station_status가 누적되면 prospective label 검증 |
| leakage-safe validation | PASS | 날짜 경계 chronological split과 shifted rolling feature 사용 | rolling-origin prospective validation 추가 |
| baseline/model/ablation or benchmark | PASS | historical baseline, ridge, gradient boosting, permutation importance | LightGBM/CatBoost는 dependency 근거가 생길 때 추가 |
| uncertainty/robustness/failure audit | PASS | bootstrap CI, conformal coverage, weather shock, segment residual audit | peak-specific conformal calibration 추가 |
| product surface | PASS | `scripts/run_all.sh`, `scripts/run_station_level.sh`, `station_service --check`, local dashboard/API 존재 | public deploy는 privacy/auth 경계 확정 후 수행 |
| privacy publication gate | PASS | raw ride_id/zip/json은 `/DATA/HJ` artifact로 분리, Git에는 aggregate/report 경로만 기록 | 내부 데이터 사용 시 synthetic fallback 추가 |
| CI/tests/smoke | PASS | GitHub Actions, `scripts/run_all.sh`, station synthetic tests 존재 | validator를 CI에 추가 |
| GitHub/deploy/runbook | PASS_WITH_LIMITATION | GitHub repo와 local runbook, local API/dashboard 존재, public deployed service는 없음 | public deploy는 인증/비공개 artifact 경계 확정 후 수행 |

## Station-Level Extension 결과

- 데이터: Citi Bike JC trip history 50,661 rows, GBFS station metadata/status 2,400+ rows, Open-Meteo weather 744 hours
- 결합 결과: 35 stations, 25,200 station-hour rows, GBFS join rate 97.1%, inventory join rate 97%+
- 모델: `gradient_boosting`
- 성능: best MAE 1.006, station-hour profile baseline MAE 1.025
- 불확실성: split-conformal coverage 88.9%
- 운영 산출물: `station_rebalancing_priority.csv` 12개 station priority rows, `station_inventory_snapshot.csv`, local `/api/rebalancing-priority`, `/api/inventory-snapshot`, dashboard HTML
