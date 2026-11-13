"""Pure request and receipt contracts for the optional Mini-project 3 Airflow DAG."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

PROJECT_ID = "dataforge-p7-lab-d0f725"
REGION = "us-central1"
BRONZE_BUCKET = "dataforge-p7-lab-d0f725-bronze"
WEATHER_PREFIX = "weather_mini3/v1"
PROVINCES = ("HCM", "HN", "DN")
SOURCE_SETTLING_LAG_DAYS = 7
PIPELINE_TIMEZONE = "Asia/Ho_Chi_Minh"
EXECUTION_RECEIPT_SCHEMA = "dataforge.weather.mini3.execution.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_INVOCATION_ID = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised when an Airflow configuration or cloud receipt is out of contract."""


class ReceiptNotFound(LookupError):
    """Raised by a receipt reader while the immutable object is not yet visible."""


class ReceiptTimeout(ContractError):
    """Raised after the bounded post-job receipt visibility window expires."""


def cloud_opt_in_enabled(value: str | None) -> bool:
    """Parse the separate deployment authorization switch; missing means OFF."""
    if value is None or not value.strip():
        return False
    normalized = value.strip().lower()
    if normalized == "false":
        return False
    if normalized == "true":
        return True
    raise ContractError("DATAFORGE_WEATHER_CLOUD_ENABLED must be exactly 'true' or 'false'")


def is_retryable_http_status(status_code: int) -> bool:
    """Only classify standard transient request statuses as retryable."""
    if isinstance(status_code, bool) or not isinstance(status_code, int):
        return False
    return status_code in {408, 429} or 500 <= status_code <= 599


def is_retryable_cloud_operation_error(error: Any) -> bool:
    """Classify retryable google.rpc.Status codes without exposing provider text."""
    if not isinstance(error, Mapping):
        return False
    code = error.get("code")
    if isinstance(code, bool) or not isinstance(code, int):
        return False
    return code in {4, 8, 13, 14}  # DEADLINE_EXCEEDED, RESOURCE_EXHAUSTED, INTERNAL, UNAVAILABLE


