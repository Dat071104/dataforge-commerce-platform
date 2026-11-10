"""PostgreSQL operational journal, deterministic scenarios, and local extraction.

The simulator deliberately uses a separate DSN and schema from the accepted
snapshot source. Every writer acquires one transaction-scoped advisory lock
before changing operational state or allocating a journal sequence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

SOURCE_IDENTITY = "dataforge-operational-v1"
SCHEMA_VERSION = 1
_LOCK_KEY = (1145458769, 1463897168)
_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MONEY_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]{0,15})\.[0-9]{2}\Z")
_SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_SQL = _ROOT / "labs" / "operational_source" / "001_init.sql"

_ORDER_FIELDS = {
    "order_id", "customer_id", "order_date", "province_id", "status",
    "order_net_amount",
}
_PAYMENT_FIELDS = {
    "payment_id", "order_id", "payment_date", "amount", "status", "method",
}


class SourceContractError(ValueError):
    """An event violates the source contract."""


class IdempotencyConflict(SourceContractError):
    """A change ID was already committed with different event content."""


class SourceStateConflict(SourceContractError):
    """An insert, update, or delete does not fit current operational state."""


class EmptyBatch(SourceContractError):
    """An export was requested for a range with no journal events."""


@dataclass(frozen=True)
class JournalEvent:
    change_seq: int
    source_identity: str
    change_id: str
    source_table: str
    business_key: str
    operation: str
    source_updated_at: str
    business_event_at: str
    schema_version: int
    payload: dict[str, str]
    payload_sha256: str
    event_sha256: str

    def as_dict(self) -> dict[str, Any]:
        """Return a portable event mapping suitable for the independent oracle."""
        return {
            "change_seq": self.change_seq,
            "source_identity": self.source_identity,
            "change_id": self.change_id,
            "source_table": self.source_table,
            "business_key": self.business_key,
            "operation": self.operation,
            "source_updated_at": self.source_updated_at,
            "business_event_at": self.business_event_at,
            "schema_version": self.schema_version,
            "payload": dict(self.payload),
            "payload_sha256": self.payload_sha256,
            "event_sha256": self.event_sha256,
        }


@dataclass(frozen=True)
class SequenceBatch:
    """Events observed in one repeatable-read snapshot."""

    events: tuple[JournalEvent, ...]
    captured_upper_seq: int
    requested_range: tuple[int, int] | None = None
    extraction_mode: str = "normal"

    @property
    def lower_seq(self) -> int | None:
        if self.requested_range is not None:
            return self.requested_range[0]
        return self.events[0].change_seq if self.events else None

    @property
    def upper_seq(self) -> int | None:
        if self.requested_range is not None:
            return self.requested_range[1]
        return self.events[-1].change_seq if self.events else None


@dataclass(frozen=True)
class ExportedBatch:
    batch_id: str
    parquet_path: Path
    manifest_path: Path
    parquet_sha256: str
    row_value_sha256: str
    lower_seq: int
    upper_seq: int
    row_count: int


def operational_database_url() -> str:
    """Return the isolated Week 5 DSN without consulting the baseline `.env`."""
    return os.environ.get(
        "DATAFORGE_OPERATIONAL_DATABASE_URL",
        "postgresql://dataforge_week5:week5_local_only@127.0.0.1:55432/"
        "dataforge_operational",
    )


def _psycopg():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "Operational PostgreSQL support requires psycopg; install the project dependencies"
        ) from exc
    return psycopg


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise SourceContractError("event contains a non-canonical JSON value") from exc


def _normalize_timestamp(value: datetime | str, field: str) -> str:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SourceContractError(f"{field} must be an ISO-8601 timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise SourceContractError(f"{field} must be a timezone-aware datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SourceContractError(f"{field} must include a timezone")
    utc_value = parsed.astimezone(timezone.utc)
    return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _database_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical_money(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _MONEY_PATTERN.fullmatch(value):
        raise SourceContractError(
            f"{field} must be a canonical decimal string with exactly two fractional digits"
        )
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise SourceContractError(f"{field} is not a valid Decimal") from exc
    if not amount.is_finite():
        raise SourceContractError(f"{field} must be finite")
    return value


def _canonical_date(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise SourceContractError(f"{field} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise SourceContractError(f"{field} must be an ISO date string") from exc
    if parsed.isoformat() != value:
        raise SourceContractError(f"{field} must use canonical YYYY-MM-DD form")
    return value


def _validate_payload(
    source_table: str, business_key: str, operation: str, payload: Mapping[str, Any]
) -> dict[str, str]:
    if source_table not in {"orders", "payment_events"}:
        raise SourceContractError("source_table must be 'orders' or 'payment_events'")
    if operation not in {"I", "U", "D"}:
        raise SourceContractError("operation must be I, U, or D")
    if not isinstance(business_key, str) or not business_key or len(business_key) > 512:
        raise SourceContractError("business_key must be a non-empty string of at most 512 characters")
    key_field = "order_id" if source_table == "orders" else "payment_id"
    if not isinstance(payload, Mapping):
        raise SourceContractError("payload must be a JSON object")
    if operation == "D":
        if set(payload) != {key_field} or payload.get(key_field) != business_key:
            raise SourceContractError(f"{source_table} delete payload must contain only {key_field}")
        return {key_field: business_key}

    fields = _ORDER_FIELDS if source_table == "orders" else _PAYMENT_FIELDS
    if set(payload) != fields:
        missing = sorted(fields - set(payload))
        unexpected = sorted(set(payload) - fields)
        raise SourceContractError(
            f"{source_table} post-image fields do not match contract "
            f"(missing={missing}, unexpected={unexpected})"
        )
    if payload.get(key_field) != business_key:
        raise SourceContractError(f"payload {key_field} must equal business_key")

    clean: dict[str, str] = {}
    for field in sorted(fields):
        value = payload[field]
        if not isinstance(value, str):
            if field in {"order_net_amount", "amount"}:
                raise SourceContractError(
                    f"{field} must be a canonical decimal string with exactly two fractional digits"
                )
            raise SourceContractError(f"payload field {field} must be a string")
        if not value:
            raise SourceContractError(f"payload field {field} must not be empty")
        clean[field] = value
    if source_table == "orders":
        _canonical_date(clean["order_date"], "order_date")
        _canonical_money(clean["order_net_amount"], "order_net_amount")
    else:
        _canonical_date(clean["payment_date"], "payment_date")
        _canonical_money(clean["amount"], "amount")
    return clean


def _event_digest(
    source_table: str,
    business_key: str,
    operation: str,
    source_updated_at: str,
    business_event_at: str,
    payload: Mapping[str, str],
) -> str:
    envelope = {
        "source_identity": SOURCE_IDENTITY,
        "schema_version": SCHEMA_VERSION,
        "source_table": source_table,
        "business_key": business_key,
        "operation": operation,
        "source_updated_at": source_updated_at,
        "business_event_at": business_event_at,
        "payload": dict(payload),
    }
    return hashlib.sha256(_canonical_json(envelope).encode("utf-8")).hexdigest()


def _prepare_event(
    source_table: str,
    business_key: str,
    operation: str,
    payload: Mapping[str, Any],
    source_updated_at: datetime | str,
    business_event_at: datetime | str,
    change_id: str | None,
) -> tuple[dict[str, str], str, str, str, str, str]:
    clean_payload = _validate_payload(source_table, business_key, operation, payload)
    source_time = _normalize_timestamp(source_updated_at, "source_updated_at")
    business_time = _normalize_timestamp(business_event_at, "business_event_at")
    if operation != "D":
        date_field = "order_date" if source_table == "orders" else "payment_date"
        if _database_timestamp(business_time).date().isoformat() != clean_payload[date_field]:
            raise SourceContractError(
                f"business_event_at date must match payload {date_field}"
            )
    payload_sha = hashlib.sha256(_canonical_json(clean_payload).encode("utf-8")).hexdigest()
    event_sha = _event_digest(
        source_table, business_key, operation, source_time, business_time, clean_payload
    )
    stable_id = change_id or f"dfw1:{event_sha}"
    if not isinstance(stable_id, str) or not _ID_PATTERN.fullmatch(stable_id):
        raise SourceContractError("change_id must be a stable 1-128 character identifier")
    return clean_payload, source_time, business_time, payload_sha, event_sha, stable_id


def initialize(dsn: str | None = None) -> None:
    """Create the isolated simulator schema and append-only journal tables."""
    psycopg = _psycopg()
    if not _SCHEMA_SQL.is_file():
        raise FileNotFoundError(f"Missing operational source schema: {_SCHEMA_SQL}")
    with psycopg.connect(dsn or operational_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL.read_text(encoding="utf-8"))


def _row_to_event(row: Mapping[str, Any]) -> JournalEvent:
    payload = row["payload"]
    if not isinstance(payload, Mapping):
        raise SourceContractError("stored journal payload is not an object")
    clean, source_time, business_time, payload_sha, event_sha, _ = _prepare_event(
        row["source_table"], row["business_key"], row["operation"], payload,
        row["source_updated_at"], row["business_event_at"], row["change_id"],
    )
    if row["source_identity"] != SOURCE_IDENTITY or row["schema_version"] != SCHEMA_VERSION:
        raise SourceContractError("stored journal row has an unsupported source or schema version")
    if row["payload_sha256"] != payload_sha or row["event_sha256"] != event_sha:
        raise SourceContractError("stored journal row checksum does not match canonical content")
    return JournalEvent(
        change_seq=int(row["change_seq"]),
        source_identity=row["source_identity"],
        change_id=row["change_id"],
        source_table=row["source_table"],
        business_key=row["business_key"],
        operation=row["operation"],
        source_updated_at=source_time,
        business_event_at=business_time,
        schema_version=SCHEMA_VERSION,
        payload=clean,
        payload_sha256=payload_sha,
        event_sha256=event_sha,
    )


def append_change(
    source_table: str,
    business_key: str,
    operation: str,
    payload: Mapping[str, Any],
    *,
    source_updated_at: datetime | str,
    business_event_at: datetime | str,
    change_id: str | None = None,
    dsn: str | None = None,
) -> JournalEvent:
    """Atomically mutate current state and append the matching journal event.

    Exact retries return their original journal row. Reusing a change ID with a
    different canonical event digest fails before any state mutation.
    """
    psycopg = _psycopg()
    from psycopg.types.json import Jsonb

    clean, source_time, business_time, payload_sha, event_sha, stable_id = _prepare_event(
        source_table, business_key, operation, payload,
        source_updated_at, business_event_at, change_id,
    )
    state_table = f"dataforge_operational.{source_table}"
    key_field = "order_id" if source_table == "orders" else "payment_id"
    with psycopg.connect(dsn or operational_database_url()) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", _LOCK_KEY)
            cur.execute(
                "SELECT * FROM dataforge_operational.change_journal WHERE change_id = %s",
                (stable_id,),
            )
            existing = cur.fetchone()
            if existing:
                stored = _row_to_event(existing)
                if stored.event_sha256 != event_sha:
                    raise IdempotencyConflict(
                        f"change_id {stable_id!r} is already bound to different event content"
                    )
                return stored

            if operation == "I":
                if source_table == "orders":
                    values = (
                        clean["order_id"], clean["customer_id"], clean["order_date"],
                        clean["province_id"], clean["status"], Decimal(clean["order_net_amount"]),
                    )
                    cur.execute(
                        f"INSERT INTO {state_table} "
                        "(order_id, customer_id, order_date, province_id, status, order_net_amount) "
                        "VALUES (%s, %s, %s, %s, %s, %s)", values,
                    )
                else:
                    values = (
                        clean["payment_id"], clean["order_id"], clean["payment_date"],
                        Decimal(clean["amount"]), clean["status"], clean["method"],
                    )
                    cur.execute(
                        f"INSERT INTO {state_table} "
                        "(payment_id, order_id, payment_date, amount, status, method) "
                        "VALUES (%s, %s, %s, %s, %s, %s)", values,
                    )
            elif operation == "U":
                if source_table == "orders":
                    cur.execute(
                        f"UPDATE {state_table} SET customer_id = %s, order_date = %s, "
                        "province_id = %s, status = %s, order_net_amount = %s "
                        "WHERE order_id = %s",
                        (clean["customer_id"], clean["order_date"], clean["province_id"],
                         clean["status"], Decimal(clean["order_net_amount"]), business_key),
                    )
                else:
                    cur.execute(
                        f"UPDATE {state_table} SET order_id = %s, payment_date = %s, "
                        "amount = %s, status = %s, method = %s WHERE payment_id = %s",
                        (clean["order_id"], clean["payment_date"], Decimal(clean["amount"]),
                         clean["status"], clean["method"], business_key),
                    )
                if cur.rowcount != 1:
                    raise SourceStateConflict(f"cannot update missing {source_table} key {business_key!r}")
            else:
                cur.execute(
                    f"DELETE FROM {state_table} WHERE {key_field} = %s", (business_key,)
                )
                if cur.rowcount != 1:
                    raise SourceStateConflict(f"cannot delete missing {source_table} key {business_key!r}")

            cur.execute(
                """
                INSERT INTO dataforge_operational.change_journal
                  (source_identity, change_id, source_table, business_key, operation,
                   source_updated_at, business_event_at, schema_version, payload,
                   payload_sha256, event_sha256)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    SOURCE_IDENTITY, stable_id, source_table, business_key, operation,
                    _database_timestamp(source_time), _database_timestamp(business_time),
                    SCHEMA_VERSION, Jsonb(clean), payload_sha, event_sha,
                ),
            )
            return _row_to_event(cur.fetchone())


