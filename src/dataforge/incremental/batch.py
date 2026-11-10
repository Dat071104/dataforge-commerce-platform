"""Pure, deterministic journal validation and bounded batch selection."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

SOURCE_IDENTITY = "dataforge-operational-v1"
EVENT_SCHEMA_VERSION = 1
MAX_BATCH_EVENTS = 10_000
MAX_RUN_ATTEMPT = 1
EVENT_KEYS = (
    "change_seq",
    "change_id",
    "source_table",
    "business_key",
    "operation",
    "source_updated_at",
    "business_event_at",
    "schema_version",
    "payload",
    "payload_sha256",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MONEY = re.compile(r"^-?(?:0|[1-9][0-9]{0,15})\.[0-9]{2}$")
_ORDER_FIELDS = {
    "order_id",
    "customer_id",
    "order_date",
    "province_id",
    "status",
    "order_net_amount",
}
_PAYMENT_FIELDS = {
    "payment_id",
    "order_id",
    "payment_date",
    "amount",
    "status",
    "method",
}


class BatchValidationError(ValueError):
    """An event or requested range violates the Week-5 source contract."""


def make_run_id(execution_id: str, attempt: int) -> str:
    """Derive an opaque stable task-attempt ID from the Cloud Run execution."""
    if not execution_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", execution_id):
        raise BatchValidationError("Cloud Run execution ID is missing or malformed")
    if isinstance(attempt, bool) or not isinstance(attempt, int):
        raise BatchValidationError("Cloud Run task attempt must be an integer")
    if not 0 <= attempt <= MAX_RUN_ATTEMPT:
        raise BatchValidationError("Cloud Run task attempt exceeds the single-retry limit")
    return hashlib.sha256(f"{execution_id}|{attempt}".encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class EventBatch:
    source_identity: str
    schema_version: int
    lower_seq: int
    upper_seq: int
    batch_id: str
    row_value_sha256: str
    events: tuple[dict[str, Any], ...]

    @property
    def row_count(self) -> int:
        return len(self.events)


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise BatchValidationError("value is not valid canonical JSON") from exc


def canonical_timestamp(value: Any, field_name: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise BatchValidationError(f"{field_name} must be an ISO-8601 timestamp") from exc
    else:
        raise BatchValidationError(f"{field_name} must be an ISO-8601 timestamp")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BatchValidationError(f"{field_name} must include a UTC timezone")
    if parsed.utcoffset().total_seconds() != 0:
        raise BatchValidationError(f"{field_name} must be expressed in UTC")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BatchValidationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise BatchValidationError(f"{field_name} must not contain outer whitespace")
    return value


def _validate_payload(source_table: str, operation: str, business_key: str, payload: Any) -> str:
    if isinstance(payload, str):
        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise BatchValidationError("payload contains a duplicate JSON object key")
                result[key] = value
            return result

        try:
            payload_value = json.loads(
                payload,
                parse_float=Decimal,
                parse_int=int,
                object_pairs_hook=unique_object,
            )
        except (json.JSONDecodeError, InvalidOperation) as exc:
            raise BatchValidationError("payload must contain valid JSON") from exc
    elif isinstance(payload, Mapping):
        payload_value = dict(payload)
    else:
        raise BatchValidationError("payload must be a JSON object")

    if not isinstance(payload_value, dict):
        raise BatchValidationError("payload must be a JSON object")
    if any(isinstance(item, float) for item in _walk(payload_value)):
        raise BatchValidationError("payload must not contain binary floating-point values")

    if source_table == "orders":
        key_field = "order_id"
        expected = {key_field} if operation == "D" else _ORDER_FIELDS
        money_fields = {"order_net_amount"}
        date_fields = {"order_date"}
    else:
        key_field = "payment_id"
        expected = {key_field} if operation == "D" else _PAYMENT_FIELDS
        money_fields = {"amount"}
        date_fields = {"payment_date"}

    if set(payload_value) != expected:
        raise BatchValidationError(
            f"{source_table} {operation} payload keys differ from the source contract"
        )
    if _required_string(payload_value[key_field], key_field) != business_key:
        raise BatchValidationError("payload business key does not match journal business_key")

    for field in expected - {key_field}:
        value = payload_value[field]
        if not isinstance(value, str) or not value:
            raise BatchValidationError(f"payload field {field!r} must be a non-empty string")
        if field in money_fields:
            if not _MONEY.fullmatch(value):
                raise BatchValidationError(f"payload field {field!r} must be NUMERIC(18,2) text")
            try:
                amount = Decimal(value)
            except InvalidOperation as exc:
                raise BatchValidationError(f"payload field {field!r} is not a decimal") from exc
            if amount.as_tuple().exponent != -2:
                raise BatchValidationError(f"payload field {field!r} must have scale two")
        if field in date_fields:
            try:
                parsed_date = date.fromisoformat(value)
            except ValueError as exc:
                raise BatchValidationError(f"payload field {field!r} must be an ISO date") from exc
            if parsed_date.isoformat() != value:
                raise BatchValidationError(f"payload field {field!r} must be YYYY-MM-DD")

    canonical_payload = canonical_json(payload_value)
    if isinstance(payload, str) and payload != canonical_payload:
        raise BatchValidationError("payload text must use canonical compact sorted JSON")
    return canonical_payload


def _walk(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield key
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)
    else:
        yield value


def normalize_event(event: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(event, Mapping):
        raise BatchValidationError("each journal event must be a mapping")
    if set(event) != set(EVENT_KEYS):
        raise BatchValidationError("journal event keys differ from the documented event schema")

    change_seq = event["change_seq"]
    if isinstance(change_seq, bool) or not isinstance(change_seq, int) or change_seq <= 0:
        raise BatchValidationError("change_seq must be a positive INT64")
    if change_seq > 9_223_372_036_854_775_807:
        raise BatchValidationError("change_seq exceeds INT64")

    change_id = _required_string(event["change_id"], "change_id")
    if len(change_id) > 128:
        raise BatchValidationError("change_id exceeds the 128-character source limit")
    source_table = _required_string(event["source_table"], "source_table")
    if source_table not in {"orders", "payment_events"}:
        raise BatchValidationError("source_table must be orders or payment_events")
    business_key = _required_string(event["business_key"], "business_key")
    if len(business_key) > 256:
        raise BatchValidationError("business_key exceeds the 256-character source limit")
    operation = _required_string(event["operation"], "operation")
    if operation not in {"I", "U", "D"}:
        raise BatchValidationError("operation must be I, U, or D")

    schema_version = event["schema_version"]
    if isinstance(schema_version, bool) or schema_version not in {1, "1"}:
        raise BatchValidationError("schema_version must be the supported integer 1")
    payload = _validate_payload(source_table, operation, business_key, event["payload"])
    if operation != "D":
        payload_value = json.loads(payload)
        date_field = "order_date" if source_table == "orders" else "payment_date"
        business_date = datetime.fromisoformat(
            canonical_timestamp(event["business_event_at"], "business_event_at").replace(
                "Z", "+00:00"
            )
        ).date().isoformat()
        if business_date != payload_value[date_field]:
            raise BatchValidationError(
                f"business_event_at date must match payload {date_field}"
            )
    payload_sha256 = _required_string(event["payload_sha256"], "payload_sha256")
    if not _SHA256.fullmatch(payload_sha256):
        raise BatchValidationError("payload_sha256 must be lowercase SHA-256 hex")
    actual_payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if payload_sha256 != actual_payload_sha256:
        raise BatchValidationError("payload_sha256 does not match canonical payload bytes")

    return {
        "change_seq": change_seq,
        "change_id": change_id,
        "source_table": source_table,
        "business_key": business_key,
        "operation": operation,
        "source_updated_at": canonical_timestamp(event["source_updated_at"], "source_updated_at"),
        "business_event_at": canonical_timestamp(event["business_event_at"], "business_event_at"),
        "schema_version": EVENT_SCHEMA_VERSION,
        "payload": payload,
        "payload_sha256": payload_sha256,
    }


def row_value_sha256(events: Iterable[Mapping[str, Any]]) -> str:
    normalized = tuple(normalize_event(event) for event in events)
    ordered = sorted(normalized, key=lambda item: item["change_seq"])
    seen_seq: set[int] = set()
    seen_ids: set[str] = set()
    encoded_rows = []
    for event in ordered:
        if event["change_seq"] in seen_seq:
            raise BatchValidationError("duplicate change_seq in event rows")
        if event["change_id"] in seen_ids:
            raise BatchValidationError("duplicate change_id in event rows")
        seen_seq.add(event["change_seq"])
        seen_ids.add(event["change_id"])
        canonical = {
            key: event[key] if key in {"change_seq", "schema_version"} else str(event[key])
            for key in EVENT_KEYS
        }
        encoded_rows.append(canonical_json(canonical).encode("utf-8"))
    return hashlib.sha256(b"\n".join(encoded_rows)).hexdigest()


def make_batch_id(
    source_identity: str, lower_seq: int, upper_seq: int, row_digest: str
) -> str:
    if source_identity != SOURCE_IDENTITY:
        raise BatchValidationError("source identity differs from the Week-5 contract")
    if not _SHA256.fullmatch(row_digest):
        raise BatchValidationError("row-value digest must be lowercase SHA-256 hex")
    identity = f"{source_identity}|{lower_seq}|{upper_seq}|{row_digest}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def extract_batch(
    events: Iterable[Mapping[str, Any]],
    *,
    checkpoint: int = 0,
    max_events: int = 1_000,
    from_seq: int | None = None,
    to_seq: int | None = None,
    captured_upper_seq: int | None = None,
) -> EventBatch | None:
    """Validate and select one bounded range from an iterable journal snapshot.

    When explicit bounds are supplied, the complete requested range must fit under
    ``max_events``; this prevents a backfill request from being silently shortened.
    Normal extraction begins at ``checkpoint + 1`` and uses a caller-captured source
    snapshot upper bound when provided.
    """
    if isinstance(max_events, bool) or not isinstance(max_events, int):
        raise BatchValidationError("max_events must be an integer")
    if not 1 <= max_events <= MAX_BATCH_EVENTS:
        raise BatchValidationError(f"max_events must be between 1 and {MAX_BATCH_EVENTS}")
    if isinstance(checkpoint, bool) or not isinstance(checkpoint, int) or checkpoint < 0:
        raise BatchValidationError("checkpoint must be a non-negative integer")
    if (from_seq is None) != (to_seq is None):
        raise BatchValidationError("from_seq and to_seq must be specified together")
    explicit_range = from_seq is not None
    if explicit_range:
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (from_seq, to_seq)):
            raise BatchValidationError("explicit sequence bounds must be integers")
        if from_seq is None or to_seq is None or from_seq <= 0 or to_seq < from_seq:
            raise BatchValidationError("explicit range must satisfy 1 <= from_seq <= to_seq")
        lower_bound, upper_bound = from_seq, to_seq
    else:
        if captured_upper_seq is not None and (
            isinstance(captured_upper_seq, bool)
            or not isinstance(captured_upper_seq, int)
            or captured_upper_seq < 0
        ):
            raise BatchValidationError("captured_upper_seq must be a non-negative integer")
        lower_bound = checkpoint + 1
        upper_bound = captured_upper_seq

    selected: list[dict[str, Any]] = []
    seen_seq: set[int] = set()
    seen_ids: set[str] = set()
    observed_max = 0
    for raw_event in events:
        normalized = normalize_event(raw_event)
        seq = normalized["change_seq"]
        observed_max = max(observed_max, seq)
        if seq in seen_seq or normalized["change_id"] in seen_ids:
            if not explicit_range or (lower_bound <= seq <= upper_bound):
                raise BatchValidationError("duplicate change_seq or change_id in selected events")
        if not explicit_range and seq > checkpoint and (
            captured_upper_seq is None or seq <= captured_upper_seq
        ):
            if seq in seen_seq or normalized["change_id"] in seen_ids:
                raise BatchValidationError("duplicate change_seq or change_id in selected events")
            selected.append(normalized)
            seen_seq.add(seq)
            seen_ids.add(normalized["change_id"])
        elif explicit_range and lower_bound <= seq <= upper_bound:
            selected.append(normalized)
            seen_seq.add(seq)
            seen_ids.add(normalized["change_id"])

    if not explicit_range:
        upper_bound = min(
            captured_upper_seq if captured_upper_seq is not None else observed_max,
            observed_max if captured_upper_seq is None else captured_upper_seq,
        )
    selected.sort(key=lambda item: item["change_seq"])
    if explicit_range and len(selected) > max_events:
        raise BatchValidationError("explicit range exceeds max_events")
    if not explicit_range:
        selected = selected[:max_events]
        if not selected:
            return None
        upper_bound = selected[-1]["change_seq"]
    elif not selected:
        return None

    digest = row_value_sha256(selected)
    batch_id = make_batch_id(SOURCE_IDENTITY, lower_bound, upper_bound, digest)
    return EventBatch(
        source_identity=SOURCE_IDENTITY,
        schema_version=EVENT_SCHEMA_VERSION,
        lower_seq=lower_bound,
        upper_seq=upper_bound,
        batch_id=batch_id,
        row_value_sha256=digest,
        events=tuple(selected),
    )