def wait_for_execution_receipt(
    read: Callable[[], Any],
    *,
    timeout_seconds: float = 120,
    poll_interval_seconds: float = 2,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Boundedly wait for the post-job receipt without Airflow occupying a sensor slot."""
    if timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise ContractError("receipt wait bounds must be positive")
    deadline = monotonic() + timeout_seconds
    while True:
        try:
            return read()
        except ReceiptNotFound as exc:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ReceiptTimeout(
                    "timed out waiting for the completed invocation receipt"
                ) from exc
            sleep(min(poll_interval_seconds, remaining))


def make_invocation_id(dag_id: str, run_id: str) -> str:
    """Return a stable, path-safe identifier for retries of the same DagRun."""
    if not dag_id or not run_id:
        raise ContractError("DAG and run identifiers are required")
    return hashlib.sha256(f"{dag_id}\0{run_id}".encode("utf-8")).hexdigest()


def weather_dbt_vars_argument(observation_date: str) -> str:
    """Serialize the one validated partition date passed to Mini3 dbt tasks."""
    if not isinstance(observation_date, str):
        raise ContractError("dbt observation date must be an ISO YYYY-MM-DD string")
    try:
        parsed_date = date.fromisoformat(observation_date)
    except ValueError as exc:
        raise ContractError("dbt observation date must be an ISO YYYY-MM-DD string") from exc
    if parsed_date.isoformat() != observation_date:
        raise ContractError("dbt observation date must use canonical YYYY-MM-DD form")
    return json.dumps(
        {"weather_observation_date": parsed_date.isoformat()},
        sort_keys=True,
        separators=(",", ":"),
    )


def invocation_receipt_object(invocation_id: str) -> str:
    if not _INVOCATION_ID.fullmatch(invocation_id):
        raise ContractError("invocation ID must be a lowercase SHA-256 digest")
    return f"{WEATHER_PREFIX}/executions/invocation_id={invocation_id}.json"


def resolve_request(
    *,
    params: Mapping[str, Any],
    dag_id: str,
    run_id: str,
    logical_date: datetime,
    data_interval_end: datetime | None = None,
) -> dict[str, Any]:
    """Resolve a manual or scheduled run from validated Params and fixed run dates.

    ``data_interval_end`` is the schedule boundary. It is fixed for a DagRun and
    therefore makes retries resolve the same settled date even when they happen
    on a later wall-clock day. A manual date is an explicit input override.
    """
    if not isinstance(params, Mapping):
        raise ContractError("Airflow Params must be a JSON object")
    if set(params) - {"mode", "observation_date"}:
        raise ContractError("Airflow Params contain unsupported keys")

    mode = params.get("mode", "scheduled")
    if not isinstance(mode, str) or mode not in {"scheduled", "manual"}:
        raise ContractError("mode must be either 'scheduled' or 'manual'")
    raw_date = params.get("observation_date")
    if mode == "scheduled" and raw_date is not None:
        raise ContractError("scheduled runs cannot override observation_date; use manual mode")

    anchor = data_interval_end or logical_date
    if not isinstance(logical_date, datetime) or not isinstance(anchor, datetime):
        raise ContractError("Airflow logical and interval dates must be datetimes")
    if anchor.tzinfo is None or logical_date.tzinfo is None:
        raise ContractError("Airflow logical and interval dates must be timezone-aware")
    anchor_date = anchor.astimezone(ZoneInfo(PIPELINE_TIMEZONE)).date()
    latest_safe_date = anchor_date - timedelta(days=SOURCE_SETTLING_LAG_DAYS)

    if raw_date is None:
        observation_date = latest_safe_date
    elif isinstance(raw_date, str):
        try:
            observation_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ContractError("observation_date must be an ISO YYYY-MM-DD date") from exc
        if observation_date.isoformat() != raw_date:
            raise ContractError("observation_date must use canonical YYYY-MM-DD form")
    else:
        raise ContractError("observation_date must be a string")

    if observation_date < date(1940, 1, 1):
        raise ContractError("observation_date precedes the ERA5 historical range")
    if observation_date > latest_safe_date:
        raise ContractError("observation_date is newer than the seven-day source-settling limit")

    return {
        "mode": mode,
        "project_id": PROJECT_ID,
        "region": REGION,
        "bucket": BRONZE_BUCKET,
        "observation_date": observation_date.isoformat(),
        "provinces": list(PROVINCES),
        "invocation_id": make_invocation_id(dag_id, run_id),
        "dag_run_id": run_id,
    }


def validate_execution_receipt(
    value: Any,
    *,
    expected_invocation_id: str,
    expected_observation_date: str,
    object_generation: int,
) -> dict[str, Any]:
    """Fail closed on malformed or mismatched GCS execution receipts."""
    if not isinstance(value, dict):
        raise ContractError("execution receipt must be a JSON object")
    if value.get("schema_version") != EXECUTION_RECEIPT_SCHEMA:
        raise ContractError("execution receipt schema version is unsupported")
    if value.get("status") != "COMPLETE":
        raise ContractError("execution receipt is not COMPLETE")
    if value.get("invocation_id") != expected_invocation_id:
        raise ContractError("execution receipt invocation ID does not match this DagRun")
    if value.get("observation_date") != expected_observation_date:
        raise ContractError("execution receipt observation date does not match this DagRun")
    if value.get("provinces") != list(PROVINCES):
        raise ContractError("execution receipt province allowlist does not match")
    if value.get("provider") != "Open-Meteo" or value.get("model") != "era5":
        raise ContractError("execution receipt source identity does not match the approved contract")
    if value.get("settling_lag_days") != SOURCE_SETTLING_LAG_DAYS:
        raise ContractError("execution receipt settling lag does not match")
    if value.get("attribution_url") != "https://open-meteo.com/":
        raise ContractError("execution receipt attribution is missing or unexpected")

    request_id = value.get("request_id")
    source_sha256 = value.get("source_sha256")
    manifest_generation = value.get("manifest_generation")
    row_count = value.get("row_count")
    manifest_uri = value.get("manifest_uri")
    if not isinstance(request_id, str) or not _SHA256.fullmatch(request_id):
        raise ContractError("execution receipt request ID is invalid")
    if not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256):
        raise ContractError("execution receipt source checksum is invalid")
    if isinstance(manifest_generation, bool) or not isinstance(manifest_generation, int):
        raise ContractError("execution receipt manifest generation must be an integer")
    if manifest_generation <= 0:
        raise ContractError("execution receipt manifest generation must be positive")
    if isinstance(row_count, bool) or not isinstance(row_count, int):
        raise ContractError("execution receipt row count must be an integer")
    if row_count != len(PROVINCES):
        raise ContractError("execution receipt row count must be one per allowed province")
    expected_uri = (
        f"gs://{BRONZE_BUCKET}/{WEATHER_PREFIX}/manifests/"
        f"observation_date={expected_observation_date}/request_id={request_id}/manifest.json"
    )
    if manifest_uri != expected_uri:
        raise ContractError("execution receipt manifest URI is outside the approved immutable prefix")
    if isinstance(object_generation, bool) or not isinstance(object_generation, int):
        raise ContractError("GCS execution receipt generation must be an integer")
    if object_generation <= 0:
        raise ContractError("GCS execution receipt generation must be positive")

    # Keep the Airflow XCom limited to immutable identifiers and aggregate counts.
    return {
        "invocation_id": expected_invocation_id,
        "observation_date": expected_observation_date,
        "request_id": request_id,
        "source_sha256": source_sha256,
        "manifest_uri": manifest_uri,
        "manifest_generation": manifest_generation,
        "invocation_receipt_generation": object_generation,
        "row_count": row_count,
    }
