"""Run bounded live Workflow input and immutable-generation contract drills."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import requests

from dataforge.settings import ROOT

TARGET_FILE = ROOT / "docs" / "cloud" / "target.json"
EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
EXPECTED_PROJECT_NUMBER = "955038620072"
EXPECTED_REGION = "us-central1"
WORKFLOW_ID = "dataforge-week7-orchestrator"
EXECUTIONS_API = "https://workflowexecutions.googleapis.com/v1"


class Week7WorkflowDrillError(RuntimeError):
    """A bounded contract drill did not return its expected failure."""


def _approved_target() -> dict[str, Any]:
    try:
        target = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Week7WorkflowDrillError("The approved target file is missing or invalid") from exc
    if (
        target.get("project_id") != EXPECTED_PROJECT
        or target.get("project_number") != EXPECTED_PROJECT_NUMBER
        or target.get("region") != EXPECTED_REGION
    ):
        raise Week7WorkflowDrillError("Workflow contract drills are restricted to the approved project")
    return target


def _parse_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _run_one(
    *, name: str, arguments: dict[str, Any], expected_error: str, headers: dict[str, str]
) -> dict[str, Any]:
    target = _approved_target()
    workflow_name = (
        f"projects/{target['project_number']}/locations/{target['region']}"
        f"/workflows/{WORKFLOW_ID}"
    )
    create = requests.post(
        f"{EXECUTIONS_API}/{workflow_name}/executions",
        headers=headers,
        json={"argument": json.dumps(arguments, separators=(",", ":"))},
        timeout=30,
    )
    if create.status_code >= 400:
        raise Week7WorkflowDrillError(f"Workflow create returned HTTP {create.status_code}")
    created = create.json()
    execution_name = created.get("name")
    if not isinstance(execution_name, str) or "/executions/" not in execution_name:
        raise Week7WorkflowDrillError("Workflow API returned an invalid execution resource name")

    deadline = time.monotonic() + 180
    while True:
        response = requests.get(f"{EXECUTIONS_API}/{execution_name}", headers=headers, timeout=30)
        if response.status_code >= 400:
            raise Week7WorkflowDrillError(f"Workflow read returned HTTP {response.status_code}")
        execution = response.json()
        if execution.get("state") in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            break
        if time.monotonic() >= deadline:
            raise Week7WorkflowDrillError(f"Workflow execution exceeded 180 seconds: {execution_name}")
        time.sleep(3)

    steps_response = requests.get(
        f"{EXECUTIONS_API}/{execution_name}/stepEntries", headers=headers, params={"pageSize": 100}, timeout=30
    )
    if steps_response.status_code >= 400:
        raise Week7WorkflowDrillError(f"Workflow step history returned HTTP {steps_response.status_code}")
    step_names = sorted(
        {entry.get("step", "") for entry in steps_response.json().get("stepEntries", [])}
    )
    error = execution.get("error") or {}
    error_text = json.dumps(error, sort_keys=True)
    data_plane_steps = {
        "run_week5_silver_consumer",
        "run_dbt_build_and_tests",
        "publish_verified_gold_pointer",
    }
    no_data_plane = not any(step in data_plane_steps for step in step_names)
    if execution.get("state") != "FAILED" or expected_error not in error_text or not no_data_plane:
        raise Week7WorkflowDrillError(
            f"{name} did not fail with the expected contract before data-plane work; "
            f"state={execution.get('state')}, steps={step_names}"
        )
    return {
        "scenario": name,
        "status": "PASS_EXPECTED_FAILURE",
        "workflow_execution_name": execution_name,
        "state": execution.get("state"),
        "start_time": execution.get("startTime"),
        "end_time": execution.get("endTime"),
        "arguments": arguments,
        "error": error,
        "step_names": step_names,
        "data_plane_invoked": not no_data_plane,
    }


def run_drills(*, batch_id: str, manifest_generation: int, output_dir: Path) -> list[dict[str, Any]]:
    target = _approved_target()
    try:
        import google.auth
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise Week7WorkflowDrillError("Live Workflow drills require the project's [gcp] dependencies") from exc
    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    if adc_project and adc_project != target["project_id"]:
        raise Week7WorkflowDrillError("ADC project differs from the approved target")
    headers = {"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"}
    manifest_uri = (
        f"gs://{target['bucket']}/manifests/week5/batch_id={batch_id}/manifest.json"
    )
    incomplete = {
        "manifest_uri": manifest_uri,
        "batch_id": batch_id,
        "run_mode": "normal",
        "trigger": "manual",
    }
    wrong_generation = {
        **incomplete,
        "manifest_generation": str(manifest_generation + 1),
    }
    receipts = [
        _run_one(
            name="ORC-04_incomplete_manifest",
            arguments=incomplete,
            expected_error="INVALID_WEEK7_WORKFLOW_INPUT",
            headers=headers,
        ),
        _run_one(
            name="ORC-05_generation_mismatch",
            arguments=wrong_generation,
            expected_error="404",
            headers=headers,
        ),
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    for receipt in receipts:
        file_name = "orc04_incomplete_manifest.json" if receipt["scenario"].startswith("ORC-04") else "orc05_generation_mismatch.json"
        (output_dir / file_name).write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return receipts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--manifest-generation", type=int, required=True)
    parser.add_argument("--output-dir", default="docs/cloud/week7")
    args = parser.parse_args(argv)
    receipts = run_drills(
        batch_id=args.batch_id,
        manifest_generation=args.manifest_generation,
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(receipts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
