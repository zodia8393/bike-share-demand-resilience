# 주제 선정 기록

## 선정 주제

- 주제: 공공자전거 수요 회복력 예측과 운영 재배치 의사결정
- 대상 의사결정: 시간대별 수요 위험을 예측해 운영자가 재배치 target과 human review threshold를 정한다.
- 채용시장 신호: forecasting, uncertainty, operations optimization, reproducible ML pipeline, CI를 한 repo에서 보여준다.

## 후보 평가

| 후보 | 도메인 | 데이터 가능성 | 운영/제품 가치 | 연구 난이도 | 채용시장 신호 | 판단 |
|---|---|---|---|---|---|---|
| 공공자전거 수요 회복력 | urban mobility | UCI 공개 데이터 즉시 사용, station 확장 가능 | 재배치·shortage risk 의사결정 | 시간순 검증, conformal, optimization | DS/ML/Operations 모두 설명 가능 | 선택 |
| 택시 수요 이상징후 | mobility operations | 내부/공공 데이터 필요 | 배차·혼잡 대응 가치 높음 | 공간-시간 anomaly | data engineering 신호 강함 | 내부 공개성 이슈로 보류 |
| SNS 기반 지역 이벤트 수요 예측 | social intelligence | 공개 SNS/API 제약 큼 | leading indicator 가치 | privacy gate 난이도 높음 | AI product signal 강함 | 다음 후보 |
| 물류 지연 리스크 조기경보 | logistics | 공개 benchmark와 날씨 결합 가능 | SLA·dispatch 의사결정 | 불균형 classification | MLE/backend 확장 용이 | 다음 후보 |
| 전력 수요와 기상 리스크 | energy | 공개 load/weather 가능 | capacity planning | probabilistic forecast | applied scientist signal | 다음 후보 |

## 제외 기준

단일 CSV EDA, Titanic류 classification, 일반 집값/매출 예측, 단순 감성분석처럼 제품 의사결정과 검증 설계가 약한 주제는 제외했다.
