# Public Deployment Decision

## 현재 결정

Status: `NO_GO`

현재 local dashboard/API는 portfolio review와 내부 검증용으로 충분하지만, public deployment는 아직 보류한다. 이유는 true shortage label을 만들기 위한 2주 `station_status` snapshot coverage가 아직 충족되지 않았기 때문이다.

2026-07-07 09:17 KST 기준 최신 readiness는 다음과 같다.

| 항목 | 값 | 판단 |
|---|---:|---|
| Snapshot count | 191 / 336 | 2주 목표의 56.8% |
| Minimum gate | 191 / 268 | 최소 기준의 71.3% |
| Latest snapshot | `2026-07-07T09:15:04+09:00` | hourly monitor 정상 누적 중 |
| Earliest ready | `2026-07-13T14:04:57+09:00` | 그 전까지 public deploy 보류 |
| Public deploy decision | `NO_GO` | prospective validation `NOT_READY` |

서울 따릉이 adapter는 Citi Bike 2주 gate와 분리해 먼저 검증할 수 있다. 2026-07-07 KST 현재 서울 snapshot은 103개이며 기본 gate 24개를 통과했고, rule/model validation은 `READY`다. 다만 public deployment는 여전히 `NO_GO`다. Global top-50 rule metric은 `Precision@50=0.9976`이지만 `send_bikes_count=0`, `remove_bikes_count=5050`이라 반납 포화 완화 후보 중심이다. 이를 보완하기 위해 balanced action metric을 추가했고, `send_bikes_count=2525`, `remove_bikes_count=2525`, `balanced Precision@50=0.9552`, `send_bikes precision=0.9121`, `remove_bikes precision=0.9984`를 별도 보조 근거로 본다. 따라서 서울 결과는 "서울 따릉이 next-snapshot validation READY"로 표현하되, 외부 공개 성과 claim은 별도 impact simulator 전까지 하지 않는다.

## 배포 전 필수 Gate

다음 명령이 모두 통과해야 public deployment를 다시 검토한다.

```bash
cd /workspace/prj/data-scientist-career/bike-share-demand-resilience
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
- readiness check가 `GO`가 되기 전에는 Fly.io/GitHub Pages/외부 host 배포를 하지 않는다.
- 2주 snapshot이 쌓여도 prospective validation이 `PASS`가 아니면 성능 claim과 public deployment는 계속 보류한다.
- 서울 따릉이 검증은 `READY`지만, balanced action metric은 검증 보조 지표다. 실제 대여 불가 보충/반납 포화 완화 성과 claim은 decision impact simulator와 운영 제약 검토 후에만 한다.

## Reviewer용 현재 사용법

현재는 local product surface를 사용한다.

```bash
scripts/run_station_dashboard.sh
```

기본 주소는 `http://127.0.0.1:8765`이다.
