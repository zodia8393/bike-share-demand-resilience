# Bike-Share Demand Resilience

[![ci](https://github.com/zodia8393/bike-share-demand-resilience/actions/workflows/ci.yml/badge.svg)](https://github.com/zodia8393/bike-share-demand-resilience/actions/workflows/ci.yml)

공공자전거 수요 예측을 **현장 운영 의사결정**으로 바꾸는 Stage 1 프로젝트입니다. UCI/Citi Bike benchmark에서 출발해 서울 따릉이 공개데이터 adapter까지 확장했고, 대여 불가, 반납 포화, 재배치 우선순위, 검증 전 배포 차단을 하나의 reproducible ML pipeline으로 묶었습니다.

이 repo는 DecisionOps 포트폴리오의 upstream evidence layer입니다.

| Stage | 역할 | 연결 프로젝트 |
|---|---|---|
| Stage 1 | 수요 예측, station risk, 서울 따릉이 adapter, validation gate | 이 repo |
| Stage 2 | ML 산출물을 agent/tool/eval/review queue로 변환 | [Agentic DecisionOps Workbench](https://github.com/zodia8393/data-scientist-career/tree/main/agentic-decisionops-workbench) |
| Stage 3 | 지도, impact card, approval API, Docker demo로 제품화 | [DecisionOps Control Tower](https://github.com/zodia8393/decisionops-control-tower) |

## What This Shows

| 평가자가 봐야 할 것 | 구현 증거 |
|---|---|
| Product DS 문제 정의 | 단순 demand forecast가 아니라 재배치, 부족 위험, 포화 위험, 배포 보류 기준까지 연결 |
| Time-aware ML discipline | random split 대신 시간순 split, bootstrap CI, conformal coverage, segment audit 사용 |
| ML-to-ops translation | 예측값을 uncertainty-aware rebalancing priority와 reviewer-readable gate로 변환 |
| Real-world adapter design | 미국 benchmark와 서울 따릉이 실시간 대여정보를 공통 inventory contract로 정규화 |
| Responsible deployment | live snapshot 검증이 충분하기 전 public deploy와 성과 claim을 `NO_GO`로 차단 |
| Downstream product readiness | Stage 2 agentic eval과 Stage 3 Control Tower가 읽을 수 있는 공개 안전 산출물 생성 |

## Current Evidence

최신 로컬 산출물 기준: 2026-07-07 KST.

| 항목 | 값 | 의미 |
|---|---:|---|
| UCI demand rows | 17,379 | 시간대별 수요 예측 기준 데이터 |
| Best model | `gradient_boosting` | baseline/Ridge 대비 holdout 성능 우수 |
| Test MAE / WAPE / R2 | 35.95 / 15.36% / 0.933 | 수요 규모 대비 예측 오차와 설명력 |
| Bootstrap MAE 95% CI | [34.31, 37.61] | 단일 점수 우연성을 줄인 안정성 확인 |
| Split-conformal 90% coverage | 92.3% | 운영 buffer로 쓸 예측구간 보정 |
| Station model frame | 35 stations, 25,200 station-hour rows | 집계 수요를 station 단위 판단으로 확장 |
| Citi Bike live inventory monitor | 2,412 stations, 191 snapshots | 2주 prospective validation을 위해 hourly snapshot 축적 중, minimum gate까지 77개 부족 |
| Seoul Ddareungi latest snapshot | 2,733 stations, 103 snapshots | 서울 열린데이터광장 실시간 대여정보 adapter 동작 |
| Seoul next-snapshot validation | 103 / 24 snapshots, `READY` | 101 evaluated snapshots, 276,000 label rows, global Precision@50 0.9976 |
| Seoul balanced action validation | send_bikes 2,525 / remove_bikes 2,525 recommendations | balanced Precision@50 0.9552, send_bikes precision 0.9121, remove_bikes precision 0.9984 |
| Seoul priority output | top 50 candidates | 지도/API/Control Tower에서 읽을 재배치 후보 surface |
| Public deploy decision | `NO_GO` | 실패가 아니라 검증 전 공개 차단 guardrail |
| CI | GitHub Actions + pytest | pipeline, station, Seoul adapter, service test 자동 검증 |

`NO_GO`는 의도한 안전장치입니다. live inventory는 현재 상태 데이터이므로, 충분한 snapshot이 쌓이기 전까지 "검증된 운영 성과"로 주장하지 않습니다.

## Product Surfaces

| Surface | 설명 | 주요 산출물 |
|---|---|---|
| System demand forecasting | 시간대별 수요 예측, uncertainty, segment audit | `reports/run_summary.json`, `reports/model_metrics.csv` |
| Rebalancing optimization | 예측 수요와 fleet budget 제약으로 후보 배정 | `reports/rebalancing_optimization.csv` |
| Station-level extension | trip, GBFS metadata/status, weather join 기반 station risk | `station_level/reports/station_run_summary.json` |
| Snapshot readiness | 2주 hourly snapshot coverage와 prospective label 생성 | `station_level/reports/station_snapshot_readiness.json` |
| Seoul Ddareungi adapter | 실시간 대여소 상태, 좌표, 거치율, 지도 point 정규화 | `seoul_ddareungi/reports/latest_inventory_snapshot_summary.json` |
| Seoul priority and validation | 대여 불가/반납 포화 우선순위와 next-snapshot rule check | `seoul_ddareungi/reports/rebalancing_priority.csv`, `validation_summary.json` |
| Local dashboard/API | Stage 3가 소비할 public-safe summary payload | `scripts/run_station_dashboard.sh` |

## Demo Evidence

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
- 서울 따릉이 next-snapshot validation은 2026-07-07 KST 기준 `READY`입니다. Global top-K metric은 `remove_bikes` 후보 중심이고, balanced action metric은 `send_bikes`와 `remove_bikes`를 분리해 보조 근거로 사용합니다. 현장 운영 성과 claim은 별도 impact simulator 전까지 보류합니다.
- API key, raw private credential, `.env` 값은 Git, report, screenshot에 남기지 않습니다.
- 대용량 원천 데이터와 생성 산출물은 `OUTPUT_ROOT` 아래에 두고 Git에는 넣지 않습니다.
- Stage 2/3 downstream system은 이 repo의 `NO_GO`, `NOT_READY`, blocker를 유지해야 합니다.
