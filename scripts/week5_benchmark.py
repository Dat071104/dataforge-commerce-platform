"""Bounded synthetic BigQuery snapshot-versus-incremental benchmark."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq
from google.cloud import bigquery

from dataforge.cloud.google_cloud import GoogleCloudBackend

APPROVED_TARGET = {
    "project_id": "dataforge-p7-lab-d0f725",
    "project_number": "955038620072",
    "region": "us-central1",
    "bucket": "dataforge-p7-lab-d0f725-bronze",
}


ROW_COUNT = 100_000
CHANGE_INTERVAL = 100
MAXIMUM_QUERY_BYTES_BILLED = 268_435_456
_SCHEMA = pa.schema(
    [
        pa.field("order_id", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("amount", pa.decimal128(18, 2), nullable=False),
        pa.field("payload", pa.string(), nullable=False),
        pa.field("effective_seq", pa.int64(), nullable=False),
    ],
    metadata={b"dataforge.contract": b"week5-synthetic-benchmark-v1"},
)
_BQ_SCHEMA = [
    bigquery.SchemaField("order_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("amount", "NUMERIC", mode="REQUIRED"),
    bigquery.SchemaField("payload", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("effective_seq", "INT64", mode="REQUIRED"),
]


class BenchmarkError(RuntimeError):
    """A bounded benchmark setup or verification failed."""


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _order_id(index: int) -> str:
    return f"W5BENCH{index:06d}"


def _payload(index: int, revision: str) -> str:
    return "".join(
        hashlib.sha256(f"dataforge-week5-benchmark|{index}|{revision}|{part}".encode()).hexdigest()
        for part in range(6)
    )


def _base_amount(index: int) -> Decimal:
    return Decimal("100.00") + Decimal(index % 1000) / Decimal("100")


def _record(index: int, *, final: bool) -> dict[str, Any]:
    changed = final and index % CHANGE_INTERVAL == 0
    return {
        "order_id": _order_id(index),
        "status": "settled" if changed else ("processing" if index % 3 == 0 else "paid"),
        "amount": _base_amount(index) + (Decimal("1.25") if changed else Decimal("0.00")),
        "payload": _payload(index, "updated" if changed else "base"),
        "effective_seq": ROW_COUNT + index // CHANGE_INTERVAL + 1 if changed else 1,
    }


def _write_parquet(records: Iterable[dict[str, Any]]) -> bytes:
    buffer = io.BytesIO()
    writer = pq.ParquetWriter(
        buffer,
        _SCHEMA,
        compression="zstd",
        compression_level=7,
        use_dictionary=False,
        version="2.6",
        write_statistics=True,
    )
    chunk: list[dict[str, Any]] = []
    try:
        for record in records:
            chunk.append(record)
            if len(chunk) == 10_000:
                writer.write_table(pa.Table.from_pylist(chunk, schema=_SCHEMA))
                chunk.clear()
        if chunk:
            writer.write_table(pa.Table.from_pylist(chunk, schema=_SCHEMA))
    finally:
        writer.close()
    return buffer.getvalue()


def _job_receipt(job: Any) -> dict[str, Any]:
    job.reload()
    started = getattr(job, "started", None)
    ended = getattr(job, "ended", None)
    elapsed = None
    if started and ended:
        elapsed = round((ended - started).total_seconds(), 3)
    return {
        "job_id": str(job.job_id),
        "job_type": getattr(job, "job_type", None),
        "state": getattr(job, "state", None),
        "statement_type": getattr(job, "statement_type", None),
        "started_at": started,
        "ended_at": ended,
        "elapsed_seconds": elapsed,
        "bytes_processed": getattr(job, "total_bytes_processed", None),
        "bytes_billed": getattr(job, "total_bytes_billed", None),
        "slot_ms": getattr(job, "slot_millis", None),
        "error_result": getattr(job, "error_result", None),
    }


def _aggregate_query_usage(jobs: list[dict[str, Any]]) -> tuple[int, int, float]:
    """Sum top-level query jobs only; load/copy jobs carry no query-analysis bytes."""
    query_jobs = [row for row in jobs if str(row.get("job_type", "")).lower() == "query"]
    processed = sum(int(row.get("bytes_processed") or 0) for row in query_jobs)
    billed = sum(int(row.get("bytes_billed") or 0) for row in query_jobs)
    gross_list_cost = (billed / 1_099_511_627_776) * 6.25
    return processed, billed, gross_list_cost


def _run_query(
    client: Any,
    *,
    sql: str,
    job_id: str,
    location: str,
) -> Any:
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            use_legacy_sql=False,
            maximum_bytes_billed=MAXIMUM_QUERY_BYTES_BILLED,
        ),
        job_id=job_id,
        job_retry=None,
        location=location,
    )
    job.result(timeout=600)
    return job


def _load_parquet(
    client: Any,
    *,
    payload: bytes,
    table_id: str,
    job_id: str,
    location: str,
) -> Any:
    stream = io.BytesIO(payload)
    job = client.load_table_from_file(
        stream,
        table_id,
        rewind=True,
        job_config=bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            schema=_BQ_SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_EMPTY,
        ),
        job_id=job_id,
        num_retries=3,
        location=location,
    )
    job.result(timeout=600)
    return job


def _create_scratch_table(client: Any, table_id: str, expires: datetime) -> None:
    table = bigquery.Table(table_id, schema=_BQ_SCHEMA)
    table.expires = expires
    client.create_table(table, exists_ok=False)


def _upload_immutable(backend: GoogleCloudBackend, *, bucket: str, name: str, payload: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(payload).hexdigest()
    metadata = {"dataforge-week5-sha256": digest, "dataforge-week5-purpose": "synthetic-benchmark"}
    backend.put_object(
        bucket,
        name,
        payload,
        metadata,
        "application/vnd.apache.parquet",
        if_generation_match=0,
    )
    stored = backend.get_object(bucket, name)
    if stored is None or bytes(stored.payload or b"") != payload:
        raise BenchmarkError("created benchmark GCS object failed exact byte verification")
    return {
        "uri": f"gs://{bucket}/{name}",
        "generation": int(stored.generation),
        "sha256": digest,
        "size_bytes": len(payload),
        "metadata": dict(stored.metadata or {}),
    }


def execute_benchmark() -> dict[str, Any]:
    target = dict(APPROVED_TARGET)
    token = os.environ.get("DATAFORGE_GCP_ACCESS_TOKEN", "")
    if not token:
        raise BenchmarkError("benchmark execution requires a short-lived DataForge access token")
    backend = GoogleCloudBackend.from_local_access_token(target["project_id"], token)
    bucket_location, dataset_location = backend.target_locations(
        target["project_id"], target["bucket"], "staging", target["project_number"]
    )
    if bucket_location.upper() != target["region"].upper() or dataset_location != target["region"]:
        raise BenchmarkError("benchmark GCS and BigQuery locations differ from the approved target")

    run_id = os.urandom(8).hex()
    client = backend._bigquery
    table_prefix = f"{target['project_id']}.staging.week5_bench_{run_id}"
    table_ids = {
        name: f"{table_prefix}_{name}"
        for name in ("base_source", "final_source", "delta_source", "full_target", "incremental_target")
    }
    object_names: list[tuple[str, int]] = []
    object_receipts: dict[str, dict[str, Any]] = {}
    jobs: list[dict[str, Any]] = []
    created_tables: list[str] = []
    cleanup: dict[str, Any] = {"tables_deleted": [], "gcs_objects_deleted": [], "cleanup_errors": []}
    report: dict[str, Any] | None = None
    expiry = datetime.now(timezone.utc) + timedelta(days=1)
    build_start = time.perf_counter()

    base_bytes = _write_parquet(_record(index, final=False) for index in range(ROW_COUNT))
    base_size = len(base_bytes)
    base_sha = hashlib.sha256(base_bytes).hexdigest()
    base_total = sum((_base_amount(index) for index in range(ROW_COUNT)), Decimal("0.00"))
    changed_count = (ROW_COUNT + CHANGE_INTERVAL - 1) // CHANGE_INTERVAL
    final_total = base_total + Decimal(changed_count) * Decimal("1.25")

    final_bytes = _write_parquet(_record(index, final=True) for index in range(ROW_COUNT))
    final_sha = hashlib.sha256(final_bytes).hexdigest()
    delta_bytes = _write_parquet(
        _record(index, final=True)
        for index in range(0, ROW_COUNT, CHANGE_INTERVAL)
    )
    delta_sha = hashlib.sha256(delta_bytes).hexdigest()
    parquet_build_seconds = round(time.perf_counter() - build_start, 3)

    try:
        final_object_name = (
            f"tmp/week5/benchmark/run_id={run_id}/full_snapshot/sha256={final_sha}/snapshot.parquet"
        )
        delta_object_name = (
            f"tmp/week5/benchmark/run_id={run_id}/incremental/sha256={delta_sha}/changes.parquet"
        )
        upload_start = time.perf_counter()
        object_receipts["full_snapshot"] = _upload_immutable(
            backend, bucket=target["bucket"], name=final_object_name, payload=final_bytes
        )
        object_names.append((final_object_name, object_receipts["full_snapshot"]["generation"]))
        object_receipts["incremental_delta"] = _upload_immutable(
            backend, bucket=target["bucket"], name=delta_object_name, payload=delta_bytes
        )
        object_names.append((delta_object_name, object_receipts["incremental_delta"]["generation"]))
        gcs_upload_seconds = round(time.perf_counter() - upload_start, 3)

        for table_name, table_id in table_ids.items():
            if table_name == "full_target":
                continue
            _create_scratch_table(client, table_id, expiry)
            created_tables.append(table_id)

        base_load = _load_parquet(
            client,
            payload=base_bytes,
            table_id=table_ids["base_source"],
            job_id=f"week5_benchmark_load_base_{run_id}",
            location=target["region"],
        )
        jobs.append(_job_receipt(base_load))
        del base_bytes

        final_load = _load_parquet(
            client,
            payload=final_bytes,
            table_id=table_ids["final_source"],
            job_id=f"week5_benchmark_load_final_{run_id}",
            location=target["region"],
        )
        jobs.append(_job_receipt(final_load))

        delta_load = _load_parquet(
            client,
            payload=delta_bytes,
            table_id=table_ids["delta_source"],
            job_id=f"week5_benchmark_load_delta_{run_id}",
            location=target["region"],
        )
        jobs.append(_job_receipt(delta_load))
        del final_bytes, delta_bytes

        full_sql = f"""
