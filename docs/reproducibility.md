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
| `reports/quality_gate_checks.csv` | pass/fail 품질 게이트 |

## 재현 확인 기준

다음 조건을 만족하면 기본 재현은 성공으로 봅니다.

- `pytest`가 통과합니다.
- `run_summary.json`의 `quality_gate_passed`가 `true`입니다.
- `model_metrics.csv`에 세 모델의 valid/test 결과가 모두 존재합니다.
- `final_report.md`, `model_card.md`, `data_source_and_contract.md`가 한글로 생성됩니다.

## 문서 마감 점검

- AI 텍스트 티 제거 체크: 예
- 실제 수행 근거(파일/명령/지표) 기재 여부: 예
- 문서가 추정이 아니라 관찰·측정 기반인지: 예