_EVENT_SELECT = """
    SELECT change_seq, source_identity, change_id, source_table, business_key,
           operation, source_updated_at, business_event_at, schema_version, payload,
           payload_sha256, event_sha256
      FROM dataforge_operational.change_journal
"""


def _read_events(cur, query: str, params: tuple[Any, ...]) -> tuple[JournalEvent, ...]:
    cur.execute(query, params)
    return tuple(_row_to_event(row) for row in cur.fetchall())


def read_normal_batch(
    committed_checkpoint: int,
    *,
    max_events: int = 1000,
    dsn: str | None = None,
) -> SequenceBatch:
    """Read the next bounded sequence batch within one repeatable-read snapshot."""
    if type(committed_checkpoint) is not int or committed_checkpoint < 0:
        raise SourceContractError("committed_checkpoint must be a non-negative integer")
    if type(max_events) is not int or not 1 <= max_events <= 100_000:
        raise SourceContractError("max_events must be between 1 and 100000")
    psycopg = _psycopg()
    with psycopg.connect(dsn or operational_database_url()) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SELECT COALESCE(MAX(change_seq), 0) AS upper_seq "
                        "FROM dataforge_operational.change_journal")
            captured_upper = int(cur.fetchone()["upper_seq"])
            events = _read_events(
                cur,
                _EVENT_SELECT + " WHERE change_seq > %s AND change_seq <= %s "
                "ORDER BY change_seq LIMIT %s",
                (committed_checkpoint, captured_upper, max_events),
            )
    requested_range = (committed_checkpoint + 1, events[-1].change_seq) if events else None
    return SequenceBatch(events, captured_upper, requested_range, "normal")


