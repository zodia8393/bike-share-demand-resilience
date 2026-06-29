# 재현 가이드

## 환경

- Python: 3.10 이상
- 주요 패키지: `pandas`, `numpy`, `scikit-learn`, `matplotlib`, `seaborn`, `scipy`
- 실행 기준 OS: Linux
- 한글 그림 라벨: `/usr/share/fonts/truetype/nanum/NanumGothic.ttf`가 있으면 자동 등록

## 설치

```bash
cd /workspace/prj/data-scientist-career/bike-share-demand-resilience
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 전체 실행

```bash
scripts/run_all.sh
```

`scripts/run_all.sh`는 pipeline 실행 후 `pytest`를 실행합니다.

## pipeline 직접 실행

```bash
PYTHONPATH=src python3 -m bike_share_resilience.pipeline \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience \
  --report-dir /DATA/HJ/prj/data-scientist-career/reports
```

## 테스트

```bash
PYTHONPATH=src python3 -m pytest tests -q
python3 -m py_compile src/bike_share_resilience/pipeline.py tests/test_pipeline.py
```

## Station-Level 확장

실제 공개 데이터 run:

```bash
scripts/run_station_level.sh
```

CI/smoke용 synthetic run:

```bash
SYNTHETIC_FLAG=--synthetic TOP_STATIONS=10 OUTPUT_ROOT=/tmp/bike-share-station-smoke scripts/run_station_level.sh
```

live inventory snapshot:

```bash
python3 scripts/capture_station_status_snapshot.py \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience
```

station dashboard/API artifact check:

```bash
PYTHONPATH=src python3 -m bike_share_resilience.station_service \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience \
  --check
```

2주 snapshot readiness와 public deploy readiness 갱신:

```bash
scripts/run_station_snapshot_monitor.sh
```

readiness만 직접 확인:

```bash
PYTHONPATH=src python3 -m bike_share_resilience.station_snapshot_analysis \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience
PYTHONPATH=src python3 -m bike_share_resilience.station_prospective_validation \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience
PYTHONPATH=src python3 -m bike_share_resilience.station_readiness_notifications \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience \
  --phase ready-start \
  --dry-run
python3 scripts/check_public_deploy_readiness.py \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience \
  --report-only
```

local dashboard:

```bash
scripts/run_station_dashboard.sh
```

## 성공 시 생성되는 핵심 파일

| 파일 | 용도 |
|---|---|
| `reports/final_report.md` | 전체 분석 보고서 |
| `reports/model_card.md` | 모델 사용 범위, 지표, 한계 |
| `reports/data_source_and_contract.md` | 데이터 원천과 계약 |
| `reports/model_metrics.csv` | 모델별 holdout 지표 |
| `reports/time_series_cv_metrics.csv` | 시계열 CV 결과 |
| `reports/segment_residual_audit.csv` | 구간별 오차 감사 |
| `reports/conformal_prediction_intervals.csv` | test 예측구간 |
| `reports/conformal_segment_coverage.csv` | 구간별 coverage |
| `reports/rebalancing_optimization.csv` | 운영 최적화 데모 |
| `station_level/reports/station_level_report.md` | station-hour 복합 데이터 확장 보고서 |
| `station_level/reports/station_rebalancing_priority.csv` | station별 운영 우선순위 |
| `station_level/data/processed/station_inventory_snapshot.csv` | station-level run 시점 live inventory join |
| `station_level/data/processed/latest_inventory_snapshot.csv` | snapshot capture job의 최신 inventory |
| `station_level/reports/latest_inventory_snapshot_summary.json` | snapshot capture summary |
| `station_level/data/processed/station_inventory_history.csv` | hourly snapshot 누적 history |
| `station_level/data/processed/station_shortage_label_panel.csv` | next-snapshot shortage prospective label panel |
| `station_level/reports/station_snapshot_readiness.json` | 2주 snapshot readiness gate |
| `station_level/reports/station_prospective_validation.json` | true shortage prospective validation status |
| `station_level/reports/station_prospective_validation_metrics.csv` | readiness 이후 baseline/model prospective metrics |
| `station_level/reports/station_public_deploy_readiness.json` | public deploy readiness decision |
| `station_level/reports/station_readiness_notification_state.json` | READY 전환과 validation 결과 Telegram 중복 발송 방지 state |

## 재현 확인 기준

다음 조건을 만족하면 기본 재현은 성공으로 봅니다.

- `pytest`가 통과합니다.
- `model_metrics.csv`에 세 모델의 valid/test 결과가 모두 존재합니다.
- `final_report.md`, `model_card.md`, `data_source_and_contract.md`가 한글로 생성됩니다.
- station-level 확장은 `station_quality_gate_checks.csv`가 모두 `True`이고 `station_run_summary.json`의 `quality_gate_passed`가 `true`입니다.
- `station_service --check`가 `ok: true`를 반환하고 inventory snapshot row가 1개 이상입니다.
- `station_snapshot_readiness.json`이 생성되고, 2주 coverage 전에는 `ready_for_prospective_validation=false`를 명확히 반환합니다.
- `station_prospective_validation.json`이 생성되고, 2주 coverage 전에는 `validation_status=NOT_READY`를 명확히 반환합니다.
- `station_public_deploy_readiness.json`이 생성되고, 배포 전 조건 미충족 시 `decision=NO_GO`를 반환합니다.
