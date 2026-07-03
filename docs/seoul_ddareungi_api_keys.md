# 서울 따릉이 API Key 정리

최종 업데이트: 2026-07-02 KST

## 결론

서울 따릉이 adapter의 필수 key는 1개다.

| 구분 | 필요 여부 | 환경변수명 | 용도 |
|---|---:|---|---|
| 서울 열린데이터광장 인증키 | 필수 | `SEOUL_OPEN_DATA_API_KEY` | 따릉이 실시간 대여정보 API 호출 |
| 공공데이터포털 service key | 선택 | `DATA_GO_KR_SERVICE_KEY` | data.go.kr OpenAPI fallback 또는 기상청/공휴일 API 사용 시 |
| Open-Meteo key | 불필요 | 없음 | 날씨 feature용 공개 API, key 없이 사용 가능 |
| OpenAI API key | 불필요 | 없음 | 현재 deterministic pipeline/guardrail 기준. LLM planner 붙일 때만 별도 검토 |
| Telegram token | 불필요 | 기존 로컬 설정 사용 | 작업 완료 알림용이며 따릉이 데이터 수집과 무관 |

## 1. 필수: 서울 열린데이터광장 인증키

서울 따릉이 실시간 대여정보는 서울 열린데이터광장의 Open API를 사용한다.

공식 데이터셋:

- 서울 열린데이터광장: `서울시 공공자전거 따릉이 실시간 대여정보`
- URL: https://data.seoul.go.kr/dataList/OA-15493/A/1/datasetView.do

이 API가 제공하는 핵심 필드는 다음과 같다.

- 대여소 ID
- 대여소명
- 거치대 수
- 현재 대여 가능 자전거 수
- 거치율
- 위도/경도

공식 설명상 JSON API이며, 한 번에 최대 1,000건을 넘기지 않도록 `1/1000`, `1001/2000`처럼 나누어 호출해야 한다.

프로젝트에서는 key 값을 코드나 문서에 쓰지 않고 다음 환경변수명만 사용한다.

```bash
export SEOUL_OPEN_DATA_API_KEY="<issued-key>"
```

예상 endpoint 형태:

```text
http://openapi.seoul.go.kr:8088/${SEOUL_OPEN_DATA_API_KEY}/json/bikeList/1/1000/
http://openapi.seoul.go.kr:8088/${SEOUL_OPEN_DATA_API_KEY}/json/bikeList/1001/2000/
```

실제 구현에서는 호출 범위를 설정값으로 두고, 응답 row count와 schema를 검증한 뒤 raw snapshot을 `/DATA/HJ` 아래에 저장한다.

응답 schema 검증:

```bash
python3 scripts/check_seoul_ddareungi_schema.py --full-scan
```

이 명령은 `/workspace/.env` 또는 process environment의 `SEOUL_OPEN_DATA_API_KEY`를 읽고, 1,000건 단위로 마지막 partial page까지 schema를 확인한다. 출력과 report에는 key 값이나 raw 응답을 남기지 않고 `result_code`, `row_count`, 필수 field 누락, 타입 오류만 저장한다.

검증 report 위치:

```text
/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/seoul_ddareungi/reports/seoul_ddareungi_schema_check.json
```

live inventory snapshot 수집:

```bash
python3 scripts/capture_seoul_ddareungi_snapshot.py
```

이 명령은 schema 검증을 통과한 page만 `station inventory contract`로 정규화한다. 기본 성공 기준은 2,000행 이상이며, `latest_inventory_snapshot.csv`, timestamped snapshot CSV, raw API payload JSON, summary JSON을 모두 `/DATA/HJ` 아래에 남긴다. 이어서 live 자전거 부족/거치대 부족 기준으로 `rebalancing_priority.csv`와 `rebalancing_priority_summary.json`도 생성한다. 저장되는 raw payload에는 API key나 호출 URL을 포함하지 않는다.

local API/dashboard 확인:

```bash
PYTHONPATH=src python3 -m bike_share_resilience.station_service --check
scripts/run_station_dashboard.sh
```

next-snapshot label과 rule/model validation 산출:

```bash
PYTHONPATH=src python3 scripts/run_seoul_ddareungi_validation.py
```

이 명령은 timestamped inventory snapshot을 station별 시간축으로 연결해 `bike_shortage_next_snapshot`, `dock_shortage_next_snapshot`, `next_gap_minutes`를 생성한다. snapshot 수가 기본 기준인 24개보다 적으면 rule metric은 preliminary로 저장하되 validation/model status는 `NOT_READY`로 둔다.

정기 수집에서는 capture와 validation을 한 번에 실행한다.

```bash
scripts/run_seoul_ddareungi_snapshot_monitor.sh
```

