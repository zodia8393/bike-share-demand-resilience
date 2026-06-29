# Prospective Shortage Validation Plan

## 목적

station-level extension의 남은 핵심 리스크는 live `station_status`가 2024년 1월 trip history와 같은 시점의 historical label이 아니라는 점이다. 이 문서는 hourly inventory snapshot을 2주 이상 축적해 true shortage outcome을 만들고, 이후 prospective validation으로 전환하는 운영 계획을 정의한다.

## 자동화

현재 등록된 자동화는 매시 15분에 실행된다.

```bash
/workspace/prj/data-scientist-career/bike-share-demand-resilience/scripts/run_station_snapshot_monitor.sh
```

이 스크립트는 다음 순서로 동작한다.

1. Citi Bike GBFS `station_status.json` snapshot 저장
2. inventory snapshot CSV 저장
3. snapshot history와 next-snapshot shortage label panel 생성
4. 2주 readiness report 갱신
5. public deploy readiness report 갱신
6. cron watchdog용 success marker 생성

## Readiness Gate

| 항목 | 기준 |
|---|---|
| 목표 기간 | 14일 |
| 목표 snapshot 수 | 336개 hourly snapshot |
| 최소 허용 coverage | 80% |
| 최소 snapshot 수 | 268개 |
| label 기준 | 같은 station의 다음 snapshot gap이 90분 이하일 때 next-snapshot shortage label 생성 |

산출물:

- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/reports/station_snapshot_readiness.json`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/reports/station_snapshot_readiness.md`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/data/processed/station_inventory_history.csv`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/data/processed/station_shortage_label_panel.csv`

## 현재 판단

2026-06-29 KST 기준으로 자동 축적은 시작됐지만 2주 coverage는 아직 충족되지 않았다. 따라서 shortage-risk model claim과 public deployment decision은 `NO_GO`로 유지한다. 다만 automation이 계속 실행되면 2026-07-13 KST 이후 readiness gate가 충족될 수 있다.

## 다음 전환 조건

`station_snapshot_readiness.json`의 `ready_for_prospective_validation`이 `true`가 되면 다음 작업을 수행한다.

1. `station_shortage_label_panel.csv`를 기준으로 shortage-risk baseline과 main model을 분리한다.
2. time-based prospective split으로 next-snapshot shortage 예측을 평가한다.
3. station-level priority output에 true shortage calibration metric을 추가한다.
4. public deploy readiness check를 다시 실행한다.