def read_backfill(
    from_seq: int,
    to_seq: int,
    *,
    max_events: int = 1000,
    dsn: str | None = None,
) -> SequenceBatch:
    """Read an explicit inclusive journal range without changing a checkpoint."""
    if type(from_seq) is not int or from_seq < 1:
        raise SourceContractError("from_seq must be a positive integer")
    if type(to_seq) is not int or to_seq < from_seq:
        raise SourceContractError("to_seq must be an integer greater than or equal to from_seq")
    if type(max_events) is not int or not 1 <= max_events <= 100_000:
        raise SourceContractError("max_events must be between 1 and 100000")
    psycopg = _psycopg()
    with psycopg.connect(dsn or operational_database_url()) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SELECT COALESCE(MAX(change_seq), 0) AS upper_seq "
                        "FROM dataforge_operational.change_journal")
            captured_upper = int(cur.fetchone()["upper_seq"])
            events = _read_events(
                cur,
                _EVENT_SELECT + " WHERE change_seq BETWEEN %s AND %s "
                "ORDER BY change_seq LIMIT %s",
                (from_seq, to_seq, max_events + 1),
            )
            if len(events) > max_events:
                raise SourceContractError(
                    f"backfill range contains more than max_events={max_events} rows"
                )
    return SequenceBatch(events, captured_upper, (from_seq, to_seq), "backfill")


