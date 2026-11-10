"""Google Cloud client implementation; imported only for explicit --execute runs."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from io import BytesIO
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
_MAXIMUM_PUBLISH_BYTES_BILLED = 1073741824
_WEEK5_PROVENANCE_PREFIX = "dataforge-week5-v1:"
_WEEK5_TABLE_COMPONENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
_GCP_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_WEEK5_STAGE_TABLE = re.compile(r"^week5_events_[a-f0-9]{16}$")


class GoogleCloudBackend:
    def __init__(self, project_id: str) -> None:
        credentials = self._load_isolated_adc(project_id)
        self._initialize_clients(project_id, credentials)

    @staticmethod
    def _load_isolated_adc(project_id: str) -> Any:
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
            import google.auth
        except ImportError as exc:
            raise CloudAdapterError(
                'Install GCP extras with `pip install -e ".[gcp]"` before --execute.'
            ) from exc

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
        return credentials

    def _initialize_clients(
        self,
        project_id: str,
        credentials: Any,
        *,
        clients_factory: Callable[[str, Any, Any, Any], tuple[Any, Any]] | None = None,
    ) -> None:
        try:
            from google.api_core import retry as api_retry
            from google.cloud import bigquery, storage
        except ImportError as exc:
            raise CloudAdapterError(
                'Install GCP extras with `pip install -e ".[gcp]"` before cloud execution.'
            ) from exc
        self._request_retry = api_retry.Retry(deadline=_REQUEST_RETRY_DEADLINE_SECONDS)
        self._bigquery_module = bigquery
        if clients_factory is None:
            self._storage = storage.Client(project=project_id, credentials=credentials)
            self._bigquery = bigquery.Client(project=project_id, credentials=credentials)
        else:
            self._storage, self._bigquery = clients_factory(
                project_id, credentials, storage, bigquery
            )

    @classmethod
    def from_local_access_token(
        cls,
        project_id: str,
        access_token: str,
        *,
        credentials_factory: Callable[[str, str], Any] | None = None,
        clients_factory: Callable[[str, Any, Any, Any], tuple[Any, Any]] | None = None,
    ) -> GoogleCloudBackend:
        """Build a one-off backend from a caller-supplied current CLI OAuth token.

        The token is neither read from disk nor retained by this module after the
        credential/client objects are created. Existing default construction keeps
        requiring ADC beneath the isolated DataForge ``CLOUDSDK_CONFIG`` root.
        """
        if not isinstance(access_token, str) or not access_token.strip():
            raise CloudAdapterError("an explicit non-empty OAuth access token is required")
        if "\n" in access_token or "\r" in access_token:
            raise CloudAdapterError("OAuth access token must be a single line")
        if credentials_factory is None:
            try:
                from google.oauth2.credentials import Credentials
            except ImportError as exc:
                raise CloudAdapterError(
                    'Install GCP extras with `pip install -e ".[gcp]"` before cloud execution.'
                ) from exc

            def credentials_factory(token: str, quota_project: str) -> Any:
                return Credentials(token=token, quota_project_id=quota_project)

        credentials = credentials_factory(access_token, project_id)
        backend = cls.__new__(cls)
        backend._initialize_clients(project_id, credentials, clients_factory=clients_factory)
        return backend

    @classmethod
    def from_cloud_run_metadata(
        cls,
        project_id: str,
        *,
        credentials_factory: Callable[[str], Any] | None = None,
        clients_factory: Callable[[str, Any, Any, Any], tuple[Any, Any]] | None = None,
    ) -> GoogleCloudBackend:
        """Use Cloud Run Job ADC while refusing developer-only credential files."""
        if not os.environ.get("CLOUD_RUN_JOB") or not os.environ.get("CLOUD_RUN_EXECUTION"):
            raise CloudAdapterError("metadata ADC is allowed only in a Cloud Run Job execution")
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            raise CloudAdapterError(
                "Cloud Run metadata ADC must not be overridden by a credential file"
            )
        if credentials_factory is None:
            try:
                import google.auth
            except ImportError as exc:
                raise CloudAdapterError(
                    'Install GCP extras with `pip install -e ".[gcp]"` before cloud execution.'
                ) from exc

            def credentials_factory(quota_project: str) -> Any:
                credentials, _ = google.auth.default(quota_project_id=quota_project)
                return credentials

        credentials = credentials_factory(project_id)
        backend = cls.__new__(cls)
        backend._initialize_clients(project_id, credentials, clients_factory=clients_factory)
        return backend

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

    def get_object_generation(self, bucket: str, name: str, generation: int) -> StoredObject:
        if isinstance(generation, bool) or generation <= 0:
            raise CloudAdapterError("GCS generation must be a positive integer")
        blob = self._storage.bucket(bucket).blob(name, generation=generation)
        blob.reload(
            if_generation_match=generation,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        if int(blob.generation) != generation:
            raise DataIntegrityError("GCS returned a different object generation")
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

    def stage_week5_events(
        self,
        *,
        table_id: str,
        run_id: str,
        region: str,
        batch_id: str,
        parquet_bytes: bytes,
        parquet_sha256: str,
        manifest_sha256: str,
        manifest_generation: int,
        object_generation: int,
        row_value_sha256: str,
        row_count: int,
        attempt: int,
    ) -> dict[str, Any]:
        """Load verified local Parquet bytes into a batch-scoped disposable table."""
        from ..incremental.batch import EVENT_KEYS
        from ..incremental.batch import row_value_sha256 as digest_event_rows

        table_parts = table_id.split(".")
        if (
            len(table_parts) != 3
            or not _GCP_PROJECT_ID.fullmatch(table_parts[0])
            or any(not _WEEK5_TABLE_COMPONENT.fullmatch(part) for part in table_parts[1:])
        ):
            raise CloudAdapterError("Week-5 staging table ID is not a validated project.dataset.table")
        project_id, dataset, table_name = table_parts
        if dataset != "staging" or not _WEEK5_STAGE_TABLE.fullmatch(table_name):
            raise CloudAdapterError("Week-5 stage table must use the batch-scoped staging name")
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise CloudAdapterError("Week-5 stage run ID must be lowercase 32-character hex")
        if isinstance(attempt, bool) or attempt < 0 or attempt > 1 or row_count <= 0:
            raise CloudAdapterError("Week-5 stage attempt or row count is outside its bound")
        expected_provenance = {
            "role": "week5-events",
            "batch_id": batch_id,
            "parquet_sha256": parquet_sha256,
            "manifest_sha256": manifest_sha256,
            "manifest_generation": str(manifest_generation),
            "object_generation": str(object_generation),
            "row_value_sha256": row_value_sha256,
            "row_count": str(row_count),
        }
        candidate_load_job_id = f"week5_load_{batch_id[:16]}_{attempt}"
        expected_schema = (
            FieldContract("change_seq", "INT64", False),
            FieldContract("change_id", "STRING", False),
            FieldContract("source_table", "STRING", False),
            FieldContract("business_key", "STRING", False),
            FieldContract("operation", "STRING", False),
            FieldContract("source_updated_at", "TIMESTAMP", False),
            FieldContract("business_event_at", "TIMESTAMP", False),
            FieldContract("schema_version", "STRING", False),
            FieldContract("payload", "STRING", False),
            FieldContract("payload_sha256", "STRING", False),
        )
        schema = [
            self._bigquery_module.SchemaField(field.name, field.bq_type, mode="REQUIRED")
            for field in expected_schema
        ]
        table = _get_table_or_none(
            self._bigquery,
            table_id,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        if table is None:
            table = self._bigquery_module.Table(table_id, schema=schema)
            table.expires = datetime.now(timezone.utc) + timedelta(days=7)
            table.description = _week5_provenance_description(
                {**expected_provenance, "stage_load_job_id": candidate_load_job_id}
            )
            try:
                self._bigquery.create_table(
                    table,
                    exists_ok=False,
                    retry=self._request_retry,
                    timeout=_API_REQUEST_TIMEOUT_SECONDS,
                )
            except Exception:
                # Another same-batch attempt may have won the create-only race.
                table = _get_table_or_none(
                    self._bigquery,
                    table_id,
                    retry=self._request_retry,
                    timeout=_API_REQUEST_TIMEOUT_SECONDS,
                )
                if table is None:
                    raise

        provenance = _read_week5_provenance(table)
        if any(provenance.get(key) != value for key, value in expected_provenance.items()):
            raise DataIntegrityError("existing Week-5 staging table belongs to another batch")
        actual_schema = tuple(_contract_from_schema(field) for field in table.schema)
        if actual_schema != expected_schema:
            raise DataIntegrityError("Week-5 staging table schema differs from the event contract")

        load_reused = int(table.num_rows or 0) == row_count
        if int(table.num_rows or 0) not in {0, row_count}:
            raise DataIntegrityError("Week-5 staging table has an unexpected partial row count")
        if load_reused:
            load_job_id = provenance.get("stage_load_job_id")
            if not isinstance(load_job_id, str) or not load_job_id:
                raise DataIntegrityError(
                    "reused Week-5 staging data has no recorded originating load job ID"
                )
        else:
            load_job_id = candidate_load_job_id
            table.description = _week5_provenance_description(
                {**expected_provenance, "stage_load_job_id": load_job_id}
            )
            table = self._bigquery.update_table(
                table,
                ["description"],
                retry=self._request_retry,
                timeout=_API_REQUEST_TIMEOUT_SECONDS,
            )
        if not load_reused:
            load_config = self._bigquery_module.LoadJobConfig(
                source_format=self._bigquery_module.SourceFormat.PARQUET,
                schema=schema,
                autodetect=False,
                create_disposition=self._bigquery_module.CreateDisposition.CREATE_NEVER,
                write_disposition=self._bigquery_module.WriteDisposition.WRITE_EMPTY,
                max_bad_records=0,
                ignore_unknown_values=False,
            )
            load_job = self._bigquery.load_table_from_file(
                BytesIO(parquet_bytes),
                table_id,
                job_config=load_config,
                job_id=load_job_id,
                location=region,
                size=len(parquet_bytes),
                rewind=True,
                num_retries=3,
                timeout=_API_REQUEST_TIMEOUT_SECONDS,
            )
            load_job.result(
                retry=self._request_retry,
                timeout=_JOB_WAIT_TIMEOUT_SECONDS,
            )
            if load_job.output_rows is not None and int(load_job.output_rows) != row_count:
                raise DataIntegrityError("Week-5 BigQuery load returned an unexpected row count")

        table = self._bigquery.get_table(
            table_id,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        actual_schema = tuple(_contract_from_schema(field) for field in table.schema)
        if actual_schema != expected_schema or int(table.num_rows or 0) != row_count:
            raise DataIntegrityError("Week-5 BigQuery staging schema or row count is invalid")
        verify_job_id = f"week5_stageverify_{batch_id[:12]}_{run_id[:16]}"
        select_sql = (
            f"SELECT {', '.join(f'`{name}`' for name in EVENT_KEYS)} "
            f"FROM `{table_id}` ORDER BY `change_seq`"
        )
        verify_job = self._bigquery.query(
            select_sql,
            job_config=self._bigquery_module.QueryJobConfig(
                use_legacy_sql=False,
                maximum_bytes_billed=_MAXIMUM_BYTES_BILLED,
            ),
            job_id=verify_job_id,
            job_retry=None,
            location=region,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        actual_rows = tuple(
            {name: row[name] for name in EVENT_KEYS}
            for row in verify_job.result(
                retry=self._request_retry,
                timeout=_JOB_WAIT_TIMEOUT_SECONDS,
            )
        )
        try:
            actual_digest = digest_event_rows(actual_rows)
        except ValueError as exc:
            raise DataIntegrityError("Week-5 BigQuery staged rows fail event validation") from exc
        if len(actual_rows) != row_count or actual_digest != row_value_sha256:
            raise DataIntegrityError("Week-5 BigQuery staged row values differ from Parquet")
        return {
            "table_id": table_id,
            "load_job_id": load_job_id,
            "verify_job_id": str(verify_job.job_id),
            "row_count": row_count,
            "row_value_sha256": actual_digest,
            "load_reused": load_reused,
            "maximum_bytes_billed": _MAXIMUM_BYTES_BILLED,
            "expiration_days": 7,
        }

    def is_week5_batch_published(
        self,
        *,
        project_id: str,
        region: str,
        batch_id: str,
        expected_metadata: Mapping[str, Any],
        job_id: str,
        maximum_bytes_billed: int = _MAXIMUM_BYTES_BILLED,
    ) -> dict[str, Any]:
        """Read durable publication metadata before staging, including expired replays."""
        if not _GCP_PROJECT_ID.fullmatch(project_id):
            raise CloudAdapterError("Week-5 project ID is invalid")
        if not re.fullmatch(r"[a-f0-9]{64}", batch_id):
            raise CloudAdapterError("Week-5 batch ID must be lowercase SHA-256 hex")
        if not re.fullmatch(r"week5_published_[a-f0-9]{16}_[a-f0-9]{16}", job_id):
            raise CloudAdapterError("Week-5 precheck job ID is outside the bounded form")
        if maximum_bytes_billed <= 0 or maximum_bytes_billed > _MAXIMUM_BYTES_BILLED:
            raise CloudAdapterError("Week-5 precheck byte cap exceeds the local ceiling")
        expected_columns = {
            "run_mode": "run_mode",
            "lower_seq": "lower_seq",
            "upper_seq": "upper_seq",
            "row_value_sha256": "row_value_sha256",
            "expected_row_count": "expected_row_count",
            "manifest_sha256": "manifest_sha256",
            "manifest_generation": "manifest_generation",
            "object_sha256": "object_sha256",
            "object_generation": "object_generation",
        }
        if set(expected_metadata) != set(expected_columns):
            raise CloudAdapterError("Week-5 replay metadata differs from the durable run schema")
        table_id = f"{project_id}.ops.week5_run_events"
        query_sql = (
            "SELECT run_mode, lower_seq, upper_seq, row_value_sha256, expected_row_count, "
            "manifest_sha256, manifest_generation, object_sha256, object_generation "
            f"FROM `{table_id}` WHERE batch_id = @batch_id AND status = 'PUBLISHED'"
        )
        job = self._bigquery.query(
            query_sql,
            job_config=self._bigquery_module.QueryJobConfig(
                use_legacy_sql=False,
                query_parameters=[
                    self._bigquery_module.ScalarQueryParameter("batch_id", "STRING", batch_id)
                ],
                maximum_bytes_billed=maximum_bytes_billed,
            ),
            job_id=job_id,
            job_retry=None,
            location=region,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        rows = list(
            job.result(
                retry=self._request_retry,
                timeout=_JOB_WAIT_TIMEOUT_SECONDS,
            )
        )
        if len(rows) > 1:
            raise DataIntegrityError("ops ledger has multiple PUBLISHED events for one batch")
        if not rows:
            published = False
        else:
            actual = {name: rows[0][name] for name in expected_columns}
            expected = dict(expected_metadata)
            if any(actual[name] != expected[name] for name in expected_columns):
                raise DataIntegrityError("published batch metadata differs from the immutable manifest")
            published = True
        return {
            "published": published,
            "job_id": str(job.job_id),
            "bytes_processed": getattr(job, "total_bytes_processed", None),
            "bytes_billed": getattr(job, "total_bytes_billed", None),
            "maximum_bytes_billed": maximum_bytes_billed,
        }

    def read_week5_checkpoint(
        self,
        *,
        project_id: str,
        region: str,
        source_id: str = "dataforge-operational-v1",
        maximum_bytes_billed: int = _MAXIMUM_BYTES_BILLED,
    ) -> dict[str, Any]:
        """Read the committed journal high-water mark without mutating warehouse state."""
        if not _GCP_PROJECT_ID.fullmatch(project_id):
            raise CloudAdapterError("Week-5 project ID is invalid")
        if source_id != "dataforge-operational-v1":
            raise CloudAdapterError("Week-5 checkpoint source ID is not approved")
        if maximum_bytes_billed <= 0 or maximum_bytes_billed > _MAXIMUM_BYTES_BILLED:
            raise CloudAdapterError("Week-5 checkpoint byte cap exceeds the local ceiling")
        table_id = f"{project_id}.ops.pipeline_checkpoints"
        job_id = f"week5_checkpoint_{uuid4().hex[:24]}"
        job = self._bigquery.query(
            f"SELECT committed_seq FROM `{table_id}` WHERE source_id = @source_id",
            job_config=self._bigquery_module.QueryJobConfig(
                use_legacy_sql=False,
                query_parameters=[
                    self._bigquery_module.ScalarQueryParameter("source_id", "STRING", source_id)
                ],
                maximum_bytes_billed=maximum_bytes_billed,
            ),
            job_id=job_id,
            job_retry=None,
            location=region,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        rows = list(
            job.result(
                retry=self._request_retry,
                timeout=_JOB_WAIT_TIMEOUT_SECONDS,
            )
        )
        if len(rows) != 1:
            raise DataIntegrityError("Week-5 checkpoint must contain exactly one source row")
        checkpoint = int(rows[0]["committed_seq"])
        if checkpoint < 0:
            raise DataIntegrityError("Week-5 checkpoint cannot be negative")
        return {
            "source_id": source_id,
            "committed_seq": checkpoint,
            "job_id": str(job.job_id),
            "bytes_processed": getattr(job, "total_bytes_processed", None),
            "bytes_billed": getattr(job, "total_bytes_billed", None),
            "maximum_bytes_billed": maximum_bytes_billed,
        }

    def read_week5_run_events(
        self,
        *,
        project_id: str,
        region: str,
        limit: int = 50,
        maximum_bytes_billed: int = _MAXIMUM_BYTES_BILLED,
    ) -> dict[str, Any]:
        """Read a bounded recent ledger view for status/recovery commands."""
        if not _GCP_PROJECT_ID.fullmatch(project_id):
            raise CloudAdapterError("Week-5 project ID is invalid")
        if isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise CloudAdapterError("Week-5 run-event limit must be between 1 and 1000")
        if maximum_bytes_billed <= 0 or maximum_bytes_billed > _MAXIMUM_BYTES_BILLED:
            raise CloudAdapterError("Week-5 run-event byte cap exceeds the local ceiling")
        table_id = f"{project_id}.ops.week5_run_events"
        job_id = f"week5_runstatus_{uuid4().hex[:24]}"
        job = self._bigquery.query(
            f"""
