from __future__ import annotations

import csv
import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
DEFAULT_ENV_PATH = Path("/workspace/.env")
DEFAULT_OUTPUT_ROOT = Path("/DATA/HJ/prj/data-scientist-career/projects/bike-share-demand-resilience")
SEOUL_OPEN_DATA_API_KEY_ENV = "SEOUL_OPEN_DATA_API_KEY"
SEOUL_BIKE_LIST_URL_TEMPLATE = "http://openapi.seoul.go.kr:8088/{api_key}/json/bikeList/{start}/{end}/"
SEOUL_BIKE_LIST_REDACTED_URL_TEMPLATE = (
    "http://openapi.seoul.go.kr:8088/<SEOUL_OPEN_DATA_API_KEY>/json/bikeList/{start}/{end}/"
)
SEOUL_SUCCESS_CODE = "INFO-000"
SEOUL_SOURCE_NAME = "seoul_open_data_bikeList"
NORMALIZED_INVENTORY_COLUMNS = [
    "station_id",
    "station_name",
    "capacity",
    "bikes_available",
    "docks_available",
    "shared_rate",
    "station_lat",
    "station_lon",
    "captured_at_kst",
    "source",
]
REBALANCING_PRIORITY_COLUMNS = [
    "priority_rank",
    "station_id",
    "station_name",
    "issue_type",
    "recommended_action",
    "severity_score",
    "recommended_bikes_delta",
    "capacity",
    "bikes_available",
    "docks_available",
    "bike_shortage_threshold",
    "dock_shortage_threshold",
    "bike_fill_rate",
    "dock_fill_rate",
    "shared_rate",
    "captured_at_kst",
    "station_lat",
    "station_lon",
    "source",
]


@dataclass(frozen=True)
class FieldRule:
    field: str
    kind: str


@dataclass
class SeoulDdareungiPaths:
    output_root: Path

    @property
    def seoul_root(self) -> Path:
        return self.output_root / "seoul_ddareungi"

    @property
    def raw_dir(self) -> Path:
        return self.seoul_root / "data" / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.seoul_root / "data" / "processed"

    @property
    def snapshot_dir(self) -> Path:
        return self.seoul_root / "data" / "status_snapshots"

    @property
    def report_dir(self) -> Path:
        return self.seoul_root / "reports"

    def ensure(self) -> None:
        for path in [self.raw_dir, self.processed_dir, self.snapshot_dir, self.report_dir]:
            path.mkdir(parents=True, exist_ok=True)


REQUIRED_ROW_FIELDS = (
    FieldRule("rackTotCnt", "int"),
    FieldRule("stationName", "str"),
    FieldRule("parkingBikeTotCnt", "int"),
    FieldRule("shared", "float"),
    FieldRule("stationLatitude", "float"),
    FieldRule("stationLongitude", "float"),
    FieldRule("stationId", "str"),
)


class SeoulDdareungiError(RuntimeError):
    """Base exception for sanitized Ddareungi API failures."""


class SeoulDdareungiFetchError(SeoulDdareungiError):
    """Raised when the API cannot be fetched safely."""


class SeoulDdareungiSchemaError(SeoulDdareungiError):
    """Raised when the API response cannot be parsed as JSON."""


def load_env_file(path: Path | str = DEFAULT_ENV_PATH) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def resolve_api_key(
    env: dict[str, str] | os._Environ[str] | None = None,
    env_file: Path | str = DEFAULT_ENV_PATH,
) -> str | None:
    source = os.environ if env is None else env
    key = source.get(SEOUL_OPEN_DATA_API_KEY_ENV)
    if key:
        return key
    return load_env_file(env_file).get(SEOUL_OPEN_DATA_API_KEY_ENV)


def build_bike_list_url(api_key: str, start: int = 1, end: int = 5) -> str:
    validate_range(start, end)
    if not api_key:
        raise ValueError("api_key is required")
    return SEOUL_BIKE_LIST_URL_TEMPLATE.format(api_key=api_key, start=start, end=end)