def _wire_event(event: JournalEvent) -> dict[str, Any]:
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


def row_value_sha256(events: Iterable[JournalEvent]) -> str:
    """Hash the shared wire-event contract, excluding source-only envelope fields."""
    from .batch import row_value_sha256 as wire_row_value_sha256

    ordered = tuple(events)
    if tuple(sorted(ordered, key=lambda item: item.change_seq)) != ordered:
        raise SourceContractError("events must be ordered by change_seq")
    wire_events = [
        {
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
        for event in ordered
    ]
    try:
        return wire_row_value_sha256(wire_events)
    except ValueError as exc:
        raise SourceContractError("journal rows do not match the Week-5 wire digest") from exc


def batch_identity(lower_seq: int, upper_seq: int, row_value_digest: str) -> str:
    if lower_seq < 1 or upper_seq < lower_seq or not _SHA_PATTERN.fullmatch(row_value_digest):
        raise SourceContractError("invalid batch identity inputs")
    body = f"{SOURCE_IDENTITY}|{lower_seq}|{upper_seq}|{row_value_digest}"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _arrow_schema():
    from .bronze import EVENT_ARROW_SCHEMA

    return EVENT_ARROW_SCHEMA


def _parquet_bytes(
    events: tuple[JournalEvent, ...], lower_seq: int, upper_seq: int
) -> bytes:
    from .batch import extract_batch
    from .bronze import serialize_batch

    batch = extract_batch(
        (_wire_event(event) for event in events),
        from_seq=lower_seq,
        to_seq=upper_seq,
        max_events=len(events),
    )
    if batch is None:
        raise SourceContractError("cannot serialize an empty source event batch")
    return serialize_batch(batch)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def verify_parquet(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_row_value_sha256: str | None = None,
) -> tuple[JournalEvent, ...]:
    """Verify Parquet bytes, Arrow schema, canonical payloads, and row digests."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    file_path = Path(path)
    data = file_path.read_bytes()
    actual_file_sha = hashlib.sha256(data).hexdigest()
    if expected_sha256 and actual_file_sha != expected_sha256:
        raise SourceContractError("Parquet SHA-256 does not match manifest")
    table = pq.read_table(pa.BufferReader(data))
    if not table.schema.equals(_arrow_schema(), check_metadata=True):
        raise SourceContractError("Parquet schema does not match the source event contract")
    events: list[JournalEvent] = []
    seen_seq: set[int] = set()
    seen_change_id: set[str] = set()
    for record in table.to_pylist():
        from .batch import normalize_event

        try:
            normalized = normalize_event(record)
        except ValueError as exc:
            raise SourceContractError("Parquet row violates the canonical Week-5 wire schema") from exc
        payload = json.loads(normalized["payload"])
        source_time = normalized["source_updated_at"]
        business_time = normalized["business_event_at"]
        payload_sha = normalized["payload_sha256"]
        event_sha = _event_digest(
            normalized["source_table"],
            normalized["business_key"],
            normalized["operation"],
            source_time,
            business_time,
            payload,
        )
        seq = normalized["change_seq"]
        if type(seq) is not int or seq < 1 or seq in seen_seq:
            raise SourceContractError("Parquet change_seq values must be unique positive integers")
        if normalized["change_id"] in seen_change_id:
            raise SourceContractError("Parquet change_id values must be unique")
        seen_seq.add(seq)
        seen_change_id.add(normalized["change_id"])
        events.append(JournalEvent(
            seq, SOURCE_IDENTITY, normalized["change_id"], normalized["source_table"],
            normalized["business_key"], normalized["operation"], source_time, business_time,
            SCHEMA_VERSION, payload, payload_sha, event_sha,
        ))
    ordered = tuple(events)
    if tuple(sorted(ordered, key=lambda item: item.change_seq)) != ordered:
        raise SourceContractError("Parquet events are not in change_seq order")
    if expected_row_value_sha256 and row_value_sha256(ordered) != expected_row_value_sha256:
        raise SourceContractError("Parquet row-value SHA-256 does not match manifest")
    return ordered


def verify_manifest(path: str | Path) -> ExportedBatch:
    """Verify one local COMPLETE manifest and its content-addressed Parquet file."""
    manifest_path = Path(path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceContractError("COMPLETE manifest is missing or invalid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("status") != "COMPLETE":
        raise SourceContractError("manifest status must be COMPLETE")
    required = {
        "schema_version", "batch_id", "lower_seq", "upper_seq", "row_count",
        "row_value_sha256", "parquet_file", "parquet_sha256", "parquet_size_bytes",
        "source_updated_at_min", "source_updated_at_max", "created_at",
        "extraction_mode", "requested_range", "source_identity", "source_run_id",
        "event_seq_min", "event_seq_max", "primary_key_columns", "unique_change_id",
    }
    if not required.issubset(manifest):
        raise SourceContractError(
            f"COMPLETE manifest is missing fields: {sorted(required - set(manifest))}"
        )
    if manifest.get("source_identity") != SOURCE_IDENTITY:
        raise SourceContractError("manifest source identity is invalid")
    if (type(manifest["schema_version"]) is not int
            or manifest["schema_version"] != SCHEMA_VERSION):
        raise SourceContractError("manifest schema_version is unsupported")
    if (not isinstance(manifest["parquet_sha256"], str)
            or not _SHA_PATTERN.fullmatch(manifest["parquet_sha256"])):
        raise SourceContractError("manifest parquet_sha256 is invalid")
    if (not isinstance(manifest["row_value_sha256"], str)
            or not _SHA_PATTERN.fullmatch(manifest["row_value_sha256"])):
        raise SourceContractError("manifest row_value_sha256 is invalid")
    relative_file = manifest.get("parquet_file")
    if not isinstance(relative_file, str) or not relative_file:
        raise SourceContractError("manifest is missing parquet_file")
    parquet_path = (manifest_path.parent / relative_file).resolve()
    try:
        parquet_path.relative_to(manifest_path.parent.resolve())
    except ValueError as exc:
        raise SourceContractError("manifest parquet_file escapes its batch directory") from exc
    if not parquet_path.is_file():
        raise SourceContractError("manifest Parquet artifact is missing")
    if (type(manifest["parquet_size_bytes"]) is not int or manifest["parquet_size_bytes"] < 1
            or parquet_path.stat().st_size != manifest["parquet_size_bytes"]):
        raise SourceContractError("manifest Parquet size does not match artifact")
    if parquet_path.parent.name != f"sha256={manifest['parquet_sha256']}":
        raise SourceContractError("manifest Parquet path is not content-addressed")
    events = verify_parquet(
        parquet_path,
        expected_sha256=manifest.get("parquet_sha256"),
        expected_row_value_sha256=manifest.get("row_value_sha256"),
    )
    if not events:
        raise SourceContractError("COMPLETE manifest cannot describe an empty batch")
    actual_min, actual_max = events[0].change_seq, events[-1].change_seq
    lower, upper = manifest.get("lower_seq"), manifest.get("upper_seq")
    if type(lower) is not int or type(upper) is not int:
        raise SourceContractError("manifest lower_seq and upper_seq must be integers")
    if lower < 1 or upper < lower:
        raise SourceContractError("manifest sequence bounds are invalid")
    if actual_min < lower or actual_max > upper:
        raise SourceContractError("event sequence values fall outside manifest bounds")
    row_digest = row_value_sha256(events)
    expected_batch_id = batch_identity(lower, upper, row_digest)
    try:
        created_at = _normalize_timestamp(manifest["created_at"], "created_at")
        updated_min = _normalize_timestamp(
            manifest["source_updated_at_min"], "source_updated_at_min"
        )
        updated_max = _normalize_timestamp(
            manifest["source_updated_at_max"], "source_updated_at_max"
        )
    except SourceContractError as exc:
        raise SourceContractError("manifest timestamp range or created_at is invalid") from exc
    expected_min = min(item.source_updated_at for item in events)
    expected_max = max(item.source_updated_at for item in events)
    extraction_mode = manifest["extraction_mode"]
    requested_range = manifest["requested_range"]
    if extraction_mode == "normal":
        if requested_range is not None:
            raise SourceContractError("normal extraction manifest cannot declare a backfill range")
    elif extraction_mode == "backfill":
        if (not isinstance(requested_range, list) or len(requested_range) != 2
                or any(type(value) is not int for value in requested_range)
                or requested_range[0] != lower or requested_range[1] != upper):
            raise SourceContractError("backfill manifest requested_range is invalid")
    else:
        raise SourceContractError("manifest extraction_mode must be normal or backfill")
    if (manifest.get("schema_version") != SCHEMA_VERSION
            or type(manifest.get("row_count")) is not int
            or manifest.get("row_count") != len(events)
            or manifest.get("event_seq_min") != actual_min
            or manifest.get("event_seq_max") != actual_max
            or manifest.get("primary_key_columns") != ["change_seq"]
            or manifest.get("unique_change_id") is not True
            or manifest.get("source_run_id") != f"{SOURCE_IDENTITY}:{expected_batch_id}"
            or updated_min != expected_min
            or updated_max != expected_max
            or manifest.get("batch_id") != expected_batch_id):
        raise SourceContractError("manifest bounds, count, schema, or batch ID are inconsistent")
    if created_at != manifest["created_at"]:
        raise SourceContractError("manifest created_at must be canonical UTC")
    return ExportedBatch(
        expected_batch_id, parquet_path, manifest_path,
        manifest["parquet_sha256"], row_digest, lower, upper, len(events),
    )


def export_batch(batch: SequenceBatch | Iterable[JournalEvent], output_dir: str | Path) -> ExportedBatch:
    """Write deterministic typed Parquet then a COMPLETE manifest after verification."""
    events = batch.events if isinstance(batch, SequenceBatch) else tuple(batch)
    events = tuple(events)
    if not events:
        raise EmptyBatch("cannot export an empty source journal batch")
    if tuple(sorted(events, key=lambda item: item.change_seq)) != events:
        raise SourceContractError("events must be ordered by change_seq")
    if len({item.change_seq for item in events}) != len(events):
        raise SourceContractError("batch contains duplicate change_seq values")
    row_digest = row_value_sha256(events)
    lower, upper = events[0].change_seq, events[-1].change_seq
    if isinstance(batch, SequenceBatch) and batch.requested_range is not None:
        lower, upper = batch.requested_range
    if events[0].change_seq < lower or events[-1].change_seq > upper:
        raise SourceContractError("event sequence values fall outside the selected batch bounds")
    batch_id = batch_identity(lower, upper, row_digest)
    payload = _parquet_bytes(events, lower, upper)
    parquet_sha = hashlib.sha256(payload).hexdigest()
    batch_dir = Path(output_dir) / f"batch_id={batch_id}"
    relative_parquet = Path(f"sha256={parquet_sha}") / "changes.parquet"
    parquet_path = batch_dir / relative_parquet
    manifest_path = batch_dir / "COMPLETE.json"

    if parquet_path.exists():
        if hashlib.sha256(parquet_path.read_bytes()).hexdigest() != parquet_sha:
            raise SourceContractError("content-addressed Parquet path contains different bytes")
    else:
        _atomic_write(parquet_path, payload)
    # Verify the final path before a COMPLETE marker can be created.
    verified = verify_parquet(
        parquet_path, expected_sha256=parquet_sha, expected_row_value_sha256=row_digest
    )
    if len(verified) != len(events):
        raise SourceContractError("Parquet verification row count does not match source batch")

    if not manifest_path.exists():
        source_run_id = f"{SOURCE_IDENTITY}:{batch_id}"
        extraction_mode = (
            batch.extraction_mode if isinstance(batch, SequenceBatch) else "normal"
        )
        manifest_range = (
            list((lower, upper)) if extraction_mode == "backfill" else None
        )
        manifest = {
            "status": "COMPLETE",
            "source_identity": SOURCE_IDENTITY,
            "source_run_id": source_run_id,
            "schema_version": SCHEMA_VERSION,
            "batch_id": batch_id,
            "lower_seq": lower,
            "upper_seq": upper,
            "event_seq_min": events[0].change_seq,
            "event_seq_max": events[-1].change_seq,
            "row_count": len(events),
            "row_value_sha256": row_digest,
            "primary_key_columns": ["change_seq"],
            "unique_change_id": True,
            "parquet_file": relative_parquet.as_posix(),
            "parquet_sha256": parquet_sha,
            "parquet_size_bytes": len(payload),
            "source_updated_at_min": min(item.source_updated_at for item in events),
            "source_updated_at_max": max(item.source_updated_at for item in events),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "extraction_mode": extraction_mode,
            "requested_range": manifest_range,
        }
        _atomic_write(
            manifest_path,
            (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            .encode("utf-8"),
        )
    exported = verify_manifest(manifest_path)
    if exported.batch_id != batch_id or exported.parquet_sha256 != parquet_sha:
        raise SourceContractError("existing COMPLETE manifest conflicts with this batch")
    return exported


def seed_source(*, dsn: str | None = None) -> tuple[JournalEvent, ...]:
    """Append the deterministic initial operational seed; safe to retry."""
    baseline = datetime(2026, 10, 10, tzinfo=timezone.utc)
    orders = [
        {
            "order_id": "W5O0001", "customer_id": "W5C0001", "order_date": "2026-10-01",
            "province_id": "VN-HN", "status": "delivered", "order_net_amount": "125000.00",
        },
        {
            "order_id": "W5O0002", "customer_id": "W5C0002", "order_date": "2026-10-02",
            "province_id": "VN-SG", "status": "delivered", "order_net_amount": "250000.00",
        },
        {
            "order_id": "W5O0003", "customer_id": "W5C0003", "order_date": "2026-10-03",
            "province_id": "VN-DN", "status": "processing", "order_net_amount": "75000.00",
        },
    ]
    payments = [
        {
            "payment_id": "W5P0001", "order_id": "W5O0001", "payment_date": "2026-10-02",
            "amount": "125000.00", "status": "success", "method": "bank_transfer",
        },
        {
            "payment_id": "W5P0002", "order_id": "W5O0002", "payment_date": "2026-10-04",
            "amount": "200000.00", "status": "success", "method": "card",
        },
        {
            "payment_id": "W5P0003", "order_id": "W5O0002", "payment_date": "2026-10-04",
            "amount": "10000.00", "status": "failed", "method": "card",
        },
    ]
    events = []
    items = [("orders", row, "order_id") for row in orders]
    items += [("payment_events", row, "payment_id") for row in payments]
    for offset, (table, row, key) in enumerate(items):
        date_key = "order_date" if table == "orders" else "payment_date"
        business_at = datetime.fromisoformat(row[date_key]).replace(tzinfo=timezone.utc)
        events.append(append_change(
            table, row[key], "I", row,
            source_updated_at=baseline.replace(second=offset),
            business_event_at=business_at,
            change_id=f"seed-{row[key]}", dsn=dsn,
        ))
    return tuple(events)


def apply_scenario(scenario_id: str, *, dsn: str | None = None) -> tuple[JournalEvent, ...]:
    """Append deterministic, source-local events for INC-03 through INC-10."""
    utc = timezone.utc

    def event(
        change_id: str, table: str, key: str, operation: str,
        row: Mapping[str, str], source_at: datetime, business_at: datetime,
    ) -> JournalEvent:
        return append_change(
            table, key, operation, row, source_updated_at=source_at,
            business_event_at=business_at, change_id=change_id, dsn=dsn,
        )

    if scenario_id == "INC-03":
        at = datetime(2026, 11, 1, 10, 0, tzinfo=utc)
        order = {
            "order_id": "W5O0001", "customer_id": "W5C0001", "order_date": "2026-10-01",
            "province_id": "VN-HN", "status": "delivered", "order_net_amount": "130000.00",
        }
        payment = {
            "payment_id": "W5P0001", "order_id": "W5O0001", "payment_date": "2026-10-02",
            "amount": "130000.00", "status": "success", "method": "bank_transfer",
        }
        return (
            event("inc03-order-w5o0001", "orders", "W5O0001", "U", order, at,
                  datetime(2026, 10, 1, tzinfo=utc)),
            event("inc03-payment-w5p0001", "payment_events", "W5P0001", "U", payment,
                  at.replace(second=1), datetime(2026, 10, 2, tzinfo=utc)),
        )
    if scenario_id == "INC-04":
        at = datetime(2026, 11, 2, 10, 0, tzinfo=utc)
        return (
            event("inc04-delete-payment-w5p0003", "payment_events", "W5P0003", "D",
                  {"payment_id": "W5P0003"}, at,
                  datetime(2026, 10, 4, tzinfo=utc)),
            event("inc04-delete-order-w5o0002", "orders", "W5O0002", "D",
                  {"order_id": "W5O0002"}, at.replace(second=1),
                  datetime(2026, 10, 2, tzinfo=utc)),
        )
    if scenario_id == "INC-05":
        source_at = datetime(2026, 10, 1, 8, 0, tzinfo=utc)
        order = {
            "order_id": "W5O0001", "customer_id": "W5C0001", "order_date": "2026-09-15",
            "province_id": "VN-HN", "status": "delivered", "order_net_amount": "130000.00",
        }
        payment = {
            "payment_id": "W5P0001", "order_id": "W5O0001", "payment_date": "2026-09-16",
            "amount": "130000.00", "status": "success", "method": "bank_transfer",
        }
        return (
            event("inc05-correct-order-business-date", "orders", "W5O0001", "U", order,
                  source_at, datetime(2026, 9, 15, tzinfo=utc)),
            event("inc05-correct-payment-business-date", "payment_events", "W5P0001", "U",
                  payment, source_at.replace(second=1), datetime(2026, 9, 16, tzinfo=utc)),
        )
    if scenario_id == "INC-06":
        source_at = datetime(2026, 11, 5, 12, 0, tzinfo=utc)
        business_at = datetime(2026, 9, 15, tzinfo=utc)
        events = []
        for suffix, amount in (("a", "132000.00"), ("b", "133000.00")):
            order = {
                "order_id": "W5O0001", "customer_id": "W5C0001", "order_date": "2026-09-15",
                "province_id": "VN-HN", "status": "delivered", "order_net_amount": amount,
            }
            events.append(event(
                f"inc06-order-same-timestamp-{suffix}", "orders", "W5O0001", "U",
                order, source_at, business_at,
            ))
        return tuple(events)
    if scenario_id == "INC-09":
        retroactive_at = datetime(2026, 8, 1, 2, 0, tzinfo=utc)
        business_at = datetime(2026, 8, 1, tzinfo=utc)
        order = {
            "order_id": "W5O0004", "customer_id": "W5C0004", "order_date": "2026-08-01",
            "province_id": "VN-CT", "status": "delivered", "order_net_amount": "50000.00",
        }
        payment = {
            "payment_id": "W5P0004", "order_id": "W5O0004", "payment_date": "2026-08-02",
            "amount": "12500.00", "status": "success", "method": "bank_transfer",
        }
        return (
            event("inc09-retroactive-order", "orders", "W5O0004", "I", order,
                  retroactive_at, business_at),
            event("inc09-retroactive-payment", "payment_events", "W5P0004", "I", payment,
                  retroactive_at.replace(second=1), datetime(2026, 8, 2, tzinfo=utc)),
        )
    if scenario_id == "INC-08":
        payment = {
            "payment_id": "W5P0004", "order_id": "W5O0004", "payment_date": "2026-08-02",
            "amount": "13000.00", "status": "success", "method": "bank_transfer",
        }
        return (event(
            "inc08-after-merge-payment-w5p0004", "payment_events", "W5P0004", "U",
            payment, datetime(2026, 11, 8, 12, 0, tzinfo=utc),
            datetime(2026, 8, 2, tzinfo=utc),
        ),)
    if scenario_id == "INC-10":
        payment = {
            "payment_id": "W5P0004", "order_id": "W5O0004", "payment_date": "2026-08-02",
            "amount": "14000.00", "status": "success", "method": "bank_transfer",
        }
        return (event(
            "inc10-before-publish-payment-w5p0004", "payment_events", "W5P0004", "U",
            payment, datetime(2026, 11, 9, 12, 0, tzinfo=utc),
            datetime(2026, 8, 2, tzinfo=utc),
        ),)
    raise SourceContractError(
        "source simulator supports scenarios INC-01/02 via seed/extraction and "
        "INC-03/04/05/06/08/09/10 via apply_scenario; INC-07 is a cloud-only "
        "quarantine/fail-closed test"
    )