CREATE TABLE `{table_ids['full_target']}`
OPTIONS (expiration_timestamp = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 1 DAY))
AS SELECT * FROM `{table_ids['final_source']}`
""".strip()
        full_start = time.perf_counter()
        full_job = _run_query(
            client,
            sql=full_sql,
            job_id=f"week5_benchmark_full_snapshot_{run_id}",
            location=target["region"],
        )
        full_elapsed = round(time.perf_counter() - full_start, 3)
        full_job_receipt = _job_receipt(full_job)
        jobs.append(full_job_receipt)
        created_tables.append(table_ids["full_target"])

        incremental_target = client.get_table(table_ids["incremental_target"])
        incremental_target.expires = expiry
        client.update_table(incremental_target, ["expires"])
        base_copy = client.copy_table(
            table_ids["base_source"],
            table_ids["incremental_target"],
            job_id=f"week5_benchmark_incremental_baseline_{run_id}",
            location=target["region"],
            job_config=bigquery.CopyJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_EMPTY),
        )
        base_copy.result(timeout=600)
        jobs.append(_job_receipt(base_copy))

        merge_sql = f"""
MERGE `{table_ids['incremental_target']}` AS target
USING `{table_ids['delta_source']}` AS source
ON target.order_id = source.order_id
WHEN MATCHED AND source.effective_seq > target.effective_seq THEN
  UPDATE SET
    status = source.status,
    amount = source.amount,
    payload = source.payload,
    effective_seq = source.effective_seq
