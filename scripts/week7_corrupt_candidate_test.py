"""Inject and verify one bounded candidate-only corruption for ORC-08."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from dataforge.settings import ROOT

TARGET_FILE = ROOT / "docs" / "cloud" / "target.json"
EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
EXPECTED_PROJECT_NUMBER = "955038620072"
EXPECTED_REGION = "us-central1"
MAXIMUM_BYTES_BILLED = 67_108_864
ORDER_ID = "W5O0004"
EXPECTED_COLLECTED_AMOUNT = Decimal("15000.00")


class Week7CandidateFaultError(RuntimeError):
    """The approved candidate-only corruption did not meet its fence contract."""


def _target() -> dict[str, Any]:
    try:
        target = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Week7CandidateFaultError("The approved target file is missing or invalid") from exc
    if (
        target.get("project_id") != EXPECTED_PROJECT
        or target.get("project_number") != EXPECTED_PROJECT_NUMBER
        or target.get("region") != EXPECTED_REGION
    ):
        raise Week7CandidateFaultError("ORC-08 corruption is restricted to the approved project")
    return target


def inject_candidate_corruption(*, output: Path | None = None) -> dict[str, Any]:
    target = _target()
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from google.cloud import bigquery
    except ImportError as exc:
        raise Week7CandidateFaultError("ORC-08 requires the project's [gcp] dependencies") from exc
    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    if adc_project and adc_project != target["project_id"]:
        raise Week7CandidateFaultError("ADC project differs from the approved target")

    project = target["project_id"]
    client = bigquery.Client(project=project, credentials=credentials, location=target["region"])
    before_sql = f"""
    SELECT candidate.order_id, candidate.order_id_bucket,
           CAST(candidate.collected_amount AS STRING) AS collected_amount,
           pointer.pointer_version, pointer.candidate_sha256,
           pointer.publication_is_current,
           CAST(published.collected_amount AS STRING) AS published_collected_amount
    FROM `{project}.dbt_week7.fct_week7_order_reconciliation` AS candidate
    CROSS JOIN `{project}.gold_week7.week7_publication_pointer` AS pointer
    LEFT JOIN `{project}.gold_week7.published_order_reconciliation` AS published
      ON published.order_id = candidate.order_id
     AND published.publication_id = pointer.publication_id
    WHERE candidate.order_id = @order_id
      AND pointer.pointer_name = 'current_order_reconciliation'
    """
    before_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("order_id", "STRING", ORDER_ID)],
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        labels={"application": "dataforge", "phase": "week7", "action": "orc08before"},
    )
    before_job = client.query(before_sql, job_config=before_config, location=target["region"])
    before_rows = list(before_job.result(timeout=300))
    if len(before_rows) != 1:
        raise Week7CandidateFaultError("Expected exactly one candidate and pointer row before corruption")
    before = before_rows[0]
    if (
        int(before["pointer_version"]) <= 0
        or before["publication_is_current"] is not True
        or Decimal(before["collected_amount"]) != EXPECTED_COLLECTED_AMOUNT
        or Decimal(before["published_collected_amount"]) != EXPECTED_COLLECTED_AMOUNT
    ):
        raise Week7CandidateFaultError("The active candidate does not match the reviewed ORC-08 precondition")

    update_sql = f"""
    UPDATE `{project}.dbt_week7.fct_week7_order_reconciliation`
    SET collected_amount = collected_amount + NUMERIC '1.00'
    WHERE order_id = @order_id AND order_id_bucket = @order_id_bucket
    """
    update_job = client.query(
        update_sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("order_id", "STRING", ORDER_ID),
                bigquery.ScalarQueryParameter("order_id_bucket", "INT64", int(before["order_id_bucket"])),
            ],
            maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
            labels={"application": "dataforge", "phase": "week7", "action": "orc08fault"},
        ),
        location=target["region"],
    )
    update_job.result(timeout=300)
    if int(update_job.num_dml_affected_rows or 0) != 1:
        raise Week7CandidateFaultError("The controlled candidate fault must update exactly one row")

    after_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("order_id", "STRING", ORDER_ID)],
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        labels={"application": "dataforge", "phase": "week7", "action": "orc08after"},
    )
    after_job = client.query(before_sql, job_config=after_config, location=target["region"])
    after_rows = list(after_job.result(timeout=300))
    if len(after_rows) != 1:
        raise Week7CandidateFaultError("Candidate or pointer singleton changed during ORC-08 verification")
    after = after_rows[0]
    if (
        Decimal(after["collected_amount"]) != Decimal("15001.00")
        or Decimal(after["published_collected_amount"]) != EXPECTED_COLLECTED_AMOUNT
        or int(after["pointer_version"]) != int(before["pointer_version"])
        or after["publication_is_current"] is not True
        or after["candidate_sha256"] != before["candidate_sha256"]
    ):
        raise Week7CandidateFaultError("Candidate fault escaped the publication fence")

    receipt = {
        "status": "FAULT_INJECTED_AND_FENCED",
        "project_id": project,
        "project_number": target["project_number"],
        "region": target["region"],
        "order_id": ORDER_ID,
        "before": {
            "candidate_collected_amount": format(Decimal(before["collected_amount"]), "f"),
            "published_collected_amount": format(Decimal(before["published_collected_amount"]), "f"),
            "pointer_version": int(before["pointer_version"]),
            "publication_is_current": bool(before["publication_is_current"]),
            "candidate_sha256": before["candidate_sha256"],
        },
        "after": {
            "candidate_collected_amount": format(Decimal(after["collected_amount"]), "f"),
            "published_collected_amount": format(Decimal(after["published_collected_amount"]), "f"),
            "pointer_version": int(after["pointer_version"]),
            "publication_is_current": bool(after["publication_is_current"]),
            "candidate_sha256": after["candidate_sha256"],
        },
        "before_job_id": before_job.job_id,
        "before_bytes_billed": int(before_job.total_bytes_billed or 0),
        "update_job_id": update_job.job_id,
        "update_rows": int(update_job.num_dml_affected_rows or 0),
        "update_bytes_billed": int(update_job.total_bytes_billed or 0),
        "after_job_id": after_job.job_id,
        "after_bytes_billed": int(after_job.total_bytes_billed or 0),
        "maximum_bytes_billed": MAXIMUM_BYTES_BILLED,
        "published_view_unchanged": True,
        "pointer_unchanged": True,
    }
    encoded = json.dumps(receipt, indent=2, sort_keys=True)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    inject_candidate_corruption(output=Path(args.output) if args.output else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
