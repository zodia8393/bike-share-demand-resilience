# Station-Level 수요 회복력 확장

## 목적

기존 UCI system-level slice의 가장 큰 한계는 station 좌표, capacity, 실시간 운영 제약이 없다는 점이었다. 이 확장은 Jersey City Citi Bike 공개 trip history, Citi Bike GBFS station metadata, Open-Meteo hourly weather를 결합해 station-hour 수요 회복력과 재배치 우선순위를 검증한다.

## 데이터 원천

| 원천 | 역할 | 공개성 | 저장 위치 |
|---|---|---|---|
| Citi Bike Jersey City trip history `JC-202401` | station-hour start/end demand 생성 | 공개 zip | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/data/raw/JC-202401-citibike-tripdata.csv.zip` |
| Citi Bike GBFS `station_information.json` | station name, coordinate, capacity join | 공개 JSON | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/data/raw/citibike_gbfs_station_information.json` |
| Open-Meteo historical weather | hourly temperature, humidity, precipitation, wind join | 공개 API, no key | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/data/raw/open_meteo_hourly_2024-01-01_2024-01-31.json` |

공개 repo에는 raw ride_id, raw zip, raw JSON을 커밋하지 않는다. 공개 가능한 산출물은 aggregate schema, 코드, 테스트, 보고서 경로뿐이다.

## 실행

실제 공개 데이터 run:

```bash
cd /workspace/prj/data-scientist-career/bike-share-demand-resilience
scripts/run_station_level.sh
```

네트워크 없이 synthetic smoke:

```bash
SYNTHETIC_FLAG=--synthetic TOP_STATIONS=10 OUTPUT_ROOT=/tmp/bike-share-station-smoke scripts/run_station_level.sh
```

## 최신 실행 결과

2026-06-29 KST 실행 기준:

| 항목 | 값 |
|---|---:|
| Trip rows | 50,661 |
| GBFS station rows | 2,412 |
| Weather hours | 744 |
| Station-hour rows | 25,200 |
| Top stations | 35 |
| GBFS join rate | 97.1% |
| Best model | `gradient_boosting` |
| Baseline test MAE | 1.025 |
| Best test MAE | 1.006 |
| Conformal coverage | 88.9% |

## Quality Gate

| Gate | 상태 | 근거 |
|---|---|---|
| multi-source join | PASS | 35 stations, GBFS join rate 97.1% |
| weather join | PASS | 744 hourly weather rows |
| baseline comparison | PASS | best MAE 1.006 <= baseline MAE 1.025 |
| conformal coverage | PASS | 0.889 |
| decision output | PASS | 12 station rebalancing priority rows |

## 운영 의사결정

`station_rebalancing_priority.csv`는 최근 24시간 test window에서 station별 forecast, conformal upper demand, capacity, risk score, recommended buffer bikes를 산출한다. 이는 실제 dispatch 확정값이 아니라, 재고 부족 가능성이 큰 station을 human review queue에 올리는 의사결정 surface다.

## 한계

- GBFS capacity는 현재 metadata라 2024년 1월 historical capacity와 다를 수 있다.
- Trip history만으로는 실제 재고 부족 label을 만들 수 없어 demand pressure proxy를 사용한다.
- 다음 단계는 station_status snapshot 또는 별도 inventory data를 결합해 true shortage outcome을 구성하는 것이다.
