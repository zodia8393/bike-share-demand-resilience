# Bike-Share Demand Resilience

공공자전거 수요와 재고 상태를 shortage·saturation risk, 재배치 우선순위, 배포 보류 기준으로 연결하는 forecasting 프로젝트입니다.

[DecisionOps portfolio](https://github.com/zodia8393/data-scientist-career) · [Guardrail Workbench](https://github.com/zodia8393/agentic-decisionops-workbench) · [Technical notes](docs/README.md)

## 문제와 결과

| 문제 | 구현 |
|---|---|
| 어느 대여소가 부족하거나 포화될 가능성이 높은가 | 시간 기준 split과 uncertainty-aware risk prediction |
| 어떤 조치를 먼저 검토해야 하는가 | 제약 기반 rebalancing priority |
| 아직 배포해도 되는가 | frozen prospective cohort와 validation gate |

미국 Citi Bike benchmark와 서울 따릉이 공개 API adapter를 같은 inventory contract로 다룹니다. 결과는 운영 검토용 근거이며, 실제 현장 조치의 인과 효과를 주장하지 않습니다.

## 빠른 실행

```bash
git clone https://github.com/zodia8393/bike-share-demand-resilience.git
cd bike-share-demand-resilience
python3 -m pip install -r requirements.txt
scripts/run_all.sh
```

## 검증 원칙

- random split 대신 시간 순서와 prospective validation을 사용합니다.
- 전체 점수뿐 아니라 station·시간대별 오류와 uncertainty coverage를 확인합니다.
- validation gate가 준비되지 않으면 public deployment는 `NO_GO`입니다.

## 문서

- [data contract](docs/data_contract.md)
- [validation](docs/prospective_shortage_validation.md)
- [deployment decision](docs/public_deployment_decision.md)
- [technical notes](docs/README.md)
