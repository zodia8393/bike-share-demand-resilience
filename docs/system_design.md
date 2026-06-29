# 시스템 설계

## Product Surface

현재 product surface는 `scripts/run_all.sh`로 실행되는 batch pipeline/CLI다. pipeline은 데이터 획득, feature 생성, baseline/model 학습, evaluation, uncertainty, optimization, report 생성을 한 번에 수행한다.

## Architecture

```text
UCI/public or synthetic fallback
  -> data contract and raw preservation
  -> leakage-safe feature pipeline
  -> baseline/ridge/gradient boosting
  -> holdout, bootstrap, conformal, segment audit
  -> rebalancing optimization output
  -> report/model card/quality gate
```

## Runtime

- Source root: `/workspace/prj/data-scientist-career/bike-share-demand-resilience`
- Artifact root: `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience`
- Product command: `scripts/run_all.sh`
- CI: `.github/workflows/ci.yml`
- Deployment/runbook: 현재는 local production runbook 수준이며, API/dashboard 배포는 station-level 확장 후 수행한다.

## Operations

- Healthcheck: `run_summary.json`의 `quality_gate_passed`와 CSV 산출물 존재 여부를 확인한다.
- Monitoring/drift: prospective 실행 시 WAPE, conformal coverage, segment residual shift를 주간 단위로 추적한다.
- Retraining cadence: 데이터가 매일 갱신되는 운영 환경에서는 rolling-origin validation과 월간 recalibration을 기본값으로 둔다.
