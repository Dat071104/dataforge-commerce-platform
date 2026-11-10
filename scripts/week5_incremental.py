"""Operator CLI for the isolated P7.2 source, batch, and status workflow.

Network access is opt-in. `batch` is local/dry-run by default; only `--execute`
uploads immutable objects to the fixed approved target. No command advances a
warehouse checkpoint directly; only the Cloud Run publish transaction does.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dataforge.cloud.google_cloud import GoogleCloudBackend
from dataforge.incremental import oracle, reconciliation, source
from dataforge.incremental.batch import EventBatch, extract_batch, make_run_id
from dataforge.incremental.bronze import (
    download_verified_batch,
    parse_gs_uri,
    serialize_batch,
    upload_batch,
)

ROOT = Path(__file__).resolve().parents[1]
TARGET_FILE = ROOT / "docs" / "cloud" / "target.json"
SCHEMA_SQL = ROOT / "cloud" / "sql_bigquery" / "week5" / "001_schema.sql"
APPROVED_TARGET = {
    "project_id": "dataforge-p7-lab-d0f725",
    "project_number": "955038620072",
    "region": "us-central1",
    "bucket": "dataforge-p7-lab-d0f725-bronze",
}
MAXIMUM_BYTES_BILLED = 268_435_456


class Week5CliError(RuntimeError):
    """A safe, user-actionable Week-5 CLI failure."""


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default))


def _target() -> dict[str, Any]:
    try:
        target = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Week5CliError("canonical cloud target metadata is missing or invalid") from exc
    for key, expected in APPROVED_TARGET.items():
        if target.get(key) != expected:
            raise Week5CliError(f"cloud target {key} differs from the approved Week-5 target")
    return target


def _backend(target: dict[str, Any]) -> GoogleCloudBackend:
    token = os.environ.get("DATAFORGE_GCP_ACCESS_TOKEN", "")
    if not token:
        raise Week5CliError(
            "cloud access requires the short-lived DATAFORGE_GCP_ACCESS_TOKEN from the "
            "isolated DataForge gcloud session"
        )
    return GoogleCloudBackend.from_local_access_token(target["project_id"], token)


def _wire_event(event: source.JournalEvent) -> dict[str, Any]:
    return {
        "change_seq": event.change_seq,
        "change_id": event.change_id,
        "source_table": event.source_table,
        "business_key": event.business_key,
        "operation": event.operation,
        "source_updated_at": event.source_updated_at,
        "business_event_at": event.business_event_at,
        "schema_version": event.schema_version,
        "payload": event.payload,
        "payload_sha256": event.payload_sha256,
    }


def _batch_from_source(args: argparse.Namespace, target: dict[str, Any]) -> tuple[EventBatch | None, str, int | None]:
    if (args.from_seq is None) != (args.to_seq is None):
        raise Week5CliError("--from-seq and --to-seq must be supplied together")
    if args.from_seq is not None:
        source_batch = source.read_backfill(
            args.from_seq,
            args.to_seq,
            max_events=args.max_events,
        )
        if not source_batch.events:
            return None, "backfill", None
        batch = extract_batch(
            (_wire_event(event) for event in source_batch.events),
            from_seq=args.from_seq,
            to_seq=args.to_seq,
            max_events=args.max_events,
        )
        return batch, "backfill", None

    if args.execute:
        backend = _backend(target)
        checkpoint = backend.read_week5_checkpoint(
            project_id=target["project_id"],
            region=target["region"],
            maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        )["committed_seq"]
    else:
        checkpoint = args.checkpoint if args.checkpoint is not None else 0
    source_batch = source.read_normal_batch(
        checkpoint,
        max_events=args.max_events,
    )
    if not source_batch.events:
        return None, "normal", checkpoint
    batch = extract_batch(
        (_wire_event(event) for event in source_batch.events),
        checkpoint=checkpoint,
        captured_upper_seq=source_batch.captured_upper_seq,
        max_events=args.max_events,
    )
    return batch, "normal", checkpoint


def _cmd_source_init(_: argparse.Namespace) -> None:
    source.initialize()
    _emit({"status": "SOURCE_INITIALIZED", "source_identity": source.SOURCE_IDENTITY})


def _cmd_seed(_: argparse.Namespace) -> None:
    events = source.seed_source()
    _emit(
        {
            "status": "SEEDED_OR_REUSED",
            "source_identity": source.SOURCE_IDENTITY,
            "event_count": len(events),
            "change_seq_min": min(item.change_seq for item in events),
            "change_seq_max": max(item.change_seq for item in events),
        }
    )


def _cmd_scenario(args: argparse.Namespace) -> None:
    events = source.apply_scenario(args.scenario)
    _emit(
        {
            "status": "SCENARIO_APPLIED_OR_REUSED",
            "scenario": args.scenario,
            "event_count": len(events),
            "change_seq_min": min(item.change_seq for item in events),
            "change_seq_max": max(item.change_seq for item in events),
        }
    )


def _cmd_batch(args: argparse.Namespace) -> None:
    target = _target()
    batch, run_mode, checkpoint = _batch_from_source(args, target)
    if batch is None:
        _emit(
            {
                "status": "NO_NEW_BATCH",
                "run_mode": run_mode,
                "checkpoint_read": checkpoint,
                "source_identity": source.SOURCE_IDENTITY,
            }
        )
        return

    parquet = serialize_batch(batch)
    payload_sha256 = hashlib.sha256(parquet).hexdigest()
    receipt: dict[str, Any] = {
        "status": "DRY_RUN_READY",
        "run_mode": run_mode,
        "source_identity": batch.source_identity,
        "source_run_id": f"{batch.source_identity}:{batch.batch_id}",
        "batch_id": batch.batch_id,
        "lower_seq": batch.lower_seq,
        "upper_seq": batch.upper_seq,
        "event_seq_min": min(event["change_seq"] for event in batch.events),
        "event_seq_max": max(event["change_seq"] for event in batch.events),
        "event_count": batch.row_count,
        "row_value_sha256": batch.row_value_sha256,
        "parquet_sha256": payload_sha256,
        "parquet_size_bytes": len(parquet),
        "checkpoint_read": checkpoint,
        "checkpoint_mutated": False,
    }
    if args.execute:
        backend = _backend(target)
        bucket_location, dataset_location = backend.target_locations(
            target["project_id"],
            target["bucket"],
            "staging",
            target["project_number"],
        )
        if bucket_location.upper() != target["region"].upper() or dataset_location != target["region"]:
            raise Week5CliError("approved GCS and BigQuery staging locations do not match the target region")
        bronze = upload_batch(batch, backend, bucket=target["bucket"], fail_after_upload=args.fail_after_upload)
        receipt.update(
            {
                "status": "UPLOADED_COMPLETE",
                "gcs_uri": bronze.object_uri,
                "gcs_generation": bronze.object_generation,
                "gcs_sha256": bronze.parquet_sha256,
                "manifest_uri": bronze.manifest_uri,
                "manifest_generation": bronze.manifest_generation,
                "manifest_sha256": bronze.manifest_sha256,
            }
        )
    elif args.fail_after_upload:
        raise Week5CliError("--fail-after-upload requires --execute because it tests GCS promotion")
    _emit(receipt)


def _cmd_schema(args: argparse.Namespace) -> None:
    target = _target()
    if not args.execute:
        raise Week5CliError("cloud schema creation requires the explicit --execute flag")
    backend = _backend(target)
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    if "DROP TABLE" in sql.upper() or "TRUNCATE TABLE" in sql.upper():
        raise Week5CliError("Week-5 schema DDL contains a destructive statement")
    job_id = f"week5_schema_{os.urandom(12).hex()}"
    job = backend._bigquery.query(
        sql,
        job_config=backend._bigquery_module.QueryJobConfig(
            use_legacy_sql=False,
            maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        ),
        job_id=job_id,
        job_retry=None,
        location=target["region"],
        retry=backend._request_retry,
        timeout=60,
    )
    job.result(retry=backend._request_retry, timeout=300)
    _emit(
        {
            "status": "SCHEMA_CREATED_OR_VERIFIED",
            "project_id": target["project_id"],
            "region": target["region"],
            "job_id": str(job.job_id),
            "bytes_processed": getattr(job, "total_bytes_processed", None),
            "bytes_billed": getattr(job, "total_bytes_billed", None),
            "maximum_bytes_billed": MAXIMUM_BYTES_BILLED,
        }
    )


def _cmd_status(args: argparse.Namespace) -> None:
    target = _target()
    backend = _backend(target)
    checkpoint = backend.read_week5_checkpoint(
        project_id=target["project_id"],
        region=target["region"],
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
    )
    events = backend.read_week5_run_events(
        project_id=target["project_id"],
        region=target["region"],
        limit=args.limit,
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
    )
    _emit(
        {
            "project_id": target["project_id"],
            "region": target["region"],
            "checkpoint": checkpoint,
            "recent_run_events": events,
        }
    )


def _job_summary(job: Any) -> dict[str, Any]:
    return {
        "job_id": str(getattr(job, "job_id", "")),
        "job_type": getattr(job, "job_type", None),
        "state": getattr(job, "state", None),
        "statement_type": getattr(job, "statement_type", None),
        "parent_job_id": getattr(job, "parent_job_id", None),
        "created": getattr(job, "created", None),
        "started": getattr(job, "started", None),
        "ended": getattr(job, "ended", None),
        "total_bytes_processed": getattr(job, "total_bytes_processed", None),
        "total_bytes_billed": getattr(job, "total_bytes_billed", None),
        "total_slot_ms": getattr(job, "slot_millis", None),
        "error_result": getattr(job, "error_result", None),
    }


def _cmd_job_stats(args: argparse.Namespace) -> None:
    target = _target()
    if not args.job_id.startswith("week5_") or not args.job_id.replace("_", "").replace("-", "").isalnum():
        raise Week5CliError("job ID must use the bounded Week-5 identifier prefix")
    backend = _backend(target)
    region_view = f"region-{target['region']}"
    query = f"""
