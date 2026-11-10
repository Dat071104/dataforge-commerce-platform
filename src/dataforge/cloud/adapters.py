"""Local validation and opt-in immutable GCS/typed BigQuery staging adapters."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

import pyarrow as pa
import pyarrow.parquet as pq

from ..settings import BRONZE, MANIFESTS
from .contracts import FieldContract, SourceContract, source_contract

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[0-9a-f]{32}$")
_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_REGION = re.compile(r"^[a-z]+-[a-z]+[0-9]$")
_DATASET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
_CONTRACT_VERSION = "dataforge-source-v1"


class CloudAdapterError(RuntimeError):
    """Base error for opt-in cloud adapter operations."""


class ManifestError(CloudAdapterError):
    """The local active run manifest is incomplete or invalid."""


class SnapshotNotFoundError(ManifestError):
    """The selected source is not in the active complete snapshot."""


class DataIntegrityError(CloudAdapterError):
    """Local or remote artifact bytes do not match their recorded digest."""


class DuplicateObjectError(DataIntegrityError):
    """A content-addressed object name already exists with different bytes."""


class LocationMismatchError(CloudAdapterError):
    """The requested, bucket, and BigQuery locations are not identical."""


class ProjectMismatchError(CloudAdapterError):
    """The destination bucket is not owned by the explicitly selected project."""


class PermissionDeniedError(CloudAdapterError):
    """The active identity does not have the minimum required permission."""


@dataclass(frozen=True)
class ValidatedSnapshot:
    source: str
    active_run_id: str
    source_ingest_run_id: str
    source_sha256: str
    parquet_sha256: str
    row_count: int
    parquet_path: Path
    parquet_bytes: bytes
    source_class: str
    contract: SourceContract
    parquet_schema: tuple[str, ...]
    filter_field: str
    filter_value: str
    expected_filter_rows: int
    expected_null_counts: dict[str, int]
    expected_rows: tuple[tuple[str | None, ...], ...]
    source_value_sha256: str


@dataclass(frozen=True)
class StoredObject:
    generation: int
    size_bytes: int
    crc32c: str
    metadata: dict[str, str]
    payload: bytes | None = None


@dataclass(frozen=True)
class BigQueryLoadReceipt:
    raw_table: str
    typed_table: str
    load_job_id: str
    cast_job_id: str
    metrics_job_id: str
    row_count: int
    filtered_row_count: int
    null_counts: dict[str, int]
    schema: tuple[FieldContract, ...]
    raw_reconciliation_job_id: str = ""
    raw_value_sha256: str = ""
    raw_values_match: bool = False
    raw_reconciliation_bytes_processed: int | None = None
    raw_reconciliation_bytes_billed: int | None = None
    reconciliation_job_id: str = ""
    source_value_sha256: str = ""
    bigquery_value_sha256: str = ""
    exact_values_match: bool = False
    load_reused: bool = False
    cast_reused: bool = False
    cast_bytes_processed: int | None = None
    cast_bytes_billed: int | None = None
    metrics_bytes_processed: int | None = None
    metrics_bytes_billed: int | None = None
    reconciliation_bytes_processed: int | None = None
    reconciliation_bytes_billed: int | None = None
    maximum_bytes_billed: int = 268435456
    request_retry_deadline_seconds: int = 60
    api_request_timeout_seconds: int = 60
    job_wait_timeout_seconds: int = 300


def canonical_value_rows(
    rows: tuple[tuple[Any, ...], ...], contract: SourceContract
) -> tuple[tuple[Any, ...], ...]:
    """Normalize source strings and BigQuery values into a stable typed row representation."""
    canonical = []
    for row in rows:
        if len(row) != len(contract.fields):
            raise DataIntegrityError("record width differs from the declared source contract")
        normalized = []
        for field, value in zip(contract.fields, row, strict=True):
            if value is None or (field.nullable and value == ""):
                normalized.append(None)
            elif field.bq_type == "STRING":
                normalized.append(str(value))
            elif field.bq_type == "DATE":
                normalized.append(value.isoformat() if hasattr(value, "isoformat") else str(value))
            elif field.bq_type == "INT64":
                normalized.append(int(value))
            elif field.bq_type == "NUMERIC":
                scale = field.scale or 0
                quantum = Decimal(1).scaleb(-scale)
                try:
                    amount = Decimal(str(value)).quantize(quantum)
                except InvalidOperation as exc:
                    raise DataIntegrityError(
                        f"value for {field.name!r} is not a valid NUMERIC"
                    ) from exc
                normalized.append(format(amount, f".{scale}f"))
            else:
                raise DataIntegrityError(f"unsupported canonical type {field.bq_type!r}")
        canonical.append(tuple(normalized))

    positions = {field.name: index for index, field in enumerate(contract.fields)}
    key_positions = tuple(positions[name] for name in contract.primary_key)
    canonical.sort(key=lambda row: tuple(row[index] for index in key_positions))
    return tuple(canonical)


def value_rows_sha256(rows: tuple[tuple[Any, ...], ...], contract: SourceContract) -> str:
    canonical = canonical_value_rows(rows, contract)
    payload = json.dumps(
        canonical, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_raw_rows(
    rows: tuple[tuple[Any, ...], ...], contract: SourceContract
) -> tuple[tuple[str | None, ...], ...]:
    """Normalize raw BigQuery STRING values without applying typed NULLIF conversions."""
    canonical = []
    for row in rows:
        if len(row) != len(contract.fields):
            raise DataIntegrityError("raw record width differs from the declared source contract")
        canonical.append(tuple(None if value is None else str(value) for value in row))

    positions = {field.name: index for index, field in enumerate(contract.fields)}
    key_positions = tuple(positions[name] for name in contract.primary_key)
    canonical.sort(key=lambda row: tuple(row[index] for index in key_positions))
    return tuple(canonical)


def raw_value_rows_sha256(rows: tuple[tuple[Any, ...], ...], contract: SourceContract) -> str:
    canonical = canonical_raw_rows(rows, contract)
    payload = json.dumps(
        canonical, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class TransferReceipt:
    source: str
    target_project_number: str
    active_run_id: str
    source_ingest_run_id: str
    source_sha256: str
    parquet_sha256: str
    row_count: int
    gcs_uri: str
    gcs_generation: int
    gcs_size_bytes: int
    gcs_crc32c: str
    manifest_uri: str
    manifest_sha256: str
    manifest_generation: int
    manifest_size_bytes: int
    manifest_crc32c: str
    bucket_location: str
    dataset_location: str
    bigquery: BigQueryLoadReceipt


class ObjectStore(Protocol):
    def get_object(self, bucket: str, name: str) -> StoredObject | None: ...

    def put_object(
        self,
        bucket: str,
        name: str,
        payload: bytes,
        metadata: dict[str, str],
        content_type: str,
        *,
        if_generation_match: int,
    ) -> None: ...


class CloudBackend(ObjectStore, Protocol):
    def target_locations(
        self,
        project_id: str,
        bucket: str,
        dataset: str,
        expected_project_number: str,
    ) -> tuple[str, str]: ...

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
    ) -> BigQueryLoadReceipt: ...


def _read_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManifestError(f"cannot read {description}: {path}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"{description} must be a JSON object: {path}")
    return value


def _filter_check(payload: bytes, contract: SourceContract) -> tuple[str, str, int]:
    field = next(
        (name for name in contract.primary_key
         if next(item for item in contract.fields if item.name == name).bq_type == "STRING"),
        None,
    )
    if field is None:
        raise ManifestError("source contract must have a string primary-key field")
    values = pq.read_table(io.BytesIO(payload), columns=[field]).column(field).to_pylist()
    sample = next((value for value in values if isinstance(value, str) and value), None)
    if sample is None:
        raise ManifestError(f"source primary key {field!r} has no non-empty value")
    return field, sample, sum(value == sample for value in values)


def _null_counts(payload: bytes, contract: SourceContract) -> dict[str, int]:
    nullable_fields = [field.name for field in contract.fields if field.nullable]
    if not nullable_fields:
        return {}
    table = pq.read_table(io.BytesIO(payload), columns=nullable_fields)
    return {
        name: sum(value is None or value == "" for value in table.column(name).to_pylist())
        for name in nullable_fields
    }


def _validate_primary_keys(
    rows: tuple[tuple[str | None, ...], ...], contract: SourceContract
) -> None:
    positions = {field.name: index for index, field in enumerate(contract.fields)}
    key_positions = tuple(positions[name] for name in contract.primary_key)
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key = tuple(row[index] for index in key_positions)
        if any(value is None or value == "" for value in key):
            raise DataIntegrityError("validated Parquet contains a null or blank primary key")
        if key in seen:
            raise DataIntegrityError("validated Parquet contains a duplicate primary key")
        seen.add(key)


def load_validated_snapshot(
    source: str,
    *,
    manifest_dir: Path = MANIFESTS,
    bronze_root: Path = BRONZE,
) -> ValidatedSnapshot:
    """Resolve one source from a complete active run and verify its exact Parquet bytes."""
    try:
        contract = source_contract(source)
    except ValueError as exc:
        raise ManifestError(str(exc)) from exc

    manifest_dir = Path(manifest_dir)
    bronze_root = Path(bronze_root)
    pointer = _read_json_object(manifest_dir / "active.json", "active manifest pointer")
    active_run_id = pointer.get("run_id")
    if not isinstance(active_run_id, str) or not _RUN_ID.fullmatch(active_run_id):
        raise ManifestError("active manifest pointer has an invalid run_id")

    run = _read_json_object(manifest_dir / "runs" / f"{active_run_id}.json", "active run")
    if run.get("run_id") != active_run_id or run.get("status") != "complete":
        raise ManifestError("active run is not a complete run matching active.json")
    sources = run.get("sources")
    if not isinstance(sources, dict):
        raise ManifestError("active run has no sources map")
    configured_sources = set(source_contracts())
    if set(sources) != configured_sources:
        raise ManifestError("active run must contain the complete configured source set")
    metadata = sources.get(source)
    if not isinstance(metadata, dict) or metadata.get("source") != source:
        raise SnapshotNotFoundError(f"source {source!r} is absent from the active run")

    source_sha256 = metadata.get("source_sha256")
    parquet_sha256 = metadata.get("bronze_sha256")
    source_ingest_run_id = metadata.get("ingest_run_id")
    row_count = metadata.get("rows_accepted")
    source_class = metadata.get("data_classification")
    if not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256):
        raise ManifestError(f"source {source!r} has an invalid source_sha256")
    if not isinstance(parquet_sha256, str) or not _SHA256.fullmatch(parquet_sha256):
        raise ManifestError(f"source {source!r} has an invalid bronze_sha256")
    if not isinstance(source_ingest_run_id, str) or not _RUN_ID.fullmatch(source_ingest_run_id):
        raise ManifestError(f"source {source!r} has an invalid ingest_run_id")
    if type(row_count) is not int or row_count <= 0:
        raise ManifestError(f"source {source!r} has an invalid rows_accepted count")
    if metadata.get("rows_rejected", 0) != 0:
        raise ManifestError(f"source {source!r} records rejected rows")
    if source_class != "synthetic":
        raise ManifestError(f"cloud transfer is limited to synthetic sources; got {source_class!r}")

    expected_path = bronze_root / source / f"sha256={source_sha256}" / "part-000.parquet"
    recorded_path = metadata.get("bronze_file")
    if not isinstance(recorded_path, str) or not recorded_path:
        raise ManifestError(f"source {source!r} is missing bronze_file")
    try:
        actual_path = Path(recorded_path).resolve(strict=True)
        resolved_expected = expected_path.resolve(strict=True)
    except OSError as exc:
        raise ManifestError(f"source {source!r} Parquet artifact is missing") from exc
    if actual_path != resolved_expected:
        raise ManifestError(f"source {source!r} Parquet path is outside its expected Bronze location")

    try:
        payload = actual_path.read_bytes()
    except OSError as exc:
        raise ManifestError(f"cannot read Parquet artifact for {source!r}") from exc
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != parquet_sha256:
        raise DataIntegrityError(
            f"Parquet SHA-256 mismatch for {source!r}: expected {parquet_sha256}, found {actual_sha256}"
        )

    try:
        parquet = pq.ParquetFile(io.BytesIO(payload))
        schema = parquet.schema_arrow
        row_count_actual = parquet.metadata.num_rows
    except Exception as exc:
        raise DataIntegrityError(f"invalid Parquet for {source!r}: {exc}") from exc
    names = tuple(schema.names)
    if names != contract.columns:
        raise DataIntegrityError(
            f"Parquet schema mismatch for {source!r}: expected {contract.columns}, found {names}"
        )
    if not all(pa.types.is_string(field.type) for field in schema):
        raise DataIntegrityError(
            f"Parquet fields for {source!r} must remain strings under the current local contract"
        )
    if row_count_actual != row_count:
        raise DataIntegrityError(
            f"Parquet row-count mismatch for {source!r}: expected {row_count}, found {row_count_actual}"
        )

    value_table = pq.read_table(io.BytesIO(payload), columns=list(contract.columns))
    expected_rows = tuple(
        tuple(row[name] for name in contract.columns) for row in value_table.to_pylist()
    )
    if len(expected_rows) != row_count:
        raise DataIntegrityError("Parquet value rows do not match the manifest row count")
    _validate_primary_keys(expected_rows, contract)
    source_value_sha256 = value_rows_sha256(expected_rows, contract)
    filter_field, filter_value, expected_filter_rows = _filter_check(payload, contract)
    expected_null_counts = _null_counts(payload, contract)
    return ValidatedSnapshot(
        source=source,
        active_run_id=active_run_id,
        source_ingest_run_id=source_ingest_run_id,
        source_sha256=source_sha256,
        parquet_sha256=parquet_sha256,
        row_count=row_count,
        parquet_path=actual_path,
        parquet_bytes=payload,
        source_class=source_class,
        contract=contract,
        parquet_schema=tuple(f"{field.name}:{field.type}" for field in schema),
        filter_field=filter_field,
        filter_value=filter_value,
        expected_filter_rows=expected_filter_rows,
        expected_null_counts=expected_null_counts,
        expected_rows=expected_rows,
        source_value_sha256=source_value_sha256,
    )


def source_contracts() -> dict[str, SourceContract]:
    """Return contracts only after verifying every one still matches the local config."""
    return {name: source_contract(name) for name in sorted_contract_names()}


def sorted_contract_names() -> tuple[str, ...]:
    from .contracts import SOURCE_CONTRACTS

    return tuple(SOURCE_CONTRACTS)


def validate_location_match(region: str, bucket_location: str, dataset_location: str) -> None:
    if not _REGION.fullmatch(region):
        raise LocationMismatchError(f"invalid single-region choice {region!r}")
    actuals = {
        "requested": region.casefold(),
        "bucket": bucket_location.casefold(),
        "dataset": dataset_location.casefold(),
    }
    if len(set(actuals.values())) != 1:
        raise LocationMismatchError(
            "requested region, GCS bucket, and BigQuery dataset must match exactly; "
            f"observed {actuals}"
        )


def _validate_target_ids(
    project_id: str,
    bucket: str,
    dataset: str,
    region: str,
    expected_project_number: str,
) -> None:
    if not _PROJECT_ID.fullmatch(project_id):
        raise CloudAdapterError("invalid GCP project ID")
    if not _BUCKET.fullmatch(bucket) or ".." in bucket:
        raise CloudAdapterError("invalid GCS bucket name")
    if not _DATASET.fullmatch(dataset) or dataset != "staging":
        raise CloudAdapterError("Week-4 adapter writes only to the staging dataset")
    if not _REGION.fullmatch(region):
        raise CloudAdapterError("invalid single-region location")
    if not expected_project_number.isdigit() or int(expected_project_number) <= 0:
        raise CloudAdapterError("expected_project_number must be a positive numeric project number")


def _object_names(snapshot: ValidatedSnapshot) -> tuple[str, str]:
    data_name = (
        f"bronze/source={snapshot.source}/sha256={snapshot.parquet_sha256}/part-000.parquet"
    )
    manifest_name = (
        f"manifests/source={snapshot.source}/active_run={snapshot.active_run_id}/manifest.json"
    )
    return data_name, manifest_name


def _remote_object_sha256(stored: StoredObject) -> str:
    if stored.payload is None:
        raise DataIntegrityError("remote object read did not return object bytes for SHA-256 verification")
    return hashlib.sha256(stored.payload).hexdigest()


def _ensure_immutable_object(
    store: ObjectStore,
    *,
    bucket: str,
    name: str,
    payload: bytes,
    content_type: str,
) -> StoredObject:
    expected_sha = hashlib.sha256(payload).hexdigest()
    metadata = {"dataforge-sha256": expected_sha}
    try:
        existing = store.get_object(bucket, name)
    except Exception as exc:
        if _is_permission_error(exc):
            raise PermissionDeniedError("active identity cannot read the target GCS object") from exc
        raise
    if existing is None:
        try:
            store.put_object(
                bucket,
                name,
                payload,
                metadata,
                content_type,
                if_generation_match=0,
            )
        except Exception as exc:
            if _is_permission_error(exc):
                raise PermissionDeniedError("active identity cannot create the target GCS object") from exc
            # A request can succeed remotely while its response is lost. Re-read and hash the
            # committed object before treating this as a retry-safe success.
            try:
                existing_after_error = store.get_object(bucket, name)
            except Exception as read_error:
                if _is_permission_error(read_error):
                    raise PermissionDeniedError(
                        "active identity cannot verify the target GCS object after upload"
                    ) from read_error
                raise
            if existing_after_error is None:
                raise CloudAdapterError(f"GCS upload did not commit object {name!r}") from exc
            existing = existing_after_error
        if existing is None:
            try:
                existing = store.get_object(bucket, name)
            except Exception as exc:
                if _is_permission_error(exc):
                    raise PermissionDeniedError(
                        "active identity cannot verify the target GCS object"
                    ) from exc
                raise
    if existing is None:
        raise CloudAdapterError(f"GCS object {name!r} is missing after upload")
    if existing.generation <= 0 or existing.size_bytes != len(payload):
        raise DuplicateObjectError(f"existing GCS object metadata does not match expected size for {name!r}")
    if not existing.crc32c:
        raise DuplicateObjectError(f"existing GCS object {name!r} has no CRC32C checksum")
    if _remote_object_sha256(existing) != expected_sha:
        raise DuplicateObjectError(
            f"GCS object {name!r} already exists with bytes that do not match SHA-256 {expected_sha}"
        )
    recorded_sha = existing.metadata.get("dataforge-sha256")
    if recorded_sha is not None and recorded_sha != expected_sha:
        raise DuplicateObjectError(f"GCS metadata digest disagrees for existing object {name!r}")
    return existing


def _is_permission_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if callable(code):
        try:
            code = code()
        except Exception:
            code = None
    status = getattr(exc, "status_code", None)
    return (
        isinstance(exc, PermissionError)
        or code in {401, 403, "401", "403"}
        or status in {401, 403}
        or type(exc).__name__ in {"Forbidden", "Unauthorized", "PermissionDenied"}
    )


def _portable_manifest(snapshot: ValidatedSnapshot, data: StoredObject) -> bytes:
    body = {
        "schema_version": _CONTRACT_VERSION,
        "active_run_id": snapshot.active_run_id,
        "source_ingest_run_id": snapshot.source_ingest_run_id,
        "source": snapshot.source,
        "source_class": snapshot.source_class,
        "source_sha256": snapshot.source_sha256,
        "parquet_sha256": snapshot.parquet_sha256,
        "row_count": snapshot.row_count,
        "source_value_sha256": snapshot.source_value_sha256,
        "expected_null_counts": snapshot.expected_null_counts,
        "primary_key": list(snapshot.contract.primary_key),
        "parquet_schema": list(snapshot.parquet_schema),
        "logical_schema": [asdict(field) for field in snapshot.contract.fields],
        "gcs_generation": str(data.generation),
        "gcs_size_bytes": data.size_bytes,
        "gcs_crc32c": data.crc32c,
        "checksum_note": "CRC32C is the Cloud Storage transport/object checksum; it is not SHA-256.",
    }
    return (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def preflight_snapshot(
    snapshot: ValidatedSnapshot,
    *,
    project_id: str | None = None,
    expected_project_number: str | None = None,
    bucket: str | None = None,
    dataset: str = "staging",
    region: str = "us-central1",
    bucket_location: str | None = None,
    dataset_location: str | None = None,
) -> dict[str, Any]:
    """Build a network-free plan; supplied target locations are declarations, not live reads."""
    if project_id is not None and not _PROJECT_ID.fullmatch(project_id):
        raise CloudAdapterError("invalid GCP project ID")
    if expected_project_number is not None and (
        not expected_project_number.isdigit() or int(expected_project_number) <= 0
    ):
        raise CloudAdapterError("expected_project_number must be a positive numeric project number")
    if bucket is not None and (not _BUCKET.fullmatch(bucket) or ".." in bucket):
        raise CloudAdapterError("invalid GCS bucket name")
    if dataset != "staging":
        raise CloudAdapterError("Week-4 adapter writes only to the staging dataset")
    if not _REGION.fullmatch(region):
        raise CloudAdapterError("invalid single-region location")
    region_status = "NOT_SUPPLIED"
    if bucket_location is not None or dataset_location is not None:
        if bucket_location is None or dataset_location is None:
            raise LocationMismatchError("provide both bucket and BigQuery locations")
        validate_location_match(region, bucket_location, dataset_location)
        region_status = "DECLARED_MATCH_NOT_LIVE_VERIFIED"
    data_name, manifest_name = _object_names(snapshot)
    return {
        "status": "LOCAL_PREFLIGHT_PASS",
        "cloud_status": "NOT_CHECKED",
        "network_used": False,
        "credentials_checked": False,
        "resource_mutation": False,
        "project_id": project_id,
        "expected_project_number": expected_project_number,
        "bucket": bucket,
        "dataset": dataset,
        "requested_region": region,
        "region_check": region_status,
        "source": snapshot.source,
        "active_run_id": snapshot.active_run_id,
        "source_ingest_run_id": snapshot.source_ingest_run_id,
        "source_sha256": snapshot.source_sha256,
        "parquet_sha256": snapshot.parquet_sha256,
        "row_count": snapshot.row_count,
        "expected_null_counts": snapshot.expected_null_counts,
        "parquet_size_bytes": len(snapshot.parquet_bytes),
        "parquet_schema": list(snapshot.parquet_schema),
        "gcs_object_name": data_name,
        "manifest_object_name": manifest_name,
        "bigquery_raw_table": f"{snapshot.source}_raw_{snapshot.active_run_id}",
        "bigquery_typed_table": f"{snapshot.source}_{snapshot.active_run_id}",
        "typed_schema": [asdict(field) for field in snapshot.contract.fields],
        "note": "GCP authentication, IAM, resource existence, billing, and live region were not checked.",
    }


def transfer_snapshot(
    snapshot: ValidatedSnapshot,
    backend: CloudBackend,
    *,
    project_id: str,
    expected_project_number: str,
    bucket: str,
    dataset: str = "staging",
    region: str = "us-central1",
) -> TransferReceipt:
    """Upload verified bytes create-only, publish a portable manifest, then load typed staging."""
    _validate_target_ids(project_id, bucket, dataset, region, expected_project_number)
    try:
        bucket_location, dataset_location = backend.target_locations(
            project_id, bucket, dataset, expected_project_number
        )
    except Exception as exc:
        if _is_permission_error(exc):
            raise PermissionDeniedError("active identity cannot inspect the GCS bucket or BQ dataset") from exc
        raise
    validate_location_match(region, bucket_location, dataset_location)

    data_name, manifest_name = _object_names(snapshot)
    data = _ensure_immutable_object(
        backend,
        bucket=bucket,
        name=data_name,
        payload=snapshot.parquet_bytes,
        content_type="application/vnd.apache.parquet",
    )
    portable_manifest = _portable_manifest(snapshot, data)
    manifest = _ensure_immutable_object(
        backend,
        bucket=bucket,
        name=manifest_name,
        payload=portable_manifest,
        content_type="application/json",
    )
    gcs_uri = f"gs://{bucket}/{data_name}"
    try:
        load = backend.load_typed_parquet(
            project_id=project_id,
            dataset=dataset,
            region=region,
            source=snapshot.source,
            run_id=snapshot.active_run_id,
            source_sha256=snapshot.source_sha256,
            parquet_sha256=snapshot.parquet_sha256,
            gcs_generation=data.generation,
            gcs_uri=gcs_uri,
            row_count=snapshot.row_count,
            contract=snapshot.contract,
            expected_rows=snapshot.expected_rows,
            raw_value_sha256=raw_value_rows_sha256(
                snapshot.expected_rows, snapshot.contract
            ),
            source_value_sha256=snapshot.source_value_sha256,
            filter_field=snapshot.filter_field,
            filter_value=snapshot.filter_value,
            expected_null_counts=snapshot.expected_null_counts,
        )
    except Exception as exc:
        if _is_permission_error(exc):
            raise PermissionDeniedError("active identity cannot load/query the BigQuery staging dataset") from exc
        raise
    if load.row_count != snapshot.row_count:
        raise DataIntegrityError(
            f"BigQuery staging row count mismatch: expected {snapshot.row_count}, found {load.row_count}"
        )
    if load.filtered_row_count != snapshot.expected_filter_rows:
        raise DataIntegrityError(
            "BigQuery filter query row count mismatch: "
            f"expected {snapshot.expected_filter_rows}, found {load.filtered_row_count}"
        )
    if load.null_counts != snapshot.expected_null_counts:
        raise DataIntegrityError(
            f"BigQuery null-count mismatch: expected {snapshot.expected_null_counts}, "
            f"found {load.null_counts}"
        )
    if load.schema != snapshot.contract.fields:
        raise DataIntegrityError("BigQuery typed table schema does not match the source contract")
    if (
        not load.exact_values_match
        or load.source_value_sha256 != snapshot.source_value_sha256
        or load.bigquery_value_sha256 != snapshot.source_value_sha256
    ):
        raise DataIntegrityError("BigQuery typed row values differ from the validated Parquet source")
    if not load.raw_values_match or load.raw_value_sha256 != raw_value_rows_sha256(
        snapshot.expected_rows, snapshot.contract
    ):
        raise DataIntegrityError("BigQuery raw row values differ from the validated Parquet source")

    try:
        current = backend.get_object(bucket, data_name)
    except Exception as exc:
        if _is_permission_error(exc):
            raise PermissionDeniedError("active identity cannot re-check the GCS object generation") from exc
        raise
    if current is None or current.generation != data.generation:
        raise DataIntegrityError("GCS object generation changed while BigQuery was loading")

    return TransferReceipt(
        source=snapshot.source,
        target_project_number=expected_project_number,
        active_run_id=snapshot.active_run_id,
        source_ingest_run_id=snapshot.source_ingest_run_id,
        source_sha256=snapshot.source_sha256,
        parquet_sha256=snapshot.parquet_sha256,
        row_count=snapshot.row_count,
        gcs_uri=gcs_uri,
        gcs_generation=data.generation,
        gcs_size_bytes=data.size_bytes,
        gcs_crc32c=data.crc32c,
        manifest_uri=f"gs://{bucket}/{manifest_name}",
        manifest_sha256=hashlib.sha256(portable_manifest).hexdigest(),
        manifest_generation=manifest.generation,
        manifest_size_bytes=manifest.size_bytes,
        manifest_crc32c=manifest.crc32c,
        bucket_location=bucket_location,
        dataset_location=dataset_location,
        bigquery=load,
    )
