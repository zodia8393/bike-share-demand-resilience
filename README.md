# 공공자전거 수요 회복력 예측 연구

[![ci](https://github.com/zodia8393/bike-share-demand-resilience/actions/workflows/ci.yml/badge.svg)](https://github.com/zodia8393/bike-share-demand-resilience/actions/workflows/ci.yml)

공공자전거 시간대별 수요 예측을 재배치 판단까지 연결한 프로젝트입니다. 핵심은 모델 점수뿐 아니라, 실패 구간·예측 불확실성·배포 보류 기준까지 함께 만든 것입니다.

## 결론

한 줄로 말하면, **시간대별 수요를 WAPE 15.36%, R2 0.933 수준으로 예측하고, 그 예측을 피크/악천후 리스크와 재배치 우선순위로 바꾼 프로젝트**입니다.

- 예측 모델: `gradient_boosting`, MAE 35.95건, WAPE 15.36%, R2 0.933.
- 리스크 분석: 출퇴근 피크와 악천후에서 평균보다 더 흔들리는 구간을 확인.
- 운영 연결: 예측값에 불확실성을 붙여 재배치 우선순위로 변환.
- 데이터 확장: 35개 station의 trip, GBFS, weather, live inventory를 결합.
- 배포 판단: live snapshot이 아직 3/336개라 외부 공개는 `NO_GO`.

## 무엇을 만들었나

| 구성 | 한 줄 설명 |
|---|---|
| 수요 예측 파이프라인 | 시간순 split으로 시간대별 수요를 예측하고 baseline, Ridge, Gradient Boosting을 비교 |
| 실패 구간 분석 | 출퇴근, 주말, 악천후 구간에서 모델이 어디서 흔들리는지 확인 |
| 예측 불확실성 | 단일 예측값에 예측구간을 붙여 운영 buffer로 사용 |
| 재배치 우선순위 | 예측 수요와 fleet budget 제약을 이용해 재배치 후보를 산출 |
| Station-level 확장 | trip history, GBFS station metadata/status, Open-Meteo weather를 station-hour 단위로 결합 |
| 배포 보류 기준 | live inventory snapshot이 충분히 쌓이기 전까지 외부 공개를 막는 readiness check |

## 핵심 수치

| 항목 | 값 | 의미 |
|---|---:|---|
| 시스템 수요 데이터 | UCI Bike Sharing Dataset, 17,379행 | 시간대별 수요 예측의 기준 데이터 |
| 선택 모델 | `gradient_boosting` | baseline/Ridge보다 holdout 성능이 가장 안정적 |
| 테스트 MAE / WAPE / R2 | 35.95건 / 15.36% / 0.933 | 평균 오차와 전체 패턴 설명력이 모두 양호 |
| Bootstrap MAE 95% CI | [34.31, 37.61] | MAE가 우연한 단일 점수에 그치지 않음 |
| Split-conformal 90% coverage | 92.3% | 예측구간이 목표 coverage를 충족 |
| Station-level 데이터 | 35개 station, 25,200 station-hour rows | 집계 예측을 station 단위 운영 판단으로 확장 |
| GBFS join rate | 97.1% | station metadata/status 결합 품질이 충분 |
| Station-level best MAE | 1.006 | 점수 개선보다 부족 위험 순위 해석이 핵심 |
| Snapshot readiness | 3 / 336 hourly snapshots | 2주 검증 데이터가 아직 부족 |
| Public deploy decision | `NO_GO` | 검증 전 외부 공개를 보류 |
| CI | GitHub Actions PASS, 14 tests | 재현 실행과 테스트가 자동 검증됨 |

## 얻은 인사이트

- 시간순 검증이 핵심입니다. 랜덤 split을 쓰면 미래 패턴이 섞여 실제 배포 성능보다 좋아 보일 수 있습니다.
- 평균 성능만으로는 부족합니다. 출퇴근 피크와 악천후 구간은 별도 리스크로 관리해야 합니다.
- 악천후 시나리오에서 평균 예측 수요가 약 17% 낮아졌습니다. 날씨는 운영 보수성을 조정하는 신호로 쓸 수 있습니다.
- Station-level 모델의 점수 개선폭은 크지 않았습니다. 대신 station별 부족 위험 순위와 배포 보류 기준을 만든 것이 더 중요한 산출물입니다.
- live inventory는 현재 상태 데이터이지 과거 정답 label이 아닙니다. 그래서 2주 snapshot이 쌓이기 전까지는 공개 배포를 막았습니다.

## 방법 선택 이유

| 선택 | 이유 |
|---|---|
| 시간순 검증 | 랜덤 split은 미래 정보가 섞일 수 있어 실제 운영 성능을 과대평가합니다. |
| Baseline 비교 | 복잡한 모델이 단순 시간대 패턴보다 정말 나은지 먼저 확인했습니다. |
| 여러 metric | MAPE 하나로는 수요량 scale과 0 근처 값을 안정적으로 설명하기 어렵습니다. |
| 예측구간 | 예측값 하나보다 "얼마나 여유를 둬야 하는가"가 운영에 더 중요합니다. |
| 구간별 오차 분석 | 전체 평균에 가려지는 출퇴근·주말·악천후 실패를 찾기 위해 사용했습니다. |
| Station-level 결합 | 집계 수요 예측을 실제 station capacity와 inventory 판단으로 확장했습니다. |
| 배포 보류 기준 | 검증되지 않은 live snapshot을 production 성과처럼 과장하지 않기 위해 사용했습니다. |

## 대표 시각화

| 수요 패턴 | 예측 불확실성 | 재배치 의사결정 |
|---|---|---|
| ![요일과 시간대별 평균 수요](docs/assets/eda_weekday_hour_heatmap.png) | ![Split-conformal 예측구간](docs/assets/uncertainty_conformal_intervals.png) | ![제약 기반 재배치 배정](docs/assets/optimization_rebalancing_allocation.png) |

## 현재 상태

- CI: PASS, 14 tests.
- Station snapshot monitor: 매시 실행.
- Snapshot readiness: 3/336 snapshots, earliest ready at `2026-07-13T14:04:57+09:00`.
- Public deployment: `NO_GO`. 현재는 local dashboard/API만 사용.

## Repo 구조

```text
.
├── src/bike_share_resilience/   # forecasting, station pipeline, dashboard service
├── scripts/                     # 재현 실행, snapshot, deploy readiness check
├── tests/                       # pipeline, station, service tests
├── docs/                        # protocol, station extension, deployment decision
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

테스트:

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

Station-level 확장과 dashboard:

```bash
OUTPUT_ROOT=/tmp/bike-share-demand-resilience scripts/run_station_level.sh
OUTPUT_ROOT=/tmp/bike-share-demand-resilience scripts/run_station_snapshot_monitor.sh
OUTPUT_ROOT=/tmp/bike-share-demand-resilience scripts/run_station_dashboard.sh
```

네트워크 없는 smoke 실행:

```bash
SYNTHETIC_FLAG=--synthetic TOP_STATIONS=10 OUTPUT_ROOT=/tmp/bike-share-station-smoke scripts/run_station_level.sh
```

## 산출물 확인 방법

핵심 문서는 `docs/`에 커밋하고, 대용량 데이터·모델·생성 report는 `OUTPUT_ROOT` 아래에 재생성합니다. GitHub README에는 로컬 절대경로 대신 재현 명령과 상대 위치만 남겼습니다.

| 보고 싶은 것 | 명령 | 위치 |
|---|---|---|
| 시스템 예측 결과 | `scripts/run_all.sh` | `reports/`, `figures/` |
| Station-level 결과 | `scripts/run_station_level.sh` | `station_level/reports/` |
| Inventory snapshot과 readiness | `scripts/run_station_snapshot_monitor.sh` | `station_level/data/processed/`, `station_level/reports/` |
| Dashboard/API 상태 | `scripts/run_station_dashboard.sh` 또는 `station_service --check` | local API/dashboard |

커밋된 문서로 먼저 검토하려면 [docs/modeling_protocol.md](docs/modeling_protocol.md), [docs/station_level_extension.md](docs/station_level_extension.md), [docs/prospective_shortage_validation.md](docs/prospective_shortage_validation.md), [docs/public_deployment_decision.md](docs/public_deployment_decision.md)를 보면 됩니다.

## 한계

- UCI 데이터는 시스템 집계 자료라 station capacity와 live inventory를 포함하지 않습니다. 이 한계는 station-level extension으로 보완했습니다.
- 날씨 충격 분석은 인과 추정이 아니라 모델 기반 민감도 분석입니다.
- live `station_status`는 아직 true historical shortage label이 아닙니다. 2주 snapshot validation이 끝날 때까지 public deployment는 `NO_GO`입니다.
