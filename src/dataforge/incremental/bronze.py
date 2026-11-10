"""Deterministic Parquet and immutable manifest handling for Week-5 batches."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import pyarrow as pa
import pyarrow.parquet as pq

from .batch import (
    BatchValidationError,
    EventBatch,
    canonical_timestamp,
    extract_batch,
    make_batch_id,
    normalize_event,
    row_value_sha256,
)

_MANIFEST_VERSION = 1
_OBJECT_METADATA_PREFIX = "dataforge-week5-"
_MAX_UPLOAD_ATTEMPTS = 3

EVENT_ARROW_SCHEMA = pa.schema(
    [
        pa.field("change_seq", pa.int64(), nullable=False),
        pa.field("change_id", pa.string(), nullable=False),
        pa.field("source_table", pa.string(), nullable=False),
        pa.field("business_key", pa.string(), nullable=False),
        pa.field("operation", pa.string(), nullable=False),
        pa.field("source_updated_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("business_event_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("payload", pa.string(), nullable=False),
        pa.field("payload_sha256", pa.string(), nullable=False),
    ],
    metadata={b"dataforge.contract": b"dataforge-week5-events-v1"},
)


class BronzeArtifactError(RuntimeError):
    """A local or remote Week-5 Bronze artifact failed integrity checks."""


class InjectedUploadFailure(BronzeArtifactError):
    """A deliberate test failure after immutable Parquet upload and before manifest."""


class ImmutableObjectStore(Protocol):
    def get_object(self, bucket: str, name: str) -> Any | None: ...

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

    def get_object_generation(self, bucket: str, name: str, generation: int) -> Any: ...


@dataclass(frozen=True)
class BronzeReceipt:
    bucket: str
    batch_id: str
    object_name: str
    object_generation: int
    parquet_sha256: str
    parquet_size_bytes: int
    row_value_sha256: str
    manifest_name: str
    manifest_generation: int
    manifest_sha256: str
    manifest_size_bytes: int

    @property
    def object_uri(self) -> str:
        return f"gs://{self.bucket}/{self.object_name}"

    @property
    def manifest_uri(self) -> str:
        return f"gs://{self.bucket}/{self.manifest_name}"


def _datetime_for_arrow(value: str) -> datetime:
    normalized = canonical_timestamp(value, "timestamp")
    return datetime.fromisoformat(normalized[:-1] + "+00:00")


def serialize_batch(batch: EventBatch) -> bytes:
    if not batch.events:
        raise BronzeArtifactError("empty event batches cannot be serialized")
    if row_value_sha256(batch.events) != batch.row_value_sha256:
        raise BronzeArtifactError("batch row-value digest changed before Parquet serialization")
    if make_batch_id(
        batch.source_identity, batch.lower_seq, batch.upper_seq, batch.row_value_sha256
    ) != batch.batch_id:
        raise BronzeArtifactError("batch ID does not match its source range and row digest")

    columns = {
        "change_seq": [event["change_seq"] for event in batch.events],
        "change_id": [event["change_id"] for event in batch.events],
        "source_table": [event["source_table"] for event in batch.events],
        "business_key": [event["business_key"] for event in batch.events],
        "operation": [event["operation"] for event in batch.events],
        "source_updated_at": [
            _datetime_for_arrow(event["source_updated_at"]) for event in batch.events
        ],
        "business_event_at": [
            _datetime_for_arrow(event["business_event_at"]) for event in batch.events
        ],
        "schema_version": [str(event["schema_version"]) for event in batch.events],
        "payload": [event["payload"] for event in batch.events],
        "payload_sha256": [event["payload_sha256"] for event in batch.events],
    }
    table = pa.Table.from_pydict(columns, schema=EVENT_ARROW_SCHEMA)
    buffer = io.BytesIO()
    pq.write_table(
        table,
        buffer,
        compression="zstd",
        compression_level=7,
        use_dictionary=False,
        write_statistics=True,
        version="2.6",
        data_page_version="1.0",
        coerce_timestamps="us",
        allow_truncated_timestamps=False,
        use_deprecated_int96_timestamps=False,
    )
    return buffer.getvalue()


def _schema_description() -> list[dict[str, Any]]:
    return [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in EVENT_ARROW_SCHEMA
    ]


def build_manifest(
    batch: EventBatch,
    *,
    object_name: str,
    object_generation: int,
    parquet_bytes: bytes,
) -> dict[str, Any]:
    if not object_name or object_generation <= 0:
        raise BronzeArtifactError("manifest requires the verified immutable object generation")
    source_times = [event["source_updated_at"] for event in batch.events]
    business_times = [event["business_event_at"] for event in batch.events]
    return {
        "status": "COMPLETE",
        "manifest_version": _MANIFEST_VERSION,
        "source_identity": batch.source_identity,
        "source_run_id": f"{batch.source_identity}:{batch.batch_id}",
        "schema_version": batch.schema_version,
        "batch_id": batch.batch_id,
        "lower_seq": batch.lower_seq,
        "upper_seq": batch.upper_seq,
        "event_seq_min": min(event["change_seq"] for event in batch.events),
        "event_seq_max": max(event["change_seq"] for event in batch.events),
        "row_count": batch.row_count,
        "row_value_sha256": batch.row_value_sha256,
        "primary_key_columns": ["change_seq"],
        "unique_change_id": True,
        "parquet": {
            "object_name": object_name,
            "generation": int(object_generation),
            "sha256": hashlib.sha256(parquet_bytes).hexdigest(),
            "size_bytes": len(parquet_bytes),
        },
        "parquet_schema": _schema_description(),
        "timestamp_ranges": {
            "source_updated_at_min": min(source_times),
            "source_updated_at_max": max(source_times),
            "business_event_at_min": min(business_times),
            "business_event_at_max": max(business_times),
        },
    }


def _canonical_manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    return json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _verify_stored_object(
    stored: Any,
    *,
    payload: bytes,
    metadata: dict[str, str],
    expected_generation: int | None = None,
) -> int:
    if stored is None:
        raise BronzeArtifactError("object was not found after create-only upload")
    generation = int(stored.generation)
    if generation <= 0 or (expected_generation is not None and generation != expected_generation):
        raise BronzeArtifactError("stored object generation differs from the requested generation")
    if int(stored.size_bytes) != len(payload):
        raise BronzeArtifactError("stored object size differs from uploaded bytes")
    if stored.payload is None or bytes(stored.payload) != payload:
        raise BronzeArtifactError("stored object bytes differ from uploaded bytes")
    actual_metadata = dict(stored.metadata or {})
    if any(actual_metadata.get(key) != value for key, value in metadata.items()):
        raise BronzeArtifactError("stored object metadata differs from the batch contract")
    return generation


def _create_or_reuse(
    store: ImmutableObjectStore,
    *,
    bucket: str,
    name: str,
    payload: bytes,
    metadata: dict[str, str],
    content_type: str,
) -> int:
    last_error: Exception | None = None
    for _ in range(_MAX_UPLOAD_ATTEMPTS):
        existing = store.get_object(bucket, name)
        if existing is not None:
            generation = int(existing.generation)
            exact = store.get_object_generation(bucket, name, generation)
            return _verify_stored_object(
                exact, payload=payload, metadata=metadata, expected_generation=generation
            )
        try:
            store.put_object(
                bucket,
                name,
                payload,
                metadata,
                content_type,
                if_generation_match=0,
            )
        except Exception as exc:  # response loss and generation conflicts are rechecked
            last_error = exc
        try:
            stored = store.get_object(bucket, name)
        except Exception as exc:
            last_error = exc
            continue
        if stored is not None:
            generation = int(stored.generation)
            exact = store.get_object_generation(bucket, name, generation)
            return _verify_stored_object(
                exact, payload=payload, metadata=metadata, expected_generation=generation
            )
    detail = type(last_error).__name__ if last_error is not None else "no generation was created"
    raise BronzeArtifactError(f"create-only upload was not verified after bounded retries ({detail})")


def upload_batch(
    batch: EventBatch,
    store: ImmutableObjectStore,
    *,
    bucket: str,
    object_prefix: str = "bronze/week5",
    manifest_prefix: str = "manifests/week5",
    fail_after_upload: bool = False,
) -> BronzeReceipt:
    if not bucket or "/" in bucket:
        raise BronzeArtifactError("bucket must be a plain bucket name")
    parquet_bytes = serialize_batch(batch)
    parquet_sha = hashlib.sha256(parquet_bytes).hexdigest()
    object_name = (
        f"{object_prefix.strip('/')}/source={batch.source_identity}/"
        f"sha256={parquet_sha}/part-000.parquet"
    )
    object_metadata = {
        f"{_OBJECT_METADATA_PREFIX}sha256": parquet_sha,
        f"{_OBJECT_METADATA_PREFIX}batch-id": batch.batch_id,
        f"{_OBJECT_METADATA_PREFIX}row-value-sha256": batch.row_value_sha256,
        f"{_OBJECT_METADATA_PREFIX}source": batch.source_identity,
    }
    object_generation = _create_or_reuse(
        store,
        bucket=bucket,
        name=object_name,
        payload=parquet_bytes,
        metadata=object_metadata,
        content_type="application/vnd.apache.parquet",
    )
    if fail_after_upload:
        raise InjectedUploadFailure("INJECTED_AFTER_UPLOAD: Parquet is verified; COMPLETE manifest omitted")
    manifest = build_manifest(
        batch,
        object_name=object_name,
        object_generation=object_generation,
        parquet_bytes=parquet_bytes,
    )
    manifest_bytes = _canonical_manifest_bytes(manifest)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_name = f"{manifest_prefix.strip('/')}/batch_id={batch.batch_id}/manifest.json"
    manifest_metadata = {
        f"{_OBJECT_METADATA_PREFIX}sha256": manifest_sha,
        f"{_OBJECT_METADATA_PREFIX}batch-id": batch.batch_id,
    }
    manifest_generation = _create_or_reuse(
        store,
        bucket=bucket,
        name=manifest_name,
        payload=manifest_bytes,
        metadata=manifest_metadata,
        content_type="application/json",
    )
    return BronzeReceipt(
        bucket=bucket,
        batch_id=batch.batch_id,
        object_name=object_name,
        object_generation=object_generation,
        parquet_sha256=parquet_sha,
        parquet_size_bytes=len(parquet_bytes),
        row_value_sha256=batch.row_value_sha256,
        manifest_name=manifest_name,
        manifest_generation=manifest_generation,
        manifest_sha256=manifest_sha,
        manifest_size_bytes=len(manifest_bytes),
    )


def parse_gs_uri(uri: str) -> tuple[str, str]:
    if not isinstance(uri, str) or not uri.startswith("gs://"):
        raise BronzeArtifactError("manifest URI must use gs://")
    remainder = uri[5:]
    bucket, separator, name = remainder.partition("/")
    if not separator or not bucket or not name or "?" in name or "#" in name:
        raise BronzeArtifactError("manifest URI must identify one immutable GCS object")
    return bucket, name


def load_verified_manifest(
    store: ImmutableObjectStore,
    *,
    manifest_uri: str,
    manifest_generation: int,
) -> tuple[dict[str, Any], bytes, str]:
    if isinstance(manifest_generation, bool) or manifest_generation <= 0:
        raise BronzeArtifactError("manifest generation must be positive")
    bucket, name = parse_gs_uri(manifest_uri)
    stored = store.get_object_generation(bucket, name, manifest_generation)
    if int(stored.generation) != manifest_generation or stored.payload is None:
        raise BronzeArtifactError("requested manifest generation could not be downloaded exactly")
    payload = bytes(stored.payload)
    if len(payload) != int(stored.size_bytes):
        raise BronzeArtifactError("manifest bytes do not match the recorded object size")
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BronzeArtifactError("manifest is not valid UTF-8 JSON") from exc
    expected_keys = {
        "status",
        "manifest_version",
        "source_identity",
        "source_run_id",
        "schema_version",
        "batch_id",
        "lower_seq",
        "upper_seq",
        "event_seq_min",
        "event_seq_max",
        "row_count",
        "row_value_sha256",
        "primary_key_columns",
        "unique_change_id",
        "parquet",
        "parquet_schema",
        "timestamp_ranges",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise BronzeArtifactError("manifest fields differ from the COMPLETE schema")
    if manifest["status"] != "COMPLETE" or manifest["manifest_version"] != _MANIFEST_VERSION:
        raise BronzeArtifactError("manifest is incomplete or uses an unknown version")
    if manifest["source_identity"] != "dataforge-operational-v1" or manifest["schema_version"] != 1:
        raise BronzeArtifactError("manifest source identity or event schema is unsupported")
    if manifest["source_run_id"] != f"{manifest['source_identity']}:{manifest['batch_id']}":
        raise BronzeArtifactError("manifest source_run_id does not match the batch identity")
    if manifest["primary_key_columns"] != ["change_seq"] or manifest["unique_change_id"] is not True:
        raise BronzeArtifactError("manifest primary-key or unique change-ID controls are invalid")
    if not isinstance(manifest["parquet"], dict) or set(manifest["parquet"]) != {
        "object_name",
        "generation",
        "sha256",
        "size_bytes",
    }:
        raise BronzeArtifactError("manifest Parquet reference is malformed")
    if not isinstance(manifest["timestamp_ranges"], dict) or set(manifest["timestamp_ranges"]) != {
        "source_updated_at_min",
        "source_updated_at_max",
        "business_event_at_min",
        "business_event_at_max",
    }:
        raise BronzeArtifactError("manifest timestamp ranges are malformed")
    if dict(stored.metadata or {}).get(f"{_OBJECT_METADATA_PREFIX}sha256") != hashlib.sha256(
        payload
    ).hexdigest():
        raise BronzeArtifactError("manifest object metadata SHA-256 mismatch")
    if dict(stored.metadata or {}).get(f"{_OBJECT_METADATA_PREFIX}batch-id") != manifest[
        "batch_id"
    ]:
        raise BronzeArtifactError("manifest object metadata batch ID mismatch")
    return manifest, payload, hashlib.sha256(payload).hexdigest()


def validate_parquet_bytes(
    parquet_bytes: bytes,
    *,
    manifest: Mapping[str, Any],
    manifest_bucket: str,
    store: ImmutableObjectStore,
    downloaded_object: Any | None = None,
) -> EventBatch:
    parquet_ref = manifest["parquet"]
    if not isinstance(parquet_ref, Mapping):
        raise BronzeArtifactError("manifest Parquet reference is malformed")
    try:
        generation = int(parquet_ref["generation"])
        expected_size = int(parquet_ref["size_bytes"])
        expected_sha = str(parquet_ref["sha256"])
        object_name = str(parquet_ref["object_name"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BronzeArtifactError("manifest Parquet reference is incomplete") from exc
    if generation <= 0 or expected_size <= 0:
        raise BronzeArtifactError("manifest Parquet generation and size must be positive")
    if not object_name.endswith(f"sha256={expected_sha}/part-000.parquet"):
        raise BronzeArtifactError("Parquet object name is not content-addressed by its SHA-256")
    if len(parquet_bytes) != expected_size:
        raise BronzeArtifactError("Parquet size differs from COMPLETE manifest")
    actual_sha = hashlib.sha256(parquet_bytes).hexdigest()
    if actual_sha != expected_sha:
        raise BronzeArtifactError("Parquet SHA-256 mismatch")
    if manifest.get("source_run_id") != f"{manifest.get('source_identity')}:{manifest.get('batch_id')}":
        raise BronzeArtifactError("COMPLETE manifest source_run_id differs from batch identity")
    if manifest.get("primary_key_columns") != ["change_seq"] or manifest.get(
        "unique_change_id"
    ) is not True:
        raise BronzeArtifactError("COMPLETE manifest uniqueness controls differ from event schema")

    stored = downloaded_object or store.get_object_generation(
        manifest_bucket, object_name, generation
    )
    if int(stored.generation) != generation or int(stored.size_bytes) != expected_size:
        raise BronzeArtifactError("downloaded Parquet generation or size differs from manifest")
    if stored.payload is None or bytes(stored.payload) != parquet_bytes:
        raise BronzeArtifactError("downloaded Parquet generation bytes differ from verified bytes")
    expected_object_metadata = {
        f"{_OBJECT_METADATA_PREFIX}sha256": expected_sha,
        f"{_OBJECT_METADATA_PREFIX}batch-id": str(manifest["batch_id"]),
        f"{_OBJECT_METADATA_PREFIX}row-value-sha256": str(manifest["row_value_sha256"]),
        f"{_OBJECT_METADATA_PREFIX}source": str(manifest["source_identity"]),
    }
    actual_metadata = dict(stored.metadata or {})
    if any(actual_metadata.get(key) != value for key, value in expected_object_metadata.items()):
        raise BronzeArtifactError("Parquet object metadata differs from COMPLETE manifest")

    try:
        table = pq.read_table(io.BytesIO(parquet_bytes))
    except Exception as exc:
        raise BronzeArtifactError("Parquet bytes cannot be decoded") from exc
    if not table.schema.equals(EVENT_ARROW_SCHEMA, check_metadata=True):
        raise BronzeArtifactError("Parquet schema differs from the explicit event schema")
    if manifest.get("parquet_schema") != _schema_description():
        raise BronzeArtifactError("manifest schema differs from the explicit event schema")
    rows = table.to_pylist()
    events: list[dict[str, Any]] = []
    for row in rows:
        event = dict(row)
        event["source_updated_at"] = canonical_timestamp(
            event["source_updated_at"], "source_updated_at"
        )
        event["business_event_at"] = canonical_timestamp(
            event["business_event_at"], "business_event_at"
        )
        try:
            event["schema_version"] = int(event["schema_version"])
        except (TypeError, ValueError) as exc:
            raise BronzeArtifactError("Parquet schema_version is not an integer string") from exc
        try:
            events.append(normalize_event(event))
        except BatchValidationError as exc:
            raise BronzeArtifactError("Parquet event payload or schema version is invalid") from exc

    if not events:
        raise BronzeArtifactError("COMPLETE manifest cannot describe an empty batch")
    if len(events) != int(manifest["row_count"]):
        raise BronzeArtifactError("Parquet row count differs from COMPLETE manifest")
    if [event["change_seq"] for event in events] != sorted(
        event["change_seq"] for event in events
    ):
        raise BronzeArtifactError("Parquet events are not ordered by change_seq")
    event_seq_min = events[0]["change_seq"]
    event_seq_max = events[-1]["change_seq"]
    if (
        event_seq_min != int(manifest["event_seq_min"])
        or event_seq_max != int(manifest["event_seq_max"])
        or event_seq_min < int(manifest["lower_seq"])
        or event_seq_max > int(manifest["upper_seq"])
    ):
        raise BronzeArtifactError("Parquet event sequence min/max differ from COMPLETE manifest")
    digest = row_value_sha256(events)
    if digest != manifest["row_value_sha256"]:
        raise BronzeArtifactError("Parquet row-value digest differs from COMPLETE manifest")
    try:
        batch = extract_batch(
            events,
            from_seq=int(manifest["lower_seq"]),
            to_seq=int(manifest["upper_seq"]),
            max_events=max(1, len(events)),
        )
    except (BatchValidationError, ValueError) as exc:
        raise BronzeArtifactError("Parquet events violate the manifest sequence range") from exc
    if batch is None or batch.batch_id != manifest["batch_id"]:
        raise BronzeArtifactError("batch ID differs from COMPLETE manifest")
    if batch.row_value_sha256 != digest:
        raise BronzeArtifactError("batch row-value digest changed during validation")
    timestamp_ranges = {
        "source_updated_at_min": min(event["source_updated_at"] for event in events),
        "source_updated_at_max": max(event["source_updated_at"] for event in events),
        "business_event_at_min": min(event["business_event_at"] for event in events),
        "business_event_at_max": max(event["business_event_at"] for event in events),
    }
    if dict(manifest["timestamp_ranges"]) != timestamp_ranges:
        raise BronzeArtifactError("Parquet timestamp ranges differ from COMPLETE manifest")
    return batch


def download_verified_batch(
    store: ImmutableObjectStore,
    *,
    manifest_uri: str,
    manifest_generation: int,
) -> tuple[EventBatch, dict[str, Any], str, bytes]:
    manifest, _, manifest_sha = load_verified_manifest(
        store, manifest_uri=manifest_uri, manifest_generation=manifest_generation
    )
    bucket, _ = parse_gs_uri(manifest_uri)
    parquet_ref = manifest["parquet"]
    try:
        object_generation = int(parquet_ref["generation"])
        object_name = str(parquet_ref["object_name"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BronzeArtifactError("manifest Parquet generation is malformed") from exc
    stored = store.get_object_generation(bucket, object_name, object_generation)
    if stored.payload is None:
        raise BronzeArtifactError("exact Parquet object generation returned no bytes")
    parquet_bytes = bytes(stored.payload)
    batch = validate_parquet_bytes(
        parquet_bytes,
        manifest=manifest,
        manifest_bucket=bucket,
        store=store,
        downloaded_object=stored,
    )
    return batch, manifest, manifest_sha, parquet_bytes