SELECT event_id, run_id, execution_id, batch_id, status, run_mode, source_run_id, event_at,
       attempt, manifest_uri, lower_seq, upper_seq, expected_row_count,
       row_value_sha256, manifest_sha256, manifest_generation, object_sha256,
       object_generation, stage_table_id, stage_load_job_id, stage_verify_job_id,
       publish_job_id, published_check_job_id, checkpoint_before, checkpoint_after,
       affected_order_count, delivered_sales_proxy, collected_amount,
       error_code, error_message
FROM `{table_id}`
ORDER BY event_at DESC, run_id DESC
LIMIT @row_limit
""".strip(),
            job_config=self._bigquery_module.QueryJobConfig(
                use_legacy_sql=False,
                query_parameters=[
                    self._bigquery_module.ScalarQueryParameter("row_limit", "INT64", limit)
                ],
                maximum_bytes_billed=maximum_bytes_billed,
            ),
            job_id=job_id,
            job_retry=None,
            location=region,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        rows = [dict(row.items()) for row in job.result(
            retry=self._request_retry,
            timeout=_JOB_WAIT_TIMEOUT_SECONDS,
        )]
        return {
            "rows": rows,
            "job_id": str(job.job_id),
            "bytes_processed": getattr(job, "total_bytes_processed", None),
            "bytes_billed": getattr(job, "total_bytes_billed", None),
            "maximum_bytes_billed": maximum_bytes_billed,
        }

    def record_week5_run_event(
        self,
        *,
        project_id: str,
        region: str,
        run_id: str,
        status: str,
        attempt: int,
        metadata: Mapping[str, Any],
        maximum_bytes_billed: int = _MAXIMUM_BYTES_BILLED,
    ) -> dict[str, Any]:
        """Append an idempotent non-terminal lifecycle event for one task attempt."""
        allowed_statuses = {
            "DISCOVERED", "VALIDATED", "STAGED", "NO_OP", "FAILED", "IAM_NEGATIVE_PASS"
        }
        if not _GCP_PROJECT_ID.fullmatch(project_id):
            raise CloudAdapterError("Week-5 project ID is invalid")
        if not re.fullmatch(r"[a-f0-9]{32}", run_id) or status not in allowed_statuses:
            raise CloudAdapterError("Week-5 run ID/status is outside the ledger contract")
        if isinstance(attempt, bool) or not 0 <= attempt <= 1:
            raise CloudAdapterError("Week-5 attempt is outside the configured single retry")
        if maximum_bytes_billed <= 0 or maximum_bytes_billed > _MAXIMUM_BYTES_BILLED:
            raise CloudAdapterError("Week-5 ledger query byte cap exceeds the local ceiling")
        if status not in allowed_statuses:
            raise CloudAdapterError("Week-5 lifecycle status is not appendable by the runtime")
        event_id = f"{run_id}:{status}"
        table_id = f"{project_id}.ops.week5_run_events"
        # The row event_id is deterministic; query job IDs are not. This lets an
        # operator retry the ledger insert with corrected SQL after an earlier
        # failed BigQuery job ID has been retained by the service.
        job_id = f"week5_ledger_{status.lower()}_{run_id[:12]}_{uuid4().hex[:12]}"
        field_types = {
            "execution_id": "STRING",
            "batch_id": "STRING",
            "run_mode": "STRING",
            "source_run_id": "STRING",
            "manifest_uri": "STRING",
            "lower_seq": "INT64",
            "upper_seq": "INT64",
            "expected_row_count": "INT64",
            "row_value_sha256": "STRING",
            "manifest_sha256": "STRING",
            "manifest_generation": "INT64",
            "object_sha256": "STRING",
            "object_generation": "INT64",
            "stage_table_id": "STRING",
            "stage_load_job_id": "STRING",
            "stage_verify_job_id": "STRING",
            "publish_job_id": "STRING",
            "published_check_job_id": "STRING",
            "checkpoint_before": "INT64",
            "checkpoint_after": "INT64",
            "affected_order_count": "INT64",
            "delivered_sales_proxy": "NUMERIC",
            "collected_amount": "NUMERIC",
            "error_code": "STRING",
            "error_message": "STRING",
        }
        query_parameters = [
            self._bigquery_module.ScalarQueryParameter("event_id", "STRING", event_id),
            self._bigquery_module.ScalarQueryParameter("run_id", "STRING", run_id),
            self._bigquery_module.ScalarQueryParameter("status", "STRING", status),
            self._bigquery_module.ScalarQueryParameter("attempt", "INT64", attempt),
        ]
        query_parameters.extend(
            self._bigquery_module.ScalarQueryParameter(
                name, kind, metadata.get(name)
            )
            for name, kind in field_types.items()
        )
        insert_columns = [
            "event_id", "run_id", "execution_id", "batch_id", "status", "run_mode", "source_run_id",
            "event_at", "attempt", "manifest_uri", "lower_seq", "upper_seq",
            "expected_row_count", "row_value_sha256", "manifest_sha256",
            "manifest_generation", "object_sha256", "object_generation", "stage_table_id",
            "stage_load_job_id", "stage_verify_job_id", "publish_job_id",
            "published_check_job_id", "checkpoint_before", "checkpoint_after",
            "affected_order_count", "delivered_sales_proxy", "collected_amount",
            "error_code", "error_message",
        ]
        select_values = [
            "@event_id", "@run_id", "@execution_id", "@batch_id", "@status", "@run_mode", "@source_run_id",
            "CURRENT_TIMESTAMP()", "@attempt", "@manifest_uri", "@lower_seq", "@upper_seq",
            "@expected_row_count", "@row_value_sha256", "@manifest_sha256",
            "@manifest_generation", "@object_sha256", "@object_generation", "@stage_table_id",
            "@stage_load_job_id", "@stage_verify_job_id", "@publish_job_id",
            "@published_check_job_id", "@checkpoint_before", "@checkpoint_after",
            "@affected_order_count", "@delivered_sales_proxy", "@collected_amount",
            "@error_code", "@error_message",
        ]
        query = (
            f"INSERT INTO `{table_id}` ({', '.join(insert_columns)}) "
            f"SELECT {', '.join(select_values)} FROM UNNEST([1]) AS seed WHERE NOT EXISTS "
            f"(SELECT 1 FROM `{table_id}` WHERE event_id = @event_id)"
        )
        job = self._bigquery.query(
            query,
            job_config=self._bigquery_module.QueryJobConfig(
                use_legacy_sql=False,
                query_parameters=query_parameters,
                maximum_bytes_billed=maximum_bytes_billed,
            ),
            job_id=job_id,
            job_retry=None,
            location=region,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        job.result(retry=self._request_retry, timeout=_JOB_WAIT_TIMEOUT_SECONDS)
        return {
            "event_id": event_id,
            "status": status,
            "job_id": str(job.job_id),
            "bytes_processed": getattr(job, "total_bytes_processed", None),
            "bytes_billed": getattr(job, "total_bytes_billed", None),
            "maximum_bytes_billed": maximum_bytes_billed,
        }

    def record_week5_failure(
        self,
        *,
        project_id: str,
        region: str,
        run_id: str,
        error_code: str,
        error_message: str,
        attempt: int = 0,
        metadata: Mapping[str, Any] | None = None,
        maximum_bytes_billed: int = _MAXIMUM_BYTES_BILLED,
    ) -> dict[str, Any]:
        """Append one sanitized early-failure event unless SQL already recorded it."""
        if not _GCP_PROJECT_ID.fullmatch(project_id):
            raise CloudAdapterError("Week-5 project ID is invalid")
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise CloudAdapterError("Week-5 run ID must be 32 lowercase hex characters")
        if not re.fullmatch(r"[A-Z0-9_]{1,64}", error_code):
            raise CloudAdapterError("Week-5 failure code must be a sanitized identifier")
        if len(error_message) > 512 or any(ch in error_message for ch in "\r\n\x00"):
            raise CloudAdapterError("Week-5 failure message must be a sanitized single line")
        if maximum_bytes_billed <= 0 or maximum_bytes_billed > _MAXIMUM_BYTES_BILLED:
            raise CloudAdapterError("Week-5 failure query byte cap exceeds the local ceiling")
        table_id = f"{project_id}.ops.week5_run_events"
        check_job_id = f"week5_failcheck_{run_id[:12]}_{uuid4().hex[:12]}"
        check_job = self._bigquery.query(
            "SELECT status FROM "
            f"`{table_id}` WHERE run_id = @run_id AND status IN ('FAILED', 'PUBLISHED')",
            job_config=self._bigquery_module.QueryJobConfig(
                use_legacy_sql=False,
                query_parameters=[
                    self._bigquery_module.ScalarQueryParameter("run_id", "STRING", run_id)
                ],
                maximum_bytes_billed=maximum_bytes_billed,
            ),
            job_id=check_job_id,
            job_retry=None,
            location=region,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        prior_rows = list(
            check_job.result(
                retry=self._request_retry,
                timeout=_JOB_WAIT_TIMEOUT_SECONDS,
            )
        )
        if len(prior_rows) > 1:
            raise DataIntegrityError("one Week-5 run has multiple terminal ledger events")
        prior_statuses = {str(row["status"]) for row in prior_rows}
        if len(prior_statuses) > 1:
            raise DataIntegrityError("one Week-5 run has both FAILED and PUBLISHED ledger events")
        if prior_statuses:
            return {
                "recorded": False,
                "existing_status": next(iter(prior_statuses)),
                "check_job_id": str(check_job.job_id),
                "insert_job_id": "",
            }

        event_metadata = dict(metadata or {})
        event_metadata.update({"error_code": error_code, "error_message": error_message})
        insert = self.record_week5_run_event(
            project_id=project_id,
            region=region,
            run_id=run_id,
            status="FAILED",
            attempt=attempt,
            metadata=event_metadata,
            maximum_bytes_billed=maximum_bytes_billed,
        )
        return {
            "recorded": True,
            "existing_status": "FAILED",
            "check_job_id": str(check_job.job_id),
            "insert_job_id": str(insert["job_id"]),
        }

    def run_week5_publish(
        self,
        *,
        sql: str,
        staging_table_id: str,
        region: str,
        parameters: Mapping[str, Any],
        job_id: str,
        maximum_bytes_billed: int = _MAXIMUM_PUBLISH_BYTES_BILLED,
    ) -> dict[str, Any]:
        """Run the reviewed multi-statement publish script with bounded identifiers/jobs."""
        if sql.count("{{STAGING_TABLE_ID}}") != 1:
            raise CloudAdapterError("publish.sql must contain exactly one {{STAGING_TABLE_ID}} token")
        if maximum_bytes_billed <= 0 or maximum_bytes_billed > _MAXIMUM_PUBLISH_BYTES_BILLED:
            raise CloudAdapterError("Week-5 publish byte cap exceeds the 1 GiB script ceiling")
        if not re.fullmatch(r"week5_publish_[a-f0-9]{16}_[a-f0-9]{16}", job_id):
            raise CloudAdapterError("Week-5 publish job ID is outside the bounded identifier form")
        parts = staging_table_id.split(".")
        if (
            len(parts) != 3
            or not _GCP_PROJECT_ID.fullmatch(parts[0])
            or any(not _WEEK5_TABLE_COMPONENT.fullmatch(p) for p in parts[1:])
        ):
            raise CloudAdapterError("Week-5 staging table ID is not a validated identifier")
        if parts[1] != "staging" or not _WEEK5_STAGE_TABLE.fullmatch(parts[2]):
            raise CloudAdapterError("Week-5 staging table must use the batch-scoped staging name")
        required_types = {
            "run_id": "STRING",
            "execution_id": "STRING",
            "batch_id": "STRING",
            "run_mode": "STRING",
            "source_run_id": "STRING",
            "attempt": "INT64",
            "manifest_uri": "STRING",
            "lower_seq": "INT64",
            "upper_seq": "INT64",
            "row_value_sha256": "STRING",
            "manifest_sha256": "STRING",
            "manifest_generation": "INT64",
            "object_sha256": "STRING",
            "object_generation": "INT64",
            "expected_row_count": "INT64",
            "stage_table_id": "STRING",
            "stage_load_job_id": "STRING",
            "stage_verify_job_id": "STRING",
            "publish_job_id": "STRING",
            "published_check_job_id": "STRING",
            "fail_after_merge_once": "BOOL",
            "fail_before_publish": "BOOL",
        }
        if set(parameters) != set(required_types):
            raise CloudAdapterError("publish parameters differ from the Week-5 named parameter contract")
        publish_sql = sql.replace(
            "{{STAGING_TABLE_ID}}", f"`{staging_table_id}`", 1
        )
        query_parameters = [
            self._bigquery_module.ScalarQueryParameter(name, kind, parameters[name])
            for name, kind in required_types.items()
        ]
        job = self._bigquery.query(
            publish_sql,
            job_config=self._bigquery_module.QueryJobConfig(
                use_legacy_sql=False,
                query_parameters=query_parameters,
                maximum_bytes_billed=maximum_bytes_billed,
            ),
            job_id=job_id,
            job_retry=None,
            location=region,
            retry=self._request_retry,
            timeout=_API_REQUEST_TIMEOUT_SECONDS,
        )
        result_rows = list(job.result(
            retry=self._request_retry,
            timeout=_JOB_WAIT_TIMEOUT_SECONDS,
        ))
        publication_status = ""
        if len(result_rows) == 1:
            try:
                publication_status = str(result_rows[0]["publication_status"])
            except (KeyError, TypeError):
                publication_status = ""
        if publication_status not in {"PUBLISHED", "NO_OP"}:
            raise CloudAdapterError("publish.sql did not return one recognized publication status")
        return {
            "job_id": str(job.job_id),
            "publication_status": publication_status,
            "bytes_processed": getattr(job, "total_bytes_processed", None),
            "bytes_billed": getattr(job, "total_bytes_billed", None),
            "maximum_bytes_billed": maximum_bytes_billed,
        }

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


def _week5_provenance_description(values: dict[str, str]) -> str:
    return _WEEK5_PROVENANCE_PREFIX + json.dumps(
        values, sort_keys=True, separators=(",", ":")
    )


def _read_week5_provenance(table: Any) -> dict[str, str]:
    description = str(table.description or "")
    if not description.startswith(_WEEK5_PROVENANCE_PREFIX):
        raise DataIntegrityError("existing Week-5 staging table has no DataForge provenance")
    try:
        values = json.loads(description[len(_WEEK5_PROVENANCE_PREFIX):])
    except json.JSONDecodeError as exc:
        raise DataIntegrityError("existing Week-5 staging provenance is malformed") from exc
    if not isinstance(values, dict) or values.get("role") != "week5-events":
        raise DataIntegrityError("existing staging table has the wrong Week-5 role")
    return values


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
