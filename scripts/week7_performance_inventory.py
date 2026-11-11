"""Capture Week-7 BigQuery, Cloud Run, Workflow, and image usage receipts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
EXPECTED_PROJECT_NUMBER = "955038620072"
EXPECTED_REGION = "us-central1"
MAXIMUM_BYTES_BILLED = 67_108_864
ROOT = Path(__file__).resolve().parents[1]

EXPECTED_PROJECT_NUMBER = "955038620072"
EXPECTED_REGION = "us-central1"
START_UTC = "2026-11-11T09:00:00Z"
BIGQUERY_LIST_USD_PER_TIB = Decimal("6.25")
CLOUD_RUN_CPU_USD_PER_SECOND = Decimal("0.000018")
CLOUD_RUN_MEMORY_USD_PER_GIB_SECOND = Decimal("0.000002")
RUN_API = "https://run.googleapis.com/v2"
WORKFLOWS_API = "https://workflowexecutions.googleapis.com/v1"


class Week7InventoryError(RuntimeError):
    """The cost inventory could not safely inspect the approved target."""


def _approved_target() -> dict[str, Any]:
    target_file = ROOT / "docs" / "cloud" / "target.json"
    try:
        target = json.loads(target_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Week7InventoryError("The approved target file is missing or invalid") from exc
    if (
        target.get("project_id") != EXPECTED_PROJECT
        or target.get("project_number") != EXPECTED_PROJECT_NUMBER
        or target.get("region") != EXPECTED_REGION
    ):
        raise Week7InventoryError("Cost inventory is restricted to the approved project and region")
    return target


def _auth() -> tuple[Any, dict[str, str]]:
    try:
        import google.auth
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise Week7InventoryError("Usage inventory requires the project's [gcp] dependencies") from exc
    target = _approved_target()
    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    if adc_project and adc_project != target["project_id"]:
        raise Week7InventoryError("ADC project differs from the approved DataForge project")
    return target, {"Authorization": f"Bearer {credentials.token}"}


def _pages(url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None, key: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    page_token = None
    while True:
        page_params = dict(params or {})
        if page_token:
            page_params["pageToken"] = page_token
        response = requests.get(url, headers=headers, params=page_params, timeout=30)
        if response.status_code >= 400:
            raise Week7InventoryError(f"Usage inventory read returned HTTP {response.status_code}")
        data = response.json()
        results.extend(data.get(key, []))
        page_token = data.get("nextPageToken")
        if not page_token:
            return results


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _cloud_run_inventory(target: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    job_specs = {
        "dataforge-week5-processor": Decimal("0.5"),
        "dataforge-week7-dbt": Decimal("1"),
    }
    start = _parse_time(START_UTC)
    jobs: list[dict[str, Any]] = []
    totals = {
        "execution_count": 0,
        "completed_execution_count": 0,
        "failed_execution_count": 0,
        "running_execution_count": 0,
        "task_runtime_seconds": Decimal("0"),
        "wall_clock_seconds": Decimal("0"),
        "conservative_billable_seconds": Decimal("0"),
        "vcpu_seconds_upper": Decimal("0"),
        "gib_seconds_upper": Decimal("0"),
    }
    for job_id, memory_gib in job_specs.items():
        url = f"https://run.googleapis.com/v2/projects/{target['project_id']}/locations/{target['region']}/jobs/{job_id}/executions"
        executions = _pages(url, headers=headers, params={"pageSize": 100}, key="executions")
        scoped = []
        for execution in executions:
            created = _parse_time(execution.get("createTime"))
            if not created or created < start:
                continue
            started = _parse_time(execution.get("startTime"))
            completed = _parse_time(execution.get("completionTime"))
            duration = max(Decimal("0"), Decimal(str((completed - started).total_seconds()))) if started and completed else None
            wall = max(Decimal("0"), Decimal(str((completed - created).total_seconds()))) if completed else None
            succeeded = int(execution.get("succeededCount") or 0)
            failed = int(execution.get("failedCount") or 0)
            status = "SUCCEEDED" if succeeded else "FAILED" if failed else "ACTIVE"
            item = {
                "job_id": job_id,
                "execution_id": execution.get("name", "").rsplit("/", 1)[-1],
                "status": status,
                "created_at": execution.get("createTime"),
                "started_at": execution.get("startTime"),
                "completed_at": execution.get("completionTime"),
                "task_count": int(execution.get("taskCount") or 0),
                "succeeded_count": succeeded,
                "failed_count": failed,
                "task_runtime_seconds": float(duration) if duration is not None else None,
                "wall_clock_seconds": float(wall) if wall is not None else None,
            }
            scoped.append(item)
            totals["execution_count"] += 1
            if status == "ACTIVE":
                totals["running_execution_count"] += 1
                continue
            totals["completed_execution_count"] += 1
            totals["failed_execution_count"] += int(status == "FAILED")
            if duration is not None and wall is not None:
                billable = max(Decimal("60"), wall)
                totals["task_runtime_seconds"] += duration
                totals["wall_clock_seconds"] += wall
                totals["conservative_billable_seconds"] += billable
                totals["vcpu_seconds_upper"] += billable
                totals["gib_seconds_upper"] += billable * memory_gib
        jobs.append({"job_id": job_id, "memory_gib": str(memory_gib), "executions": scoped})

    totals_json = {key: float(value) if isinstance(value, Decimal) else value for key, value in totals.items()}
    cpu_cost = totals["vcpu_seconds_upper"] * CLOUD_RUN_CPU_USD_PER_SECOND
    memory_cost = totals["gib_seconds_upper"] * CLOUD_RUN_MEMORY_USD_PER_GIB_SECOND
    totals_json["cloud_run_gross_upper_estimate_usd"] = float((cpu_cost + memory_cost).quantize(Decimal("0.000001")))
    totals_json["cpu_gross_upper_estimate_usd"] = float(cpu_cost.quantize(Decimal("0.000001")))
    totals_json["memory_gross_upper_estimate_usd"] = float(memory_cost.quantize(Decimal("0.000001")))
    return {"jobs": jobs, "totals": totals_json}


def _workflow_inventory(target: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    start = _parse_time(START_UTC)
    parent = (
        f"projects/{target['project_number']}/locations/{target['region']}"
        "/workflows/dataforge-week7-orchestrator"
    )
    url = f"{WORKFLOWS_API}/{parent}/executions"
    executions = _pages(url, headers=headers, params={"pageSize": 100}, key="executions")
    selected = []
    totals = {"execution_count": 0, "succeeded_count": 0, "failed_count": 0, "active_count": 0, "step_entry_count": 0, "duration_seconds": 0.0}
    for item in executions:
        created = _parse_time(item.get("startTime"))
        if not created or created < start:
            continue
        name = item.get("name")
        if not name:
            continue
        detail_response = requests.get(f"{WORKFLOWS_API}/{name}", headers=headers, timeout=30)
        if detail_response.status_code >= 400:
            raise Week7InventoryError(f"Workflow detail read returned HTTP {detail_response.status_code}")
        detail = detail_response.json()
        state = detail.get("state")
        end = _parse_time(detail.get("endTime"))
        start_time = _parse_time(detail.get("startTime"))
        duration = (end - start_time).total_seconds() if end and start_time else None
        step_url = f"{WORKFLOWS_API}/{name}/stepEntries"
        step_response = requests.get(step_url, headers=headers, params={"pageSize": 1000}, timeout=30)
        if step_response.status_code >= 400:
            raise Week7InventoryError(f"Workflow step-entry read returned HTTP {step_response.status_code}")
        step_count = int(step_response.json().get("totalSize") or 0)
        entry = {
            "execution_id": name.rsplit("/", 1)[-1],
            "state": state,
            "start_time": detail.get("startTime"),
            "end_time": detail.get("endTime"),
            "duration_seconds": round(duration, 3) if duration is not None else None,
            "step_entry_count": step_count,
        }
        selected.append(entry)
        totals["execution_count"] += 1
        totals["succeeded_count"] += int(state == "SUCCEEDED")
        totals["failed_count"] += int(state == "FAILED")
        totals["active_count"] += int(state == "ACTIVE")
        totals["step_entry_count"] += step_count
        totals["duration_seconds"] += duration or 0
    totals["duration_seconds"] = round(totals["duration_seconds"], 3)
    return {"executions": selected, "totals": totals}


def _bigquery_inventory(target: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    del headers
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from google.cloud import bigquery
    except ImportError as exc:
        raise Week7InventoryError("BigQuery inventory requires the project's [gcp] dependencies") from exc
    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    if adc_project and adc_project != target["project_id"]:
        raise Week7InventoryError("ADC project differs from the approved target")
    client = bigquery.Client(project=target["project_id"], credentials=credentials, location=target["region"])
    job_id = f"week7_costinventory_{uuid4().hex}"
    sql = f"""
    SELECT job_type, statement_type, COUNT(*) AS top_level_job_count,
           SUM(COALESCE(total_bytes_processed, 0)) AS bytes_processed,
           SUM(COALESCE(total_bytes_billed, 0)) AS bytes_billed,
           SUM(COALESCE(total_slot_ms, 0)) AS slot_ms,
           COUNTIF(error_result IS NOT NULL) AS failed_job_count
    FROM `region-{target['region']}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
    WHERE creation_time >= @start_time
      AND job_id != @inventory_job_id
      AND parent_job_id IS NULL
    GROUP BY job_type, statement_type
    ORDER BY job_type, statement_type
    """
    job = client.query(
        sql,
        job_id=job_id,
        job_config=bigquery.QueryJobConfig(
            maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
            labels={"application": "dataforge", "phase": "week7", "action": "costinventory"},
            query_parameters=[
                bigquery.ScalarQueryParameter("start_time", "TIMESTAMP", START_UTC),
                bigquery.ScalarQueryParameter("inventory_job_id", "STRING", job_id),
            ],
        ),
        job_retry=None,
        location=target["region"],
    )
    rows = []
    total_processed = 0
    total_billed = 0
    total_slot_ms = 0
    total_jobs = 0
    total_failures = 0
    for row in job.result(timeout=300):
        item = {
            "job_type": row["job_type"],
            "statement_type": row["statement_type"],
            "top_level_job_count": int(row["top_level_job_count"] or 0),
            "bytes_processed": int(row["bytes_processed"] or 0),
            "bytes_billed": int(row["bytes_billed"] or 0),
            "slot_ms": int(row["slot_ms"] or 0),
            "failed_job_count": int(row["failed_job_count"] or 0),
        }
        rows.append(item)
        total_jobs += item["top_level_job_count"]
        total_processed += item["bytes_processed"]
        total_billed += item["bytes_billed"]
        total_slot_ms += item["slot_ms"]
        total_failures += item["failed_job_count"]
    list_price = Decimal(total_billed) / Decimal(1024**4) * BIGQUERY_LIST_USD_PER_TIB
    return {
        "inventory_job_id": job.job_id,
        "inventory_query_bytes_billed": int(job.total_bytes_billed or 0),
        "maximum_bytes_billed": MAXIMUM_BYTES_BILLED,
        "grouped_jobs": rows,
        "totals": {
            "top_level_job_count": total_jobs,
            "failed_job_count": total_failures,
            "bytes_processed": total_processed,
            "bytes_billed": total_billed,
            "slot_ms": total_slot_ms,
            "gross_list_price_estimate_usd_at_6_25_per_tib": float(list_price.quantize(Decimal("0.000001"))),
        },
    }


def _scheduler_job_absent(target: dict[str, Any], headers: dict[str, str]) -> bool:
    name = (
        f"projects/{target['project_id']}/locations/{target['region']}"
        "/jobs/dataforge-week7-no-new-batch"
    )
    response = requests.get(f"https://cloudscheduler.googleapis.com/v1/{name}", headers=headers, timeout=30)
    if response.status_code == 404:
        return True
    if response.status_code >= 400:
        raise Week7InventoryError(f"Cloud Scheduler inventory returned HTTP {response.status_code}")
    return False


def build_inventory() -> dict[str, Any]:
    target, headers = _auth()
    bq = _bigquery_inventory(target, headers)
    cloud_run = _cloud_run_inventory(target, headers)
    workflows = _workflow_inventory(target, headers)
    receipt = {
        "project_id": target["project_id"],
        "project_number": target["project_number"],
        "region": target["region"],
        "window_start_utc": START_UTC,
        "window_end_utc": datetime.now(timezone.utc).isoformat(),
        "bigquery": bq,
        "cloud_run": cloud_run,
        "workflows": workflows,
        "scheduler_job_absent": _scheduler_job_absent(target, headers),
        "billing_export_or_settled_cost": "NOT_QUERIED; Billing API remains disabled; use gross list-price estimate only",
    }
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/cloud/week7/performance_inventory.json")
    args = parser.parse_args(argv)
    receipt = build_inventory()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
