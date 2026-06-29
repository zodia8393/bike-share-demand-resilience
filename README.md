# 따릉이 대여 수요 회복력 예측 프로젝트

서울시 따릉이 대여량의 시간대별 수요를 예측하고, 날씨 충격·계절성·휴일·출퇴근 피크와 같은 급변 상황에서의 복원력을 측정하는 포트폴리오형 데이터 과학 프로젝트입니다.

이 프로젝트는 UCI Bike Sharing 공개 데이터셋을 기반으로 시계열 누수 방지 분할, 피처 엔지니어링(달력/계절성/날씨 스트레스/라그/이동평균/상호작용), 모델 비교, 잔차 감사, 신뢰구간 산출, 운영 의사결정 레이어를 end-to-end로 구성했습니다.

## 과제 정의

따릉이 운영자는 짧은 시간대 예측 수요를 기반으로 재배치 자전거 배치 위치와 인력 운영 시점을 판단해야 합니다. 따라서 단순 예측값만 내는 프로젝트가 아니라,
- 기준선 모델 비교
- 시간 순서 유지 분할
- 구간별 오차 감사
- 운영팀이 바로 쓸 수 있는 해석 중심 권고
까지 포함해야 합니다.

## 실행 방법

```bash
cd /workspace/prj/data-scientist-career/bike-share-demand-resilience
scripts/run_all.sh
```

`pytest`가 설치되어 있지 않다면 아래로 실행하세요.

```bash
python3 tests/test_pipeline.py
```

## 산출물

모든 생성 결과물은 원본 저장소 외부에 저장됩니다.

- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/models`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports`
- `/DATA/HJ/prj/data-scientist-career/reports`

## 방법론

- 공개 데이터 수집 + 메타데이터 기반 소스 계약 관리
- 시간 인식을 고려한 train/validation/test 분할
- 달력 변수, 계절성, 날씨 스트레스, 1/24/168시간 lag, 이동평균, 상호작용 항목을 포함한 피처 엔지니어링
- 기준선: 시간별 중앙값 프로파일, Ridge 회귀
- 본선 모델: Gradient Boosting Regressor
- 검증: Holdout MAE 지표, WAPE/sMAPE/MAPE, 시계열 교차검증, MAE 부트스트랩 신뢰구간, Split-Conformal 예측 구간, 구간별 잔차 감사
- 해석: 순열 중요도, 날씨 충격 민감도, 구간 커버리지, 운영 권고
- 의사결정 레이어: 수요 구간별 스테이징 타깃 + 한정된 차량 예산 기반 제약 최적화 시연

## 포트폴리오 산출물

- 최종 보고서: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/final_report.md`
- 모델 카드: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/model_card.md`
- 실험 추적기: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/experiment_tracker.csv`
- Conformal 신뢰구간: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/conformal_prediction_intervals.csv`
- 재배치 최적화 결과: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/reports/rebalancing_optimization.csv`
- 핵심 그림:
  - `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures/uncertainty_conformal_intervals.png`
  - `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures/optimization_rebalancing_allocation.png`
  - `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/figures/interpretation_permutation_importance.png`

## 품질 게이트

최종 보고서에는 주말형 커리어 프로젝트 일정에서 요구되는 10개 카테고리 자동화 품질 점수표가 포함됩니다. 각 카테고리 점수가 모두 90점 이상일 때만 완료로 판단합니다.

## 앞으로의 프로젝트 문서화 규칙

새 프로젝트를 시작할 때 기본 문서를 모두 **한글**로 작성하고, 결과물(`README.md`, `final_report.md`, `model_card.md` 등)도 모두 한글로 정리합니다.
