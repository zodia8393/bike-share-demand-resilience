# Hiring Market Alignment

## 목표 역할

- Data Scientist: 문제 정의, baseline, metric, segment error audit
- Machine Learning Engineer: reproducible pipeline, CI, model artifact, quality gate
- Research Engineer / Applied Scientist: leakage-safe validation, uncertainty, bootstrap, conformal, ablation
- Data/Product Engineer: batch product surface, runbook, decision output, public-safe artifact policy

## 보여줄 역량

| 평가축 | 프로젝트 증거 |
|---|---|
| 문제 정의와 business/product/operation impact | 수요 예측을 재배치 staging target 의사결정으로 연결 |
| Python/data engineering | raw preservation, feature pipeline, artifact root 분리, tests |
| 복합 데이터 수집·정제·결합 | 현재는 UCI 공개 데이터 내부의 calendar/weather 변수 활용, station/SNS/internal 결합은 명시적 gap |
| 통계·실험·불확실성 | bootstrap MAE CI, split-conformal interval, segment coverage |
| ML 모델링 또는 system benchmark | historical baseline, ridge, gradient boosting 비교 |
| product delivery | `scripts/run_all.sh`, CI, model card, quality gate |
| deployment/runbook | local production runbook과 GitHub Actions smoke run |
| privacy/security judgment | 공개 불가 데이터와 secret 노출 금지 문서화 |

## 시장 근거

이 repo는 “모델 점수”보다 “운영 의사결정으로 연결되는 검증 가능한 ML system”을 보여주는 방향으로 설계했다. 이직 포트폴리오에서는 단일 notebook보다 재현 명령, CI, data contract, model card, failure audit, product surface가 더 강한 평가 신호다.
