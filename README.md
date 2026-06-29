# 따릉이 수요 회복력 예측 연구

[![ci](https://github.com/zodia8393/bike-share-demand-resilience/actions/workflows/ci.yml/badge.svg)](https://github.com/zodia8393/bike-share-demand-resilience/actions/workflows/ci.yml)

시간대별 공공자전거 수요를 예측하고, 출퇴근 피크·악천후·주말 수요 구간에서 모델이 얼마나 안정적으로 작동하는지 검증한 연구형 데이터 사이언스 포트폴리오입니다. 단순 예측 점수보다 운영 의사결정에 필요한 기준선 비교, 시간순 검증, 예측구간, 구간별 오차 감사, 제약 기반 재배치 데모를 한 pipeline으로 묶었습니다.

## 핵심 결과

최근 재현 실행 기준:

| 항목 | 값 |
|---|---:|
| 데이터 | UCI Bike Sharing Dataset, 17,379행 |
| 선택 모델 | `gradient_boosting` |
| 테스트 MAE | 35.95건 |
| 테스트 WAPE | 15.36% |
| 테스트 R2 | 0.933 |
| Bootstrap MAE 95% CI | [34.31, 37.61] |
| Split-conformal 90% coverage | 92.3% |
| Station-level 확장 | 35개 station, trip+GBFS+weather+live inventory 결합, quality gate PASS |
| Snapshot readiness | 3 / 336 hourly snapshots, 2026-07-13 이후 2주 gate 재평가 |
| Public deploy decision | `NO_GO` until 2-week prospective validation readiness |
| CI | GitHub Actions PASS, 14 tests |

## 핵심 인사이트

- 랜덤 분할은 이 문제에서 성능을 과대평가할 가능성이 큽니다. 그래서 모든 모델 비교를 시간순 holdout으로 고정하고, lag와 rolling feature도 과거 시점만 보도록 설계했습니다.
- 시스템 단위 수요는 `gradient_boosting`이 가장 안정적이었습니다. 다만 출퇴근 피크는 전체 평균보다 오차가 커서, 운영 관점에서는 단일 평균 성능보다 peak risk segment 관리가 더 중요합니다.
- 악천후 시나리오에서는 관측 조건 대비 평균 예측 수요가 약 17% 낮아졌습니다. 날씨 변수는 단순 설명 변수가 아니라 배차·재배치 보수성을 조정하는 운영 신호로 해석할 수 있습니다.
- `lag_1`, `hr`, `is_commute_peak`, `lag_24`, `lag_168`이 테스트 구간 순열 중요도 상위 feature였습니다. 단기 관성, 시간대 주기성, 출퇴근 패턴이 수요 회복력의 핵심 축입니다.
- Split-conformal coverage 92.3%는 point forecast를 그대로 믿지 않고, 예측 반경을 재배치 staging target에 반영할 수 있음을 보여줍니다.
- Station-level 확장에서는 35개 station, 25,200개 station-hour panel, 97.1% GBFS join rate를 확보했습니다. 예측 프로젝트를 단순 점수 경쟁이 아니라 station capacity, live inventory, weather를 결합한 운영 의사결정 문제로 확장했습니다.
- Station-level 모델 개선폭은 baseline MAE 1.025에서 best MAE 1.006으로 크지 않습니다. 이 프로젝트의 가치는 과장된 metric lift보다 shortage risk ranking, human review queue, public deploy gate까지 포함한 production-readiness 설계에 있습니다.
- live inventory는 현재 상태 snapshot이지 과거 shortage label이 아닙니다. 그래서 현재 readiness 3/336 snapshots 단계에서는 public deployment를 `NO_GO`로 막고, 2주 prospective validation 이후에만 외부 공개를 재평가합니다.

## 대표 시각화

| 수요 패턴 | 예측 불확실성 | 재배치 의사결정 |
|---|---|---|
| ![요일과 시간대별 평균 수요](docs/assets/eda_weekday_hour_heatmap.png) | ![Split-conformal 예측구간](docs/assets/uncertainty_conformal_intervals.png) | ![제약 기반 재배치 배정](docs/assets/optimization_rebalancing_allocation.png) |

## 연구 질문

1. 시간순 분할을 보존했을 때 공공자전거 시간대별 수요를 어느 수준까지 예측할 수 있는가?
2. 전체 평균 성능이 아니라 출퇴근·주말·악천후 구간에서 어떤 실패 패턴이 나타나는가?
3. point forecast를 운영자가 검토 가능한 불확실성 구간과 재배치 target으로 변환할 수 있는가?
4. station-level 수요는 station capacity와 weather를 결합했을 때 운영 우선순위로 변환 가능한가?
5. live station_status snapshot이 2주 이상 축적되면 true shortage label 기반 prospective validation으로 확장 가능한가?

## 방법론

| 단계 | 설계 |
|---|---|
| 데이터 계약 | UCI 원천 zip 다운로드, raw CSV 보존, source metadata와 data dictionary 생성 |
| 피처 엔지니어링 | 달력, 시간대, 출퇴근 window, 악천후 flag, `temp_x_hum`, 1/24/168시간 lag, shift된 rolling mean |
| 분할 | 시간순 train/valid/test 분할. 랜덤 분할 금지 |
| 기준선 | 근무일 여부와 시간대별 중앙값 profile |
| 모델 | Ridge regression, Gradient Boosting Regressor |
| 검증 | holdout metrics, `TimeSeriesSplit`, bootstrap MAE CI, split-conformal coverage |
| 해석 | residual segment audit, permutation importance, weather shock scenario |
| 의사결정 | conformal radius를 반영한 demand bucket staging target과 linear programming allocation |
| Station-level 확장 | Jersey City Citi Bike trip history, GBFS station metadata/status, Open-Meteo hourly weather를 station-hour grain으로 결합 |
| Prospective 운영화 | hourly station_status snapshot monitor, next-snapshot shortage label panel, public deploy readiness gate |

## 방법론 선택 의도

이 프로젝트의 방법 선택 기준은 "점수가 높은 모델"보다 "시간이 지나도 설명 가능하고 운영에 연결되는 예측 시스템"입니다. 각 방법은 아래 위험을 줄이기 위해 사용했습니다.

| 선택 | 사용 의도 | 피하려는 실패 | reviewer에게 보여주는 역량 |
|---|---|---|---|
| 시간순 train/valid/test split | 실제 배포 상황처럼 과거로 미래를 예측하게 만들기 | 랜덤 split으로 미래 정보가 섞여 성능이 과대평가되는 문제 | leakage control, time-series validation |
| `historical_profile_median` baseline | 복잡한 모델이 단순 계절·시간대 규칙보다 실제로 나은지 검증 | 모델을 만들었지만 운영 기준선보다 낫지 않은 상황 | baseline-first modeling, honest benchmarking |
| Ridge + Gradient Boosting 비교 | 선형 기준과 비선형 모델을 같이 두고 성능·해석성 tradeoff를 확인 | 단일 모델만 제시해 선택 근거가 약해지는 문제 | model selection rationale, tradeoff thinking |
| lag/rolling feature를 shift 후 생성 | 수요의 단기 관성과 주기성을 반영하되 현재/미래 정보를 보지 않게 제한 | rolling 계산에서 target leakage가 발생하는 문제 | feature engineering discipline |
| WAPE, sMAPE, MAE, R2 병행 | 수요량 scale과 0 근처 값에 덜 취약한 성능 해석 제공 | MAPE 하나로 운영 오차를 오해하는 문제 | metric literacy, business-aware evaluation |
| Bootstrap MAE CI | 단일 test score가 우연인지 불확실성을 함께 보고 | "MAE 35.95"만 보고 성능 안정성을 과신하는 문제 | statistical uncertainty communication |
| Split-conformal interval | point forecast를 운영 buffer와 risk band로 전환 | 예측값 하나만 보고 재배치 결정을 과감하게 내리는 문제 | uncertainty-aware decisioning |
| residual segment audit | 출퇴근·주말·악천후처럼 실패 가능성이 큰 구간을 별도 점검 | 평균 성능은 좋아 보이지만 중요한 구간에서 실패하는 문제 | error analysis, risk segmentation |
| weather shock scenario | 날씨가 수요와 운영 보수성에 미치는 방향을 stress test | 상관 feature를 넣고도 실제 의사결정 의미를 설명하지 못하는 문제 | scenario analysis, operational interpretation |
| linear programming rebalancing demo | 예측과 불확실성을 fleet budget 제약 안의 staging target으로 연결 | 예측 결과가 dashboard 숫자에서 끝나는 문제 | optimization, decision-system design |
| station-level multi-source join | system-level 집계 한계를 station capacity, inventory, weather 결합으로 보완 | 단일 공개 데이터셋만 쓴 toy forecast로 보이는 문제 | data integration, production data modeling |
| 2주 prospective snapshot gate | live inventory를 실제 shortage label 검증으로 확장하기 전까지 공개 배포를 보류 | 현재 snapshot을 과거 정답처럼 과장하는 문제 | deployment governance, scientific restraint |

## 현재 운영 상태

| 항목 | 상태 |
|---|---|
| Source repo | `main` synced with `origin/main` |
| Latest CI | PASS |
| Station snapshot monitor | 매시 15분 cron 등록 |
| Snapshot readiness | `ready_for_prospective_validation=false`, 3 snapshots, 265 snapshots remaining |
| Earliest 2-week readiness | `2026-07-13T14:04:57+09:00` |
| Public deployment | `NO_GO`; local dashboard/API만 사용 |
| Local dashboard | `http://127.0.0.1:8765` via `scripts/run_station_dashboard.sh` |

## Repo 구조

```text
.
├── README.md
├── docs/
│   ├── data_contract.md
│   ├── modeling_protocol.md
│   ├── portfolio_review.md
│   ├── prospective_shortage_validation.md
│   ├── public_deployment_decision.md
│   ├── reproducibility.md
│   └── station_level_extension.md
├── scripts/
│   ├── capture_station_status_snapshot.py
│   ├── check_public_deploy_readiness.py
│   ├── run_all.sh
│   ├── run_station_dashboard.sh
│   ├── run_station_snapshot_monitor.sh
│   └── run_station_level.sh
├── src/bike_share_resilience/
│   ├── __init__.py
│   ├── pipeline.py
│   ├── station_pipeline.py
│   ├── station_snapshot_analysis.py
│   └── station_service.py
├── tests/
│   ├── conftest.py
│   ├── test_pipeline.py
│   ├── test_station_pipeline.py
│   ├── test_station_service.py
│   └── test_station_snapshot_analysis.py
├── pyproject.toml
└── requirements.txt
```

대용량 데이터, 모델 pickle, 그림, 보고서 산출물은 Git에 넣지 않습니다. 산출물 위치는 `OUTPUT_ROOT`로 지정하며, 아래에는 로컬 절대경로 대신 재생성 명령과 `OUTPUT_ROOT` 기준 상대 위치를 문서화합니다.

## 실행 방법

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

아래 산출물 관련 명령은 같은 shell에서 `OUTPUT_ROOT`를 지정한 상태를 기준으로 합니다.

테스트만 실행:

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

pipeline 직접 실행:

```bash
export OUTPUT_ROOT=/tmp/bike-share-demand-resilience
export REPORT_DIR=/tmp/bike-share-demand-resilience/portfolio_reports
PYTHONPATH=src python3 -m bike_share_resilience.pipeline \
  --output-root "$OUTPUT_ROOT" \
  --report-dir "$REPORT_DIR"
```

station-level 확장 실행:

```bash
OUTPUT_ROOT=/tmp/bike-share-demand-resilience scripts/run_station_level.sh
```

live inventory snapshot 캡처:

```bash
python3 scripts/capture_station_status_snapshot.py --output-root "$OUTPUT_ROOT"
```

station dashboard/API artifact check:

```bash
PYTHONPATH=src python3 -m bike_share_resilience.station_service --output-root "$OUTPUT_ROOT" --check
```

2주 snapshot readiness와 배포 전 gate 갱신:

```bash
OUTPUT_ROOT=/tmp/bike-share-demand-resilience scripts/run_station_snapshot_monitor.sh
```

public deploy readiness 확인:

```bash
python3 scripts/check_public_deploy_readiness.py --output-root "$OUTPUT_ROOT" --report-only
```

local dashboard 실행:

```bash
OUTPUT_ROOT=/tmp/bike-share-demand-resilience scripts/run_station_dashboard.sh
```

네트워크 없는 smoke 실행:

```bash
SYNTHETIC_FLAG=--synthetic TOP_STATIONS=10 OUTPUT_ROOT=/tmp/bike-share-station-smoke scripts/run_station_level.sh
```

## 산출물 확인 방법

이 repo는 reviewer가 GitHub에서 바로 판단할 수 있도록 핵심 프로토콜과 의사결정 문서는 `docs/`에 커밋하고, 대용량 실행 산출물은 `OUTPUT_ROOT` 아래에 재생성합니다. 절대경로 대신 아래 artifact contract를 기준으로 확인합니다.

이 방식을 쓴 의도는 세 가지입니다.

- GitHub에는 검토에 필요한 설계·프로토콜·의사결정 문서만 남겨 repo를 가볍게 유지합니다.
- raw data, model pickle, generated report는 실행 환경마다 달라질 수 있으므로 `OUTPUT_ROOT` 아래에 재생성하게 해 재현성을 명확히 합니다.
- 로컬 절대경로를 README에 노출하지 않아 외부 reviewer가 clone 후 같은 명령으로 산출물을 만들 수 있게 합니다.

| 확인하려는 내용 | 생성 명령 | `OUTPUT_ROOT` 기준 상대 위치 |
|---|---|---|
| 최종 보고서, 모델 카드, 데이터 계약 | `scripts/run_all.sh` | `reports/final_report.md`, `reports/model_card.md`, `reports/data_source_and_contract.md` |
| 모델 비교와 실험 추적 | `scripts/run_all.sh` | `reports/model_metrics.csv`, `reports/experiment_tracker.csv` |
| 불확실성·오차 감사 | `scripts/run_all.sh` | `reports/conformal_prediction_intervals.csv`, `reports/residual_segment_audit.csv`, `reports/bootstrap_mae_ci.csv` |
| 재배치 최적화 데모 | `scripts/run_all.sh` | `reports/rebalancing_optimization.csv` |
| 시각화 | `scripts/run_all.sh` | `figures/` |
| Station-level 보고서와 우선순위 | `scripts/run_station_level.sh` | `station_level/reports/station_level_report.md`, `station_level/reports/station_rebalancing_priority.csv` |
| Station inventory snapshot/history | `scripts/run_station_snapshot_monitor.sh` | `station_level/data/processed/station_inventory_snapshot.csv`, `station_level/data/processed/station_inventory_history.csv` |
| Prospective shortage label panel | `scripts/run_station_snapshot_monitor.sh` | `station_level/data/processed/station_shortage_label_panel.csv` |
| 2주 snapshot readiness | `scripts/run_station_snapshot_monitor.sh` | `station_level/reports/station_snapshot_readiness.json` |
| Public deploy gate | `scripts/check_public_deploy_readiness.py --report-only` | `station_level/reports/station_public_deploy_readiness.json` |

커밋된 문서로 먼저 검토하려면 [docs/modeling_protocol.md](docs/modeling_protocol.md), [docs/station_level_extension.md](docs/station_level_extension.md), [docs/prospective_shortage_validation.md](docs/prospective_shortage_validation.md), [docs/public_deployment_decision.md](docs/public_deployment_decision.md)를 보면 됩니다.

## 한계

- UCI 데이터는 시스템 집계 자료라 정류장 좌표, dock capacity, 장애·점검, 이벤트, 요금 정보를 포함하지 않습니다. 이를 보완하기 위해 별도 station-level extension에서 Citi Bike trip history, GBFS station metadata/status, Open-Meteo weather를 결합했습니다.
- 날씨 충격 분석은 인과 추정이 아니라 모델 기반 민감도 분석입니다.
- station-level extension은 live `station_status` snapshot을 결합하지만 2024년 1월 trip history와 시점이 다르므로, 현재는 true historical shortage label이 아니라 prospective snapshot 기반 human review queue로 해석해야 합니다. 이 리스크는 hourly snapshot 2주 축적 자동화와 readiness gate로 관리합니다.
- public deployment는 `docs/public_deployment_decision.md`의 readiness gate가 `GO`가 되기 전까지 보류합니다.
- `station_public_deploy_readiness.json`이 `NO_GO`인 동안은 외부 배포 대신 local API/dashboard만 사용합니다.

## 면접에서 설명할 포인트

- 랜덤 split 대신 시간순 split을 쓴 이유와 누수 차단 방식
- baseline을 두고 nonlinear model을 비교한 이유
- MAPE만 보지 않고 WAPE/sMAPE/MAE CI를 함께 보고한 이유
- conformal interval을 운영 의사결정의 보수성 기준으로 연결한 방식
- 공개 데이터의 한계를 인정하고 station-level 확장 설계를 분리한 점
- 실시간 inventory를 바로 production claim으로 과장하지 않고, 2주 prospective validation gate와 public deployment `NO_GO` 정책으로 리스크를 통제한 점
