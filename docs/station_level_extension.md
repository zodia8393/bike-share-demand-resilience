# Station-Level 수요 회복력 확장

## 목적

기존 UCI system-level slice의 가장 큰 한계는 station 좌표, capacity, 실시간 운영 제약이 없다는 점이었다. 이 확장은 Jersey City Citi Bike 공개 trip history, Citi Bike GBFS station metadata/status, Open-Meteo hourly weather를 결합해 station-hour 수요 회복력과 재배치 우선순위를 검증한다.

## 데이터 원천

| 원천 | 역할 | 공개성 | 저장 위치 |
|---|---|---|---|
| Citi Bike Jersey City trip history `JC-202401` | station-hour start/end demand 생성 | 공개 zip | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/data/raw/JC-202401-citibike-tripdata.csv.zip` |
| Citi Bike GBFS `station_information.json` | station name, coordinate, capacity join | 공개 JSON | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/data/raw/citibike_gbfs_station_information.json` |
| Citi Bike GBFS `station_status.json` | live bikes/docks inventory snapshot, shortage flag | 공개 JSON | `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/data/status_snapshots/` |
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

live inventory snapshot만 캡처:

```bash
python3 scripts/capture_station_status_snapshot.py \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience
```

dashboard/API artifact contract 확인:

```bash
PYTHONPATH=src python3 -m bike_share_resilience.station_service \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience \
  --check
```

로컬 dashboard 실행:

```bash
scripts/run_station_dashboard.sh
```

hourly snapshot monitor와 readiness/deploy gate 갱신:

```bash
scripts/run_station_snapshot_monitor.sh
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
| Inventory join rate | 97%+ |
| Best model | `gradient_boosting` |
| Baseline test MAE | 1.025 |
| Best test MAE | 1.006 |
| Conformal coverage | 88.9% |

## Quality Gate

| Gate | 상태 | 근거 |
|---|---|---|
| multi-source join | PASS | 35 stations, GBFS join rate 97.1% |
| weather join | PASS | 744 hourly weather rows |
| inventory snapshot | PASS | GBFS station_status live inventory join >=80% |
| baseline comparison | PASS | best MAE 1.006 <= baseline MAE 1.025 |
| conformal coverage | PASS | 0.889 |
| decision output | PASS | 12 station rebalancing priority rows |

## 운영 의사결정

`station_rebalancing_priority.csv`는 최근 24시간 test window에서 station별 forecast, conformal upper demand, capacity, live bikes/docks, risk score, recommended buffer bikes를 산출한다. live `station_status`에서 현재 자전거 부족 신호가 있으면 risk score를 보수적으로 높인다. 이는 실제 dispatch 확정값이 아니라, 재고 부족 가능성이 큰 station을 human review queue에 올리는 의사결정 surface다.

`bike_share_resilience.station_service`는 산출물을 읽어 다음 local product surface를 제공한다.

- `/health`
- `/api/summary`
- `/api/rebalancing-priority`
- `/api/seoul-ddareungi-priority`
- `/api/seoul-ddareungi-map-points`
- `/api/seoul-ddareungi-inventory`
- `/api/seoul-ddareungi-summary`
- `/api/seoul-ddareungi-validation`
- `/api/seoul-ddareungi-model-metrics`
- `/api/inventory-snapshot`
- `/api/snapshot-readiness`
- `/api/deploy-readiness`
- `/` dashboard HTML

서울 따릉이 adapter는 실시간 대여정보 snapshot을 `station inventory contract`로 정규화하고, 대여 불가 위험은 `send_bikes`, 반납 포화 위험은 `remove_bikes`, 그 외는 `monitor`로 지도와 table에 표시한다. 지도는 `/api/seoul-ddareungi-map-points`를 사용하며 Leaflet + OpenStreetMap 기반이라 별도 지도 API key가 필요 없다.

prospective 검증은 다음 명령으로 갱신한다.

```bash
PYTHONPATH=src python3 scripts/run_seoul_ddareungi_validation.py
```

현재 서울 snapshot은 아직 충분한 시간축 coverage가 아니므로 rule metric은 preliminary로 저장하고, validation/model status는 `NOT_READY`로 유지한다.

## 한계

- GBFS capacity는 현재 metadata라 2024년 1월 historical capacity와 다를 수 있다.
- 현재 한 번의 live station_status snapshot은 2024년 1월 historical inventory label이 아니므로, true shortage outcome은 시간별 snapshot이 누적된 뒤 prospective validation으로 구성한다. 이 축적은 매시 15분 cron으로 자동화되어 있고, readiness 기준은 `docs/prospective_shortage_validation.md`에 고정했다.
- Trip history와 live inventory의 시점이 다르므로 현재 priority는 dispatch 확정값이 아니라 reviewer-facing risk queue로 제한한다.
