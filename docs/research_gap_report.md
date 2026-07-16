# Research Gap Report

현재 slice는 frozen prospective cohort, leakage-safe night calibration, post-cutoff monitoring과 public evidence gate까지 구현했다. Station-level multi-source extension, live inventory snapshot, local API/dashboard, 2주 snapshot readiness automation, prospective validation evaluator, monitoring drift, public deploy readiness gate가 연결되어 있다.

2026-07-15 KST 기준 cutoff `2026-07-13T14:15:03+09:00`까지 340/336개 snapshot과 14.01일 coverage를 고정했다. 817,668개 label의 prospective validation은 `PASS`, upstream evidence gate는 `GO`다. Rolling-origin, ablation, drift, failure audit과 최신 JUnit을 quality rubric에 연결해 minimum score 96.0으로 기존 active floor 95.8을 넘겼고, portfolio floor를 96.0으로 ratchet했다. 이후 21개 snapshot은 별도 drift monitoring에서 4/4 PASS다. Night calibrated candidate는 final non-degradation gate를 넘지 못해 persistence를 유지했다. 현재 score는 새 reference floor와 같으므로 다음 strict ratchet 대상은 별도로 남는다.

| Gate | 현재 상태 | 미달 근거 | 다음 작업 |
|---|---|---|---|
| topic candidates >= 5 | PASS | `docs/topic_selection.md`에 5개 후보 평가 기록 | 다음 후보는 SNS/물류/에너지 중 하나로 확장 |
| data sources explored >= 3 | PASS | UCI, Citi Bike JC trip history, Citi Bike GBFS station metadata/status, Open-Meteo weather, SNS/event 후보를 분리 기록 | 이벤트/장애/요금 source 추가 시 decision feature 확장 |
| data sources joined >= 2 or documented exception | PASS | station-level extension에서 trip history + GBFS station metadata/status + Open-Meteo weather를 station-hour grain과 inventory surface로 결합 | post-cutoff monitoring을 최근 24시간/7일 window로 확장할 때 추세 계약 추가 |
| leakage-safe validation | PASS | 날짜 경계 chronological split, shifted rolling feature, cutoff 고정 3-fold expanding-window와 train 내부 threshold calibration 사용 | final holdout은 acceptance gate로만 유지하고 재튜닝 금지 |
| baseline/model/ablation or benchmark | PASS | historical baseline, ridge, gradient boosting, permutation importance | LightGBM/CatBoost는 dependency 근거가 생길 때 추가 |
| uncertainty/robustness/failure audit | PASS | bootstrap CI, conformal coverage, weather shock, prospective drift 4/4, failure 6 segments, post-cutoff drift 4/4 | night 전이율 6.40% 원인을 event·service 상태 feature로 분석 |
| product surface | PASS | `scripts/run_all.sh`, `scripts/run_station_level.sh`, `station_service --check`, local dashboard/API, deploy readiness gate 존재 | 외부 endpoint auth/운영 gate는 Stage 3에서 별도 검증 |
| privacy publication gate | PASS | raw ride_id/zip/json은 `/DATA/HJ` artifact로 분리, Git에는 aggregate/report 경로만 기록 | 내부 데이터 사용 시 synthetic fallback 추가 |
| CI/tests/smoke | PASS | GitHub Actions, `scripts/run_all.sh`, 63 tests와 source freshness를 확인하는 JUnit evidence 존재 | advanced artifact freshness를 CI에서도 교차검증 |
| GitHub/deploy/runbook | PASS_WITH_LIMITATION | GitHub repo, local runbook, local API/dashboard, upstream evidence `GO` gate 존재 | hosted/public endpoint auth와 운영 정책 검증 |

## Station-Level Extension 결과

