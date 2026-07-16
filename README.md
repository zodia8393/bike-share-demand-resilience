# Bike-Share Demand Resilience

[![ci](https://github.com/zodia8393/bike-share-demand-resilience/actions/workflows/ci.yml/badge.svg)](https://github.com/zodia8393/bike-share-demand-resilience/actions/workflows/ci.yml)

공공자전거 수요 예측을 **현장 운영 의사결정**으로 바꾸는 Stage 1 프로젝트입니다. UCI/Citi Bike benchmark에서 출발해 서울 따릉이 공개데이터 adapter까지 확장했고, 대여 불가, 반납 포화, 재배치 우선순위, 검증 전 배포 차단을 하나의 reproducible ML pipeline으로 묶었습니다.

이 repo는 DecisionOps 포트폴리오의 upstream evidence layer입니다.

| Stage | 역할 | 연결 프로젝트 |
|---|---|---|
| Stage 1 | 수요 예측, station risk, 서울 따릉이 adapter, validation gate | 이 repo |
| Stage 2 | ML 산출물을 agent/tool/eval/review queue로 변환 | [Agentic DecisionOps Workbench](https://github.com/zodia8393/data-scientist-career/tree/main/agentic-decisionops-workbench) |
| Stage 3 | 지도, impact card, approval API, Docker demo로 제품화 | [DecisionOps Control Tower](https://github.com/zodia8393/decisionops-control-tower) |

## 결론

고정된 340개 Citi Bike snapshot cohort가 14일 readiness와 prospective validation을 통과해 upstream evidence gate는 `GO`입니다. 서울 따릉이 adapter도 302개 snapshot 기준 `READY`이며, 결과는 Stage 2/3의 reviewer workflow로 전달됩니다. 다만 수치는 의사결정 지원용 예측 근거이지 현장 재배치의 인과효과가 아닙니다.

## 무엇을 만들었나

| 평가자가 봐야 할 것 | 구현 증거 |
|---|---|
| Product DS 문제 정의 | 단순 demand forecast가 아니라 재배치, 부족 위험, 포화 위험, 배포 보류 기준까지 연결 |
| Time-aware ML discipline | random split 대신 시간순 split, bootstrap CI, conformal coverage, segment audit 사용 |
| ML-to-ops translation | 예측값을 uncertainty-aware rebalancing priority와 reviewer-readable gate로 변환 |
| Real-world adapter design | 미국 benchmark와 서울 따릉이 실시간 대여정보를 공통 inventory contract로 정규화 |
| Responsible deployment | frozen prospective cohort가 검증을 통과할 때만 public deploy gate를 `GO`로 전환 |
| Downstream product readiness | Stage 2 agentic eval과 Stage 3 Control Tower가 읽을 수 있는 공개 안전 산출물 생성 |

## 핵심 수치

최신 로컬 산출물 기준: 2026-07-15 KST. Citi Bike prospective cohort cutoff는 2026-07-13 14:15 KST로 고정했습니다.

| 항목 | 값 | 의미 |
|---|---:|---|
| UCI demand rows | 17,379 | 시간대별 수요 예측 기준 데이터 |
| Best model | `gradient_boosting` | baseline/Ridge 대비 holdout 성능 우수 |
| Test MAE / WAPE / R2 | 35.95 / 15.36% / 0.933 | 수요 규모 대비 예측 오차와 설명력 |
| Bootstrap MAE 95% CI | [34.31, 37.61] | 단일 점수 우연성을 줄인 안정성 확인 |
| Split-conformal 90% coverage | 92.3% | 운영 buffer로 쓸 예측구간 보정 |
| Station model frame | 35 stations, 25,200 station-hour rows | 집계 수요를 station 단위 판단으로 확장 |
| Citi Bike live inventory monitor | 2,412 stations, frozen 340 / source 361 snapshots | 21개 cutoff 이후 snapshot을 제외해 14.01일 prospective cohort 고정 |
| Citi Bike prospective validation | `PASS`, 817,668 labels | persistence baseline F1 0.8286, AP 0.7102, Brier 0.0478 |
| Rolling-origin validation | 3 folds / 9 model-fold rows | fold-best F1 평균 0.8477, 최저 0.8238 |
| Prospective drift audit | 4 / 4 `PASS` | shortage-rate, inventory PSI, hour distribution, station coverage 점검 |
| Feature ablation | full AP 0.8772 / temporal-only AP 0.1481 | inventory state가 shortage ranking의 핵심 근거 |
| Failure segment audit | 6 segments | night F1 0.7960이 최저로 후속 monitoring 대상 |
| Night threshold calibration | `KEEP_PERSISTENCE_BASELINE` | calibrated candidate의 final 전체/night F1 0.8275/0.7953이 baseline 0.8286/0.7960을 넘지 못함 |
| Post-cutoff monitoring | 21 snapshots, 4 / 4 `PASS` | shortage-rate diff 0.0122, PSI 0.0017, hour TV 0.1765, station coverage 1.0 |
| Seoul Ddareungi latest snapshot | 2,732 stations, 302 snapshots | 서울 열린데이터광장 실시간 대여정보 adapter 동작 |
| Seoul next-snapshot validation | 302 / 24 snapshots, `READY` | 300 evaluated snapshots, 819,485 label rows, global Precision@50 0.9978 |
| Seoul balanced action validation | send_bikes 7,500 / remove_bikes 7,500 recommendations | balanced Precision@50 0.9587, send_bikes precision 0.9192, remove_bikes precision 0.9983 |
| Seoul priority output | top 50 candidates | 지도/API/Control Tower에서 읽을 재배치 후보 surface |
| Public deploy decision | `GO` | frozen cohort readiness와 prospective validation을 모두 통과 |
| Quality floor / tests | 96.0 / 63 passed | 최신 JUnit과 advanced artifact가 있을 때만 score 승격 |

`GO`는 모델 효과가 현장에서 실현됐다는 뜻이 아니라, 고정된 검증 cohort와 공개 안전성 gate를 통과했다는 뜻입니다. 이후 수집되는 snapshot은 frozen cohort에 섞지 않고 별도 monitoring 입력으로 다룹니다.

## 얻은 인사이트

단순 snapshot 개수보다 cohort cutoff를 고정하는 것이 재현성에 더 중요했습니다. 계속 들어오는 live 관측치를 검증 데이터에 섞으면 같은 명령의 metric이 매번 달라지므로, 최초 2주 충족 시점까지를 동결하고 이후 21개 관측치를 명시적으로 제외했습니다.

서울 global top-K는 높은 precision에도 `remove_bikes`로 치우칩니다. 따라서 balanced action metric을 별도로 두고 `send_bikes`와 `remove_bikes` 성능을 분리해, 한쪽 action의 높은 점수가 전체 운영 품질처럼 보이지 않게 했습니다.

Expanding-window 세 구간에서 persistence baseline이 일관되게 가장 높은 F1을 보였습니다. 반면 logistic model은 F1보다 average precision이 높아 ranking 용도로 의미가 있었고, temporal-only ablation은 AP 0.1481로 하락했습니다. 현재 inventory state가 예측의 핵심이라는 근거입니다.

Failure audit에서는 night segment F1이 0.7960으로 가장 낮았습니다. 전체 F1만으로 이 취약 구간을 숨기지 않고 후속 drift monitoring과 threshold calibration 대상으로 유지합니다.

Train 내부 calibration에서 logistic global/night threshold를 0.900/0.675로 선택했지만 final holdout에서 전체와 night F1이 모두 persistence보다 낮았습니다. Night는 shortage rate가 0.1581로 non-night 0.1320보다 높고 상태 전이율도 6.40% 대 4.18%로 더 높았습니다. 따라서 문제를 threshold 하나로 해결됐다고 보지 않고 persistence를 유지했습니다.

Frozen cutoff 이후 21개 snapshot은 검증 cohort에 합치지 않고 별도 monitoring cohort로 평가했습니다. 네 drift check가 모두 통과했지만 hour-distribution TV 0.1765는 기준 0.20에 상대적으로 가까워, 자동 재학습 대신 계속 관찰하는 신호로 남깁니다.

## 방법 선택 이유

| 선택 | 이유 | 의사결정 영향 |
|---|---|---|
| Chronological/prospective split | 미래 관측치 누수 방지 | next-snapshot 성능만 배포 근거로 사용 |
| Frozen cohort cutoff | live snapshot 증가에도 검증 재현 | monitoring과 final validation 분리 |
| Persistence baseline 포함 | 복잡한 모델이 단순 현재 상태보다 나은지 확인 | best model을 이름이 아니라 metric으로 선택 |
| Global/balanced metric 분리 | action-class 편향 노출 | send/remove 후보를 별도 검토 |
| 3-fold expanding window | 한 번의 마지막 holdout 우연성 완화 | 시간 경과에 따른 F1 안정성 확인 |
| Drift/failure audit | 평균 성능 뒤의 분포·segment 취약점 노출 | night segment를 후속 monitoring 대상으로 지정 |
| Train-internal threshold calibration | final holdout 누수 없이 night threshold 후보 검증 | 개선 gate 미통과로 persistence 정책 유지 |
| Post-cutoff cohort 분리 | 검증 결과 재현성과 운영 변화 감시를 동시에 보존 | cutoff 이후 관측치는 drift report에만 사용 |
| Evidence-based quality rubric | 정적 self-score 상승 방지 | JUnit freshness와 audit artifact가 모두 있어야 96.0 |

## Product Surfaces

| Surface | 설명 | 주요 산출물 |
|---|---|---|
| System demand forecasting | 시간대별 수요 예측, uncertainty, segment audit | `reports/run_summary.json`, `reports/model_metrics.csv` |
| Rebalancing optimization | 예측 수요와 fleet budget 제약으로 후보 배정 | `reports/rebalancing_optimization.csv` |
| Station-level extension | trip, GBFS metadata/status, weather join 기반 station risk | `station_level/reports/station_run_summary.json` |
| Snapshot readiness | 2주 hourly snapshot coverage와 prospective label 생성 | `station_level/reports/station_snapshot_readiness.json` |
| Prospective hardening | rolling-origin, ablation, drift, failure segment audit | `station_level/reports/station_prospective_*` |
| Night calibration | calibration-only threshold search, class balance, hour transition audit | `station_level/reports/station_night_*` |
| Post-cutoff monitoring | frozen reference와 이후 snapshot drift 비교 | `station_level/reports/station_post_cutoff_drift.*` |
| Seoul Ddareungi adapter | 실시간 대여소 상태, 좌표, 거치율, 지도 point 정규화 | `seoul_ddareungi/reports/latest_inventory_snapshot_summary.json` |
| Seoul priority and validation | 대여 불가/반납 포화 우선순위와 next-snapshot rule check | `seoul_ddareungi/reports/rebalancing_priority.csv`, `validation_summary.json` |
| Local dashboard/API | Stage 3가 소비할 public-safe summary payload | `scripts/run_station_dashboard.sh` |

## 대표 시각화

| Demand pattern | Uncertainty | Rebalancing decision |
|---|---|---|
| ![Weekday-hour demand heatmap](docs/assets/eda_weekday_hour_heatmap.png) | ![Split-conformal intervals](docs/assets/uncertainty_conformal_intervals.png) | ![Constrained rebalancing allocation](docs/assets/optimization_rebalancing_allocation.png) |

## Architecture

```text
UCI Bike Sharing Dataset
        |
        v
time-aware forecasting pipeline
  - baseline / Ridge / Gradient Boosting
  - holdout metrics, bootstrap CI, conformal interval
  - segment residual audit
        |
        v
rebalancing optimization artifacts

Citi Bike trips + GBFS + Open-Meteo
        |
        v
station-level demand and live inventory monitor
  - station risk ranking
  - hourly snapshot history
  - prospective validation readiness

Seoul Ddareungi Open Data bikeList API
        |
        v
city adapter contract
  - normalized inventory
  - map coordinates
  - bike shortage / dock shortage labels
  - priority candidates
        |
        v
Agentic Workbench and DecisionOps Control Tower
```

자세한 설계는 [docs/system_design.md](docs/system_design.md), 한국어 DFD는 [docs/data_flow_diagram.md](docs/data_flow_diagram.md)를 봅니다.

## Quick Start

```bash
git clone https://github.com/zodia8393/bike-share-demand-resilience.git
cd bike-share-demand-resilience
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

export OUTPUT_ROOT=/tmp/bike-share-demand-resilience
export REPORT_DIR=/tmp/bike-share-demand-resilience/portfolio_reports
scripts/run_all.sh
```

테스트:

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

Station-level과 dashboard:

```bash
OUTPUT_ROOT=/tmp/bike-share-demand-resilience scripts/run_station_level.sh
OUTPUT_ROOT=/tmp/bike-share-demand-resilience scripts/run_station_snapshot_monitor.sh
OUTPUT_ROOT=/tmp/bike-share-demand-resilience scripts/run_station_dashboard.sh
```

서울 따릉이 adapter는 서울 열린데이터광장 실시간 대여정보 key가 필요합니다. 값은 `.env` 또는 shell environment에 두고, README나 log에 노출하지 않습니다.

```bash
export SEOUL_OPEN_DATA_API_KEY="<issued-key>"
python3 scripts/check_seoul_ddareungi_schema.py --full-scan
python3 scripts/capture_seoul_ddareungi_snapshot.py
PYTHONPATH=src python3 scripts/run_seoul_ddareungi_validation.py
```

네트워크 없는 CI/smoke:

```bash
SYNTHETIC_FLAG=--synthetic TOP_STATIONS=10 OUTPUT_ROOT=/tmp/bike-share-station-smoke scripts/run_station_level.sh
```

## Repository Guide

| 경로 | 내용 |
|---|---|
| [src/bike_share_resilience](src/bike_share_resilience) | forecasting, station pipeline, Seoul adapter, validation, dashboard service |
| [scripts](scripts) | 재현 실행, snapshot capture, readiness check, dashboard runner |
| [tests](tests) | pipeline, station, Seoul adapter, validation, service regression tests |
| [docs/modeling_protocol.md](docs/modeling_protocol.md) | 모델링과 검증 protocol |
| [docs/station_level_extension.md](docs/station_level_extension.md) | station-level 확장 설계 |
| [docs/prospective_shortage_validation.md](docs/prospective_shortage_validation.md) | snapshot 기반 prospective validation |
| [docs/public_deployment_decision.md](docs/public_deployment_decision.md) | public deploy `GO/NO_GO` 판단 |
| [docs/seoul_ddareungi_api_keys.md](docs/seoul_ddareungi_api_keys.md) | 서울 따릉이 API key와 보안 운용 |

## Boundaries

- 재배치 우선순위는 decision-support artifact이며 실제 현장 dispatch를 실행하지 않습니다.
- Night segment prospective F1은 0.7960으로 전체보다 낮고 calibrated candidate도 final gate를 넘지 못했으므로 persistence baseline과 threshold 0.5를 유지합니다.
- Cutoff 이후 snapshot은 monitoring-only이며 frozen validation metric 재산출이나 자동 모델 변경에 사용하지 않습니다.
- 서울 따릉이 next-snapshot validation은 2026-07-15 KST 기준 `READY`입니다. Global top-K metric은 `remove_bikes` 후보 중심이고, balanced action metric은 `send_bikes`와 `remove_bikes`를 분리해 보조 근거로 사용합니다. 현장 운영 성과나 인과효과로 해석하지 않습니다.
- API key, raw private credential, `.env` 값은 Git, report, screenshot에 남기지 않습니다.
- 대용량 원천 데이터와 생성 산출물은 `OUTPUT_ROOT` 아래에 두고 Git에는 넣지 않습니다.
- Stage 2/3 downstream system은 이 repo의 `GO`, `NO_GO`, `NOT_READY`, blocker를 그대로 전달하고 endpoint 배포 상태와 혼동하지 않아야 합니다.
