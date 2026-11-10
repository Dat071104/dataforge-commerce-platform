"""Google Cloud client implementation; imported only for explicit --execute runs."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .adapters import (
    BigQueryLoadReceipt,
    CloudAdapterError,
    DataIntegrityError,
    ProjectMismatchError,
    StoredObject,
    canonical_raw_rows,
    canonical_value_rows,
    raw_value_rows_sha256,
    value_rows_sha256,
)
from .contracts import FieldContract, SourceContract

_PROVENANCE_PREFIX = "dataforge-week4-v1:"
_REQUEST_RETRY_DEADLINE_SECONDS = 60.0
_API_REQUEST_TIMEOUT_SECONDS = 60.0
_JOB_WAIT_TIMEOUT_SECONDS = 300.0
_MAXIMUM_BYTES_BILLED = 268435456


class GoogleCloudBackend:
    def __init__(self, project_id: str) -> None:
        sdk_root = os.environ.get("CLOUDSDK_CONFIG")
        if not sdk_root:
            raise CloudAdapterError(
                "Set CLOUDSDK_CONFIG to the isolated DataForge gcloud configuration root"
            )
        credential_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not credential_path:
            raise CloudAdapterError(
                "Set GOOGLE_APPLICATION_CREDENTIALS to ADC inside the isolated CLOUDSDK_CONFIG root"
            )
        sdk_root_path = Path(sdk_root).resolve()
        credential_file = Path(credential_path).resolve()
        try:
            credential_file.relative_to(sdk_root_path)
        except ValueError as exc:
            raise CloudAdapterError(
                "GOOGLE_APPLICATION_CREDENTIALS must be inside the isolated CLOUDSDK_CONFIG root"
            ) from exc
        try:
            from google.cloud import bigquery, storage
        except ImportError as exc:
            raise CloudAdapterError(
                'Install GCP extras with `pip install -e ".[gcp]"` before --execute.'
            ) from exc
        import google.auth
        from google.api_core import retry as api_retry

        try:
            # Do not silently fall through to the Windows-wide ADC location or a
            # metadata server when an isolated CLI profile is requested.
            credentials, _ = google.auth.load_credentials_from_file(
                str(credential_file), quota_project_id=project_id
            )
        except Exception as exc:
            raise CloudAdapterError(
                "Could not load isolated ADC credentials for the explicit project/quota project"
            ) from exc
        self._request_retry = api_retry.Retry(deadline=_REQUEST_RETRY_DEADLINE_SECONDS)
        self._bigquery_module = bigquery
        self._storage = storage.Client(project=project_id, credentials=credentials)
        self._bigquery = bigquery.Client(project=project_id, credentials=credentials)

    def target_locations(
        self,
        project_id: str,
        bucket: str,
        dataset: str,
        expected_project_number: str,
    ) -> tuple[str, str]:
        bucket_ref = self._storage.bucket(bucket)
        bucket_ref.reload(
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        bucket_project_number = str(bucket_ref.project_number or "")
        if bucket_project_number != expected_project_number:
            raise ProjectMismatchError(
                "GCS bucket owner project number does not match the explicit target project"
            )
        dataset_ref = self._bigquery.get_dataset(
            f"{project_id}.{dataset}",
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        if str(dataset_ref.project) != project_id:
            raise ProjectMismatchError(
                "BigQuery staging dataset does not belong to the explicit target project"
            )
        return str(bucket_ref.location), str(dataset_ref.location)

    def get_object(self, bucket: str, name: str) -> StoredObject | None:
        blob = self._storage.bucket(bucket).blob(name)
        try:
            blob.reload(
                retry=self._request_retry,
                timeout=_API_REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            if _http_code(exc) == 404 or type(exc).__name__ == "NotFound":
                return None
            raise
        generation = int(blob.generation)
        payload = blob.download_as_bytes(
            if_generation_match=generation,
            checksum="crc32c",
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        return StoredObject(
            generation=generation,
            size_bytes=int(blob.size),
            crc32c=str(blob.crc32c or ""),
            metadata=dict(blob.metadata or {}),
            payload=payload,
        )

    def put_object(
        self,
        bucket: str,
        name: str,
        payload: bytes,
        metadata: dict[str, str],
        content_type: str,
        *,
        if_generation_match: int,
    ) -> None:
        blob = self._storage.bucket(bucket).blob(name)
        blob.metadata = metadata
        blob.upload_from_string(
            payload,
            content_type=content_type,
            if_generation_match=if_generation_match,
            checksum="crc32c",
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )

    def load_typed_parquet(
        self,
        *,
        project_id: str,
        dataset: str,
        region: str,
        source: str,
        run_id: str,
        source_sha256: str,
        parquet_sha256: str,
        gcs_generation: int,
        gcs_uri: str,
        row_count: int,
        contract: SourceContract,
        expected_rows: tuple[tuple[str | None, ...], ...],
        raw_value_sha256: str,
        source_value_sha256: str,
        filter_field: str,
        filter_value: str,
        expected_null_counts: dict[str, int],
    ) -> BigQueryLoadReceipt:
        bq = self._bigquery_module
        raw_table_id = f"{project_id}.{dataset}.{source}_raw_{run_id}"
        typed_table_id = f"{project_id}.{dataset}.{source}_{run_id}"
        expiration = datetime.now(timezone.utc) + timedelta(days=7)
        base_provenance = {
            "source": source,
            "run_id": run_id,
            "source_sha256": source_sha256,
            "parquet_sha256": parquet_sha256,
            "gcs_generation": str(gcs_generation),
        }

        raw_schema = [bq.SchemaField(field.name, "STRING", mode="NULLABLE") for field in contract.fields]
        raw_table = _get_table_or_none(
            self._bigquery,
            raw_table_id,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        load_reused = raw_table is not None
        if raw_table is None:
            load_job_id = _new_job_id("load", source, run_id)
            raw_table = bq.Table(raw_table_id, schema=raw_schema)
            raw_table.expires = expiration
            raw_table.description = _provenance_description(
                {**base_provenance, "role": "raw", "job_id": load_job_id}
            )
            self._bigquery.create_table(
                raw_table,
                exists_ok=False,
                retry=self._request_retry,
                timeout=_API_REQUEST_TIMEOUT_SECONDS,
            )

            load_config = bq.LoadJobConfig(
                source_format=bq.SourceFormat.PARQUET,
                schema=raw_schema,
                autodetect=False,
                create_disposition=bq.CreateDisposition.CREATE_NEVER,
                write_disposition=bq.WriteDisposition.WRITE_EMPTY,
                max_bad_records=0,
                ignore_unknown_values=False,
            )
            load_job = self._bigquery.load_table_from_uri(
                gcs_uri,
                raw_table_id,
                job_config=load_config,
                job_id=load_job_id,
                location=region,
                retry=self._request_retry,
                timeout=_API_REQUEST_TIMEOUT_SECONDS,
            )
            load_job.result(
                retry=self._request_retry,
                timeout=_JOB_WAIT_TIMEOUT_SECONDS,
            )
            loaded_rows = load_job.output_rows
            if loaded_rows is None:
                loaded_rows = self._bigquery.get_table(
                    raw_table_id,
                    retry=self._request_retry,
                    timeout=_API_REQUEST_TIMEOUT_SECONDS,
                ).num_rows
            if int(loaded_rows) != row_count:
                raise CloudAdapterError(
                    f"BigQuery Parquet load returned {loaded_rows} rows; expected {row_count}"
                )
            raw_table = self._bigquery.get_table(
                raw_table_id,
                retry=self._request_retry,
                timeout=_API_REQUEST_TIMEOUT_SECONDS,
            )
        else:
            raw_provenance = _read_provenance(raw_table, expected_role="raw")
            _require_matching_provenance(raw_provenance, base_provenance)
            load_job_id = raw_provenance["job_id"]

        raw_expected_schema = tuple(
            FieldContract(field.name, "STRING", nullable=True) for field in contract.fields
        )
        actual_raw_schema = tuple(_contract_from_schema(field) for field in raw_table.schema)
        if actual_raw_schema != raw_expected_schema or int(raw_table.num_rows) != row_count:
            raise CloudAdapterError(
                "raw BigQuery staging table does not match its immutable source contract"
            )

        raw_order_by = ", ".join(f"`{name}`" for name in contract.primary_key)
        raw_reconciliation_job_id = _new_job_id("rawreconcile", source, run_id)
        raw_reconciliation_job = self._bigquery.query(
            f"SELECT * FROM `{raw_table_id}` ORDER BY {raw_order_by}",
            job_config=bq.QueryJobConfig(
                use_legacy_sql=False,
                maximum_bytes_billed=_MAXIMUM_BYTES_BILLED,
            ),
            job_id=raw_reconciliation_job_id,
            job_retry=None,
            location=region,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        actual_raw_rows = tuple(
            tuple(row[field.name] for field in contract.fields)
            for row in raw_reconciliation_job.result(
                retry=self._request_retry,
                timeout=_JOB_WAIT_TIMEOUT_SECONDS,
            )
        )
        actual_raw_sha256 = raw_value_rows_sha256(actual_raw_rows, contract)
        if (
            len(actual_raw_rows) != row_count
            or canonical_raw_rows(actual_raw_rows, contract)
            != canonical_raw_rows(expected_rows, contract)
        ):
            raise DataIntegrityError(
                "BigQuery raw row values or primary-key ordering differ from the Parquet source"
            )
        if actual_raw_sha256 != raw_value_sha256:
            raise DataIntegrityError("BigQuery raw value digest differs from the Parquet source")

        typed_schema = [_schema_field(bq, field) for field in contract.fields]
        typed_table = _get_table_or_none(
            self._bigquery,
            typed_table_id,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        cast_reused = typed_table is not None
        cast_bytes_processed = None
        cast_bytes_billed = None
        if typed_table is None:
            cast_job_id = _new_job_id("cast", source, run_id)
            typed_table = bq.Table(typed_table_id, schema=typed_schema)
            typed_table.expires = expiration
            typed_table.description = _provenance_description(
                {**base_provenance, "role": "typed", "job_id": cast_job_id}
            )
            self._bigquery.create_table(
                typed_table,
                exists_ok=False,
                retry=self._request_retry,
                timeout=_API_REQUEST_TIMEOUT_SECONDS,
            )

            cast_sql = _typed_insert_sql(raw_table_id, typed_table_id, contract)
            cast_config = bq.QueryJobConfig(
                use_legacy_sql=False,
                maximum_bytes_billed=_MAXIMUM_BYTES_BILLED,
            )
            cast_job = self._bigquery.query(
                cast_sql,
                job_config=cast_config,
                job_id=cast_job_id,
                job_retry=None,
                location=region,
                retry=self._request_retry,
                timeout=_API_REQUEST_TIMEOUT_SECONDS,
            )
            cast_job.result(
                retry=self._request_retry,
                timeout=_JOB_WAIT_TIMEOUT_SECONDS,
            )
            cast_bytes_processed = getattr(cast_job, "total_bytes_processed", None)
            cast_bytes_billed = getattr(cast_job, "total_bytes_billed", None)
            typed_table = self._bigquery.get_table(
                typed_table_id,
                retry=self._request_retry,
                timeout=_API_REQUEST_TIMEOUT_SECONDS,
            )
        else:
            typed_provenance = _read_provenance(typed_table, expected_role="typed")
            _require_matching_provenance(typed_provenance, base_provenance)
            cast_job_id = typed_provenance["job_id"]

        actual_schema = tuple(_contract_from_schema(field) for field in typed_table.schema)
        if actual_schema != contract.fields:
            raise CloudAdapterError("typed BigQuery staging schema differs from the explicit contract")
        if int(typed_table.num_rows) != row_count:
            raise CloudAdapterError(
                f"typed BigQuery staging table has {typed_table.num_rows} rows; expected {row_count}"
            )

        null_projection = ", ".join(
            f"COUNTIF(`{name}` IS NULL) AS null_{name}"
            for name in expected_null_counts
        )
        count_sql = (
            "SELECT COUNT(*) AS row_count, "
            f"COUNTIF(`{filter_field}` = @filter_value) AS filtered_row_count"
            f"{', ' + null_projection if null_projection else ''} "
            f"FROM `{typed_table_id}`"
        )
        count_config = bq.QueryJobConfig(
            use_legacy_sql=False,
            query_parameters=[
                bq.ScalarQueryParameter("filter_value", "STRING", filter_value)
            ],
            maximum_bytes_billed=_MAXIMUM_BYTES_BILLED,
        )
        metrics_job_id = _new_job_id("verify", source, run_id)
        count_job = self._bigquery.query(
            count_sql,
            job_config=count_config,
            job_id=metrics_job_id,
            job_retry=None,
            location=region,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        count_row = next(
            iter(
                count_job.result(
                    retry=self._request_retry,
                    timeout=_JOB_WAIT_TIMEOUT_SECONDS,
                )
            )
        )
        checked_row_count = int(count_row["row_count"])
        filtered_rows = int(count_row["filtered_row_count"])
        null_counts = {name: int(count_row[f"null_{name}"]) for name in expected_null_counts}
        if checked_row_count != row_count:
            raise CloudAdapterError(
                f"BigQuery count query returned {checked_row_count} rows; expected {row_count}"
            )
        if null_counts != expected_null_counts:
            raise CloudAdapterError(
                f"BigQuery null-counts {null_counts} differ from local {expected_null_counts}"
            )

        order_by = ", ".join(f"`{name}`" for name in contract.primary_key)
        reconcile_config = bq.QueryJobConfig(
            use_legacy_sql=False,
            maximum_bytes_billed=_MAXIMUM_BYTES_BILLED,
        )
        reconciliation_job_id = _new_job_id("reconcile", source, run_id)
        reconciliation_job = self._bigquery.query(
            f"SELECT * FROM `{typed_table_id}` ORDER BY {order_by}",
            job_config=reconcile_config,
            job_id=reconciliation_job_id,
            job_retry=None,
            location=region,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        actual_rows = tuple(
            tuple(row[field.name] for field in contract.fields)
            for row in reconciliation_job.result(
                retry=self._request_retry,
                timeout=_JOB_WAIT_TIMEOUT_SECONDS,
            )
        )
        actual_canonical = canonical_value_rows(actual_rows, contract)
        expected_canonical = canonical_value_rows(expected_rows, contract)
        actual_value_sha256 = value_rows_sha256(actual_rows, contract)
        if len(actual_rows) != row_count or actual_canonical != expected_canonical:
            raise DataIntegrityError(
                "BigQuery typed row values or primary-key ordering differ from the Parquet source"
            )
        if value_rows_sha256(expected_rows, contract) != source_value_sha256:
            raise DataIntegrityError("local typed-value digest changed after source validation")
        return BigQueryLoadReceipt(
            raw_table=raw_table_id,
            typed_table=typed_table_id,
            load_job_id=load_job_id,
            cast_job_id=cast_job_id,
            metrics_job_id=str(count_job.job_id),
            row_count=checked_row_count,
            filtered_row_count=filtered_rows,
            null_counts=null_counts,
            schema=actual_schema,
            raw_reconciliation_job_id=str(raw_reconciliation_job.job_id),
            raw_value_sha256=actual_raw_sha256,
            raw_values_match=True,
            raw_reconciliation_bytes_processed=getattr(
                raw_reconciliation_job, "total_bytes_processed", None
            ),
            raw_reconciliation_bytes_billed=getattr(
                raw_reconciliation_job, "total_bytes_billed", None
            ),
            reconciliation_job_id=str(reconciliation_job.job_id),
            source_value_sha256=source_value_sha256,
            bigquery_value_sha256=actual_value_sha256,
            exact_values_match=True,
            load_reused=load_reused,
            cast_reused=cast_reused,
            cast_bytes_processed=cast_bytes_processed,
            cast_bytes_billed=cast_bytes_billed,
            metrics_bytes_processed=getattr(count_job, "total_bytes_processed", None),
            metrics_bytes_billed=getattr(count_job, "total_bytes_billed", None),
            reconciliation_bytes_processed=getattr(
                reconciliation_job, "total_bytes_processed", None
            ),
            reconciliation_bytes_billed=getattr(
                reconciliation_job, "total_bytes_billed", None
            ),
            maximum_bytes_billed=_MAXIMUM_BYTES_BILLED,
            request_retry_deadline_seconds=int(_REQUEST_RETRY_DEADLINE_SECONDS),
            api_request_timeout_seconds=int(_API_REQUEST_TIMEOUT_SECONDS),
            job_wait_timeout_seconds=int(_JOB_WAIT_TIMEOUT_SECONDS),
        )


def _new_job_id(stage: str, source: str, run_id: str) -> str:
    return f"dataforge_{stage}_{source}_{run_id}_{uuid4().hex[:12]}"


def _provenance_description(values: dict[str, str]) -> str:
    return _PROVENANCE_PREFIX + json.dumps(values, sort_keys=True, separators=(",", ":"))


def _read_provenance(table: Any, *, expected_role: str) -> dict[str, str]:
    description = str(table.description or "")
    if not description.startswith(_PROVENANCE_PREFIX):
        raise CloudAdapterError("existing staging table has no DataForge provenance")
    try:
        values = json.loads(description[len(_PROVENANCE_PREFIX):])
    except json.JSONDecodeError as exc:
        raise CloudAdapterError("existing staging table provenance is malformed") from exc
    if not isinstance(values, dict) or values.get("role") != expected_role:
        raise CloudAdapterError("existing staging table has the wrong DataForge role")
    if not isinstance(values.get("job_id"), str) or not values["job_id"]:
        raise CloudAdapterError("existing staging table has no originating BigQuery job ID")
    return values


def _require_matching_provenance(actual: dict[str, str], expected: dict[str, str]) -> None:
    if any(actual.get(name) != value for name, value in expected.items()):
        raise CloudAdapterError("existing staging table belongs to a different source generation")


def _get_table_or_none(
    client: Any,
    table_id: str,
    *,
    retry: Any,
    timeout: float,
) -> Any | None:
    try:
        return client.get_table(table_id, retry=retry, timeout=timeout)
    except Exception as exc:
        if _http_code(exc) == 404 or type(exc).__name__ == "NotFound":
            return None
        raise


def _schema_field(bq: Any, field: FieldContract) -> Any:
    kwargs: dict[str, Any] = {"mode": "NULLABLE" if field.nullable else "REQUIRED"}
    if field.precision is not None:
        kwargs["precision"] = field.precision
    if field.scale is not None:
        kwargs["scale"] = field.scale
    return bq.SchemaField(field.name, field.bq_type, **kwargs)


def _contract_from_schema(field: Any) -> FieldContract:
    return FieldContract(
        name=field.name,
        bq_type=_normalize_type(field.field_type),
        nullable=str(field.mode or "NULLABLE").upper() != "REQUIRED",
        precision=field.precision or None,
        scale=field.scale or None,
    )


def _normalize_type(value: str) -> str:
    value = value.upper()
    return {"INTEGER": "INT64", "FLOAT": "FLOAT64", "BOOLEAN": "BOOL"}.get(value, value)


def _typed_insert_sql(raw_table_id: str, typed_table_id: str, contract: SourceContract) -> str:
    columns = ", ".join(f"`{field.name}`" for field in contract.fields)
    expressions = []
    for field in contract.fields:
        raw = f"`{field.name}`"
        value = f"NULLIF({raw}, '')" if field.nullable else raw
        if field.bq_type == "STRING":
            expression = value
        else:
            expression = f"CAST({value} AS {field.bq_type})"
        expressions.append(f"{expression} AS `{field.name}`")
    return (
        f"INSERT INTO `{typed_table_id}` ({columns})\n"
        f"SELECT {', '.join(expressions)}\nFROM `{raw_table_id}`"
    )


def _http_code(exc: Exception) -> int | None:
    code = getattr(exc, "code", None)
    if callable(code):
        try:
            code = code()
        except Exception:
            return None
    if code is None:
        code = getattr(exc, "status_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None
