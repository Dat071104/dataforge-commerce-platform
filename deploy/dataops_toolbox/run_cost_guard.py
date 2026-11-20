"""Enforce a cumulative Week 9 BigQuery billed-byte ceiling per workflow run."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

MAX_RUN_BYTES_BILLED = 5 * 1024**3
MAXIMUM_BYTES_BILLED_PER_QUERY = 1024**3
_JOB_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,256}")
_RUN_ID_RE = re.compile(r"[0-9]{1,32}")
_JOB_NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,40}")


class RunCostGuardError(RuntimeError):
    """A safe, non-secret failure for incomplete or excessive query usage."""


def normalize_usage_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    billed_by_job: dict[str, int] = {}
    for record in records:
        if not isinstance(record, dict):
            raise RunCostGuardError("BigQuery usage record is invalid")
        job_id = record.get("job_id")
        billed = record.get("bytes_billed")
        if not isinstance(job_id, str) or _JOB_ID_RE.fullmatch(job_id) is None:
            raise RunCostGuardError("BigQuery usage record has no safe job ID")
        if isinstance(billed, bool) or not isinstance(billed, int) or billed < 0:
            raise RunCostGuardError("BigQuery billed bytes are unavailable for a run job")
        if billed > MAXIMUM_BYTES_BILLED_PER_QUERY:
            raise RunCostGuardError("A BigQuery query exceeded the 1 GiB per-query cap")
        billed_by_job[job_id] = max(billed_by_job.get(job_id, 0), billed)
    return [
        {"job_id": job_id, "bytes_billed": billed_by_job[job_id]}
        for job_id in sorted(billed_by_job)
    ]


def guard_usage_records(
    records: Iterable[dict[str, Any]], *, unknown_query_cap_count: int = 0
) -> dict[str, Any]:
    if (
        isinstance(unknown_query_cap_count, bool)
        or not isinstance(unknown_query_cap_count, int)
        or unknown_query_cap_count < 0
    ):
        raise RunCostGuardError("Unknown query count is invalid")
    normalized = normalize_usage_records(records)
    total = sum(record["bytes_billed"] for record in normalized)
    guarded_upper_bound = total + unknown_query_cap_count * MAXIMUM_BYTES_BILLED_PER_QUERY
    if guarded_upper_bound > MAX_RUN_BYTES_BILLED:
        raise RunCostGuardError(
            f"Week 9 run billed-byte upper bound {guarded_upper_bound} exceeds the 5 GiB per-run limit"
        )
    return {
        "total_bytes_billed": total,
        "unknown_query_cap_count": unknown_query_cap_count,
        "guarded_bytes_upper_bound": guarded_upper_bound,
        "max_run_bytes_billed": MAX_RUN_BYTES_BILLED,
        "usage_records": normalized,
    }


def build_usage_artifact(
    *,
    run_id: str,
    job_name: str,
    records: Iterable[dict[str, Any]],
    unknown_query_cap_count: int = 0,
) -> dict[str, Any]:
    if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        raise RunCostGuardError("GitHub workflow run ID is unavailable")
    if not isinstance(job_name, str) or _JOB_NAME_RE.fullmatch(job_name) is None:
        raise RunCostGuardError("Paid job name is invalid")
    return {
        "workflow_run_id": run_id,
        "paid_job": job_name,
        "guard_status": "PASS",
        **guard_usage_records(records, unknown_query_cap_count=unknown_query_cap_count),
    }


def aggregate_run_artifacts(
    *, input_dir: Path, expected_artifacts: int, run_id: str
) -> dict[str, Any]:
    if expected_artifacts < 0 or not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        raise RunCostGuardError("Run-cost guard inputs are invalid")
    files = sorted(input_dir.glob("*.json")) if input_dir.is_dir() else []
    if len(files) != expected_artifacts:
        raise RunCostGuardError(
            f"Expected {expected_artifacts} paid-job cost artifacts; received {len(files)}"
        )
    if expected_artifacts == 0:
        return {
            "workflow_run_id": run_id,
            "guard_status": "PASS",
            "paid_jobs": 0,
            "total_bytes_billed": 0,
            "unknown_query_cap_count": 0,
            "guarded_bytes_upper_bound": 0,
            "max_run_bytes_billed": MAX_RUN_BYTES_BILLED,
            "usage_records": [],
        }

    records: list[dict[str, Any]] = []
    paid_jobs: list[str] = []
    unknown_query_cap_count = 0
    for path in files:
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise RunCostGuardError("A paid-job cost artifact is missing or invalid") from None
        if artifact.get("workflow_run_id") != run_id or artifact.get("guard_status") != "PASS":
            raise RunCostGuardError("A paid-job cost artifact does not pass the run guard")
        paid_job = artifact.get("paid_job")
        if not isinstance(paid_job, str) or _JOB_NAME_RE.fullmatch(paid_job) is None:
            raise RunCostGuardError("A paid-job cost artifact has an invalid job name")
        if paid_job in paid_jobs:
            raise RunCostGuardError("Duplicate paid-job cost artifacts were found")
        paid_jobs.append(paid_job)
        unknown_count = artifact.get("unknown_query_cap_count", 0)
        if isinstance(unknown_count, bool) or not isinstance(unknown_count, int) or unknown_count < 0:
            raise RunCostGuardError("A paid-job artifact has an invalid unknown-query count")
        unknown_query_cap_count += unknown_count
        artifact_records = artifact.get("usage_records")
        if not isinstance(artifact_records, list):
            raise RunCostGuardError("A paid-job cost artifact has no usage records")
        records.extend(artifact_records)

    return {
        "workflow_run_id": run_id,
        "guard_status": "PASS",
        "paid_jobs": len(paid_jobs),
        **guard_usage_records(records, unknown_query_cap_count=unknown_query_cap_count),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--expected-artifacts", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = aggregate_run_artifacts(
            input_dir=args.input_dir,
            expected_artifacts=args.expected_artifacts,
            run_id=args.run_id,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    except RunCostGuardError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    print(
        "W9_RUN_COST_GUARD=PASS "
        f"paid_jobs={summary['paid_jobs']} "
        f"bytes_billed={summary['total_bytes_billed']} "
        f"guarded_upper_bound={summary['guarded_bytes_upper_bound']} "
        f"limit={summary['max_run_bytes_billed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
