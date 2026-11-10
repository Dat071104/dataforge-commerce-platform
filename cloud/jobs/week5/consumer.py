"""Finite Cloud Run Job consumer for immutable Week-5 event batches."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataforge.cloud.adapters import CloudAdapterError, DataIntegrityError
from dataforge.cloud.google_cloud import GoogleCloudBackend
from dataforge.incremental.batch import MAX_BATCH_EVENTS, BatchValidationError, make_run_id
from dataforge.incremental.bronze import (
    BronzeArtifactError,
    download_verified_batch,
    parse_gs_uri,
)

MAXIMUM_BYTES_BILLED = 268_435_456
MAXIMUM_PUBLISH_BYTES_BILLED = 1_073_741_824
MAXIMUM_TASK_ATTEMPT = 1
APPROVED_PROJECT_ID = "dataforge-p7-lab-d0f725"
APPROVED_PROJECT_NUMBER = "955038620072"
APPROVED_REGION = "us-central1"
APPROVED_BRONZE_BUCKET = "dataforge-p7-lab-d0f725-bronze"
_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_MODE = {"normal", "backfill"}


@dataclass(frozen=True)
class Week5ConsumerReceipt:
    status: str
    run_id: str
    batch_id: str
    stage_table_id: str
    stage_load_job_id: str
    stage_verify_job_id: str
    published_check_job_id: str
    publish_job_id: str
    row_count: int
    row_value_sha256: str
    manifest_sha256: str
    manifest_generation: int
    object_sha256: str
    object_generation: int
    query_bytes_processed: int | None
    query_bytes_billed: int | None
    maximum_bytes_billed: int
    child_job_ids: tuple[str, ...] = ()
    runtime_iam_create_denied: bool | None = None
    maximum_publish_bytes_billed: int = MAXIMUM_PUBLISH_BYTES_BILLED


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_publish_sql(sql_path: str | Path | None = None) -> str:
    path = Path(sql_path) if sql_path is not None else _repo_root() / "cloud" / "sql_bigquery" / "week5" / "publish.sql"
    try:
        sql = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Week-5 publish SQL cannot be read from {path}") from exc
    if not sql.strip() or sql.count("{{STAGING_TABLE_ID}}") != 1:
        raise RuntimeError("publish.sql must be non-empty and contain one staging table token")
    return sql


def stage_table_id(project_id: str, batch_id: str) -> str:
    if not _PROJECT_ID.fullmatch(project_id):
        raise ValueError("project ID does not match the Google Cloud project ID contract")
    if not re.fullmatch(r"[a-f0-9]{64}", batch_id):
        raise ValueError("batch ID must be lowercase SHA-256 hex")
    return f"{project_id}.staging.week5_events_{batch_id[:16]}"


def probe_runtime_object_create_denied(backend: Any, *, bucket: str, run_id: str) -> str:
    """Verify that the runtime identity cannot create objects in approved Bronze."""
    if not bucket or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise ValueError("IAM probe bucket does not match the GCS bucket-name contract")
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("IAM probe run ID must be lowercase hex")
    object_name = f"tmp/week5/iam-negative/{run_id}.txt"
    try:
        backend.put_object(
            bucket,
            object_name,
            b"DataForge Week-5 expected-denial probe",
            {"dataforge-week5-probe": "expected-denial"},
            "text/plain",
            if_generation_match=0,
        )
    except Exception as exc:
        status = getattr(exc, "code", None)
        if callable(status):
            status = status()
        if status == 403 or type(exc).__name__ in {"Forbidden", "PermissionDenied"}:
            return object_name
        raise CloudAdapterError(
            f"runtime object-create IAM probe failed with {type(exc).__name__}, expected HTTP 403"
        ) from exc
    raise CloudAdapterError("runtime unexpectedly has storage.objects.create on the Bronze bucket")


def _process_manifest_body(
    *,
    manifest_uri: str,
    manifest_generation: int,
    run_mode: str,
    project_id: str,
    region: str,
    expected_bucket: str | None,
    backend: Any,
    run_id: str,
    execution_id: str,
    attempt: int = 0,
    fail_after_merge_once: bool = False,
    fail_before_publish: bool = False,
    fail_at: str | None = None,
    probe_storage_create_denied: bool = False,
    sql_path: str | Path | None = None,
    maximum_bytes_billed: int = MAXIMUM_BYTES_BILLED,
    failure_context: dict[str, Any] | None = None,
) -> Week5ConsumerReceipt:
    """Validate exact GCS generations, stage bytes, then call the bounded publish SQL."""
    if run_mode not in _MODE:
        raise ValueError("run_mode must be normal or backfill")
    if fail_at not in {None, "after_stage", "before_merge", "before_publish"}:
        raise ValueError("fail_at is not a supported Cloud Run injection point")
    if not isinstance(probe_storage_create_denied, bool):
        raise ValueError("probe_storage_create_denied must be boolean")
    if maximum_bytes_billed <= 0 or maximum_bytes_billed > MAXIMUM_BYTES_BILLED:
        raise ValueError("maximum_bytes_billed must be within the 256 MiB ceiling")
    if not isinstance(fail_after_merge_once, bool):
        raise ValueError("fail_after_merge_once must be boolean")
    # Check that local SQL/package configuration is ready before any cloud operation.
    sql = load_publish_sql(sql_path)
    if expected_bucket:
        manifest_bucket, manifest_name = parse_gs_uri(manifest_uri)
        if manifest_bucket != expected_bucket or not manifest_name.startswith("manifests/week5/"):
            raise CloudAdapterError("manifest URI is outside the approved Week-5 Bronze prefix")
    if probe_storage_create_denied:
        if not expected_bucket:
            raise CloudAdapterError("runtime IAM probe requires the approved Bronze bucket")
        probe_runtime_object_create_denied(
            backend,
            bucket=expected_bucket,
            run_id=run_id,
        )
        backend.record_week5_run_event(
            project_id=project_id,
            region=region,
            run_id=run_id,
            status="IAM_NEGATIVE_PASS",
            attempt=attempt,
            metadata={
                "execution_id": execution_id,
                "run_mode": run_mode,
                "manifest_uri": manifest_uri,
                "error_code": "STORAGE_OBJECT_CREATE_DENIED",
                "error_message": "Expected HTTP 403; no probe object was created.",
            },
            maximum_bytes_billed=maximum_bytes_billed,
        )
    batch, manifest, manifest_sha256, parquet_bytes = download_verified_batch(
        backend,
        manifest_uri=manifest_uri,
        manifest_generation=manifest_generation,
    )
    if batch.row_count > MAX_BATCH_EVENTS:
        raise ValueError("manifest exceeds the bounded Week-5 event count")
    parquet_ref = manifest["parquet"]
    if expected_bucket and not str(parquet_ref.get("object_name", "")).startswith(
        "bronze/week5/"
    ):
        raise CloudAdapterError("Parquet object is outside the approved Week-5 Bronze prefix")
    object_sha256 = str(parquet_ref["sha256"])
    object_generation = int(parquet_ref["generation"])
    expected_rows = int(manifest["row_count"])
    if expected_rows != batch.row_count:
        raise ValueError("validated event count differs from manifest row_count")
    if not isinstance(manifest.get("source_run_id"), str) or manifest[
        "source_run_id"
    ] != f"{batch.source_identity}:{batch.batch_id}":
        raise DataIntegrityError("manifest source_run_id differs from the deterministic batch identity")
    metadata = {
        "batch_id": batch.batch_id,
        "execution_id": execution_id,
        "run_mode": run_mode,
        "source_run_id": manifest["source_run_id"],
        "manifest_uri": manifest_uri,
        "manifest_generation": manifest_generation,
        "lower_seq": batch.lower_seq,
        "upper_seq": batch.upper_seq,
        "expected_row_count": expected_rows,
        "row_value_sha256": batch.row_value_sha256,
        "manifest_sha256": manifest_sha256,
        "object_sha256": object_sha256,
        "object_generation": object_generation,
    }
    if failure_context is not None:
        failure_context.update(metadata)
    backend.record_week5_run_event(
        project_id=project_id,
        region=region,
        run_id=run_id,
        status="VALIDATED",
        attempt=attempt,
        metadata=metadata,
        maximum_bytes_billed=maximum_bytes_billed,
    )

    table_id = stage_table_id(project_id, batch.batch_id)
    metadata["stage_table_id"] = table_id
    precheck = backend.is_week5_batch_published(
        project_id=project_id,
        region=region,
        batch_id=batch.batch_id,
        expected_metadata={
            "run_mode": run_mode,
            "lower_seq": batch.lower_seq,
            "upper_seq": batch.upper_seq,
            "row_value_sha256": batch.row_value_sha256,
            "expected_row_count": expected_rows,
            "manifest_sha256": manifest_sha256,
            "manifest_generation": manifest_generation,
            "object_sha256": object_sha256,
            "object_generation": object_generation,
        },
        job_id=f"week5_published_{batch.batch_id[:16]}_{run_id[:16]}",
        maximum_bytes_billed=maximum_bytes_billed,
    )
    if precheck["published"]:
        backend.record_week5_run_event(
            project_id=project_id,
            region=region,
            run_id=run_id,
            status="NO_OP",
            attempt=attempt,
            metadata={**metadata, "published_check_job_id": str(precheck["job_id"])},
            maximum_bytes_billed=maximum_bytes_billed,
        )
        return Week5ConsumerReceipt(
            status="NO_OP",
            run_id=run_id,
            batch_id=batch.batch_id,
            stage_table_id=table_id,
            stage_load_job_id="",
            stage_verify_job_id="",
            published_check_job_id=str(precheck["job_id"]),
            publish_job_id="",
            row_count=expected_rows,
            row_value_sha256=batch.row_value_sha256,
            manifest_sha256=manifest_sha256,
            manifest_generation=manifest_generation,
            object_sha256=object_sha256,
            object_generation=object_generation,
            query_bytes_processed=precheck.get("bytes_processed"),
            query_bytes_billed=precheck.get("bytes_billed"),
            maximum_bytes_billed=int(precheck["maximum_bytes_billed"]),
            runtime_iam_create_denied=(True if probe_storage_create_denied else None),
        )
    metadata["published_check_job_id"] = str(precheck["job_id"])
    if failure_context is not None:
        failure_context.update(metadata)
    stage = backend.stage_week5_events(
        table_id=table_id,
        run_id=run_id,
        region=region,
        batch_id=batch.batch_id,
        parquet_bytes=parquet_bytes,
        parquet_sha256=object_sha256,
        manifest_sha256=manifest_sha256,
        manifest_generation=manifest_generation,
        object_generation=object_generation,
        row_value_sha256=batch.row_value_sha256,
        row_count=expected_rows,
        attempt=attempt,
    )
    metadata.update(
        {
            "stage_load_job_id": str(stage["load_job_id"]),
            "stage_verify_job_id": str(stage["verify_job_id"]),
        }
    )
    if failure_context is not None:
        failure_context.update(metadata)
    backend.record_week5_run_event(
        project_id=project_id,
        region=region,
        run_id=run_id,
        status="STAGED",
        attempt=attempt,
        metadata=metadata,
        maximum_bytes_billed=maximum_bytes_billed,
    )
    if fail_at in {"after_stage", "before_merge"}:
        code = "INJECTED_AFTER_STAGE" if fail_at == "after_stage" else "INJECTED_BEFORE_MERGE"
        raise RuntimeError(f"{code}: injected Week-5 test failure")

    publish_job_id = f"week5_publish_{batch.batch_id[:16]}_{run_id[:16]}"
    parameters = {
        "run_id": run_id,
        "execution_id": execution_id,
        "batch_id": batch.batch_id,
        "run_mode": run_mode,
        "lower_seq": batch.lower_seq,
        "upper_seq": batch.upper_seq,
        "row_value_sha256": batch.row_value_sha256,
        "manifest_sha256": manifest_sha256,
        "manifest_generation": manifest_generation,
        "object_sha256": object_sha256,
        "object_generation": object_generation,
        "expected_row_count": expected_rows,
        "source_run_id": manifest["source_run_id"],
        "attempt": attempt,
        "manifest_uri": manifest_uri,
        "stage_table_id": table_id,
        "stage_load_job_id": str(stage["load_job_id"]),
        "stage_verify_job_id": str(stage["verify_job_id"]),
        "publish_job_id": publish_job_id,
        "published_check_job_id": str(precheck["job_id"]),
        "fail_after_merge_once": fail_after_merge_once,
        "fail_before_publish": fail_before_publish or fail_at == "before_publish",
    }
    publish = backend.run_week5_publish(
        sql=sql,
        staging_table_id=table_id,
        region=region,
        parameters=parameters,
        job_id=publish_job_id,
        maximum_bytes_billed=MAXIMUM_PUBLISH_BYTES_BILLED,
    )
    status = str(publish.get("publication_status", ""))
    if status not in {"PUBLISHED", "NO_OP"}:
        raise CloudAdapterError("publish.sql returned no recognized publication status")
    if status == "NO_OP":
        backend.record_week5_run_event(
            project_id=project_id,
            region=region,
            run_id=run_id,
            status="NO_OP",
            attempt=attempt,
            metadata={**metadata, "publish_job_id": publish_job_id},
            maximum_bytes_billed=maximum_bytes_billed,
        )
    elif failure_context is not None:
        failure_context["published"] = True
    return Week5ConsumerReceipt(
        status=status,
        run_id=run_id,
        batch_id=batch.batch_id,
        stage_table_id=table_id,
        stage_load_job_id=str(stage["load_job_id"]),
        stage_verify_job_id=str(stage["verify_job_id"]),
        published_check_job_id=str(precheck["job_id"]),
        publish_job_id=str(publish["job_id"]),
        row_count=expected_rows,
        row_value_sha256=batch.row_value_sha256,
        manifest_sha256=manifest_sha256,
        manifest_generation=manifest_generation,
        object_sha256=object_sha256,
        object_generation=object_generation,
        query_bytes_processed=publish.get("bytes_processed"),
        query_bytes_billed=publish.get("bytes_billed"),
        maximum_bytes_billed=maximum_bytes_billed,
        child_job_ids=tuple(str(item) for item in publish.get("child_job_ids", ())),
        runtime_iam_create_denied=(True if probe_storage_create_denied else None),
        maximum_publish_bytes_billed=int(publish["maximum_bytes_billed"]),
    )


def _sanitized_failure_code(error: Exception) -> str:
    if isinstance(error, RuntimeError) and str(error).startswith("INJECTED_"):
        return "INJECTED_FAILURE"
    if isinstance(error, (BatchValidationError, BronzeArtifactError)):
        return "BATCH_VALIDATION_FAILED"
    if isinstance(error, DataIntegrityError):
        return "DATA_INTEGRITY_FAILED"
    if isinstance(error, CloudAdapterError):
        return "CLOUD_OPERATION_FAILED"
    if isinstance(error, ValueError):
        return "INVALID_BATCH_INPUT"
    return "WEEK5_PROCESSING_FAILED"


def process_manifest(
    *,
    manifest_uri: str,
    manifest_generation: int,
    run_mode: str,
    project_id: str,
    region: str,
    expected_bucket: str | None = None,
    backend: Any,
    execution_id: str,
    attempt: int = 0,
    fail_after_merge_once: bool = False,
    fail_before_publish: bool = False,
    fail_at: str | None = None,
    probe_storage_create_denied: bool = False,
    sql_path: str | Path | None = None,
    maximum_bytes_billed: int = MAXIMUM_BYTES_BILLED,
) -> Week5ConsumerReceipt:
    """Process one execution and persist one sanitized failure event if it fails."""
    run_id = make_run_id(execution_id, attempt)
    failure_context: dict[str, Any] = {
        "execution_id": execution_id,
        "manifest_uri": manifest_uri,
        "manifest_generation": manifest_generation,
        "run_mode": run_mode,
        "attempt": attempt,
    }
    try:
        backend.record_week5_run_event(
            project_id=project_id,
            region=region,
            run_id=run_id,
            status="DISCOVERED",
            attempt=attempt,
            metadata=failure_context,
            maximum_bytes_billed=maximum_bytes_billed,
        )
        return _process_manifest_body(
            manifest_uri=manifest_uri,
            manifest_generation=manifest_generation,
            run_mode=run_mode,
            project_id=project_id,
            region=region,
            expected_bucket=expected_bucket,
            backend=backend,
            run_id=run_id,
            execution_id=execution_id,
            attempt=attempt,
            fail_after_merge_once=fail_after_merge_once,
            fail_before_publish=fail_before_publish,
            fail_at=fail_at,
            probe_storage_create_denied=probe_storage_create_denied,
            sql_path=sql_path,
            maximum_bytes_billed=maximum_bytes_billed,
            failure_context=failure_context,
        )
    except Exception as exc:
        try:
            backend.record_week5_failure(
                project_id=project_id,
                region=region,
                run_id=run_id,
                error_code=_sanitized_failure_code(exc),
                error_message=(
                    "Week-5 processing failed; inspect bounded Cloud Run and BigQuery job records."
                ),
                attempt=attempt,
                maximum_bytes_billed=maximum_bytes_billed,
                metadata=failure_context,
            )
        except Exception as log_error:
            exc.add_note(
                "Sanitized FAILED ledger write also failed ("
                f"{type(log_error).__name__}); original error remains primary."
            )
        raise


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consume one immutable DataForge Week-5 batch")
    parser.add_argument("--manifest-uri", required=True)
    parser.add_argument("--manifest-generation", required=True, type=int)
    parser.add_argument("--run-mode", required=True, choices=sorted(_MODE))
    parser.add_argument("--fail-after-merge-once", action="store_true")
    parser.add_argument("--fail-before-publish", action="store_true")
    parser.add_argument("--probe-storage-create-denied", action="store_true")
    parser.add_argument(
        "--fail-at",
        choices=("after_stage", "before_merge", "before_publish"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    project_id = (
        os.environ.get("DATAFORGE_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    )
    expected_bucket = os.environ.get("DATAFORGE_BRONZE_BUCKET", "")
    region = os.environ.get("DATAFORGE_CLOUD_REGION", "")
    execution_id = os.environ.get("CLOUD_RUN_EXECUTION", "")
    attempt_text = os.environ.get("CLOUD_RUN_TASK_ATTEMPT", "0")
    try:
        attempt = int(attempt_text)
    except ValueError as exc:
        raise RuntimeError("CLOUD_RUN_TASK_ATTEMPT must be an integer") from exc
    if not project_id or not region or not expected_bucket:
        raise RuntimeError(
            "DATAFORGE_PROJECT_ID, DATAFORGE_CLOUD_REGION, and DATAFORGE_BRONZE_BUCKET are required"
        )
    if (
        project_id != APPROVED_PROJECT_ID
        or region != APPROVED_REGION
        or expected_bucket != APPROVED_BRONZE_BUCKET
    ):
        raise RuntimeError("Cloud Run job target differs from the approved DataForge project boundary")

    backend = GoogleCloudBackend.from_cloud_run_metadata(project_id)
    try:
        bucket_location, dataset_location = backend.target_locations(
            project_id,
            expected_bucket,
            "staging",
            APPROVED_PROJECT_NUMBER,
        )
        if bucket_location.upper() != region.upper() or dataset_location != region:
            raise RuntimeError(
                "Cloud Run target bucket/dataset location differs from the approved region"
            )
    except Exception as exc:
        try:
            backend.record_week5_failure(
                project_id=project_id,
                region=region,
                run_id=make_run_id(execution_id, attempt),
                error_code="TARGET_BOUNDARY_FAILED",
                error_message="Week-5 target bucket/dataset ownership or location check failed.",
                attempt=attempt,
                metadata={
                    "execution_id": execution_id,
                    "run_mode": args.run_mode,
                    "manifest_uri": args.manifest_uri,
                    "manifest_generation": args.manifest_generation,
                },
            )
        except Exception as log_error:
            exc.add_note(f"Could not write target-boundary failure event ({type(log_error).__name__}).")
        raise
    receipt = process_manifest(
        manifest_uri=args.manifest_uri,
        manifest_generation=args.manifest_generation,
        run_mode=args.run_mode,
        project_id=project_id,
        region=region,
        expected_bucket=expected_bucket,
        backend=backend,
        execution_id=execution_id,
        attempt=attempt,
        fail_after_merge_once=args.fail_after_merge_once,
        fail_before_publish=args.fail_before_publish,
        fail_at=args.fail_at,
        probe_storage_create_denied=args.probe_storage_create_denied,
    )
    print(receipt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
