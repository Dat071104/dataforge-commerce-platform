"""Run one bounded Week-7 Workflows execution using the isolated ADC profile."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import google.auth
import requests
from google.auth.transport.requests import Request

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TARGET_FILE = REPOSITORY_ROOT / "docs" / "cloud" / "target.json"
_BATCH_ID = re.compile(r"[0-9a-f]{64}\Z")
_WORKFLOW_ID = "dataforge-week7-orchestrator"
_EXECUTIONS_API = "https://workflowexecutions.googleapis.com/v1"


class WorkflowClientError(RuntimeError):
    """A bounded workflow call failed or returned an invalid execution."""


@dataclass(frozen=True)
class RunOptions:
    no_new_batch: bool
    manifest_uri: str | None
    manifest_generation: int | None
    batch_id: str | None
    run_mode: str
    test_fail_after_merge_once: bool
    test_fail_dbt_build: bool
    test_fail_before_publish: bool
    test_hold_after_lock_seconds: int
    timeout_seconds: int
    poll_interval_seconds: int


def read_target(path: Path = TARGET_FILE) -> dict[str, Any]:
    try:
        target = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowClientError("The approved DataForge target.json is missing or invalid") from exc
    if (
        target.get("project_id") != "dataforge-p7-lab-d0f725"
        or target.get("project_number") != "955038620072"
        or target.get("region") != "us-central1"
        or target.get("bucket") != "dataforge-p7-lab-d0f725-bronze"
    ):
        raise WorkflowClientError("target.json does not match the approved isolated Week-7 target")
    return target


def build_workflow_arguments(options: RunOptions, target: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(options.no_new_batch, bool):
        raise WorkflowClientError("no_new_batch must be a boolean")
    failpoint_count = sum(
        (
            options.test_fail_after_merge_once,
            options.test_fail_dbt_build,
            options.test_fail_before_publish,
        )
    )
    if failpoint_count > 1:
        raise WorkflowClientError("select only one failure injection for a workflow execution")
    if not 0 <= options.test_hold_after_lock_seconds <= 30:
        raise WorkflowClientError("test_hold_after_lock_seconds must be between 0 and 30")
    if not 60 <= options.timeout_seconds <= 3600:
        raise WorkflowClientError("timeout_seconds must be between 60 and 3600")
    if not 1 <= options.poll_interval_seconds <= 30:
        raise WorkflowClientError("poll_interval_seconds must be between 1 and 30")

    has_manifest = any(
        value is not None
        for value in (options.manifest_uri, options.manifest_generation, options.batch_id)
    )
    if options.no_new_batch:
        if has_manifest:
            raise WorkflowClientError("NO_NEW_BATCH cannot be combined with manifest fields")
        return {"no_new_batch": True, "trigger": "manual"}

    if not all(
        value is not None
        for value in (options.manifest_uri, options.manifest_generation, options.batch_id)
    ):
        raise WorkflowClientError("manifest URI, generation, and batch_id are required together")
    if options.run_mode not in {"normal", "backfill"}:
        raise WorkflowClientError("run_mode must be normal or backfill")
    if options.manifest_generation is None or options.manifest_generation <= 0:
        raise WorkflowClientError("manifest_generation must be a positive integer")
    if options.batch_id is None or not _BATCH_ID.fullmatch(options.batch_id):
        raise WorkflowClientError("batch_id must be a lowercase 64-character SHA-256 digest")
    expected_uri = (
        f"gs://{target['bucket']}/manifests/week5/batch_id={options.batch_id}/manifest.json"
    )
    if options.manifest_uri != expected_uri:
        raise WorkflowClientError("manifest URI must match the approved bucket and batch_id prefix")

    result: dict[str, Any] = {
        "manifest_uri": expected_uri,
        "manifest_generation": str(options.manifest_generation),
        "batch_id": options.batch_id,
        "run_mode": options.run_mode,
        "test_fail_after_merge_once": options.test_fail_after_merge_once,
        "test_fail_dbt_build": options.test_fail_dbt_build,
        "test_fail_before_publish": options.test_fail_before_publish,
        "test_hold_after_lock_seconds": options.test_hold_after_lock_seconds,
        "trigger": "manual",
    }
    return result


def _parse_result(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def run_workflow(
    *,
    options: RunOptions,
    target: dict[str, Any],
    request_session: Any = requests,
    credential_factory: Callable[..., Any] = google.auth.default,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    arguments = build_workflow_arguments(options, target)
    credentials, adc_project = credential_factory(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    if adc_project and adc_project != target["project_id"]:
        raise WorkflowClientError("ADC project differs from the approved DataForge target")

    workflow_name = (
        f"projects/{target['project_id']}/locations/{target['region']}"
        f"/workflows/{_WORKFLOW_ID}"
    )
    headers = {"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"}
    response = request_session.post(
        f"{_EXECUTIONS_API}/{workflow_name}/executions",
        headers=headers,
        json={"argument": json.dumps(arguments, separators=(",", ":"))},
        timeout=30,
    )
    if response.status_code >= 400:
        raise WorkflowClientError(
            f"Workflow execution create failed with HTTP {response.status_code}; "
            "inspect the sanitized API error and project IAM."
        )
    execution = response.json()
    execution_name = execution.get("name")
    workflow_names = {
        workflow_name,
        workflow_name.replace(
            f"projects/{target['project_id']}/",
            f"projects/{target['project_number']}/",
            1,
        ),
    }
    if not isinstance(execution_name, str) or not any(
        execution_name.startswith(f"{name}/executions/") for name in workflow_names
    ):
        raise WorkflowClientError("Workflow API returned an unexpected execution resource name")

    started_at = monotonic()
    deadline = started_at + options.timeout_seconds
    while True:
        get_response = request_session.get(
            f"{_EXECUTIONS_API}/{execution_name}", headers=headers, timeout=30
        )
        if get_response.status_code >= 400:
            raise WorkflowClientError(
                f"Workflow execution read failed with HTTP {get_response.status_code}; "
                "inspect the sanitized API error and project IAM."
            )
        execution = get_response.json()
        state = execution.get("state")
        if state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            break
        if monotonic() >= deadline:
            raise WorkflowClientError(
                f"Workflow execution exceeded its {options.timeout_seconds}s client deadline; "
                f"execution_name={execution_name}"
            )
        sleep(options.poll_interval_seconds)

    result = {
        "workflow_name": workflow_name,
        "workflow_execution_name": execution_name,
        "state": state,
        "argument": arguments,
        "result": _parse_result(execution.get("result")),
        "error": execution.get("error"),
        "start_time": execution.get("startTime"),
        "end_time": execution.get("endTime"),
        "duration_seconds": round(monotonic() - started_at, 3),
    }
    if state != "SUCCEEDED":
        raise WorkflowClientError(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute one bounded Week-7 Workflows run against the approved DataForge project."
    )
    parser.add_argument("--no-new-batch", action="store_true")
    parser.add_argument("--manifest-uri")
    parser.add_argument("--manifest-generation", type=int)
    parser.add_argument("--batch-id")
    parser.add_argument("--run-mode", choices=("normal", "backfill"), default="normal")
    parser.add_argument("--test-fail-after-merge-once", action="store_true")
    parser.add_argument("--test-fail-dbt-build", action="store_true")
    parser.add_argument("--test-fail-before-publish", action="store_true")
    parser.add_argument("--test-hold-after-lock-seconds", type=int, default=0)
    parser.add_argument(
        "--expect-failure",
        action="store_true",
        help="Treat a terminal FAILED execution as the expected outcome for a failure drill.",
    )
    parser.add_argument("--expect-error-contains", help="Require this text in the terminal Workflow error.")
    parser.add_argument("--timeout-seconds", type=int, default=2400)
    parser.add_argument("--poll-interval-seconds", type=int, default=5)
    parser.add_argument("--output", help="Optional path for the completed sanitized JSON receipt")
    return parser


def main(argv: list[str] | None = None) -> int:
    parsed = _parser().parse_args(argv)
    options = RunOptions(
        no_new_batch=parsed.no_new_batch,
        manifest_uri=parsed.manifest_uri,
        manifest_generation=parsed.manifest_generation,
        batch_id=parsed.batch_id,
        run_mode=parsed.run_mode,
        test_fail_after_merge_once=parsed.test_fail_after_merge_once,
        test_fail_dbt_build=parsed.test_fail_dbt_build,
        test_fail_before_publish=parsed.test_fail_before_publish,
        test_hold_after_lock_seconds=parsed.test_hold_after_lock_seconds,
        timeout_seconds=parsed.timeout_seconds,
        poll_interval_seconds=parsed.poll_interval_seconds,
    )
    try:
        result = run_workflow(options=options, target=read_target())
    except WorkflowClientError as exc:
        if not parsed.expect_failure:
            print(str(exc), file=sys.stderr)
            return 1
        try:
            result = json.loads(str(exc))
        except json.JSONDecodeError:
            print(str(exc), file=sys.stderr)
            return 1
        encoded_error = json.dumps(result, sort_keys=True)
        if result.get("state") != "FAILED":
            print("Expected a terminal FAILED Workflow execution.", file=sys.stderr)
            return 1
        if parsed.expect_error_contains and parsed.expect_error_contains not in encoded_error:
            print("Terminal Workflow error did not contain the expected text.", file=sys.stderr)
            return 1
        result["expected_failure"] = True
    else:
        if parsed.expect_failure:
            print("Workflow succeeded but a failure was expected.", file=sys.stderr)
            return 1

    encoded = json.dumps(result, indent=2, sort_keys=True)
    if parsed.output:
        Path(parsed.output).write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
