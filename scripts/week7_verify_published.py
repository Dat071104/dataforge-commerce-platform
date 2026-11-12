"""Reconcile the published Week-7 pointer view independently to Week-5 Gold."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from dataforge.settings import ROOT

TARGET_FILE = ROOT / "docs" / "cloud" / "target.json"
EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
EXPECTED_PROJECT_NUMBER = "955038620072"
EXPECTED_REGION = "us-central1"
MAXIMUM_BYTES_BILLED = 67_108_864


class Week7PublishedCheckError(RuntimeError):
    """A target or published Gold reconciliation did not meet its contract."""


def _read_target(path: Path = TARGET_FILE) -> dict[str, Any]:
    try:
        target = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Week7PublishedCheckError("The approved target file is missing or invalid") from exc
    if (
        target.get("project_id") != EXPECTED_PROJECT
        or target.get("project_number") != EXPECTED_PROJECT_NUMBER
        or target.get("region") != EXPECTED_REGION
    ):
        raise Week7PublishedCheckError("Published Gold verification is restricted to the approved project")
    return target


def verify_published(
    *, tombstone_order_id: str | None = None, output: Path | None = None
) -> dict[str, Any]:
    target = _read_target()
    if tombstone_order_id is not None and not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", tombstone_order_id):
        raise Week7PublishedCheckError("tombstone_order_id must use a bounded business-key format")
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from google.cloud import bigquery
    except ImportError as exc:
        raise Week7PublishedCheckError("Published Gold verification requires the project's [gcp] dependencies") from exc

    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    if adc_project and adc_project != target["project_id"]:
        raise Week7PublishedCheckError("ADC project differs from the approved DataForge target")

    project = target["project_id"]
    sql = f"""
    WITH pointer AS (
      SELECT pointer_version, publication_id, candidate_row_count, candidate_sha256,
             source_checkpoint_seq, upper_seq, publication_is_current
      FROM `{project}.gold_week7.week7_publication_pointer`
      WHERE pointer_name = 'current_order_reconciliation'
    ), published AS (
      SELECT order_id, order_status, order_is_deleted, delivered_sales_proxy,
             collected_amount, collection_variance, active_payment_count,
             successful_payment_count, order_effective_seq
      FROM `{project}.gold_week7.published_order_reconciliation`
      WHERE publication_id = (SELECT publication_id FROM pointer)
    ), week5_gold AS (
      SELECT order_id, order_status AS week5_status,
             order_is_deleted AS week5_is_deleted,
             delivered_sales_proxy AS week5_delivered_sales_proxy,
             collected_amount AS week5_collected_amount,
             collection_variance AS week5_collection_variance,
             active_payment_count AS week5_active_payment_count,
             successful_payment_count AS week5_successful_payment_count,
             order_effective_seq AS week5_order_effective_seq
      FROM `{project}.gold.week5_order_controls`
    ), compared AS (
      SELECT
        week5_gold.order_id AS week5_order_id,
        published.order_id AS published_order_id,
        week5_gold.week5_status,
        published.order_status,
        week5_gold.week5_is_deleted,
        published.order_is_deleted,
        week5_gold.week5_delivered_sales_proxy,
        published.delivered_sales_proxy,
        week5_gold.week5_collected_amount,
        published.collected_amount,
        week5_gold.week5_collection_variance,
        published.collection_variance,
        week5_gold.week5_active_payment_count,
        published.active_payment_count,
        week5_gold.week5_successful_payment_count,
        published.successful_payment_count,
        week5_gold.week5_order_effective_seq,
        published.order_effective_seq
      FROM week5_gold
      FULL OUTER JOIN published USING (order_id)
    )
    SELECT
      (SELECT AS STRUCT pointer_version, publication_id, candidate_row_count,
                       candidate_sha256, source_checkpoint_seq, upper_seq,
                       publication_is_current
       FROM pointer) AS pointer,
      (SELECT AS STRUCT order_is_deleted,
                       CAST(collected_amount AS STRING) AS collected_amount,
                       collection_variance,
                       active_payment_count,
                       successful_payment_count
       FROM published
       WHERE order_id = @tombstone_order_id) AS tombstone_order,
      COUNTIF(week5_order_id IS NOT NULL) AS week5_row_count,
      COUNTIF(published_order_id IS NOT NULL) AS published_row_count,
      COUNTIF(week5_order_id IS NOT NULL AND published_order_id IS NULL) AS missing_rows,
      COUNTIF(week5_order_id IS NULL AND published_order_id IS NOT NULL) AS extra_rows,
      COUNTIF(week5_order_id IS NOT NULL AND published_order_id IS NOT NULL AND (
        week5_status IS DISTINCT FROM order_status
        OR week5_is_deleted IS DISTINCT FROM order_is_deleted
        OR week5_delivered_sales_proxy IS DISTINCT FROM delivered_sales_proxy
        OR week5_collected_amount IS DISTINCT FROM collected_amount
        OR week5_collection_variance IS DISTINCT FROM collection_variance
        OR week5_active_payment_count IS DISTINCT FROM active_payment_count
        OR week5_successful_payment_count IS DISTINCT FROM successful_payment_count
        OR week5_order_effective_seq IS DISTINCT FROM order_effective_seq
      )) AS mismatched_rows,
      SUM(delivered_sales_proxy) AS published_delivered_sales_proxy,
      SUM(collected_amount) AS published_collections,
      COUNTIF(order_is_deleted) AS published_order_tombstones,
      COUNTIF(order_is_deleted AND collected_amount > 0) AS tombstoned_orders_with_collections
    FROM compared
    """
    client = bigquery.Client(
        project=project,
        credentials=credentials,
        location=target["region"],
    )
    parameters = (
        [bigquery.ScalarQueryParameter("tombstone_order_id", "STRING", tombstone_order_id)]
        if tombstone_order_id is not None
        else [bigquery.ScalarQueryParameter("tombstone_order_id", "STRING", "")]
    )
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
            labels={"application": "dataforge", "phase": "week7", "action": "goldreconcile"},
            query_parameters=parameters,
        ),
        location=target["region"],
    )
    row = next(iter(job.result(timeout=300)))
    pointer = row["pointer"]
    tombstone_order = row["tombstone_order"]
    tombstone_order_result = (
        {
            "order_is_deleted": bool(tombstone_order["order_is_deleted"]),
            "collected_amount": str(tombstone_order["collected_amount"]),
            "collection_variance": (
                None
                if tombstone_order["collection_variance"] is None
                else str(tombstone_order["collection_variance"])
            ),
            "active_payment_count": int(tombstone_order["active_payment_count"]),
            "successful_payment_count": int(tombstone_order["successful_payment_count"]),
        }
        if tombstone_order is not None
        else None
    )
    tombstone_matches = (
        tombstone_order_result is not None
        and tombstone_order_result["order_is_deleted"]
        and tombstone_order_result["collected_amount"] == "5000"
        and tombstone_order_result["collection_variance"] is None
        and tombstone_order_result["active_payment_count"] == 1
        and tombstone_order_result["successful_payment_count"] == 1
    )
    result = {
        "project_id": project,
        "project_number": target["project_number"],
        "region": target["region"],
        "query_job_id": job.job_id,
        "bytes_processed": int(job.total_bytes_processed or 0),
        "bytes_billed": int(job.total_bytes_billed or 0),
        "maximum_bytes_billed": MAXIMUM_BYTES_BILLED,
        "slot_ms": int(job.slot_millis or 0),
        "pointer": {key: pointer[key] for key in pointer.keys()},
        "tombstone_order_id": tombstone_order_id,
        "tombstone_order": tombstone_order_result,
        "tombstone_order_check": (
            "PASS" if tombstone_matches else "FAIL"
        ) if tombstone_order_id is not None else "NOT_REQUESTED",
        "week5_row_count": int(row["week5_row_count"] or 0),
        "published_row_count": int(row["published_row_count"] or 0),
        "missing_rows": int(row["missing_rows"] or 0),
        "extra_rows": int(row["extra_rows"] or 0),
        "mismatched_rows": int(row["mismatched_rows"] or 0),
        "published_delivered_sales_proxy": str(row["published_delivered_sales_proxy"] or 0),
        "published_collections": str(row["published_collections"] or 0),
        "published_order_tombstones": int(row["published_order_tombstones"] or 0),
        "tombstoned_orders_with_collections": int(row["tombstoned_orders_with_collections"] or 0),
    }
    result["status"] = (
        "PASS"
        if pointer["pointer_version"] > 0
        and pointer["publication_is_current"] is True
        and result["week5_row_count"] == result["published_row_count"]
        and result["missing_rows"] == result["extra_rows"] == result["mismatched_rows"] == 0
        and (tombstone_order_id is None or tombstone_matches)
        else "FAIL"
    )
    encoded = json.dumps(result, indent=2, sort_keys=True, default=str)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    if result["status"] != "PASS":
        raise Week7PublishedCheckError("Published Week-7 Gold did not reconcile to Week-5 Gold")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tombstone-order-id")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    verify_published(
        tombstone_order_id=args.tombstone_order_id,
        output=Path(args.output) if args.output else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
