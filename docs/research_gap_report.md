# Research Gap Report

현재 slice는 portfolio-ready이며 quality gate를 통과했다. 다만 research-grade station-level 운영 시스템으로 확장하려면 아래 gap이 남아 있다.

| Gate | 현재 상태 | 미달 근거 | 다음 작업 |
|---|---|---|---|
| topic candidates >= 5 | PASS | `docs/topic_selection.md`에 5개 후보 평가 기록 | 다음 후보는 SNS/물류/에너지 중 하나로 확장 |
| data sources explored >= 3 | PASS | UCI, station-level open data 후보, SNS/event 후보, internal mobility 후보를 분리 기록 | 다음 실행에서 실제 source URL과 license를 보강 |
| data sources joined >= 2 or documented exception | PASS_WITH_LIMITATION | UCI 시스템 자료는 station/event join key가 없어 외부 결합을 보류 | station-level trip/status data를 찾으면 weather/event join 추가 |
| leakage-safe validation | PASS | 날짜 경계 chronological split과 shifted rolling feature 사용 | rolling-origin prospective validation 추가 |
| baseline/model/ablation or benchmark | PASS | historical baseline, ridge, gradient boosting, permutation importance | LightGBM/CatBoost는 dependency 근거가 생길 때 추가 |
| uncertainty/robustness/failure audit | PASS | bootstrap CI, conformal coverage, weather shock, segment residual audit | peak-specific conformal calibration 추가 |
| product surface | PASS | batch pipeline/CLI와 CI smoke run 존재 | station 확장 후 API/dashboard 배포 |
| privacy publication gate | PASS | 사용자·좌표·SNS 원문 없음, `/DATA/HJ` artifact 분리 | 내부 데이터 사용 시 synthetic fallback 추가 |
| CI/tests/smoke | PASS | GitHub Actions와 `scripts/run_all.sh` 존재 | validator를 CI에 추가 |
| GitHub/deploy/runbook | PASS_WITH_LIMITATION | GitHub repo와 local runbook 존재, deployed service는 없음 | API/dashboard product로 확장 시 deploy |
