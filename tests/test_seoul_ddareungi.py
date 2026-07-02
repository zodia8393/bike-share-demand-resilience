from bike_share_resilience.seoul_ddareungi import (
    SeoulDdareungiPaths,
    build_inventory_summary,
    build_redacted_bike_list_url,
    build_rebalancing_priority,
    extract_bike_rows,
    load_env_file,
    normalize_bike_rows,
    resolve_api_key,
    validate_bike_list_schema,
    write_inventory_snapshot,
    write_rebalancing_priority,
)


def valid_payload():
    return {
        "rentBikeStatus": {
            "list_total_count": 2,
            "RESULT": {"CODE": "INFO-000", "MESSAGE": "ok"},
            "row": [
                {
                    "rackTotCnt": "10",
                    "stationName": "102. Station A",
                    "parkingBikeTotCnt": "4",
                    "shared": "40",
                    "stationLatitude": "37.555",
                    "stationLongitude": "126.970",
                    "stationId": "ST-1",
                },
                {
                    "rackTotCnt": 20,
                    "stationName": "103. Station B",
                    "parkingBikeTotCnt": 0,
                    "shared": 0,
                    "stationLatitude": 37.556,
                    "stationLongitude": 126.971,
                    "stationId": "ST-2",
                },
            ],
        }
    }


def test_validate_bike_list_schema_accepts_valid_payload():
    summary = validate_bike_list_schema(valid_payload())

    assert summary["ok"] is True
    assert summary["result_code"] == "INFO-000"
    assert summary["list_total_count"] == 2
    assert summary["row_count"] == 2
    assert summary["missing_fields"] == []
    assert summary["type_errors"] == []


def test_validate_bike_list_schema_rejects_missing_container():
    summary = validate_bike_list_schema({"RESULT": {"CODE": "INFO-000"}})

    assert summary["ok"] is False
    assert "missing rentBikeStatus object" in summary["errors"]


def test_validate_bike_list_schema_reports_api_error_code():
    payload = {"RESULT": {"CODE": "ERROR-300", "MESSAGE": "invalid request"}}
    summary = validate_bike_list_schema(payload)

    assert summary["ok"] is False
    assert summary["result_code"] == "ERROR-300"
    assert "api result code is not success" in summary["errors"]


def test_validate_bike_list_schema_reports_missing_field():
    payload = valid_payload()
    del payload["rentBikeStatus"]["row"][0]["stationId"]

    summary = validate_bike_list_schema(payload)

    assert summary["ok"] is False
    assert {"row": 0, "field": "stationId"} in summary["missing_fields"]


def test_validate_bike_list_schema_reports_numeric_type_error():
    payload = valid_payload()
    payload["rentBikeStatus"]["row"][0]["parkingBikeTotCnt"] = "many"

    summary = validate_bike_list_schema(payload)

    assert summary["ok"] is False
    assert {"row": 0, "field": "parkingBikeTotCnt", "expected": "int"} in summary["type_errors"]


def test_validate_bike_list_schema_reports_coordinate_range_error():
    payload = valid_payload()
    payload["rentBikeStatus"]["row"][0]["stationLatitude"] = "91.0"

    summary = validate_bike_list_schema(payload)

    assert summary["ok"] is False
    assert {"row": 0, "field": "stationLatitude"} in summary["range_errors"]


def test_load_env_file_and_resolve_api_key_without_printing_secret(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "export SEOUL_OPEN_DATA_API_KEY='secret-value'",
                "DATA_GO_KR_SERVICE_KEY=secondary-secret",
            ]
        ),
        encoding="utf-8",
    )

    values = load_env_file(env_file)
    key = resolve_api_key(env={}, env_file=env_file)

    assert values["SEOUL_OPEN_DATA_API_KEY"] == "secret-value"
    assert values["DATA_GO_KR_SERVICE_KEY"] == "secondary-secret"
    assert key == "secret-value"


def test_redacted_url_never_contains_real_key():
    url = build_redacted_bike_list_url(1, 5)

    assert "<SEOUL_OPEN_DATA_API_KEY>" in url
    assert "secret" not in url


def test_extract_and_normalize_bike_rows_to_inventory_contract():
    rows = extract_bike_rows(valid_payload())
    normalized = normalize_bike_rows(rows, captured_at_kst="2026-07-02T19:00:00+09:00")

    assert normalized[0] == {
        "station_id": "ST-1",
        "station_name": "102. Station A",
        "capacity": 10,
        "bikes_available": 4,
        "docks_available": 6,
        "shared_rate": 40.0,
        "station_lat": 37.555,
        "station_lon": 126.97,
        "captured_at_kst": "2026-07-02T19:00:00+09:00",
        "source": "seoul_open_data_bikeList",
    }


def test_normalize_bike_rows_clips_negative_docks_to_zero():
    rows = [
        {
            "rackTotCnt": "3",
            "stationName": "overflow station",
            "parkingBikeTotCnt": "5",
            "shared": "166",
            "stationLatitude": "37.5",
            "stationLongitude": "127.0",
            "stationId": "ST-overflow",
        }
    ]

    normalized = normalize_bike_rows(rows, captured_at_kst="2026-07-02T19:00:00+09:00")

    assert normalized[0]["docks_available"] == 0


