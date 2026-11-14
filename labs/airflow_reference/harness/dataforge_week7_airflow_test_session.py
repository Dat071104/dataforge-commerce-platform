"""Process-safe, no-network HTTP stand-in for the scheduler harness only."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from dataforge_week7_weather_cloud import PROJECT_ID, REGION
from dataforge_week7_weather_logic import (
    BRONZE_BUCKET,
    EXECUTION_RECEIPT_SCHEMA,
    PROVINCES,
    SOURCE_SETTLING_LAG_DAYS,
    WEATHER_PREFIX,
)
from requests.exceptions import ConnectionError


class _Response:
    def __init__(self, status_code: int, body: dict[str, object]) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, object]:
        return self._body


def _record(value: dict[str, object]) -> None:
    value.setdefault("dag_run_id", os.environ.get("AIRFLOW_CTX_DAG_RUN_ID"))
    ledger = Path(os.environ["DATAFORGE_AIRFLOW_HARNESS_LEDGER"])
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(ledger, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)


def _ledger_rows() -> list[dict[str, object]]:
    ledger = Path(os.environ["DATAFORGE_AIRFLOW_HARNESS_LEDGER"])
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]


def _fake_landing_insert(manifest_uri: str) -> dict[str, int]:
    receipt = next(
        (
            row
            for row in reversed(_ledger_rows())
            if row.get("target") == "fake_execution_receipt" and row.get("manifest_uri") == manifest_uri
        ),
        None,
    )
    if receipt is None:
        raise AssertionError("fake landing received a manifest with no matching invocation receipt")
    state_dir = Path(os.environ["DATAFORGE_AIRFLOW_HARNESS_STATE_DIR"])
    key_dir = state_dir / "landing_keys"
    key_dir.mkdir(exist_ok=True)
    rows_path = state_dir / "fake_landing_rows.jsonl"
    new_rows = 0
    duplicate_rows = 0
    for province in receipt["provinces"]:
        key = f"{receipt['observation_date']}|{province}"
        marker = key_dir / hashlib.sha256(key.encode()).hexdigest()
        try:
            descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            duplicate_rows += 1
            continue
        os.close(descriptor)
        row = {
            "observation_date": receipt["observation_date"],
            "province": province,
            "invocation_id": receipt["invocation_id"],
        }
        encoded = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        descriptor = os.open(rows_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, encoded)
        finally:
            os.close(descriptor)
        new_rows += 1
    result = {
        "observation_date_count": 1,
        "new_rows": new_rows,
        "duplicate_rows": duplicate_rows,
    }
    _record({"target": "fake_landing_insert", **result, "manifest_uri": manifest_uri})
    return result


def make_fake_execution_receipt(
    request: dict[str, object], expected_generation: int
) -> tuple[dict[str, object], int]:
    """Return a contract-valid receipt and map its request ID for fake landing writes."""
    invocation_id = str(request["invocation_id"])
    observation_date = str(request["observation_date"])
    request_id = hashlib.sha256(f"request:{invocation_id}".encode()).hexdigest()
    source_sha256 = hashlib.sha256(f"source:{observation_date}".encode()).hexdigest()
    manifest_uri = (
        f"gs://{BRONZE_BUCKET}/{WEATHER_PREFIX}/manifests/"
        f"observation_date={observation_date}/request_id={request_id}/manifest.json"
    )
    receipt: dict[str, object] = {
        "schema_version": EXECUTION_RECEIPT_SCHEMA,
        "status": "COMPLETE",
        "invocation_id": invocation_id,
        "observation_date": observation_date,
        "provinces": list(PROVINCES),
        "provider": "Open-Meteo",
        "model": "era5",
        "settling_lag_days": SOURCE_SETTLING_LAG_DAYS,
        "attribution_url": "https://open-meteo.com/",
        "request_id": request_id,
        "source_sha256": source_sha256,
        "manifest_generation": 1,
        "row_count": len(PROVINCES),
        "manifest_uri": manifest_uri,
    }
    _record(
        {
            "target": "fake_execution_receipt",
            "invocation_id": invocation_id,
            "observation_date": observation_date,
            "provinces": list(PROVINCES),
            "request_id": request_id,
            "manifest_uri": manifest_uri,
        }
    )
    return receipt, expected_generation


class _FakeAuthorizedSession:
    """Return only the expected scheduler/Cloud Run responses; never use sockets."""

    def __init__(self) -> None:
        self.scenario = os.environ["DATAFORGE_AIRFLOW_HARNESS_SCENARIO"]
        self.state_dir = Path(os.environ["DATAFORGE_AIRFLOW_HARNESS_STATE_DIR"])

    def _next_counter(self, name: str) -> int:
        counter = self.state_dir / f"{name}.counter"
        try:
            value = int(counter.read_text())
        except FileNotFoundError:
            value = 0
        value += 1
        counter.write_text(str(value))
        return value

    def get(self, url: str, *, timeout: tuple[int, int]) -> _Response:
        if "cloudscheduler.googleapis.com" in url:
            _record({"method": "GET", "target": "cloud_scheduler_preflight", "timeout": timeout})
            return _Response(404, {})
        if "/operations/fake-operation-" in url:
            operation_id = url.rsplit("/", 1)[-1]
            poll_number = self._next_counter(f"{operation_id}-poll")
            operation_record = next(
                (
                    row
                    for row in reversed(_ledger_rows())
                    if row.get("target") == "cloud_run_operation_submitted"
                    and row.get("operation_id") == operation_id
                ),
                None,
            )
            if operation_record is None:
                raise AssertionError("sensor polled an unknown fake Cloud Run operation")
            _record(
                {
                    "method": "GET",
                    "target": "cloud_run_operation",
                    "operation_id": operation_id,
                    "job_name": operation_record["job_name"],
                    "poll_number": poll_number,
                    "timeout": timeout,
                }
            )
            pending_pokes = 8 if self.scenario == "deadline" else 1
            if poll_number <= pending_pokes:
                return _Response(200, {"done": False})
            return _Response(
                200,
                {
                    "done": True,
                    "response": {
                        "name": (
                            f"projects/{PROJECT_ID}/locations/{REGION}/jobs/"
                            f"{operation_record['job_name']}/executions/"
                            f"{operation_id.removeprefix('fake-operation-')}"
                        )
                    },
                },
            )
        if "/executions/" in url:
            _record({"method": "GET", "target": "cloud_run_execution", "timeout": timeout})
            completion_status = (
                "EXECUTION_FAILED" if self.scenario == "execution_failed" else "EXECUTION_SUCCEEDED"
            )
            return _Response(200, {"completionStatus": completion_status})
        if "storage.googleapis.com/storage/v1/b/" in url:
            receipt_key = hashlib.sha256(url.encode()).hexdigest()[:16]
            receipt_number = self._next_counter(f"receipt-metadata-{receipt_key}")
            _record(
                {
                    "method": "GET",
                    "target": "invocation_receipt_metadata",
                    "poll_number": receipt_number,
                    "timeout": timeout,
                }
            )
            if receipt_number == 1:
                return _Response(404, {})
            return _Response(200, {"generation": "123"})
        raise AssertionError("scheduler harness received an unexpected GET target")

    def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        timeout: tuple[int, int],
    ) -> _Response:
        args = json["overrides"]["containerOverrides"][0]["args"]
        job_name = url.split("/jobs/", 1)[1].split(":run", 1)[0]
        command = args[0] if args else "unknown"
        first_transient = False
        if self.scenario == "retry_once" and command == "ingest":
            marker = self.state_dir / "transient_failure_injected"
            try:
                descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
                first_transient = True

        _record(
            {
                "method": "POST",
                "target": f"cloud_run_{command}",
                "job_name": job_name,
                "args": args,
                "timeout": timeout,
                "injected_transport_failure": first_transient,
            }
        )
        if first_transient:
            raise ConnectionError("scheduler harness injected one transient transport failure")
        if self.scenario == "forbidden" and command == "ingest":
            return _Response(403, {"error": "test-only forbidden response"})

        operation_number = self._next_counter("operation")
        operation_id = f"fake-operation-{operation_number}"
        _record(
            {
                "target": "cloud_run_operation_submitted",
                "operation_id": operation_id,
                "job_name": job_name,
                "args": args,
            }
        )
        if self.scenario == "backfill" and command == "land":
            manifest_uri = args[args.index("--manifest-uri") + 1]
            _fake_landing_insert(manifest_uri)

        return _Response(
            201,
            {
                "name": (
                    f"projects/{PROJECT_ID}/locations/{REGION}/operations/{operation_id}"
                )
            },
        )


def make_authorized_session() -> _FakeAuthorizedSession:
    return _FakeAuthorizedSession()
