"""Compare the isolated Week-7 incremental and full-refresh BigQuery outputs."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    from scripts.week7_initialize_cloud import (
        EXPECTED_PROJECT,
        MAXIMUM_BYTES_BILLED,
        _load_approved_target,
    )
except ModuleNotFoundError:
    from week7_initialize_cloud import (  # type: ignore[no-redef]
        EXPECTED_PROJECT,
        MAXIMUM_BYTES_BILLED,
        _load_approved_target,
    )


class Week7ComparisonError(RuntimeError):
    """The two isolated dbt outputs differ or cannot be checked safely."""


def build_comparison_sql(project: str) -> str:
    if project != EXPECTED_PROJECT:
        raise Week7ComparisonError("Full/incremental comparison is restricted to the approved project")
    fields = (
        "customer_id",
        "order_date",
        "province_id",
        "order_status",
        "order_is_deleted",
        "delivered_sales_proxy",
        "collected_amount",
        "collection_variance",
        "active_payment_count",
        "successful_payment_count",
        "order_effective_seq",
        "max_payment_effective_seq",
        "order_id_bucket",
        "order_ingested_at",
        "latest_payment_ingested_at",
    )
    diff = "\n".join(
        f"OR incremental.{field} IS DISTINCT FROM full_refresh.{field}" for field in fields
    )
    return f"""
    WITH incremental AS (
      SELECT *
      FROM `{project}.dbt_week7.fct_week7_order_reconciliation`
    ),
    full_refresh AS (
      SELECT *
      FROM `{project}.dbt_week7_full.fct_week7_order_reconciliation`
    ),
    differences AS (
      SELECT COALESCE(incremental.order_id, full_refresh.order_id) AS order_id
      FROM incremental
      FULL OUTER JOIN full_refresh USING (order_id)
      WHERE incremental.order_id IS NULL
         OR full_refresh.order_id IS NULL
         {diff}
    )
    SELECT
      (SELECT COUNT(*) FROM incremental) AS incremental_rows,
      (SELECT COUNT(*) FROM full_refresh) AS full_refresh_rows,
      (SELECT COUNT(DISTINCT order_id) FROM incremental) AS incremental_unique_order_ids,
      (SELECT COUNT(DISTINCT order_id) FROM full_refresh) AS full_refresh_unique_order_ids,
      (SELECT COUNT(*) FROM differences) AS mismatch_rows,
      (SELECT CAST(SUM(delivered_sales_proxy) AS STRING) FROM incremental)
        AS incremental_delivered_sales_proxy,
      (SELECT CAST(SUM(delivered_sales_proxy) AS STRING) FROM full_refresh)
        AS full_refresh_delivered_sales_proxy,
      (SELECT CAST(SUM(collected_amount) AS STRING) FROM incremental)
        AS incremental_collected_amount,
      (SELECT CAST(SUM(collected_amount) AS STRING) FROM full_refresh)
        AS full_refresh_collected_amount
    """


def compare_full_incremental(*, output: Path | None = None) -> dict[str, Any]:
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from google.cloud import bigquery
    except ImportError as exc:
        raise Week7ComparisonError("Comparison requires the project's [gcp] dependencies") from exc
    target = _load_approved_target()
    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    if adc_project and adc_project != target["project_id"]:
        raise Week7ComparisonError("ADC project differs from the approved DataForge target")

    client = bigquery.Client(
        project=target["project_id"],
        credentials=credentials,
        location=target["region"],
    )
    started = time.monotonic()
    job = client.query(
        build_comparison_sql(target["project_id"]),
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAXIMUM_BYTES_BILLED),
        location=target["region"],
    )
    row = next(iter(job.result()))
    receipt = {
        "project_id": target["project_id"],
        "location": target["region"],
        "job_id": job.job_id,
        "status": "PASS" if (
            int(row["incremental_rows"]) == int(row["full_refresh_rows"])
            and int(row["incremental_rows"]) == int(row["incremental_unique_order_ids"])
            and int(row["full_refresh_rows"]) == int(row["full_refresh_unique_order_ids"])
            and int(row["mismatch_rows"]) == 0
            and row["incremental_delivered_sales_proxy"]
            == row["full_refresh_delivered_sales_proxy"]
            and row["incremental_collected_amount"] == row["full_refresh_collected_amount"]
        ) else "FAIL",
        "incremental_rows": int(row["incremental_rows"]),
        "full_refresh_rows": int(row["full_refresh_rows"]),
        "incremental_unique_order_ids": int(row["incremental_unique_order_ids"]),
        "full_refresh_unique_order_ids": int(row["full_refresh_unique_order_ids"]),
        "mismatch_rows": int(row["mismatch_rows"]),
        "incremental_delivered_sales_proxy": row["incremental_delivered_sales_proxy"],
        "full_refresh_delivered_sales_proxy": row["full_refresh_delivered_sales_proxy"],
        "incremental_collected_amount": row["incremental_collected_amount"],
        "full_refresh_collected_amount": row["full_refresh_collected_amount"],
        "bytes_processed": int(job.total_bytes_processed or 0),
        "bytes_billed": int(job.total_bytes_billed or 0),
        "maximum_bytes_billed": MAXIMUM_BYTES_BILLED,
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    encoded = json.dumps(receipt, indent=2, sort_keys=True)
    if output:
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    if receipt["status"] != "PASS":
        raise Week7ComparisonError("The incremental and full-refresh Week-7 tables do not match")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional sanitized comparison receipt path")
    args = parser.parse_args(argv)
    try:
        compare_full_incremental(output=args.output)
    except Week7ComparisonError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