def build_redacted_bike_list_url(start: int = 1, end: int = 5) -> str:
    validate_range(start, end)
    return SEOUL_BIKE_LIST_REDACTED_URL_TEMPLATE.format(start=start, end=end)


def validate_range(start: int, end: int) -> None:
    if start < 1:
        raise ValueError("start must be >= 1")
    if end < start:
        raise ValueError("end must be >= start")
    if end - start + 1 > 1000:
        raise ValueError("Seoul Open Data bikeList supports up to 1000 rows per request")


def fetch_bike_list(api_key: str, start: int = 1, end: int = 5, timeout: int = 15) -> dict[str, Any]:
    url = build_bike_list_url(api_key, start=start, end=end)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "bike-share-demand-resilience/0.1 schema-check"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise SeoulDdareungiFetchError(f"http_error status={exc.code}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", "unknown")
        raise SeoulDdareungiFetchError(f"url_error reason={reason}") from exc
    except TimeoutError as exc:
        raise SeoulDdareungiFetchError("timeout") from exc

    try:
        decoded = payload.decode("utf-8-sig")
        parsed = json.loads(decoded)
    except UnicodeDecodeError as exc:
        raise SeoulDdareungiSchemaError("response was not utf-8 json") from exc
    except json.JSONDecodeError as exc:
        raise SeoulDdareungiSchemaError("response was not valid json") from exc

    if not isinstance(parsed, dict):
        raise SeoulDdareungiSchemaError("response root was not an object")
    return parsed


def current_kst_stamp() -> str:
    return datetime.now(KST).strftime("%Y%m%d_%H%M%S")