이 wrapper는 `SEOUL_OPEN_DATA_API_KEY`를 `.env` 또는 process environment에서 읽고, live snapshot 저장 후 validation report를 갱신한다. 성공 시 `/workspace/_codex/scripts/logs/seoul-ddareungi-snapshot-ok`와 일자별 marker를 남긴다.

따릉이 product surface는 다음 local endpoint에서 확인한다.

- `/api/seoul-ddareungi-priority`
- `/api/seoul-ddareungi-inventory`
- `/api/seoul-ddareungi-summary`
- `/api/seoul-ddareungi-map-points`
- `/api/seoul-ddareungi-validation`
- `/api/seoul-ddareungi-model-metrics`

dashboard는 Leaflet + OpenStreetMap으로 map section을 렌더링한다. 별도 지도 API key는 사용하지 않으며, CDN/network 실패 시에도 priority table과 validation summary는 계속 표시된다.

## 2. 선택: 공공데이터포털 service key

공공데이터포털에도 `서울특별시 공공자전거 실시간 대여정보`가 등록되어 있다.

공식 데이터셋:

- 공공데이터포털: `서울특별시 공공자전거 실시간 대여정보`
- URL: https://www.data.go.kr/data/15051891/openapi.do

현재 설계의 기본 경로는 서울 열린데이터광장 endpoint이므로 `DATA_GO_KR_SERVICE_KEY`는 필수로 두지 않는다.

다만 다음 경우에는 필요할 수 있다.

- data.go.kr 경유 OpenAPI를 fallback으로 붙일 때
- 기상청, 공휴일, 행정동 등 다른 공공데이터포털 OpenAPI를 추가할 때
- 따릉이 대여이력 OpenAPI 버전을 자동 호출할 때

환경변수명:

```bash
export DATA_GO_KR_SERVICE_KEY="<issued-service-key>"
```

## 3. 대여이력 데이터

과거 수요 패턴은 서울 열린데이터광장의 `서울시 공공자전거 따릉이 대여이력 정보`를 사용한다.

공식 데이터셋:

- URL: https://data.seoul.go.kr/dataList/OA-15182/F/1/datasetView.do

이 데이터는 년도별 zip 파일로 제공되는 대용량 file data다. 자동 수집 전까지는 다음 원칙을 따른다.

- raw zip은 `/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience/seoul_ddareungi/data/raw/`에 둔다.
- Git에는 raw zip을 넣지 않는다.
- 공개 repo에는 schema, 다운로드 방법, 집계 산출물 설명만 남긴다.
- 대여/반납 시각과 대여소 ID를 station-hour 단위로 집계해 사용한다.

대여이력 자동 다운로드는 파일 URL 안정성과 용량을 확인한 뒤 별도 구현한다. 이 단계에서는 `SEOUL_OPEN_DATA_API_KEY` 없이 수동 다운로드/로컬 캐시 방식도 허용한다.

## 4. 대여소 정보

대여소 기준 정보는 서울 열린데이터광장의 `서울시 공공자전거 따릉이 대여소 정보`를 사용한다.

공식 데이터셋:

- URL: https://data.seoul.go.kr/dataList/OA-13252/F/1/datasetView.do

용도:

- station ID/name 정합성 확인
- 위도/경도 보정
- 거치대 수/capacity 기준 확인
- 반납 포화 판단 기준 생성

실시간 대여정보에도 위치와 거치대 관련 필드가 있으므로, 초기 구현은 실시간 API snapshot만으로 시작하고 대여소 정보 파일은 정합성 보정용으로 붙인다.

## 5. 날씨/공휴일 데이터

날씨 feature는 기존 프로젝트처럼 Open-Meteo를 우선 사용한다. Open-Meteo는 기본 사용에 별도 API key가 필요 없다.

공휴일은 1차 구현에서 다음 순서로 처리한다.

1. 주말/시간대/출퇴근 peak feature만 사용.
2. 한국 공휴일은 작은 static calendar file로 시작.
3. 필요할 경우 공공데이터포털 특일 정보 API를 붙이고 `DATA_GO_KR_SERVICE_KEY`를 사용한다.

## Secret 관리 원칙

- `.env` 값은 출력하지 않는다.
- README와 public docs에는 환경변수 이름만 쓴다.
- key가 필요한 명령은 `.env.example` 또는 docs에 placeholder로만 남긴다.
- raw API 응답과 대용량 zip은 Git에 넣지 않는다.
- key 미설정 시 synthetic/public cached fixture로 smoke test가 가능해야 한다.

## 최초 구현 우선순위

1. `SEOUL_OPEN_DATA_API_KEY`를 읽는 설정 layer 추가.
2. 실시간 대여정보 snapshot collector 구현.
3. key가 없을 때 synthetic fixture로 schema test 실행.
4. 대여이력 zip은 수동/로컬 캐시 계약부터 문서화.
5. 이후 data.go.kr service key가 필요한 API를 붙일지 결정.
