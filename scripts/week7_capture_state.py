"""Capture bounded Week-5 and Week-7 control state for a test receipt."""

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


class Week7StateError(RuntimeError):
    """The approved target or control-state singleton is invalid."""


def _json_value(value: Any) -> Any:
    if hasattr(value, "items"):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _read_target(path: Path = TARGET_FILE) -> dict[str, Any]:
    try:
        target = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Week7StateError("The approved target file is missing or invalid") from exc
    if (
        target.get("project_id") != EXPECTED_PROJECT
        or target.get("project_number") != EXPECTED_PROJECT_NUMBER
        or target.get("region") != EXPECTED_REGION
    ):
        raise Week7StateError("State capture is restricted to the approved isolated project")
    return target


def capture_state(*, label: str, output: Path | None = None) -> dict[str, Any]:
    target = _read_target()
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from google.cloud import bigquery
    except ImportError as exc:
        raise Week7StateError("State capture requires the project's [gcp] dependencies") from exc

    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    if adc_project and adc_project != target["project_id"]:
        raise Week7StateError("ADC project differs from the approved DataForge target")

    project = target["project_id"]
    sql = f"""
    SELECT
      (SELECT AS STRUCT source_id, committed_seq, last_batch_id, manifest_generation
       FROM `{project}.ops.pipeline_checkpoints`
       WHERE source_id = 'dataforge-operational-v1') AS checkpoint,
      (SELECT AS STRUCT COUNT(*) AS row_count,
                       COUNTIF(is_deleted) AS tombstone_count,
                       MAX(effective_seq) AS max_effective_seq
       FROM `{project}.silver.week5_orders`) AS silver_orders,
      (SELECT AS STRUCT COUNT(*) AS row_count,
                       COUNTIF(is_deleted) AS tombstone_count,
                       COUNTIF(NOT is_deleted AND payment_status = 'success') AS active_successes,
                       MAX(effective_seq) AS max_effective_seq
       FROM `{project}.silver.week5_payment_events`) AS silver_payments,
      (SELECT AS STRUCT COUNT(*) AS row_count,
                       SUM(delivered_sales_proxy) AS delivered_sales_proxy,
                       SUM(collected_amount) AS collected_amount
       FROM `{project}.gold.week5_order_controls`) AS week5_gold,
      (SELECT AS STRUCT pointer_version, published_run_mode, publication_id,
                       published_run_id, batch_id, manifest_generation, upper_seq,
                       source_checkpoint_seq, candidate_dataset, candidate_row_count,
                       candidate_sha256, published_at, publication_is_current
       FROM `{project}.gold_week7.week7_publication_pointer`
       WHERE pointer_name = 'current_order_reconciliation') AS publication_pointer,
      (SELECT AS STRUCT COUNT(*) AS row_count,
                       COUNTIF(lock_owner IS NOT NULL) AS owned_rows,
                       MAX(lock_version) AS lock_version
       FROM `{project}.ops.week7_publish_lock`
       WHERE lock_name = 'week7-dbt-publication') AS publication_lock
    """
    client = bigquery.Client(
        project=project,
        credentials=credentials,
        location=target["region"],
    )
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
            labels={"application": "dataforge", "phase": "week7", "action": "statecheck"},
        ),
        location=target["region"],
    )
    row = next(iter(job.result(timeout=300)))
    values = {key: _json_value(value) for key, value in row.items()}
    pointer = values["publication_pointer"]
    lock = values["publication_lock"]
    checkpoint = values["checkpoint"]
    if checkpoint is None or pointer is None or lock["row_count"] != 1:
        raise Week7StateError("Checkpoint, publication pointer, or lock singleton is missing")
    result = {
        "label": label,
        "project_id": project,
        "project_number": target["project_number"],
        "region": target["region"],
        "state": values,
        "query_job_id": job.job_id,
        "bytes_processed": int(job.total_bytes_processed or 0),
        "bytes_billed": int(job.total_bytes_billed or 0),
        "maximum_bytes_billed": MAXIMUM_BYTES_BILLED,
        "slot_ms": int(job.slot_millis or 0),
    }
    encoded = json.dumps(result, indent=2, sort_keys=True, default=str)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    capture_state(label=args.label, output=Path(args.output) if args.output else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
