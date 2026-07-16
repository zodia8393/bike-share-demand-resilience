# Public Deployment Decision

## 현재 결정

Status: `GO` (upstream evidence gate)

고정된 Citi Bike prospective cohort가 2주 readiness와 validation을 통과해 upstream evidence gate는 `GO`다. 이 결정은 public host가 이미 운영 중이라는 뜻이 아니며, 실제 endpoint의 auth, rate limit, cache, 운영 승인 여부는 downstream deployment gate에서 별도로 판단한다.

2026-07-15 KST 기준 최신 readiness는 다음과 같다.

| 항목 | 값 | 판단 |
|---|---:|---|
| Frozen snapshot count | 340 / 336 | 2주 목표 충족 |
| Minimum gate | 340 / 268 | 최소 기준 충족 |
| Validation cutoff | `2026-07-13T14:15:03+09:00` | 재현 가능한 cohort 고정 |
| Source / excluded snapshots | 361 / 21 | cutoff 이후 관측치는 검증 cohort에서 제외 |
| Prospective validation | `PASS` | 817,668 labels, time-based split |
| Public evidence decision | `GO` | readiness와 prospective validation 통과 |

서울 따릉이 adapter는 302개 snapshot 중 300개를 평가했고 rule/model validation은 `READY`다. Global top-50 rule metric은 `Precision@50=0.9978`이지만 `send_bikes_count=0`, `remove_bikes_count=15000`이라 반납 포화 완화 후보 중심이다. Balanced action metric은 `send_bikes_count=7500`, `remove_bikes_count=7500`, `balanced Precision@50=0.9587`, `send_bikes precision=0.9192`, `remove_bikes precision=0.9983`이다. 따라서 서울 결과는 evidence 기반 claim 검토에는 사용할 수 있지만, 외부 공개 시 실현된 현장 성과나 인과효과로 표현하지 않는다.

## 배포 전 필수 Gate

다음 명령이 모두 통과해야 public deployment를 다시 검토한다.

```bash
cd /workspace/prj/personal/data-scientist-career/bike-share-demand-resilience
PYTHONPATH=src python3 -m bike_share_resilience.station_service \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience \
  --check
PYTHONPATH=src python3 -m bike_share_resilience.station_prospective_validation \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience
python3 scripts/check_public_deploy_readiness.py \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience
PYTHONPATH=src python3 scripts/run_seoul_ddareungi_validation.py
```

`check_public_deploy_readiness.py`는 다음 조건을 확인한다.

- station API/dashboard artifact contract가 정상인지
- 2주 snapshot readiness가 충족됐는지
- true shortage prospective validation이 `PASS`인지
- raw zip/parquet/pickle/database/status snapshot 같은 private/raw artifact가 Git에 tracked되지 않았는지
- 배포 전 정리 항목이 남아 있지 않은지

## 공개 배포 전 정리 원칙

- raw trip/status/weather artifacts는 `/DATA`에만 둔다.
- public endpoint는 aggregate JSON/CSV-derived payload만 노출한다.
- local preview는 기본적으로 `127.0.0.1`에만 bind한다.
- public host, auth, rate limit, cache policy는 별도 승인 후 결정한다.
- readiness check의 `GO`만으로 Fly.io/GitHub Pages/외부 host 배포를 자동 승인하지 않는다. Endpoint 운영 gate는 별도로 확인한다.
- 2주 snapshot이 쌓여도 prospective validation이 `PASS`가 아니면 성능 claim과 public deployment는 계속 보류한다.
- 서울 따릉이 검증은 `READY`지만, balanced action metric은 검증 보조 지표다. 실제 대여 불가 보충/반납 포화 완화 성과 claim은 decision impact simulator와 운영 제약 검토 후에만 한다.

## Reviewer용 현재 사용법

현재 검증된 기본 surface는 local product surface다.

```bash
scripts/run_station_dashboard.sh
```

기본 주소는 `http://127.0.0.1:8765`이다.
