# 따릉이 대여 수요 회복력 예측

서울시 공공자전거 대여 수요를 시간 단위로 예측한다. 목표는 급변 구간에서의 수요 복원력을 측정해 운영 판단에 바로 쓸 수 있는 근거를 남기는 것이다.

## 프로젝트 개요

- 출처: UCI Bike Sharing 공개 데이터셋
- 문제: 시간대별 대여 수요 예측
- 핵심 범위: 시간 인식 분할, 피처 엔지니어링, 모델 비교, 오차 감사, 예측 신뢰구간, 운영 의사결정 연동

## 왜 이 작업을 했는가

운영자가 단기 예측 수치를 받는 것만으로는 부족하다는 판단이 있었기 때문입니다.

- 기준선 대비 성능 비교 지표를 남긴다.
- 구간별 오차 특성을 확인해 과도한 기대를 줄인다.
- 제약 조건(시간대, 차량 가용량)이 있는 운영 제안까지 이어지도록 한다.

## 실행 방법

```bash
cd /workspace/prj/data-scientist-career/bike-share-demand-resilience
scripts/run_all.sh
```

테스트만 실행하려면:

```bash
python3 tests/test_pipeline.py
```

## 산출물 경로

- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/models`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports`
- `/DATA/HJ/prj/data-scientist-career/reports`

## 방법론

- 시간 인식 분할: 시점 누수 방지 목적
- 피처: 달력, 계절성, 날씨 지표, 1/24/168시간 lag, 이동평균, 상호작용 항목
- 기준선: 시간별 중앙값 프로파일, Ridge 회귀
- 본선: Gradient Boosting Regressor
- 검증: Holdout MAE, WAPE/sMAPE/MAPE, 시계열 교차검증
- 불확실성: MAE 부트스트랩 신뢰구간, Split-Conformal 신뢰구간
- 해석: 순열 중요도, 날씨 충격 민감도, 구간별 잔차
- 운영 연동: 수요 구간별 스테이징 타깃 + 차량 예산 제약 최적화

## 산출물

- 최종 보고서: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/final_report.md`
- 모델 카드: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/model_card.md`
- 실험 추적기: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/experiment_tracker.csv`
- Conformal 신뢰구간: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/conformal_prediction_intervals.csv`
- 재배치 최적화 결과: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/rebalancing_optimization.csv`
- 핵심 그림:
  - `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures/uncertainty_conformal_intervals.png`
  - `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures/optimization_rebalancing_allocation.png`
  - `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures/interpretation_permutation_importance.png`
