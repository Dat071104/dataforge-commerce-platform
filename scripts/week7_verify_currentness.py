"""Verify the public Week-7 view hides stale output and exposes only a current pointer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dataforge.settings import ROOT

TARGET_FILE = ROOT / "docs" / "cloud" / "target.json"
EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
EXPECTED_PROJECT_NUMBER = "955038620072"
EXPECTED_REGION = "us-central1"
MAXIMUM_BYTES_BILLED = 67_108_864


class Week7CurrentnessCheckError(RuntimeError):
    """The public view does not match its pointer currentness state."""


def _target() -> dict[str, Any]:
    try:
        target = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Week7CurrentnessCheckError("The approved target file is missing or invalid") from exc
    if (
        target.get("project_id") != EXPECTED_PROJECT
        or target.get("project_number") != EXPECTED_PROJECT_NUMBER
        or target.get("region") != EXPECTED_REGION
    ):
        raise Week7CurrentnessCheckError("Currentness check is restricted to the approved project")
    return target


def verify_currentness(*, expected_current: bool, output: Path | None = None) -> dict[str, Any]:
    target = _target()
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from google.cloud import bigquery
    except ImportError as exc:
        raise Week7CurrentnessCheckError("Currentness check requires the project's [gcp] dependencies") from exc
    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    if adc_project and adc_project != target["project_id"]:
        raise Week7CurrentnessCheckError("ADC project differs from the approved target")

    project = target["project_id"]
    sql = f"""
    SELECT
      pointer.pointer_version,
      pointer.publication_is_current,
      pointer.candidate_row_count,
      pointer.candidate_sha256,
      (SELECT COUNT(*) FROM `{project}.gold_week7.published_order_reconciliation`)
        AS public_view_row_count
    FROM `{project}.gold_week7.week7_publication_pointer` AS pointer
    WHERE pointer.pointer_name = 'current_order_reconciliation'
    """
    client = bigquery.Client(project=project, credentials=credentials, location=target["region"])
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
            labels={"application": "dataforge", "phase": "week7", "action": "currentness"},
        ),
        location=target["region"],
    )
    rows = list(job.result(timeout=300))
    if len(rows) != 1:
        raise Week7CurrentnessCheckError("Expected exactly one publication pointer row")
    row = rows[0]
    is_current = row["publication_is_current"] is True
    row_count = int(row["public_view_row_count"] or 0)
    candidate_rows = int(row["candidate_row_count"] or 0)
    expected_rows = candidate_rows if expected_current else 0
    result = {
        "project_id": project,
        "project_number": target["project_number"],
        "region": target["region"],
        "query_job_id": job.job_id,
        "bytes_processed": int(job.total_bytes_processed or 0),
        "bytes_billed": int(job.total_bytes_billed or 0),
        "maximum_bytes_billed": MAXIMUM_BYTES_BILLED,
        "pointer_version": int(row["pointer_version"] or 0),
        "publication_is_current": is_current,
        "candidate_row_count": candidate_rows,
        "candidate_sha256": row["candidate_sha256"],
        "public_view_row_count": row_count,
        "expected_current": expected_current,
        "status": "PASS" if is_current == expected_current and row_count == expected_rows else "FAIL",
    }
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    if result["status"] != "PASS":
        raise Week7CurrentnessCheckError("The public view did not match the pointer currentness state")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-current", choices=("true", "false"), required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    verify_currentness(
        expected_current=args.expect_current == "true",
        output=Path(args.output) if args.output else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