SELECT job_id, parent_job_id, job_type, state, statement_type,
       creation_time, start_time, end_time, total_bytes_processed,
       total_bytes_billed, total_slot_ms,
       error_result.reason AS error_reason
FROM `{region_view}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND (job_id = @job_id OR parent_job_id = @job_id)
ORDER BY creation_time
""".strip()
    job = backend._bigquery.query(
        query,
        job_config=backend._bigquery_module.QueryJobConfig(
            use_legacy_sql=False,
            query_parameters=[
                backend._bigquery_module.ScalarQueryParameter("job_id", "STRING", args.job_id)
            ],
            maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        ),
        job_id=f"week5_jobstats_{os.urandom(8).hex()}",
        job_retry=None,
        location=target["region"],
        retry=backend._request_retry,
        timeout=60,
    )
    rows = [dict(row.items()) for row in job.result(retry=backend._request_retry, timeout=300)]
    parent_rows = [row for row in rows if row["job_id"] == args.job_id]
    child_rows = [row for row in rows if row.get("parent_job_id") == args.job_id]
    capture = {
        "parent_job_id": args.job_id,
        "parent": parent_rows,
        "child_jobs": child_rows,
        "metadata_query_job_id": str(job.job_id),
        "metadata_query_bytes_billed": getattr(job, "total_bytes_billed", None),
        "maximum_bytes_billed": MAXIMUM_BYTES_BILLED,
    }
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        output_path = output_path.resolve()
        try:
            output_path.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise Week5CliError("job receipt output must stay inside the repository") from exc
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if args.append and output_path.is_file():
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if existing.get("project_id") != target["project_id"]:
                raise Week5CliError("existing job receipt belongs to a different project")
        else:
            existing = {
                "project_id": target["project_id"],
                "region": target["region"],
                "jobs": {},
            }
        existing.setdefault("jobs", {})[args.job_id] = capture
        output_path.write_text(
            json.dumps(existing, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default)
            + "\n",
            encoding="utf-8",
        )
        capture["output_path"] = str(output_path)
    _emit({"project_id": target["project_id"], "region": target["region"], **capture})


def _cmd_record_failed_attempt(args: argparse.Namespace) -> None:
    target = _target()
    bucket, _ = parse_gs_uri(args.manifest_uri)
    if bucket != target["bucket"] or not args.manifest_uri.startswith(
        f"gs://{target['bucket']}/manifests/week5/"
    ):
        raise Week5CliError("failure receipt manifest must use the approved Week-5 Bronze prefix")
    backend = _backend(target)
    batch, manifest, manifest_sha256, _ = download_verified_batch(
        backend,
        manifest_uri=args.manifest_uri,
        manifest_generation=args.manifest_generation,
    )
    if args.batch_id and args.batch_id != batch.batch_id:
        raise Week5CliError("supplied batch_id differs from the immutable manifest")
    run_id = make_run_id(args.execution_id, args.attempt)
    error_messages = {
        "BQ_LEDGER_INSERT_SQL_INVALID": (
            "Initial Cloud Run attempt failed before manifest download because the runtime "
            "ledger INSERT used unsupported BigQuery syntax; no staging or publish occurred."
        ),
        "TARGET_BOUNDARY_FAILED": "Target bucket/dataset ownership or location check failed.",
        "BATCH_VALIDATION_FAILED": "Manifest or Parquet validation failed closed.",
        "INJECTED_FAILURE": "A bounded Week-5 failure was injected for recovery verification.",
        "WEEK5_PROCESSING_FAILED": "Week-5 processing failed; inspect the recorded job receipts.",
    }
    message = error_messages[args.error_code]
    metadata = {
        "execution_id": args.execution_id,
        "batch_id": batch.batch_id,
        "run_mode": args.run_mode,
        "source_run_id": manifest["source_run_id"],
        "manifest_uri": args.manifest_uri,
        "manifest_generation": args.manifest_generation,
        "lower_seq": batch.lower_seq,
        "upper_seq": batch.upper_seq,
        "expected_row_count": batch.row_count,
        "row_value_sha256": batch.row_value_sha256,
        "manifest_sha256": manifest_sha256,
        "object_sha256": manifest["parquet"]["sha256"],
        "object_generation": manifest["parquet"]["generation"],
    }
    if not args.execute:
        _emit(
            {
                "status": "DRY_RUN_FAILURE_LEDGER_EVENT",
                "run_id": run_id,
                "execution_id": args.execution_id,
                "attempt": args.attempt,
                "error_code": args.error_code,
                **metadata,
            }
        )
        return
    receipt = backend.record_week5_failure(
        project_id=target["project_id"],
        region=target["region"],
        run_id=run_id,
        error_code=args.error_code,
        error_message=message,
        attempt=args.attempt,
        metadata=metadata,
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
    )
    _emit(
        {
            "status": "FAILED_EVENT_RECORDED" if receipt["recorded"] else "FAILED_EVENT_ALREADY_RECORDED",
            "run_id": run_id,
            "execution_id": args.execution_id,
            "attempt": args.attempt,
            "error_code": args.error_code,
            "job_ids": {"check": receipt["check_job_id"], "insert": receipt["insert_job_id"]},
            **metadata,
        }
    )


def _cmd_oracle(_: argparse.Namespace) -> None:
    import psycopg

    dsn = source.operational_database_url()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(change_seq), 0) FROM dataforge_operational.change_journal")
            upper = int(cur.fetchone()[0])
    if upper == 0:
        _emit({"status": "EMPTY_SOURCE", "source_identity": source.SOURCE_IDENTITY})
        return
    events = source.read_backfill(1, upper, max_events=100_000).events
    result = oracle.replay_journal(events)
    controls = [
        {
            "order_id": item.order_id,
            "order_date": item.order_date,
            "order_is_deleted": item.order_is_deleted,
            "order_status": item.order_status,
            "delivered_sales_proxy": format(item.delivered_sales_proxy, "f"),
            "collected_amount": format(item.collections, "f"),
            "collection_variance": (
                None if item.collection_variance is None else format(item.collection_variance, "f")
            ),
            "effective_seq": item.effective_seq,
        }
        for item in sorted(result.controls.values(), key=lambda row: row.order_id)
    ]
    _emit(
        {
            "status": "ORACLE_REPLAYED",
            "source_identity": source.SOURCE_IDENTITY,
            "upper_seq": upper,
            "journal_event_count": len(events),
            "order_count": result.order_count,
            "payment_event_count": result.payment_count,
            "delivered_sales_proxy_total": format(result.delivered_sales_total, "f"),
            "collections_total": format(result.collections_total, "f"),
            "controls": controls,
        }
    )


def _cmd_reconcile(args: argparse.Namespace) -> None:
    """Compare Silver and Gold at the committed sequence to a separate Decimal replay."""
    target = _target()
    backend = _backend(target)
    checkpoint = backend.read_week5_checkpoint(
        project_id=target["project_id"],
        region=target["region"],
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
    )
    committed_seq = int(checkpoint["committed_seq"])
    source_batch = source.read_backfill(1, committed_seq, max_events=100_000)
    source_events = source_batch.events
    if source_events and max(row.change_seq for row in source_events) != committed_seq:
        raise Week5CliError("local source journal does not contain the exact committed checkpoint")
    if not source_events and committed_seq != 0:
        raise Week5CliError("local source journal is empty but the cloud checkpoint is non-zero")
    expected = oracle.replay_journal(source_events)

    query_config = backend._bigquery_module.QueryJobConfig(
        use_legacy_sql=False,
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
    )
    table_queries = {
        "silver_orders": """
SELECT order_id, customer_id, CAST(order_date AS STRING) AS order_date,
       province_id, order_status, order_net_amount, is_deleted, effective_seq,
       last_change_id, last_payload_sha256
FROM `dataforge-p7-lab-d0f725.silver.week5_orders`
""",
        "silver_payments": """
SELECT payment_id, order_id, CAST(payment_date AS STRING) AS payment_date,
       amount, payment_status, method, is_deleted, effective_seq,
       last_change_id, last_payload_sha256
FROM `dataforge-p7-lab-d0f725.silver.week5_payment_events`
""",
        "gold_controls": """
SELECT order_id, CAST(order_date AS STRING) AS order_date, order_status,
       order_is_deleted, delivered_sales_proxy, collected_amount,
       collection_variance, active_payment_count, successful_payment_count,
       order_effective_seq
FROM `dataforge-p7-lab-d0f725.gold.week5_order_controls`
""",
    }
    query_jobs: list[dict[str, Any]] = []
    table_rows: dict[str, list[dict[str, Any]]] = {}
    for table_key, sql in table_queries.items():
        job_id = f"week5_reconcile_{table_key}_{os.urandom(6).hex()}"
        job = backend._bigquery.query(
            sql,
            job_config=query_config,
            job_id=job_id,
            job_retry=None,
            location=target["region"],
        )
        table_rows[table_key] = [dict(row.items()) for row in job.result(timeout=300)]
        query_jobs.append(
            {
                "job_id": str(job.job_id),
                "table": table_key,
                "bytes_processed": getattr(job, "total_bytes_processed", None),
                "bytes_billed": getattr(job, "total_bytes_billed", None),
                "slot_ms": getattr(job, "slot_millis", None),
            }
        )

    checks = reconciliation.compare_warehouse_state(
        expected,
        silver_orders=table_rows["silver_orders"],
        silver_payments=table_rows["silver_payments"],
        gold_controls=table_rows["gold_controls"],
    )
    mismatches = [row for row in checks if row["match"] != "true"]
    output_path = (ROOT / args.output).resolve()
    if not output_path.is_relative_to(ROOT.resolve()):
        raise Week5CliError("reconciliation output must remain inside the repository")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=reconciliation.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(checks)
    temporary.replace(output_path)

    summary = {
        "status": "RECONCILED" if not mismatches else "MISMATCHES_FOUND",
        "project_id": target["project_id"],
        "region": target["region"],
        "source_identity": source.SOURCE_IDENTITY,
        "checkpoint_seq": committed_seq,
        "source_event_count": len(source_events),
        "source_event_max_seq": max((row.change_seq for row in source_events), default=0),
        "oracle_order_count": expected.order_count,
        "oracle_payment_event_count": expected.payment_count,
        "silver_order_count": len(table_rows["silver_orders"]),
        "silver_payment_event_count": len(table_rows["silver_payments"]),
        "gold_order_control_count": len(table_rows["gold_controls"]),
        "delivered_sales_proxy_total": format(expected.delivered_sales_total, "f"),
        "collections_total_including_tombstoned_orders": format(expected.collections_total, "f"),
        "comparison_rows": len(checks),
        "mismatch_count": len(mismatches),
        "reconciliation_csv": output_path.relative_to(ROOT.resolve()).as_posix(),
        "checkpoint_job": checkpoint,
        "table_query_jobs": query_jobs,
    }
    summary_path = output_path.with_name("reconciliation_summary.json")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    _emit(summary)
    if mismatches:
        raise Week5CliError(f"{len(mismatches)} independent oracle comparisons did not match")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DataForge P7.2 incremental batch operator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("source-init", help="initialize only the isolated Week-5 PostgreSQL schema")
    subparsers.add_parser("seed", help="insert or safely reuse deterministic initial source events")
    scenario = subparsers.add_parser("scenario", help="apply or safely reuse one source change scenario")
    scenario.add_argument(
        "scenario",
        choices=("INC-03", "INC-04", "INC-05", "INC-06", "INC-08", "INC-09", "INC-10"),
    )

    batch = subparsers.add_parser("batch", help="build a bounded batch; upload only with --execute")
    batch.add_argument("--max-events", type=int, default=1000)
    batch.add_argument("--checkpoint", type=int, help="offline checkpoint for dry-run normal extraction")
    batch.add_argument("--from-seq", type=int)
    batch.add_argument("--to-seq", type=int)
    batch.add_argument("--execute", action="store_true", help="upload immutable GCS Parquet and manifest")
    batch.add_argument("--fail-after-upload", action="store_true", help="inject failure before COMPLETE manifest")

    schema = subparsers.add_parser("schema", help="create or verify additive Week-5 BigQuery schemas")
    schema.add_argument("--execute", action="store_true", help="apply the bounded additive SQL DDL")

    status = subparsers.add_parser("status", help="read committed checkpoint and recent run events")
    status.add_argument("--limit", type=int, default=50)
    job_stats = subparsers.add_parser("job-stats", help="read a Week-5 BigQuery parent and child job receipt")
    job_stats.add_argument("job_id")
    job_stats.add_argument("--output", help="repository-relative JSON receipt path")
    job_stats.add_argument("--append", action="store_true", help="merge this job into an existing receipt")
    failed = subparsers.add_parser(
        "record-failed-attempt",
        help="idempotently persist a sanitized failure receipt for a completed Cloud Run attempt",
    )
    failed.add_argument("--execution-id", required=True)
    failed.add_argument("--attempt", type=int, choices=(0, 1), required=True)
    failed.add_argument("--manifest-uri", required=True)
    failed.add_argument("--manifest-generation", type=int, required=True)
    failed.add_argument("--run-mode", choices=("normal", "backfill"), required=True)
    failed.add_argument("--batch-id")
    failed.add_argument(
        "--error-code",
        choices=(
            "BQ_LEDGER_INSERT_SQL_INVALID",
            "TARGET_BOUNDARY_FAILED",
            "BATCH_VALIDATION_FAILED",
            "INJECTED_FAILURE",
            "WEEK5_PROCESSING_FAILED",
        ),
        required=True,
    )
    failed.add_argument("--execute", action="store_true", help="append the failure event to ops")
    subparsers.add_parser("oracle", help="replay the complete local journal with the independent Decimal oracle")
    reconcile = subparsers.add_parser(
        "reconcile", help="compare committed Silver/Gold to the local independent Decimal oracle"
    )
    reconcile.add_argument("--output", default="docs/cloud/week5/reconciliation.csv")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    actions = {
        "source-init": _cmd_source_init,
        "seed": _cmd_seed,
        "scenario": _cmd_scenario,
        "batch": _cmd_batch,
        "schema": _cmd_schema,
        "status": _cmd_status,
        "job-stats": _cmd_job_stats,
        "record-failed-attempt": _cmd_record_failed_attempt,
        "oracle": _cmd_oracle,
        "reconcile": _cmd_reconcile,
    }
    actions[args.command](args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Week5CliError as exc:
        raise SystemExit(f"dataforge-week5: {exc}") from exc
