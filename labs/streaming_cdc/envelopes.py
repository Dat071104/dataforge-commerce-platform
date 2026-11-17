"""Decode Confluent-framed Debezium Avro records into CDC operations."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Mapping

from labs.streaming_cdc.operations import (
    DEBEZIUM_OPERATIONS,
    OP_DELETE,
    OP_TOMBSTONE,
)


@dataclass(frozen=True)
class DecodedChange:
    """A normalized Debezium operation before it reaches a sink."""

    operation: str
    op_code: str | None
    key: Any
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    source_lsn: int | None
    transaction_order: int | None
    ts_ms: int | None
    source_ts_ms: int | None


def unpack_confluent_frame(value: bytes | bytearray | memoryview | None) -> tuple[int, bytes] | None:
    """Remove Confluent's magic byte and 4-byte schema ID from an Avro value."""
    if value is None:
        return None
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("Confluent Avro values must be bytes or null tombstones")
    frame = bytes(value)
    if len(frame) < 6:
        raise ValueError("Confluent Avro frame must include a schema ID and payload")
    if frame[0] != 0:
        raise ValueError("Confluent Avro magic byte must be 0")
    schema_id = int.from_bytes(frame[1:5], byteorder="big", signed=False)
    if schema_id == 0:
        raise ValueError("Confluent Avro schema ID must be positive")
    return schema_id, frame[5:]


def _optional_nonnegative_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative integer") from exc
    if parsed < 0 or str(value).strip() not in {str(parsed), f"+{parsed}"}:
        raise ValueError(f"{field} must be a non-negative integer")
    return parsed


def decode_debezium_envelope(
    envelope: Mapping[str, Any] | None, *, key: Any = None
) -> DecodedChange:
    """Normalize Debezium c/u/d/r envelopes and Kafka null-valued tombstones."""
    if envelope is None:
        return DecodedChange(
            operation="tombstone",
            op_code=None,
            key=key,
            before=None,
            after=None,
            source_lsn=None,
            transaction_order=None,
            ts_ms=None,
            source_ts_ms=None,
        )
    if not isinstance(envelope, Mapping):
        raise TypeError("Debezium envelope must be a mapping or a null tombstone")

    op_code = envelope.get("op")
    if op_code not in DEBEZIUM_OPERATIONS:
        raise ValueError(f"unsupported Debezium operation: {op_code!r}")

    before = envelope.get("before")
    after = envelope.get("after")
    if before is not None and not isinstance(before, Mapping):
        raise ValueError("Debezium before must be a record or null")
    if after is not None and not isinstance(after, Mapping):
        raise ValueError("Debezium after must be a record or null")
    if op_code == "d" and before is None:
        raise ValueError("Debezium delete operation must include before")
    if op_code != "d" and after is None:
        raise ValueError(f"Debezium {op_code!r} operation must include after")

    source = envelope.get("source") or {}
    transaction = envelope.get("transaction") or {}
    if not isinstance(source, Mapping):
        raise ValueError("Debezium source metadata must be a record")
    if not isinstance(transaction, Mapping):
        raise ValueError("Debezium transaction metadata must be a record")

    return DecodedChange(
        operation=DEBEZIUM_OPERATIONS[op_code],
        op_code=str(op_code),
        key=key,
        before=before,
        after=after,
        source_lsn=_optional_nonnegative_int(source.get("lsn"), "source.lsn"),
        transaction_order=_optional_nonnegative_int(
            transaction.get("total_order"), "transaction.total_order"
        ),
        ts_ms=_optional_nonnegative_int(envelope.get("ts_ms"), "ts_ms"),
        source_ts_ms=_optional_nonnegative_int(source.get("ts_ms"), "source.ts_ms"),
    )


def to_order_change_row(change: DecodedChange) -> dict[str, Any]:
    """Map a decoded envelope to the shared Silver MERGE vocabulary."""
    if change.operation == OP_TOMBSTONE:
        order_id = change.key.get("order_id") if isinstance(change.key, Mapping) else change.key
        return {
            "order_id": order_id,
            "op": OP_TOMBSTONE,
            "source_lsn": None,
            "transaction_order": None,
            "source_ts_ms": None,
        }

    row = change.before if change.operation == OP_DELETE else change.after
    if row is None:
        raise ValueError(f"{change.operation!r} change has no source row")
    return {
        **row,
        "op": change.operation,
        "source_lsn": change.source_lsn,
        "transaction_order": change.transaction_order,
        "source_ts_ms": change.source_ts_ms,
    }


def decode_confluent_avro(
    value: bytes | bytearray | memoryview | None,
    *,
    schemas_by_id: Mapping[int, Mapping[str, Any]],
    key: Any = None,
) -> DecodedChange:
    """Decode a framed Avro envelope using its schema ID and normalize it."""
    frame = unpack_confluent_frame(value)
    if frame is None:
        return decode_debezium_envelope(None, key=key)
    schema_id, payload = frame
    try:
        schema = schemas_by_id[schema_id]
    except KeyError as exc:
        raise KeyError(f"schema ID {schema_id} is not in the provided registry map") from exc

    try:
        from fastavro import schemaless_reader
    except ImportError as exc:  # pragma: no cover - environment-specific import
        raise RuntimeError("fastavro is required to decode Confluent Avro frames") from exc

    decoded = schemaless_reader(BytesIO(payload), schema)
    return decode_debezium_envelope(decoded, key=key)
