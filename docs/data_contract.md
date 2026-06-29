# 데이터 계약

## 목적

이 문서는 pipeline이 기대하는 데이터 구조, 저장 위치, 원천 보존 정책을 정의합니다. 채용자가 repo를 실행했을 때 동일한 분석 단위와 target을 재현할 수 있게 하는 것이 목적입니다.

## 원천

- 데이터셋: UCI Machine Learning Repository Bike Sharing Dataset
- 다운로드 URL: `https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip`
- 라이선스/사용 조건: 공개 연구용 데이터셋이며 Fanaee-T and Gama (2013) 인용을 전제로 사용합니다. 상업 서비스 데이터나 내부 원천이 아니므로 공개 repo에는 원본 대신 재현 코드와 계약 문서만 둡니다.
- 사용 파일: `hour.csv`
- 분석 단위: 시스템 수준 1시간 1행
- Target: `cnt`, 시간대별 총 대여 건수

## Join 계약

현재 버전은 UCI `hour.csv` 단일 공개 원천에 calendar/weather 변수가 함께 포함된 시스템 수준 자료입니다. 별도 외부 join은 수행하지 않았고, 시간 key는 `datetime = dteday + hr`로 일반화했습니다. station, 사용자, trip ID, 좌표 원본이 없어서 재식별 가능한 join key는 존재하지 않습니다.

station-level extension은 별도 pipeline에서 다음 공개 원천을 실제 결합합니다.

- Citi Bike Jersey City trip history `JC-202401`: `start_station_id`, `started_at`로 station-hour start demand를 생성합니다.
- Citi Bike GBFS `station_information.json`: `short_name`을 trip `start_station_id`와 join해 station coordinate와 capacity를 결합합니다.
- Citi Bike GBFS `station_status.json`: `station_id`를 `gbfs_station_id`와 join해 live bikes/docks inventory snapshot과 shortage flag를 생성합니다.
- Open-Meteo historical hourly weather: `hour`를 기준으로 station-hour frame에 temperature, humidity, precipitation, wind를 결합합니다.

raw ride_id와 raw JSON/zip은 `/DATA`에만 저장하고 Git에는 포함하지 않습니다.

`station_status.json`은 현재 시점 live feed이므로 2024년 1월 trip history의 historical label로 사용하지 않습니다. 시간별 snapshot이 누적된 이후에는 prospective shortage outcome 검증 데이터로 분리합니다.

향후 station-level 확장 시 join key는 다음 원칙을 따릅니다.

- 시간: 1시간 또는 1일 단위로 bucketize합니다.
- 공간: station ID 원문 대신 공개 가능한 행정동/grid 또는 synthetic station key를 사용합니다.
- 내부 데이터: 공개 문서에는 schema, 집계값, synthetic fallback만 남깁니다.
- SNS/웹 이벤트: 원문·사용자 ID를 저장하지 않고 시간대별 event count/topic feature만 결합합니다.

## 저장 정책

| 구분 | 위치 | Git 포함 여부 |
|---|---|---|
| raw zip | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data/raw/uci_bike_sharing_dataset.zip` | 제외 |
| raw CSV | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data/raw/hour.csv` | 제외 |
| processed feature | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data/processed/hourly_features.parquet` | 제외 |
| source metadata | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data/raw/source_metadata.json` | 제외 |
| data dictionary | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/data/processed/data_dictionary.csv` | 제외 |
| station status snapshots | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/data/status_snapshots/` | 제외 |
| station inventory snapshot | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/data/processed/station_inventory_snapshot.csv` | 제외 |

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

## 누수 / Leakage 관리

- train/valid/test 분할은 날짜 경계 기준 chronological split으로 수행합니다.
- lag와 rolling feature는 예측 시점 이후 target을 참조하지 않도록 `shift(1)` 이후 계산합니다.
- validation/test metric은 모델 선택과 최종 보고 단계를 분리해 기록합니다.

## 생성 파일

pipeline은 실행 시 다음 파일을 생성해 원천 계약을 확인합니다.

- `source_metadata.json`: 원천 URL, fallback 사용 여부, 원본/실사용 컬럼 기록
- `data_dictionary.csv`: 컬럼명, dtype, 결측 수, 예시값, 설명 기록

## fallback 정책

네트워크 오류로 UCI zip을 받을 수 없을 때는 동일한 column contract를 가진 synthetic data를 생성합니다. 이 fallback은 실행 가능성을 보장하기 위한 장치이며, 결과 해석에는 `fallback_used` 값을 반드시 함께 표시합니다.
