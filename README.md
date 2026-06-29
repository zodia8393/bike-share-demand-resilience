# 공공자전거 수요 회복력 예측 연구

[![ci](https://github.com/zodia8393/bike-share-demand-resilience/actions/workflows/ci.yml/badge.svg)](https://github.com/zodia8393/bike-share-demand-resilience/actions/workflows/ci.yml)

공공자전거 시간대별 수요를 예측하고, 그 결과를 출퇴근 피크·악천후·재배치 우선순위 같은 운영 판단으로 연결한 end-to-end 데이터 프로젝트입니다.

## 결론

이 프로젝트는 "수요를 얼마나 맞히는가"에서 끝내지 않고 "예측을 어떻게 운영 의사결정으로 바꿀 것인가"까지 구현했습니다.

- 시스템 단위 수요 예측: `gradient_boosting`, MAE 35.95건, WAPE 15.36%, R2 0.933.
- 예측 불확실성: split-conformal 90% 구간 coverage 92.3%.
- 운영 리스크: 출퇴근 피크와 악천후에서 평균 성능보다 높은 실패 가능성을 확인.
- 의사결정 연결: 예측값과 불확실성을 재배치 staging target으로 변환.
- Station-level 확장: 35개 station, trip + GBFS + weather + live inventory 결합.
- 배포 판단: live snapshot이 아직 3/336개라 public deploy는 `NO_GO`. 2주 검증 전까지는 local dashboard/API만 사용.

## 무엇을 만들었나

| 구성 | 한 줄 설명 |
|---|---|
| Demand forecasting pipeline | 시간순 split으로 hourly demand를 예측하고 baseline, Ridge, Gradient Boosting을 비교 |
| Risk analysis | 출퇴근, 주말, 악천후 구간에서 모델이 어디서 흔들리는지 확인 |
| Uncertainty layer | point forecast에 conformal interval을 붙여 운영 buffer로 사용 |
| Rebalancing demo | 예측 수요와 fleet budget 제약을 이용해 재배치 우선순위를 산출 |
| Station-level extension | trip history, GBFS station metadata/status, Open-Meteo weather를 station-hour 단위로 결합 |
| Deploy gate | live inventory snapshot이 충분히 쌓이기 전까지 외부 공개를 막는 readiness check |

## 핵심 수치

| 항목 | 값 |
|---|---:|
| 시스템 수요 데이터 | UCI Bike Sharing Dataset, 17,379행 |
| 선택 모델 | `gradient_boosting` |
| 테스트 MAE / WAPE / R2 | 35.95건 / 15.36% / 0.933 |
| Bootstrap MAE 95% CI | [34.31, 37.61] |
| Split-conformal 90% coverage | 92.3% |
| Station-level 데이터 | 35개 station, 25,200 station-hour rows |
| GBFS join rate | 97.1% |
| Station-level best MAE | 1.006 |
| Snapshot readiness | 3 / 336 hourly snapshots |
| Public deploy decision | `NO_GO` |
| CI | GitHub Actions PASS, 14 tests |

## 얻은 인사이트

- 시간순 검증이 핵심입니다. 랜덤 split을 쓰면 미래 패턴이 섞여 실제 배포 성능보다 좋아 보일 수 있습니다.
- 평균 성능만으로는 부족합니다. 출퇴근 피크와 악천후 구간은 별도 리스크로 관리해야 합니다.
- 악천후 시나리오에서 평균 예측 수요가 약 17% 낮아졌습니다. 날씨는 운영 보수성을 조정하는 신호로 쓸 수 있습니다.
- Station-level 모델의 metric lift는 크지 않았습니다. 대신 station별 shortage risk ranking과 배포 gate를 만든 것이 더 중요한 산출물입니다.
- live inventory는 현재 상태 데이터이지 과거 정답 label이 아닙니다. 그래서 2주 snapshot이 쌓이기 전까지는 공개 배포를 막았습니다.

## 왜 이렇게 만들었나

| 선택 | 이유 |
|---|---|
| 시간순 split | 실제 운영은 과거 데이터로 미래를 예측하므로 leakage를 막기 위해 사용 |
| Baseline 비교 | 복잡한 모델이 단순 시간대 패턴보다 나은지 먼저 확인하기 위해 사용 |
| 여러 metric | MAPE 하나로는 수요량 scale과 0 근처 값을 안정적으로 설명하기 어려워 MAE, WAPE, sMAPE, R2를 함께 사용 |
| Conformal interval | 예측값 하나가 아니라 어느 정도 buffer가 필요한지 판단하기 위해 사용 |
| Segment audit | 전체 평균에 가려지는 출퇴근·주말·악천후 실패를 찾기 위해 사용 |
| Station-level join | 집계 수요 예측을 실제 station capacity와 inventory 판단으로 확장하기 위해 사용 |
| Public deploy gate | 검증되지 않은 live snapshot을 production 성과처럼 과장하지 않기 위해 사용 |

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
