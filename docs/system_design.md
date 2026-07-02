# 시스템 설계

## Product Surface

현재 product surface는 `scripts/run_all.sh`로 실행되는 batch pipeline/CLI다. pipeline은 데이터 획득, feature 생성, baseline/model 학습, evaluation, uncertainty, optimization, report 생성을 한 번에 수행한다.

Station-level extension은 `scripts/run_station_level.sh`로 실행되는 별도 batch pipeline/CLI다. live inventory는 `scripts/run_station_snapshot_monitor.sh`로 timestamped snapshot, 2주 readiness report, public deploy readiness report를 함께 남긴다. reviewer-facing surface는 `bike_share_resilience.station_service`의 API/dashboard로 제공한다. 네트워크 없는 CI smoke를 위해 `SYNTHETIC_FLAG=--synthetic` 경로도 제공한다.

최종 방향은 UCI/Citi Bike benchmark를 유지하면서, 서울 따릉이 공개데이터 adapter를 추가해 한국 공공자전거 운영 문제인 대여 불가, 반납 포화, 재배치 우선순위를 의사결정 제품으로 구현하는 것이다. 현재 구현은 서울 실시간 대여정보 snapshot, 지도 기반 priority, next-snapshot label, rule validation, ML baseline readiness까지 연결한다. 이 결정은 suite 문서 [architecture_decision_seoul_ddareungi_adapter.md](../../docs/architecture_decision_seoul_ddareungi_adapter.md)에 고정한다.

## Architecture

```text
UCI/public or synthetic fallback
  -> data contract and raw preservation
  -> leakage-safe feature pipeline
  -> baseline/ridge/gradient boosting
  -> holdout, bootstrap, conformal, segment audit
  -> rebalancing optimization output
  -> report/model card/quality gate

Citi Bike JC trip history + GBFS station_information + GBFS station_status + Open-Meteo weather
  -> station-hour demand frame
  -> live inventory snapshot and shortage flags
  -> station profile baseline / ridge / gradient boosting
  -> conformal interval and segment audit
  -> station rebalancing priority
  -> 2-week snapshot readiness and next-snapshot shortage label panel
  -> local API/dashboard
  -> public deployment readiness gate
  -> station_level_report.md

Seoul Ddareungi public data adapter
  -> real-time station availability snapshot
  -> normalized inventory and timestamped snapshot history
  -> live map points and rebalancing priority
  -> next-snapshot bike shortage / dock shortage label
  -> rule-based priority validation
  -> ML baseline readiness with chronological split
  -> local API/dashboard
  -> public deployment remains NO_GO until validation coverage is enough
```

데이터 흐름도(DFD): [data_flow_diagram.md](data_flow_diagram.md)

## Runtime

- Source root: `/workspace/prj/data-scientist-career/bike-share-demand-resilience`
- Artifact root: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience`
- Product command: `scripts/run_all.sh`
- Station command: `scripts/run_station_level.sh`
- Station status snapshot: `python3 scripts/capture_station_status_snapshot.py`
- Station snapshot monitor: `scripts/run_station_snapshot_monitor.sh`
- Station API/dashboard check: `PYTHONPATH=src python3 -m bike_share_resilience.station_service --check`
- Station dashboard: `scripts/run_station_dashboard.sh`
- Seoul schema check: `python3 scripts/check_seoul_ddareungi_schema.py --full-scan`
- Seoul snapshot capture: `python3 scripts/capture_seoul_ddareungi_snapshot.py`
- Seoul validation: `PYTHONPATH=src python3 scripts/run_seoul_ddareungi_validation.py`
- Public deploy readiness: `python3 scripts/check_public_deploy_readiness.py --report-only`
- CI: `.github/workflows/ci.yml`
- Deployment/runbook: 현재는 local dashboard/API surface까지 제공하며, public 배포는 2주 snapshot readiness와 privacy/publication gate가 모두 통과한 뒤 결정한다.

## Operations

- Healthcheck: `run_summary.json`/`station_run_summary.json`의 `quality_gate_passed`, inventory snapshot row count, snapshot readiness, API/dashboard `--check`, deploy readiness report를 확인한다.
- Monitoring/drift: prospective 실행 시 WAPE, conformal coverage, segment residual shift, live inventory shortage rate, 서울 rule precision@10/50을 주간 단위로 추적한다.
- Retraining cadence: 데이터가 매일 갱신되는 운영 환경에서는 rolling-origin validation과 월간 recalibration을 기본값으로 둔다.