""".strip()
        incremental_start = time.perf_counter()
        merge_job = _run_query(
            client,
            sql=merge_sql,
            job_id=f"week5_benchmark_incremental_merge_{run_id}",
            location=target["region"],
        )
        incremental_elapsed = round(time.perf_counter() - incremental_start, 3)
        merge_job_receipt = _job_receipt(merge_job)
        jobs.append(merge_job_receipt)

        validate_sql = f"""
WITH full_result AS (
  SELECT
    (SELECT COUNT(*) FROM `{table_ids['full_target']}`) AS row_count,
    (SELECT CAST(SUM(amount) AS STRING) FROM `{table_ids['full_target']}`) AS amount_total,
    (SELECT COUNTIF(expected.order_id IS NULL OR actual.order_id IS NULL
      OR expected.status IS DISTINCT FROM actual.status
      OR expected.amount IS DISTINCT FROM actual.amount
      OR expected.payload IS DISTINCT FROM actual.payload
      OR expected.effective_seq IS DISTINCT FROM actual.effective_seq)
     FROM `{table_ids['final_source']}` AS expected
     FULL OUTER JOIN `{table_ids['full_target']}` AS actual
       ON expected.order_id = actual.order_id) AS mismatches
),
incremental_result AS (
  SELECT
    (SELECT COUNT(*) FROM `{table_ids['incremental_target']}`) AS row_count,
    (SELECT CAST(SUM(amount) AS STRING) FROM `{table_ids['incremental_target']}`) AS amount_total,
    (SELECT COUNTIF(expected.order_id IS NULL OR actual.order_id IS NULL
      OR expected.status IS DISTINCT FROM actual.status
      OR expected.amount IS DISTINCT FROM actual.amount
      OR expected.payload IS DISTINCT FROM actual.payload
      OR expected.effective_seq IS DISTINCT FROM actual.effective_seq)
     FROM `{table_ids['final_source']}` AS expected
     FULL OUTER JOIN `{table_ids['incremental_target']}` AS actual
       ON expected.order_id = actual.order_id) AS mismatches
)
SELECT 'full_snapshot' AS path, row_count, amount_total, mismatches FROM full_result
UNION ALL
SELECT 'incremental_merge' AS path, row_count, amount_total, mismatches FROM incremental_result
ORDER BY path
""".strip()
        validation_job = _run_query(
            client,
            sql=validate_sql,
            job_id=f"week5_benchmark_validate_{run_id}",
            location=target["region"],
        )
        validation_rows = [dict(row.items()) for row in validation_job.result(timeout=600)]
        jobs.append(_job_receipt(validation_job))
        expected_total = format(final_total, "f")
        for row in validation_rows:
            if (
                int(row["row_count"]) != ROW_COUNT
                or Decimal(str(row["amount_total"])) != final_total
                or int(row["mismatches"]) != 0
            ):
                raise BenchmarkError(f"{row['path']} target does not match the Decimal source oracle")

        processed, billed, estimated_query_list_cost = _aggregate_query_usage(jobs)
        report = {
            "status": "BENCHMARK_RECONCILED",
            "project_id": target["project_id"],
            "region": target["region"],
            "run_id": run_id,
            "synthetic_only": True,
            "snapshot_rows": ROW_COUNT,
            "changed_events": changed_count,
            "changed_fraction": changed_count / ROW_COUNT,
            "base_total_amount_decimal": format(base_total, "f"),
            "final_total_amount_decimal": expected_total,
            "oracle_final_rows": ROW_COUNT,
            "oracle_summary_sha256": hashlib.sha256(
                f"{ROW_COUNT}|{changed_count}|{expected_total}|{final_sha}|{delta_sha}".encode()
            ).hexdigest(),
            "full_snapshot": {
                "table_id": table_ids["full_target"],
                "rows": int(validation_rows[0]["row_count"]),
                "amount_total": str(validation_rows[0]["amount_total"]),
                "mismatches_vs_decimal_oracle": int(validation_rows[0]["mismatches"]),
                "client_roundtrip_seconds": full_elapsed,
                "job_elapsed_seconds": full_job_receipt["elapsed_seconds"],
                "query_job_id": full_job.job_id,
                "bytes_processed": full_job.total_bytes_processed,
                "bytes_billed": full_job.total_bytes_billed,
            },
            "incremental": {
                "table_id": table_ids["incremental_target"],
                "rows": int(validation_rows[1]["row_count"]),
                "amount_total": str(validation_rows[1]["amount_total"]),
                "mismatches_vs_decimal_oracle": int(validation_rows[1]["mismatches"]),
                "changed_events": changed_count,
                "baseline_rows_preloaded": ROW_COUNT,
                "client_roundtrip_seconds": incremental_elapsed,
                "job_elapsed_seconds": merge_job_receipt["elapsed_seconds"],
                "merge_job_id": merge_job.job_id,
                "merge_bytes_processed": merge_job.total_bytes_processed,
                "merge_bytes_billed": merge_job.total_bytes_billed,
                "baseline_copy_job_id": base_copy.job_id,
            },
            "local_parquet_build_seconds": parquet_build_seconds,
            "gcs_upload_seconds": gcs_upload_seconds,
            "parquet_sizes": {
                "base_snapshot_bytes": base_size,
                "base_snapshot_sha256": base_sha,
                "full_snapshot_bytes": object_receipts["full_snapshot"]["size_bytes"],
                "incremental_delta_bytes": object_receipts["incremental_delta"]["size_bytes"],
            },
            "gcs_objects": object_receipts,
            "bigquery_job_count": len(jobs),
            "bigquery_jobs": jobs,
            "query_bytes_processed_total": processed,
            "query_bytes_billed_total": billed,
            "query_cost_gross_list_estimate_usd": round(estimated_query_list_cost, 8),
            "maximum_bytes_billed_per_query": MAXIMUM_QUERY_BYTES_BILLED,
            "timing_definitions": {
                "job_elapsed_seconds": "BigQuery job start-to-end duration from persisted job metadata.",
                "client_roundtrip_seconds": "Local time from query submission through result polling, including API/control-plane latency.",
            },
        }
    finally:
        for table_id in reversed(created_tables):
            try:
                client.delete_table(table_id, not_found_ok=True)
                cleanup["tables_deleted"].append(table_id)
            except Exception as exc:
                cleanup["cleanup_errors"].append(
                    {"resource": table_id, "error_type": type(exc).__name__}
                )
        for name, generation in object_names:
            try:
                blob = backend._storage.bucket(target["bucket"]).blob(name, generation=generation)
                blob.delete(if_generation_match=generation, timeout=30)
                cleanup["gcs_objects_deleted"].append(
                    {"name": name, "generation": generation}
                )
            except Exception as exc:
                # The bucket has a 30-day tmp/ lifecycle rule; the receipt reports
                # any cleanup failure without risking a broad object deletion.
                cleanup["cleanup_errors"].append(
                    {"resource": name, "generation": generation, "error_type": type(exc).__name__}
                )
    if report is None:
        raise BenchmarkError("benchmark ended without a result receipt")
    report["cleanup"] = cleanup
    report["tables_cleaned_up"] = len(cleanup["tables_deleted"]) == len(created_tables)
    report["gcs_scratch_cleanup_complete"] = len(cleanup["gcs_objects_deleted"]) == len(object_names)
    report["cleanup_error_count"] = len(cleanup["cleanup_errors"])
    return report


def local_benchmark() -> dict[str, Any]:
    """Measure the fixed synthetic Parquet fixture without claiming cloud results."""
    build_start = time.perf_counter()
    base_bytes = _write_parquet(_record(index, final=False) for index in range(ROW_COUNT))
    base_receipt = {"size_bytes": len(base_bytes), "sha256": hashlib.sha256(base_bytes).hexdigest()}
    del base_bytes
    final_bytes = _write_parquet(_record(index, final=True) for index in range(ROW_COUNT))
    final_receipt = {"size_bytes": len(final_bytes), "sha256": hashlib.sha256(final_bytes).hexdigest()}
    del final_bytes
    delta_bytes = _write_parquet(
        _record(index, final=True) for index in range(0, ROW_COUNT, CHANGE_INTERVAL)
    )
    delta_receipt = {"size_bytes": len(delta_bytes), "sha256": hashlib.sha256(delta_bytes).hexdigest()}
    del delta_bytes
    elapsed = round(time.perf_counter() - build_start, 3)
    changed_count = (ROW_COUNT + CHANGE_INTERVAL - 1) // CHANGE_INTERVAL
    base_total = sum((_base_amount(index) for index in range(ROW_COUNT)), Decimal("0.00"))
    final_total = base_total + Decimal(changed_count) * Decimal("1.25")
    return {
        "status": "LOCAL_FIXTURE_READY_CLOUD_BENCHMARK_BLOCKED",
        "synthetic_only": True,
        "snapshot_rows": ROW_COUNT,
        "changed_events": changed_count,
        "changed_fraction": changed_count / ROW_COUNT,
        "base_amount_total_decimal": format(base_total, "f"),
        "expected_final_amount_total_decimal": format(final_total, "f"),
        "local_parquet_build_seconds": elapsed,
        "parquet_sizes": {
            "base_snapshot": base_receipt,
            "full_snapshot": final_receipt,
            "incremental_delta": delta_receipt,
        },
        "oracle_summary_sha256": hashlib.sha256(
            f"{ROW_COUNT}|{changed_count}|{format(final_total, 'f')}|{final_receipt['sha256']}|{delta_receipt['sha256']}".encode()
        ).hexdigest(),
        "cloud_benchmark": {
            "status": "BLOCKED_GCP_AUTH_REFRESH_REQUIRED",
            "bigquery_job_count": None,
            "bytes_processed": None,
            "bytes_billed": None,
            "gcs_generations": None,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--execute", action="store_true",
        help="create only the fixed 100K-row synthetic benchmark in the approved target",
    )
    group.add_argument(
        "--local-only", action="store_true",
        help="measure deterministic Parquet fixtures without cloud access",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute:
        if args.local_only:
            report = local_benchmark()
            output = Path(__file__).resolve().parents[1] / "docs" / "cloud" / "week5" / "performance_benchmark_local.json"
            if output.exists():
                raise BenchmarkError("performance_benchmark_local.json already exists; refusing to overwrite")
            output.write_text(
                json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default) + "\n",
                encoding="utf-8",
            )
            print(json.dumps({"status": report["status"], "path": output.as_posix(), "rows": ROW_COUNT, "changed_events": report["changed_events"], "parquet_bytes": report["parquet_sizes"]}, sort_keys=True))
            return 0
        print(
            json.dumps(
                {
                    "status": "DRY_RUN_READY",
                    "project_id": APPROVED_TARGET["project_id"],
                    "region": APPROVED_TARGET["region"],
                    "snapshot_rows": ROW_COUNT,
                    "changed_events": ROW_COUNT // CHANGE_INTERVAL,
                    "change_fraction": 1 / CHANGE_INTERVAL,
                    "maximum_bytes_billed_per_query": MAXIMUM_QUERY_BYTES_BILLED,
                },
                sort_keys=True,
            )
        )
        return 0
    report = execute_benchmark()
    output = Path(__file__).resolve().parents[1] / "docs" / "cloud" / "week5" / "performance_benchmark.json"
    if output.exists():
        raise BenchmarkError("performance_benchmark.json already exists; refusing to overwrite evidence")
    output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "run_id": report["run_id"], "path": output.as_posix(), "full_job_seconds": report["full_snapshot"]["job_elapsed_seconds"], "incremental_job_seconds": report["incremental"]["job_elapsed_seconds"], "query_bytes_billed": report["query_bytes_billed_total"], "gcs_delta_bytes": report["parquet_sizes"]["incremental_delta_bytes"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BenchmarkError as exc:
        raise SystemExit(f"week5-benchmark: {exc}") from exc