def test_build_inventory_summary_requires_rows_and_station_ids():
    rows = normalize_bike_rows(extract_bike_rows(valid_payload()), captured_at_kst="2026-07-02T19:00:00+09:00")
    page_summaries = [validate_bike_list_schema(valid_payload())]

    summary = build_inventory_summary(
        rows,
        captured_at_kst="2026-07-02T19:00:00+09:00",
        page_summaries=page_summaries,
        min_rows=2,
    )

    assert summary["ok"] is True
    assert summary["row_count"] == 2
    assert summary["unique_station_count"] == 2
    assert summary["total_capacity"] == 30
    assert summary["total_bikes_available"] == 4


def test_build_inventory_summary_rejects_duplicate_station_ids():
    rows = normalize_bike_rows(extract_bike_rows(valid_payload()), captured_at_kst="2026-07-02T19:00:00+09:00")
    rows[1]["station_id"] = rows[0]["station_id"]

    summary = build_inventory_summary(
        rows,
        captured_at_kst="2026-07-02T19:00:00+09:00",
        page_summaries=[validate_bike_list_schema(valid_payload())],
        min_rows=2,
    )

    assert summary["ok"] is False
    assert summary["duplicate_station_rows"] == 1
    assert "station_id has duplicate values" in summary["errors"]


def test_write_inventory_snapshot_writes_csv_and_summary_without_secret(tmp_path):
    rows = normalize_bike_rows(extract_bike_rows(valid_payload()), captured_at_kst="2026-07-02T19:00:00+09:00")
    summary = build_inventory_summary(
        rows,
        captured_at_kst="2026-07-02T19:00:00+09:00",
        page_summaries=[validate_bike_list_schema(valid_payload())],
        min_rows=2,
    )

    paths = write_inventory_snapshot(
        rows,
        paths=SeoulDdareungiPaths(tmp_path),
        stamp="20260702_190000",
        summary=summary,
        raw_pages={"source": "fixture", "pages": []},
    )

    latest = tmp_path / "seoul_ddareungi" / "data" / "processed" / "latest_inventory_snapshot.csv"
    snapshot = tmp_path / "seoul_ddareungi" / "data" / "status_snapshots" / "20260702_190000_inventory_snapshot.csv"
    summary_text = (tmp_path / "seoul_ddareungi" / "reports" / "latest_inventory_snapshot_summary.json").read_text(encoding="utf-8")

    assert latest.exists()
    assert snapshot.exists()
    assert paths["raw_snapshot_path"].endswith("20260702_190000_bikeList_raw.json")
    assert "secret-value" not in summary_text


def test_build_rebalancing_priority_flags_live_shortage_actions():
    rows = normalize_bike_rows(
        [
            {
                "rackTotCnt": "10",
                "stationName": "empty station",
                "parkingBikeTotCnt": "0",
                "shared": "0",
                "stationLatitude": "37.5",
                "stationLongitude": "127.0",
                "stationId": "ST-empty",
            },
            {
                "rackTotCnt": "10",
                "stationName": "full station",
                "parkingBikeTotCnt": "10",
                "shared": "100",
                "stationLatitude": "37.6",
                "stationLongitude": "127.1",
                "stationId": "ST-full",
            },
        ],
        captured_at_kst="2026-07-02T19:00:00+09:00",
    )

    priority, summary = build_rebalancing_priority(rows, top_n=10)

    actions = {row["station_id"]: row["recommended_action"] for row in priority}
    deltas = {row["station_id"]: row["recommended_bikes_delta"] for row in priority}
    assert summary["ok"] is True
    assert actions["ST-empty"] == "send_bikes"
    assert actions["ST-full"] == "remove_bikes"
    assert deltas["ST-empty"] > 0
    assert deltas["ST-full"] < 0


def test_build_rebalancing_priority_rejects_empty_top_n():
    rows = normalize_bike_rows(extract_bike_rows(valid_payload()), captured_at_kst="2026-07-02T19:00:00+09:00")

    try:
        build_rebalancing_priority(rows, top_n=0)
    except ValueError as exc:
        assert "top_n must be >= 1" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_write_rebalancing_priority_writes_csv_and_summary(tmp_path):
    rows = normalize_bike_rows(
        [
            {
                "rackTotCnt": "10",
                "stationName": "empty station",
                "parkingBikeTotCnt": "0",
                "shared": "0",
                "stationLatitude": "37.5",
                "stationLongitude": "127.0",
                "stationId": "ST-empty",
            }
        ],
        captured_at_kst="2026-07-02T19:00:00+09:00",
    )
    priority, summary = build_rebalancing_priority(rows)

    paths = write_rebalancing_priority(priority, paths=SeoulDdareungiPaths(tmp_path), summary=summary)

    assert (tmp_path / "seoul_ddareungi" / "reports" / "rebalancing_priority.csv").exists()
    assert paths["priority_summary_path"].endswith("rebalancing_priority_summary.json")