- 데이터: Citi Bike JC trip history 50,661 rows, GBFS station metadata/status 2,400+ rows, Open-Meteo weather 744 hours
- 결합 결과: 35 stations, 25,200 station-hour rows, GBFS join rate 97.1%, inventory join rate 97%+
- 모델: `gradient_boosting`
- 성능: best MAE 1.006, station-hour profile baseline MAE 1.025
- 불확실성: split-conformal coverage 88.9%
- 운영 산출물: `station_rebalancing_priority.csv` 12개 station priority rows, `station_inventory_snapshot.csv`, local `/api/rebalancing-priority`, `/api/inventory-snapshot`, dashboard HTML

<!-- AUTO_QUALITY_RATCHET_GAP_START -->
## Quality Ratchet Gap

- Generated: `2026-07-15 17:26 KST`
- Quality artifact: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/quality_gate_scores.csv`
- Active quality floor: `96`
- README/presentation floor: `96`
- Status: 현재 quality score는 아직 ratchet 완료 상태가 아닙니다. 아래 항목을 보강한 뒤 재측정해야 합니다.

| Category | Score | Required | Gap | Next upgrade action |
|---|---:|---:|---|---|
| problem framing and business/career relevance | 96 | >96 | active floor와 동점이라 ratchet 상승을 만들지 못함 | 채용시장/운영 의사결정 문장을 더 선명하게 만들고, README 결론에 비용·리스크·사용자 행동 변화를 연결한다. |
| data quality, acquisition, and documentation | 96 | >96 | active floor와 동점이라 ratchet 상승을 만들지 못함 | 데이터 source를 하나 더 검증하거나 join coverage, license, leakage risk를 수치로 보강한다. |
| EDA depth and insight quality | 96 | >96 | active floor와 동점이라 ratchet 상승을 만들지 못함 | segment별 패턴, 실패 구간, outlier/drift 원인을 figure와 함께 추가한다. |
| feature engineering or statistical design | 96 | >96 | active floor와 동점이라 ratchet 상승을 만들지 못함 | ablation 가능한 feature family를 추가하고, 제거 실험으로 실제 기여를 검증한다. |
| modeling, inference, optimization, or analytical method rigor | 96 | >96 | active floor와 동점이라 ratchet 상승을 만들지 못함 | baseline 외 강한 benchmark나 ablation을 추가하고, 성능 차이를 confidence interval과 함께 제시한다. |
| validation, testing, and reproducibility | 96 | >96 | active floor와 동점이라 ratchet 상승을 만들지 못함 | temporal/group/prospective validation을 강화하고 validator/CI에 재현 명령을 포함한다. |
| interpretation, limitations, and decision usefulness | 96 | >96 | active floor와 동점이라 ratchet 상승을 만들지 못함 | 모델 결과를 reviewer가 실행 가능한 운영 의사결정, threshold, action list로 변환한다. |
| code quality, structure, maintainability, and automation | 96 | >96 | active floor와 동점이라 ratchet 상승을 만들지 못함 | one-shot run, typed modules, smoke tests, deployment/readiness check를 추가해 반복 실행성을 높인다. |
| portfolio presentation, README, figures, and final report | 96 | >96 | active floor와 동점이라 ratchet 상승을 만들지 못함 | README 첫 화면을 더 짧게 만들고, 핵심 수치의 의미·인사이트·방법 선택 이유를 더 직접적으로 쓴다. |
| doctoral-level originality, depth, and technical ambition | 96 | >96 | active floor와 동점이라 ratchet 상승을 만들지 못함 | 단순 모델 성능을 넘어 prospective validation, causal/robustness angle, productized decision loop를 보강한다. evaluator가 이미 있다면 충분한 snapshot coverage 후 true outcome calibration을 추가한다. |

### 다음 검증 명령

```bash
python3 /workspace/prj/personal/data-scientist-career/scripts/validate_weekend_project.py --project /workspace/prj/personal/data-scientist-career/bike-share-demand-resilience --stage sunday
python3 /workspace/prj/personal/data-scientist-career/scripts/update_quality_floor.py --quality-gate /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/quality_gate_scores.csv
```
<!-- AUTO_QUALITY_RATCHET_GAP_END -->
