# 포트폴리오 리뷰 메모

## 채용자가 먼저 볼 메시지

이 repo는 예측 모델 하나를 만든 결과물이 아니라, 공공자전거 수요 예측 문제를 운영 의사결정 문제로 재정의한 프로젝트입니다. 핵심은 시간순 검증, 불확실성 보정, 구간별 실패 감사, 제약 최적화 연결입니다.

## 강점

- 시간순 split과 shift된 lag/rolling feature로 시계열 누수 위험을 관리했습니다.
- baseline, 선형 모델, 비선형 모델을 같은 holdout 조건에서 비교했습니다.
- MAE/RMSE/R2만이 아니라 WAPE, sMAPE, bootstrap CI, conformal coverage를 함께 제시했습니다.
- 평균 성능 뒤에 숨는 출퇴근·악천후·주말 구간 실패를 별도 표로 남겼습니다.
- 예측값을 `rebalancing_optimization.csv`로 연결해 운영 적용 가능성을 검토했습니다.
- 데이터·모델·보고서를 Git 밖 `/DATA/HJ/...`에 생성해 공개 repo를 경량으로 유지했습니다.

## 면접 예상 질문과 답변 방향

| 질문 | 답변 방향 |
|---|---|
| 왜 랜덤 분할을 쓰지 않았는가? | 실제 예측은 미래 구간에 적용되므로 시간순 분할이 누수 위험을 줄입니다. |
| 왜 MAPE만 보지 않았는가? | 야간 저수요 구간에서 MAPE가 과대해질 수 있어 WAPE/sMAPE/MAE를 함께 봤습니다. |
| conformal interval을 왜 넣었는가? | 운영 행동은 point forecast보다 불확실성 폭이 중요하므로 자동 행동 억제 기준으로 쓸 수 있습니다. |
| weather shock은 인과 분석인가? | 아닙니다. 관측 feature support 안에서의 모델 기반 민감도 분석으로 제한했습니다. |
| 실제 서비스와 무엇이 다른가? | station-level 위치, dock capacity, 이벤트, 장애, 실시간 날씨 API가 필요합니다. |

## 보완하면 좋은 다음 작업

1. 서울시 따릉이 station-level 대여/반납 데이터로 공간 단위 예측 확장
2. Prophet/LightGBM/CatBoost 등 추가 모델을 같은 protocol로 비교
3. SHAP 또는 partial dependence로 feature effect 해석 강화
4. MLflow 또는 lightweight registry로 실험 versioning 강화
5. GitHub Actions로 `pytest`와 smoke run 자동화

## 문서 마감 점검

- AI 텍스트 티 제거 체크: 예
- 실제 수행 근거(파일/명령/지표) 기재 여부: 예
- 문서가 추정이 아니라 관찰·측정 기반인지: 예
