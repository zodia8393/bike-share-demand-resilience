# Privacy / Publication Gate

## Gate Result

| 항목 | 상태 | 근거 |
|---|---|---|
| 내부 데이터 원문 제외 | PASS | 내부 데이터는 사용하지 않았다. |
| 개인정보/식별자 제외 | PASS | UCI `hour.csv`는 시스템 수준 시간대 집계이며 사용자 ID, trip ID, 좌표 원본이 없다. |
| SNS 원문 제외 | PASS | SNS/웹 원문을 수집하지 않았다. 향후에는 event count/topic 집계만 공개한다. |
| secret scan | PASS | repo에는 token, API key, cookie, `.env` 값이 필요하지 않다. |
| public-safe fallback | PASS | 네트워크 실패 시 동일 schema의 synthetic fallback을 생성한다. |
| station-level raw 제외 | PASS | Citi Bike ride_id가 포함된 raw zip과 GBFS/Open-Meteo raw JSON 및 station_status snapshot은 `/DATA`에만 저장하고 Git에는 코드와 aggregate/report 경로만 남긴다. |
| public deploy gate | PASS | `scripts/check_public_deploy_readiness.py`가 raw artifact tracked 여부, frozen 2주 snapshot readiness, prospective validation을 확인하고 미충족 시 `NO_GO`로 배포를 막는다. |

## 공개 가능 산출물

공개 repo에는 코드, 문서, CI, 경량 figure만 둔다. raw zip, processed parquet/csv, model pickle, report output은 `/DATA/HJ` 아래 재생성 산출물로 둔다.

## 공개 금지 항목

raw 내부 데이터, 개인정보, private SNS 원문, 사용자 식별자, 민감 좌표, token, `.env` 값은 공개하지 않는다.

## 공개 배포 상태

2026-07-15 KST 기준 frozen 340-snapshot cohort와 prospective validation이 통과해 upstream public evidence decision은 `GO`다. 이 판정은 외부 endpoint 배포 승인이 아니며, 실제 host는 auth, rate limit, cache policy, 운영 승인을 별도로 통과해야 한다. Raw snapshot과 credential은 계속 공개 금지다.
