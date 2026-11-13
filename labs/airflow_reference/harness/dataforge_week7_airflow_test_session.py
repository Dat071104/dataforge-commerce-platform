"""Process-safe, no-network HTTP stand-in for the scheduler harness only."""

from __future__ import annotations

import json
import os
from pathlib import Path

from requests.exceptions import ConnectionError

from dataforge_week7_weather_cloud import INGEST_JOB, PROJECT_ID, REGION


class _Response:
    def __init__(self, status_code: int, body: dict[str, object]) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, object]:
        return self._body


def _record(value: dict[str, object]) -> None:
    ledger = Path(os.environ["DATAFORGE_AIRFLOW_HARNESS_LEDGER"])
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(ledger, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)


class _FakeAuthorizedSession:
    """Return only the expected scheduler/Cloud Run responses; never use sockets."""

    def __init__(self) -> None:
        self.scenario = os.environ["DATAFORGE_AIRFLOW_HARNESS_SCENARIO"]
        self.state_dir = Path(os.environ["DATAFORGE_AIRFLOW_HARNESS_STATE_DIR"])

    def get(self, url: str, *, timeout: tuple[int, int]) -> _Response:
        if "cloudscheduler.googleapis.com" in url:
            _record({"method": "GET", "target": "cloud_scheduler_preflight", "timeout": timeout})
            return _Response(404, {})
        if url.endswith("/fake-operation"):
            _record({"method": "GET", "target": "cloud_run_operation", "timeout": timeout})
            return _Response(
                200,
                {
                    "done": True,
                    "response": {
                        "name": (
                            f"projects/{PROJECT_ID}/locations/{REGION}/jobs/"
                            f"{INGEST_JOB}/executions/fake-execution"
                        )
                    },
                },
            )
        raise AssertionError("scheduler harness received an unexpected GET target")

    def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        timeout: tuple[int, int],
    ) -> _Response:
        args = json["overrides"]["containerOverrides"][0]["args"]
        first_transient = False
        if self.scenario == "retry_once":
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
                "target": "cloud_run_ingest",
                "args": args,
                "timeout": timeout,
                "injected_transport_failure": first_transient,
            }
        )
        if first_transient:
            raise ConnectionError("scheduler harness injected one transient transport failure")
        if self.scenario == "forbidden":
            return _Response(403, {"error": "test-only forbidden response"})

        return _Response(
            201,
            {
                "name": (
                    f"projects/{PROJECT_ID}/locations/{REGION}/operations/fake-operation"
                )
            },
        )


def make_authorized_session() -> _FakeAuthorizedSession:
    return _FakeAuthorizedSession()
