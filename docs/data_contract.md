# 데이터 계약

## 목적

이 문서는 pipeline이 기대하는 데이터 구조, 저장 위치, 원천 보존 정책을 정의합니다. 채용자가 repo를 실행했을 때 동일한 분석 단위와 target을 재현할 수 있게 하는 것이 목적입니다.

## 원천

- 데이터셋: UCI Machine Learning Repository Bike Sharing Dataset
- 다운로드 URL: `https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip`
- 사용 파일: `hour.csv`
- 분석 단위: 시스템 수준 1시간 1행
- Target: `cnt`, 시간대별 총 대여 건수

## 저장 정책

| 구분 | 위치 | Git 포함 여부 |
|---|---|---|
| raw zip | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data/raw/uci_bike_sharing_dataset.zip` | 제외 |
| raw CSV | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data/raw/hour.csv` | 제외 |
| processed feature | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data/processed/hourly_features.parquet` | 제외 |
| source metadata | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data/raw/source_metadata.json` | 제외 |
| data dictionary | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data/processed/data_dictionary.csv` | 제외 |

Git에는 재현 코드와 경량 문서만 포함합니다. 데이터와 모델 파일은 재생성 가능 산출물로 취급합니다.

## 필수 컬럼

| 컬럼 | 의미 |
|---|---|
| `dteday` | 날짜 |
| `hr` | 시간대 |
| `season`, `yr`, `mnth`, `weekday`, `workingday`, `holiday` | 달력/운영 calendar 변수 |
| `weathersit`, `temp`, `atemp`, `hum`, `windspeed` | 날씨 변수 |
| `casual`, `registered`, `cnt` | 대여 수요 변수 |

## 파생 피처 계약

- `lag_1`, `lag_24`, `lag_168`은 반드시 target의 과거 시점만 사용합니다.
- `rolling_24_mean`, `rolling_168_mean`은 `shift(1)` 이후 rolling을 계산합니다.
- `is_commute_peak`, `is_weekend`, `is_night`, `bad_weather`, `temp_x_hum`은 현재 시점에 관측 가능한 calendar/weather 정보에서 생성합니다.

## 품질 확인

pipeline은 실행 시 다음 파일을 생성해 원천 계약을 확인합니다.

- `source_metadata.json`: 원천 URL, fallback 사용 여부, 원본/실사용 컬럼 기록
- `data_dictionary.csv`: 컬럼명, dtype, 결측 수, 예시값, 설명 기록
- `quality_gate_checks.csv`: 데이터 행 수와 target 존재 조건 pass/fail 기록

## fallback 정책

네트워크 오류로 UCI zip을 받을 수 없을 때는 동일한 column contract를 가진 synthetic data를 생성합니다. 이 fallback은 실행 가능성을 보장하기 위한 장치이며, 결과 해석에는 `fallback_used` 값을 반드시 함께 표시합니다.