def fetch_bike_pages(
    api_key: str,
    *,
    start: int = 1,
    page_size: int = 1000,
    max_pages: int = 5,
    timeout: int = 15,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")
    if not 1 <= page_size <= 1000:
        raise ValueError("page_size must be between 1 and 1000")

    rows: list[dict[str, Any]] = []
    page_summaries: list[dict[str, Any]] = []
    raw_pages: dict[str, Any] = {
        "source": SEOUL_SOURCE_NAME,
        "captured_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "pages": [],
    }

    stopped_reason = "max_pages_reached"
    for page_index in range(max_pages):
        page_start = start + page_index * page_size
        page_end = page_start + page_size - 1
        payload = fetch_bike_list(api_key, start=page_start, end=page_end, timeout=timeout)
        schema_summary = validate_bike_list_schema(payload)
        schema_summary["checked_range"] = {"start": page_start, "end": page_end}
        page_summaries.append(schema_summary)
        if not schema_summary["ok"]:
            raise SeoulDdareungiSchemaError(f"schema validation failed for range {page_start}-{page_end}")

        page_rows = extract_bike_rows(payload)
        rows.extend(page_rows)
        raw_pages["pages"].append({"range": {"start": page_start, "end": page_end}, "payload": payload})
        if len(page_rows) < page_size:
            stopped_reason = "last_partial_page"
            break

    collection_summary = {
        "ok": stopped_reason == "last_partial_page",
        "status": "collection_ok" if stopped_reason == "last_partial_page" else "collection_incomplete",
        "pages_checked": len(page_summaries),
        "total_rows": len(rows),
        "stopped_reason": stopped_reason,
    }
    return rows, page_summaries, {**raw_pages, "summary": collection_summary}


def extract_bike_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    container = payload.get("rentBikeStatus")
    if not isinstance(container, dict):
        return []
    rows = _normalize_rows(container.get("row"))
    return [row for row in rows if isinstance(row, dict)]


def normalize_bike_rows(rows: list[dict[str, Any]], captured_at_kst: str | None = None) -> list[dict[str, Any]]:
    captured_at = captured_at_kst or datetime.now(KST).isoformat(timespec="seconds")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        capacity = _safe_int(row.get("rackTotCnt"))
        bikes_available = _safe_int(row.get("parkingBikeTotCnt"))
        docks_available = None
        if capacity is not None and bikes_available is not None:
            docks_available = max(capacity - bikes_available, 0)

        normalized.append(
            {
                "station_id": _safe_str(row.get("stationId")),
                "station_name": _safe_str(row.get("stationName")),
                "capacity": capacity,
                "bikes_available": bikes_available,
                "docks_available": docks_available,
                "shared_rate": _safe_float(row.get("shared")),
                "station_lat": _safe_float(row.get("stationLatitude")),
                "station_lon": _safe_float(row.get("stationLongitude")),
                "captured_at_kst": captured_at,
                "source": SEOUL_SOURCE_NAME,
            }
        )
    return normalized


def build_inventory_summary(
    rows: list[dict[str, Any]],
    *,
    captured_at_kst: str,
    page_summaries: list[dict[str, Any]],
    min_rows: int,
) -> dict[str, Any]:
    station_ids = [row.get("station_id") for row in rows if row.get("station_id")]
    duplicate_station_rows = len(station_ids) - len(set(station_ids))
    has_complete_station_ids = len(station_ids) == len(rows)
    has_unique_station_ids = duplicate_station_rows == 0
    meets_min_rows = len(rows) >= min_rows
    capacity_values = [row.get("capacity") for row in rows if row.get("capacity") is not None]
    bike_values = [row.get("bikes_available") for row in rows if row.get("bikes_available") is not None]
    summary = {
        "ok": meets_min_rows and has_complete_station_ids and has_unique_station_ids,
        "status": "inventory_ok" if meets_min_rows and has_complete_station_ids and has_unique_station_ids else "inventory_failed",
        "source": SEOUL_SOURCE_NAME,
        "captured_at_kst": captured_at_kst,
        "row_count": len(rows),
        "unique_station_count": len(set(station_ids)),
        "duplicate_station_rows": duplicate_station_rows,
        "min_rows": min_rows,
        "capacity_non_null_rows": len(capacity_values),
        "bikes_available_non_null_rows": len(bike_values),
        "total_capacity": int(sum(capacity_values)) if capacity_values else 0,
        "total_bikes_available": int(sum(bike_values)) if bike_values else 0,
        "pages_checked": len(page_summaries),
        "page_row_counts": [page.get("row_count") for page in page_summaries],
        "schema_ok": all(bool(page.get("ok")) for page in page_summaries),
        "required_columns": NORMALIZED_INVENTORY_COLUMNS,
    }
    if not meets_min_rows:
        summary.setdefault("errors", []).append(f"row_count is below min_rows={min_rows}")
    if not has_complete_station_ids:
        summary.setdefault("errors", []).append("station_id has missing values")
    if not has_unique_station_ids:
        summary.setdefault("errors", []).append("station_id has duplicate values")
    return summary


def write_inventory_snapshot(
    rows: list[dict[str, Any]],
    *,
    paths: SeoulDdareungiPaths,
    stamp: str,
    summary: dict[str, Any],
    raw_pages: dict[str, Any] | None = None,
) -> dict[str, str]:
    paths.ensure()
    latest_path = paths.processed_dir / "latest_inventory_snapshot.csv"
    snapshot_path = paths.snapshot_dir / f"{stamp}_inventory_snapshot.csv"
    summary_path = paths.report_dir / "latest_inventory_snapshot_summary.json"
    raw_path = paths.raw_dir / f"{stamp}_bikeList_raw.json"

    _write_csv(latest_path, rows)
    _write_csv(snapshot_path, rows)
    if raw_pages is not None:
        raw_path.write_text(json.dumps(raw_pages, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_with_paths = {
        **summary,
        "latest_inventory_path": str(latest_path),
        "snapshot_inventory_path": str(snapshot_path),
        "raw_snapshot_path": str(raw_path) if raw_pages is not None else None,
    }
    summary_path.write_text(json.dumps(summary_with_paths, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "latest_inventory_path": str(latest_path),
        "snapshot_inventory_path": str(snapshot_path),
        "summary_path": str(summary_path),
        "raw_snapshot_path": str(raw_path) if raw_pages is not None else "",
    }


def build_rebalancing_priority(
    rows: list[dict[str, Any]],
    *,
    top_n: int = 50,
    shortage_ratio: float = 0.10,
    target_low_fill_ratio: float = 0.20,
    target_high_fill_ratio: float = 0.80,
    include_balanced: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if top_n < 1:
        raise ValueError("top_n must be >= 1")
    if not 0 < shortage_ratio < 0.5:
        raise ValueError("shortage_ratio must be between 0 and 0.5")

    candidates: list[dict[str, Any]] = []
    for row in rows:
        capacity = _safe_int(row.get("capacity"))
        bikes = _safe_int(row.get("bikes_available"))
        docks = _safe_int(row.get("docks_available"))
        if capacity is None or capacity <= 0 or bikes is None or docks is None:
            continue

        bike_threshold = max(1, math.ceil(capacity * shortage_ratio))
        dock_threshold = max(1, math.ceil(capacity * shortage_ratio))
        bike_gap = max(bike_threshold - bikes, 0)
        dock_gap = max(dock_threshold - docks, 0)
        bike_fill_rate = bikes / capacity
        dock_fill_rate = docks / capacity
        bike_severity = (bike_gap / bike_threshold if bike_threshold else 0.0) + max(0.0, 1.0 - bike_fill_rate)
        dock_severity = (dock_gap / dock_threshold if dock_threshold else 0.0) + max(0.0, 1.0 - dock_fill_rate)

        if bike_gap > 0 and bike_severity >= dock_severity:
            issue_type = "bike_shortage"
            action = "send_bikes"
            target_bikes = math.ceil(capacity * target_low_fill_ratio)
            recommended_delta = max(target_bikes - bikes, 1)
            severity = bike_severity
        elif dock_gap > 0:
            issue_type = "dock_shortage"
            action = "remove_bikes"
            target_bikes = math.floor(capacity * target_high_fill_ratio)
            recommended_delta = -max(bikes - target_bikes, 1)
            severity = dock_severity
        elif include_balanced:
            issue_type = "balanced"
            action = "monitor"
            recommended_delta = 0
            severity = max(abs(bike_fill_rate - 0.5), abs(dock_fill_rate - 0.5)) * 0.1
        else:
            continue

        candidates.append(
            {
                "priority_rank": 0,
                "station_id": _safe_str(row.get("station_id")),
                "station_name": _safe_str(row.get("station_name")),
                "issue_type": issue_type,
                "recommended_action": action,
                "severity_score": round(float(severity), 6),
                "recommended_bikes_delta": int(recommended_delta),
                "capacity": capacity,
                "bikes_available": bikes,
                "docks_available": docks,
                "bike_shortage_threshold": bike_threshold,
                "dock_shortage_threshold": dock_threshold,
                "bike_fill_rate": round(float(bike_fill_rate), 6),
                "dock_fill_rate": round(float(dock_fill_rate), 6),
                "shared_rate": _safe_float(row.get("shared_rate")),
                "captured_at_kst": _safe_str(row.get("captured_at_kst")),
                "station_lat": _safe_float(row.get("station_lat")),
                "station_lon": _safe_float(row.get("station_lon")),
                "source": _safe_str(row.get("source")) or SEOUL_SOURCE_NAME,
            }
        )

    candidates.sort(
        key=lambda item: (
            -float(item["severity_score"]),
            -abs(int(item["recommended_bikes_delta"])),
            str(item.get("station_id") or ""),
        )
    )
    priority_rows = candidates[:top_n]
    for rank, item in enumerate(priority_rows, start=1):
        item["priority_rank"] = rank

    action_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    for item in priority_rows:
        action = str(item["recommended_action"])
        issue = str(item["issue_type"])
        action_counts[action] = action_counts.get(action, 0) + 1
        issue_counts[issue] = issue_counts.get(issue, 0) + 1

    summary = {
        "ok": bool(priority_rows),
        "status": "priority_ok" if priority_rows else "priority_empty",
        "source": SEOUL_SOURCE_NAME,
        "input_rows": len(rows),
        "candidate_rows": len(candidates),
        "priority_rows": len(priority_rows),
        "top_n": top_n,
        "shortage_ratio": shortage_ratio,
        "action_counts": action_counts,
        "issue_counts": issue_counts,
        "total_send_bikes": int(sum(max(int(row["recommended_bikes_delta"]), 0) for row in priority_rows)),
        "total_remove_bikes": int(sum(abs(min(int(row["recommended_bikes_delta"]), 0)) for row in priority_rows)),
        "max_severity_score": max((float(row["severity_score"]) for row in priority_rows), default=0.0),
        "required_columns": REBALANCING_PRIORITY_COLUMNS,
    }
    return priority_rows, summary


def write_rebalancing_priority(
    rows: list[dict[str, Any]],
    *,
    paths: SeoulDdareungiPaths,
    summary: dict[str, Any],
) -> dict[str, str]:
    paths.ensure()
    priority_path = paths.report_dir / "rebalancing_priority.csv"
    summary_path = paths.report_dir / "rebalancing_priority_summary.json"
    _write_csv(priority_path, rows, fieldnames=REBALANCING_PRIORITY_COLUMNS)
    summary_with_path = {**summary, "priority_path": str(priority_path)}
    summary_path.write_text(json.dumps(summary_with_path, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"priority_path": str(priority_path), "priority_summary_path": str(summary_path)}


def capture_realtime_inventory(
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    *,
    env_file: Path | str = DEFAULT_ENV_PATH,
    page_size: int = 1000,
    max_pages: int = 5,
    timeout: int = 15,
    min_rows: int = 2000,
    priority_top_n: int = 50,
) -> dict[str, Any]:
    api_key = resolve_api_key(env_file=env_file)
    if not api_key:
        raise SeoulDdareungiFetchError(f"missing {SEOUL_OPEN_DATA_API_KEY_ENV}")

    stamp = current_kst_stamp()
    captured_at_kst = datetime.now(KST).isoformat(timespec="seconds")
    raw_rows, page_summaries, raw_pages = fetch_bike_pages(
        api_key,
        page_size=page_size,
        max_pages=max_pages,
        timeout=timeout,
    )
    if not raw_pages["summary"]["ok"]:
        raise SeoulDdareungiFetchError("pagination did not reach a last partial page")

    normalized_rows = normalize_bike_rows(raw_rows, captured_at_kst=captured_at_kst)
    summary = build_inventory_summary(
        normalized_rows,
        captured_at_kst=captured_at_kst,
        page_summaries=page_summaries,
        min_rows=min_rows,
    )
    paths = SeoulDdareungiPaths(Path(output_root))
    output_paths = write_inventory_snapshot(
        normalized_rows,
        paths=paths,
        stamp=stamp,
        summary=summary,
        raw_pages=raw_pages,
    )
    priority_rows, priority_summary = build_rebalancing_priority(normalized_rows, top_n=priority_top_n)
    priority_paths = write_rebalancing_priority(priority_rows, paths=paths, summary=priority_summary)
    return {
        **summary,
        **output_paths,
        "priority": {**priority_summary, **priority_paths},
    }


def validate_bike_list_schema(
    payload: dict[str, Any],
    *,
    min_rows: int = 1,
    max_reported_issues: int = 20,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "ok": False,
        "checked_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "dataset": "seoul_ddareungi_bikeList",
        "required_env": SEOUL_OPEN_DATA_API_KEY_ENV,
        "required_container": "rentBikeStatus.row",
        "required_fields": [rule.field for rule in REQUIRED_ROW_FIELDS],
        "result_code": None,
        "result_message": None,
        "list_total_count": None,
        "row_count": 0,
        "missing_fields": [],
        "type_errors": [],
        "range_errors": [],
        "errors": [],
    }

    if not isinstance(payload, dict):
        summary["errors"].append("response root is not an object")
        return summary

    result = _extract_result(payload)
    summary["result_code"] = result.get("CODE")
    summary["result_message"] = result.get("MESSAGE")
    if summary["result_code"] and summary["result_code"] != SEOUL_SUCCESS_CODE:
        summary["errors"].append("api result code is not success")

    container = payload.get("rentBikeStatus")
    if not isinstance(container, dict):
        summary["errors"].append("missing rentBikeStatus object")
        return summary

    summary["list_total_count"] = _safe_int(container.get("list_total_count"))
    rows = _normalize_rows(container.get("row"))
    summary["row_count"] = len(rows)
    if len(rows) < min_rows:
        summary["errors"].append(f"row count is below min_rows={min_rows}")

    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            _append_limited(summary["type_errors"], {"row": row_index, "field": "row", "expected": "object"}, max_reported_issues)
            continue
        for rule in REQUIRED_ROW_FIELDS:
            value = row.get(rule.field)
            if _is_missing(value):
                _append_limited(summary["missing_fields"], {"row": row_index, "field": rule.field}, max_reported_issues)
                continue
            if not _matches_kind(value, rule.kind):
                _append_limited(
                    summary["type_errors"],
                    {"row": row_index, "field": rule.field, "expected": rule.kind},
                    max_reported_issues,
                )

        lat = _safe_float(row.get("stationLatitude"))
        lon = _safe_float(row.get("stationLongitude"))
        if lat is not None and not (33.0 <= lat <= 39.5):
            _append_limited(summary["range_errors"], {"row": row_index, "field": "stationLatitude"}, max_reported_issues)
        if lon is not None and not (124.0 <= lon <= 132.5):
            _append_limited(summary["range_errors"], {"row": row_index, "field": "stationLongitude"}, max_reported_issues)

    if summary["list_total_count"] is not None and summary["list_total_count"] < summary["row_count"]:
        summary["errors"].append("list_total_count is smaller than row_count")

    summary["ok"] = not any(
        [
            summary["errors"],
            summary["missing_fields"],
            summary["type_errors"],
            summary["range_errors"],
        ]
    )
    return summary


def write_schema_report(summary: dict[str, Any], output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path:
    report_dir = Path(output_root) / "seoul_ddareungi" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "seoul_ddareungi_schema_check.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def _extract_result(payload: dict[str, Any]) -> dict[str, Any]:
    container = payload.get("rentBikeStatus")
    if isinstance(container, dict) and isinstance(container.get("RESULT"), dict):
        return container["RESULT"]
    result = payload.get("RESULT")
    if isinstance(result, dict):
        return result
    return {}


def _normalize_rows(rows: Any) -> list[Any]:
    if rows is None:
        return []
    if isinstance(rows, list):
        return rows
    if isinstance(rows, dict):
        return [rows]
    return [rows]


def _append_limited(items: list[Any], value: Any, limit: int) -> None:
    if len(items) < limit:
        items.append(value)


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _matches_kind(value: Any, kind: str) -> bool:
    if kind == "str":
        return isinstance(value, str) and bool(value.strip())
    if kind == "int":
        return _safe_int(value) is not None
    if kind == "float":
        return _safe_float(value) is not None
    raise ValueError(f"unsupported field kind: {kind}")


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or _is_missing(value):
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not parsed.is_integer():
        return None
    return int(parsed)


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or _is_missing(value):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _safe_str(value: Any) -> str | None:
    if _is_missing(value):
        return None
    return str(value).strip()


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    columns = fieldnames or NORMALIZED_INVENTORY_COLUMNS
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})
