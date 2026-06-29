# Research Gap Report

현재 slice는 portfolio-ready이며 quality gate를 통과했다. 2026-06-29에 station-level multi-source extension을 추가해 가장 큰 gap이던 station/capacity/weather 결합을 1차 해소했다. 다만 true shortage outcome과 historical inventory는 아직 남은 gap이다.

| Gate | 현재 상태 | 미달 근거 | 다음 작업 |
|---|---|---|---|
| topic candidates >= 5 | PASS | `docs/topic_selection.md`에 5개 후보 평가 기록 | 다음 후보는 SNS/물류/에너지 중 하나로 확장 |
| data sources explored >= 3 | PASS | UCI, Citi Bike JC trip history, Citi Bike GBFS station metadata, Open-Meteo weather, SNS/event 후보를 분리 기록 | 이벤트 또는 station_status source 추가 |
| data sources joined >= 2 or documented exception | PASS | station-level extension에서 trip history + GBFS station metadata + Open-Meteo weather를 station-hour grain으로 결합 | historical station_status/inventory 결합 |
| leakage-safe validation | PASS | 날짜 경계 chronological split과 shifted rolling feature 사용 | rolling-origin prospective validation 추가 |
| baseline/model/ablation or benchmark | PASS | historical baseline, ridge, gradient boosting, permutation importance | LightGBM/CatBoost는 dependency 근거가 생길 때 추가 |
| uncertainty/robustness/failure audit | PASS | bootstrap CI, conformal coverage, weather shock, segment residual audit | peak-specific conformal calibration 추가 |
| product surface | PASS | `scripts/run_all.sh`와 `scripts/run_station_level.sh` batch/CLI 존재 | API/dashboard 배포 |
| privacy publication gate | PASS | raw ride_id/zip/json은 `/DATA/HJ` artifact로 분리, Git에는 aggregate/report 경로만 기록 | 내부 데이터 사용 시 synthetic fallback 추가 |
| CI/tests/smoke | PASS | GitHub Actions, `scripts/run_all.sh`, station synthetic tests 존재 | validator를 CI에 추가 |
| GitHub/deploy/runbook | PASS_WITH_LIMITATION | GitHub repo와 local runbook 존재, deployed service는 없음 | API/dashboard product로 확장 시 deploy |

## Station-Level Extension 결과

- 데이터: Citi Bike JC trip history 50,661 rows, GBFS station metadata 2,412 rows, Open-Meteo weather 744 hours
- 결합 결과: 35 stations, 25,200 station-hour rows, GBFS join rate 97.1%
- 모델: `gradient_boosting`
- 성능: best MAE 1.006, station-hour profile baseline MAE 1.025
- 불확실성: split-conformal coverage 88.9%
- 운영 산출물: `station_rebalancing_priority.csv` 12개 station priority rows
