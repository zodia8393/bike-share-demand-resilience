# Public Deployment Decision

## 현재 결정

Status: `NO_GO`

현재 local dashboard/API는 portfolio review와 내부 검증용으로 충분하지만, public deployment는 아직 보류한다. 이유는 true shortage label을 만들기 위한 2주 `station_status` snapshot coverage가 아직 충족되지 않았기 때문이다.

## 배포 전 필수 Gate

다음 명령이 모두 통과해야 public deployment를 다시 검토한다.

```bash
cd /workspace/prj/data-scientist-career/bike-share-demand-resilience
PYTHONPATH=src python3 -m bike_share_resilience.station_service \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience \
  --check
python3 scripts/check_public_deploy_readiness.py \
  --output-root /DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience
```

`check_public_deploy_readiness.py`는 다음 조건을 확인한다.

- station API/dashboard artifact contract가 정상인지
- 2주 snapshot readiness가 충족됐는지
- raw zip/parquet/pickle/database/status snapshot 같은 private/raw artifact가 Git에 tracked되지 않았는지
- 배포 전 정리 항목이 남아 있지 않은지

## 공개 배포 전 정리 원칙

- raw trip/status/weather artifacts는 `/DATA`에만 둔다.
- public endpoint는 aggregate JSON/CSV-derived payload만 노출한다.
- local preview는 기본적으로 `127.0.0.1`에만 bind한다.
- public host, auth, rate limit, cache policy는 별도 승인 후 결정한다.
- readiness check가 `GO`가 되기 전에는 Fly.io/GitHub Pages/외부 host 배포를 하지 않는다.

## Reviewer용 현재 사용법

현재는 local product surface를 사용한다.

```bash
scripts/run_station_dashboard.sh
```

기본 주소는 `http://127.0.0.1:8765`이다.
