# 모델링 프로토콜

## 목표

시간대별 공공자전거 수요를 예측하되, 전체 평균 성능만 보고하지 않고 운영 충격 구간의 신뢰성과 의사결정 연결 가능성을 검증합니다.

## 분할 원칙

- 시계열 문제이므로 랜덤 분할을 사용하지 않습니다.
- `chronological_split`은 고유 날짜 기준으로 train 70%, valid 15%, test 15%를 시간순으로 나눕니다.
- 모델 선택은 valid 비교를 거친 뒤 test holdout에서 최종 성능을 기록합니다.
- lag와 rolling feature는 split 이전에 만들지만 모든 rolling 값은 `shift(1)` 이후 계산해 미래 target 누수를 차단합니다.

## 기준선과 모델

| 모델 | 역할 |
|---|---|
| `historical_profile_median` | 근무일 여부와 시간대별 중앙값 baseline |
| `ridge_regression` | 선형 baseline, scaling 포함 |
| `gradient_boosting` | 비선형 상호작용과 날씨 민감도 반영 모델 |

## 평가 지표

- MAE: 운영자가 이해하기 쉬운 평균 절대 오차
- RMSE: 큰 오차에 민감한 보조 지표
- WAPE: 전체 수요 대비 절대 오차 비율
- sMAPE: 저수요 시간대의 비율 오차 해석 보완
- R2: 설명력 참고 지표
- Bootstrap MAE CI: holdout MAE의 표본 불확실성 확인
- Split-conformal coverage: 예측구간의 경험적 커버리지 확인

## 오류 감사

`segment_residual_audit.csv`는 다음 구간을 분리해 MAE, bias, p90 absolute error를 기록합니다.

- 전체
- 출퇴근 피크
- 비출퇴근
- 악천후
- 주말
- 야간

이 감사는 평균 성능이 좋아도 특정 운영 구간에서 모델이 불안정할 수 있다는 점을 확인하기 위한 절차입니다.

## 불확실성 보정

valid 구간 잔차를 calibration residual로 사용해 split-conformal 반경을 계산합니다. test 예측값에 대칭 구간을 붙이고, 전체 및 segment별 coverage를 계산합니다.

목표 coverage는 90%이며, 자동 검증 기준은 표본 변동을 고려해 0.88~0.96 범위를 통과 조건으로 둡니다.

## 운영 최적화 데모

`rebalancing_optimization.csv`는 수요 버킷별 forecast, conformal upper bound, target bikes, fleet budget, allocated bikes를 기록합니다. 공개 데이터에는 정류장 좌표와 dock capacity가 없으므로 실제 dispatch 정책이 아니라 예측-운영 연결 구조의 데모로 해석합니다.

## 확장 계획

1. station-level trip/dock data를 결합해 공간 단위 forecast로 확장
2. 이벤트·요금·장애·날씨 실측 API를 feature store로 분리
3. prospective validation과 drift monitoring 추가
4. conformal interval 폭을 운영 action threshold로 사용하는 정책 실험
