"""Run a bounded Cloud Run dbt full-refresh for candidate repair/parity."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from dataforge.settings import ROOT

TARGET_FILE = ROOT / "docs" / "cloud" / "target.json"
EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
EXPECTED_PROJECT_NUMBER = "955038620072"
EXPECTED_REGION = "us-central1"
JOB_ID = "dataforge-week7-dbt"
RUN_API = "https://run.googleapis.com/v2"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class Week7DbtJobError(RuntimeError):
    """The approved target, invocation, or Cloud Run Job run failed."""


def _target() -> dict[str, Any]:
    try:
        target = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Week7DbtJobError("The approved target file is missing or invalid") from exc
    if (
        target.get("project_id") != EXPECTED_PROJECT
        or target.get("project_number") != EXPECTED_PROJECT_NUMBER
        or target.get("region") != EXPECTED_REGION
    ):
        raise Week7DbtJobError("Full-refresh execution is restricted to the approved project")
    return target


def run_full_refresh(
    *,
    target_dataset: str,
    batch_id: str,
    manifest_generation: int,
    upper_seq: int,
    run_mode: str,
    execute: bool,
    output: Path | None = None,
) -> dict[str, Any]:
    if target_dataset not in {"dev", "full"}:
        raise Week7DbtJobError("target_dataset must be dev or full")
    if not _SHA256.fullmatch(batch_id):
        raise Week7DbtJobError("batch_id must be a lowercase SHA-256 digest")
    if manifest_generation <= 0 or upper_seq <= 0:
        raise Week7DbtJobError("manifest_generation and upper_seq must be positive")
    if run_mode not in {"normal", "backfill"}:
        raise Week7DbtJobError("run_mode must be normal or backfill")

    target = _target()
    workflow_run_id = f"repair-{uuid4().hex}"
    variables = {
        "workflow_run_id": workflow_run_id,
        "batch_id": batch_id,
        "manifest_generation": manifest_generation,
        "upper_seq": upper_seq,
        "run_mode": run_mode,
        "test_fail_dbt_build": False,
    }
    args = [
        "build",
        "--full-refresh",
        "--target",
        target_dataset,
        "--vars",
        json.dumps(variables, separators=(",", ":")),
    ]
    receipt: dict[str, Any] = {
        "project_id": target["project_id"],
        "project_number": target["project_number"],
        "region": target["region"],
        "job_id": JOB_ID,
        "dbt_target": target_dataset,
        "workflow_run_id": workflow_run_id,
        "batch_id": batch_id,
        "manifest_generation": manifest_generation,
        "upper_seq": upper_seq,
        "run_mode": run_mode,
        "command": args,
        "status": "DRY_RUN_NO_CLOUD_WRITE",
    }
    if execute:
        try:
            import google.auth
            from google.auth.transport.requests import Request
        except ImportError as exc:
            raise Week7DbtJobError("Cloud Run invocation requires the project's [gcp] dependencies") from exc
        credentials, adc_project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(Request())
        if adc_project and adc_project != target["project_id"]:
            raise Week7DbtJobError("ADC project differs from the approved DataForge project")
        headers = {"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"}
        job_resource = (
            f"projects/{target['project_id']}/locations/{target['region']}/jobs/{JOB_ID}"
        )
        started = time.monotonic()
        response = requests.post(
            f"{RUN_API}/{job_resource}:run",
            headers=headers,
            json={"overrides": {"containerOverrides": [{"name": "dbt", "args": args}]}},
            timeout=30,
        )
        if response.status_code >= 400:
            raise Week7DbtJobError(f"Cloud Run Job invocation returned HTTP {response.status_code}")
        operation = response.json()
        operation_name = operation.get("name")
        if not isinstance(operation_name, str) or not operation_name.startswith("projects/"):
            raise Week7DbtJobError("Cloud Run API returned an invalid operation resource name")
        deadline = started + 1200
        while True:
            result = requests.get(f"{RUN_API}/{operation_name}", headers=headers, timeout=30)
            if result.status_code >= 400:
                raise Week7DbtJobError(f"Cloud Run operation read returned HTTP {result.status_code}")
            operation = result.json()
            if operation.get("done"):
                break
            if time.monotonic() >= deadline:
                raise Week7DbtJobError(f"Cloud Run full-refresh exceeded 1200 seconds: {operation_name}")
            time.sleep(5)
        receipt.update(
            {
                "status": "SUCCEEDED" if "error" not in operation else "FAILED",
                "operation_name": operation_name,
                "execution": {
                    key: operation.get("metadata", {}).get(key)
                    for key in ("name", "startTime", "completionTime", "succeededCount", "failedCount")
                },
                "operation_error": operation.get("error"),
                "duration_seconds": round(time.monotonic() - started, 3),
            }
        )

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True, default=str))
    if execute and receipt["status"] != "SUCCEEDED":
        raise Week7DbtJobError("The dbt full-refresh Cloud Run Job did not succeed")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-dataset", choices=("dev", "full"), required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--manifest-generation", type=int, required=True)
    parser.add_argument("--upper-seq", type=int, required=True)
    parser.add_argument("--run-mode", choices=("normal", "backfill"), required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    run_full_refresh(
        target_dataset=args.target_dataset,
        batch_id=args.batch_id,
        manifest_generation=args.manifest_generation,
        upper_seq=args.upper_seq,
        run_mode=args.run_mode,
        execute=args.execute,
        output=Path(args.output) if args.output else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
