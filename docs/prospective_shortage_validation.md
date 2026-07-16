# Prospective Shortage Validation Plan

## 목적

station-level extension의 남은 핵심 리스크는 live `station_status`가 2024년 1월 trip history와 같은 시점의 historical label이 아니라는 점이다. 이 문서는 hourly inventory snapshot을 2주 이상 축적해 true shortage outcome을 만들고, 이후 prospective validation으로 전환하는 운영 계획을 정의한다.

## 자동화

현재 등록된 자동화는 매시 15분에 실행된다.

```bash
/workspace/prj/personal/data-scientist-career/bike-share-demand-resilience/scripts/run_station_snapshot_monitor.sh
```

이 스크립트는 다음 순서로 동작한다.

1. Citi Bike GBFS `station_status.json` snapshot 저장
2. inventory snapshot CSV 저장
3. snapshot history와 next-snapshot shortage label panel 생성
4. 2주 readiness report 갱신
5. readiness가 처음 `READY`가 되면 Telegram으로 "스냅샷 축적 완료, 검증 시작" 알림 발송
6. prospective shortage validation report 갱신
7. night threshold calibration과 class-balance/hour audit 갱신
8. frozen cutoff 이후 monitoring-only drift report 갱신
9. public deploy readiness report 갱신
10. validation/deploy 결과가 바뀌면 Telegram 결과 알림 발송
11. cron watchdog용 success marker 생성

Telegram 알림은 `station_readiness_notification_state.json`에 readiness event와 validation result key를 저장해 중복 발송을 막는다. 따라서 매시간 monitor가 계속 돌아도 같은 readiness event에 대해 시작 알림은 한 번만 발송된다.

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
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/reports/station_prospective_validation.json`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/reports/station_prospective_validation.md`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/reports/station_prospective_validation_metrics.csv`
- `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/station_level/reports/station_readiness_notification_state.json`

## 현재 판단

2026-07-15 KST 기준으로 cutoff `2026-07-13T14:15:03+09:00`까지 340개 snapshot과 14.01일 coverage를 확보했다. Source 361개 중 cutoff 이후 21개는 고정 검증 cohort에서 제외했다. `station_prospective_validation`은 817,668개 label을 시간순 split으로 평가해 `PASS`이며, public deployment evidence gate도 `GO`다.

최고 점수는 `persistence_baseline`의 F1 0.8286, average precision 0.7102, Brier 0.0478이다. 이 결과는 고정 cohort의 next-snapshot 예측 검증이며 현장 재배치의 인과효과를 뜻하지 않는다.

Advanced audit 결과는 다음과 같다.

| Audit | 결과 | 판단 |
|---|---:|---|
| Rolling-origin | 3 folds, 9 model-fold rows | fold-best F1 평균 0.8477, 최저 0.8238 |
| Feature ablation | 3 feature sets | full AP 0.8772, temporal-only AP 0.1481 |
| Drift | 4/4 PASS | rate diff 0.0115, PSI 0.0021, hour TV 0.0960, station coverage 1.0 |
| Failure segments | 6 | night F1 0.7960이 최저 |

추가 산출물은 `station_prospective_rolling_origin_metrics.csv`, `station_prospective_feature_ablation.csv`, `station_prospective_drift_audit.csv`, `station_prospective_failure_audit.csv`다.

Night calibration은 train 내부 fit/calibration 분할에서 global/night threshold 0.900/0.675를 선택했다. Candidate는 final holdout에서 전체 F1 0.8275, night F1 0.7953으로 persistence 0.8286/0.7960을 넘지 못해 `KEEP_PERSISTENCE_BASELINE`으로 판정했다. Night 상태 전이율은 6.40%로 non-night 4.18%보다 높아 단일 threshold보다 시간대 변동성이 주요 후속 리스크다.

Cutoff 이후 21개 snapshot 50,652행은 monitoring-only cohort로 분리했다. Shortage-rate diff 0.0122, inventory PSI 0.0017, hour TV 0.1765, station coverage 1.0으로 4/4 check가 통과했으며 자동 model 변경은 수행하지 않는다.

## 다음 전환 조건

`station_snapshot_readiness.json`의 `ready_for_prospective_validation`이 `true`가 되어 다음 전환을 완료했다.

1. `station_shortage_label_panel.csv`를 기준으로 shortage-risk baseline과 main model을 자동 평가했다.
2. time-based prospective split으로 next-snapshot shortage 예측을 평가했다.
3. station-level priority output과 validation report에 prospective metric을 연결했다.
4. public deploy readiness check를 다시 실행해 `GO`를 확인했다.

## 고정 검증 코호트

2주 축적 단계는 최초 `READY` snapshot인 `2026-07-13T14:15:03+09:00`을 포함해 종료했다. 이후 raw snapshot은 삭제하지 않고 보존하지만, 최종 prospective validation은 아래 cutoff로 고정해 재현한다.

```bash
PYTHONPATH=src python3 -m bike_share_resilience.station_snapshot_analysis \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience \
  --snapshot-cutoff 2026-07-13T14:15:03+09:00
```

고정 코호트 이후의 snapshot은 `excluded_snapshot_count`로 보고하며 readiness·validation 학습/평가 행에는 포함하지 않는다.

수동 검증:

```bash
PYTHONPATH=src python3 -m bike_share_resilience.station_prospective_validation \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience
PYTHONPATH=src python3 -m bike_share_resilience.station_night_calibration \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience
PYTHONPATH=src python3 -m bike_share_resilience.station_post_cutoff_monitoring \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience \
  --snapshot-cutoff 2026-07-13T14:15:03+09:00
```

Telegram readiness 알림 dry-run:

```bash
PYTHONPATH=src python3 -m bike_share_resilience.station_readiness_notifications \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience \
  --phase ready-start \
  --dry-run
```
