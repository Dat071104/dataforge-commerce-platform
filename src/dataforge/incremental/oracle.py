"""Independent Decimal replay of the operational source journal.

This module intentionally does not import the production source writer,
extractor, or any warehouse update/merge code. It reads portable event mappings
or the exported Parquet rows and reconstructs source-as-of state directly.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

SOURCE_IDENTITY = "dataforge-operational-v1"
SCHEMA_VERSION = 1
_SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MONEY_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]{0,15})\.[0-9]{2}\Z")
_ORDER_FIELDS = {
    "order_id", "customer_id", "order_date", "province_id", "status",
    "order_net_amount",
}
_PAYMENT_FIELDS = {
    "payment_id", "order_id", "payment_date", "amount", "status", "method",
}


class OracleContractError(ValueError):
    """The exported journal cannot be replayed under the source contract."""


@dataclass(frozen=True)
class OrderState:
    order_id: str
    customer_id: str
    order_date: str
    province_id: str
    status: str
    order_net_amount: Decimal
    is_deleted: bool
    effective_seq: int
    change_id: str
    payload_sha256: str


@dataclass(frozen=True)
class PaymentState:
    payment_id: str
    order_id: str
    payment_date: str
    amount: Decimal
    status: str
    method: str
    is_deleted: bool
    effective_seq: int
    change_id: str
    payload_sha256: str


@dataclass(frozen=True)
class OrderControl:
    order_id: str
    order_date: str
    order_is_deleted: bool
    order_status: str
    delivered_sales_proxy: Decimal
    collections: Decimal
    collection_variance: Decimal | None
    effective_seq: int
    change_id: str
    payload_sha256: str


@dataclass(frozen=True)
class ReplayResult:
    orders: dict[str, OrderState]
    payment_events: dict[str, PaymentState]
    controls: dict[str, OrderControl]

    @property
    def order_count(self) -> int:
        return len(self.orders)

    @property
    def active_order_count(self) -> int:
        return sum(not row.is_deleted for row in self.orders.values())

    @property
    def payment_count(self) -> int:
        return len(self.payment_events)

    @property
    def active_payment_count(self) -> int:
        return sum(not row.is_deleted for row in self.payment_events.values())

    @property
    def delivered_sales_total(self) -> Decimal:
        return sum((row.delivered_sales_proxy for row in self.controls.values()), Decimal("0.00"))

    @property
    def collections_total(self) -> Decimal:
        return sum((row.collections for row in self.controls.values()), Decimal("0.00"))


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise OracleContractError("event contains a non-canonical JSON value") from exc


def _timestamp(value: Any, field: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OracleContractError(f"{field} is not an ISO-8601 timestamp") from exc
    else:
        raise OracleContractError(f"{field} is not an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OracleContractError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _money(value: Any, field: str) -> Decimal:
    if not isinstance(value, str) or not _MONEY_PATTERN.fullmatch(value):
        raise OracleContractError(f"{field} must be a canonical two-decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise OracleContractError(f"{field} is invalid Decimal input") from exc
    if not amount.is_finite():
        raise OracleContractError(f"{field} must be finite")
    return amount


def _date(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise OracleContractError(f"{field} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise OracleContractError(f"{field} must be an ISO date string") from exc
    if parsed.isoformat() != value:
        raise OracleContractError(f"{field} must use canonical YYYY-MM-DD form")
    return value


def _payload_for(row: Mapping[str, Any], source_table: str, business_key: str,
                 operation: str) -> dict[str, str]:
    if "payload" in row:
        payload = row["payload"]
    elif "payload_json" in row:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise OracleContractError("payload_json is invalid JSON") from exc
        if not isinstance(payload, dict) or _canonical_json(payload) != row["payload_json"]:
            raise OracleContractError("payload_json is not a canonical JSON object")
    else:
        raise OracleContractError("event is missing its payload")
    if not isinstance(payload, Mapping):
        raise OracleContractError("event payload must be a JSON object")
    key_field = "order_id" if source_table == "orders" else "payment_id"
    if operation == "D":
        if set(payload) != {key_field} or payload.get(key_field) != business_key:
            raise OracleContractError(f"delete payload must contain only {key_field}")
        return {key_field: business_key}
    required = _ORDER_FIELDS if source_table == "orders" else _PAYMENT_FIELDS
    if set(payload) != required:
        raise OracleContractError("post-image fields do not match the source schema")
    if payload.get(key_field) != business_key:
        raise OracleContractError(f"payload {key_field} differs from business_key")
    clean: dict[str, str] = {}
    for field in required:
        value = payload[field]
        if not isinstance(value, str) or not value:
            raise OracleContractError(f"payload field {field} must be a non-empty string")
        clean[field] = value
    if source_table == "orders":
        _date(clean["order_date"], "order_date")
        _money(clean["order_net_amount"], "order_net_amount")
    else:
        _date(clean["payment_date"], "payment_date")
        _money(clean["amount"], "amount")
    return clean


def _event_content_digest(row: Mapping[str, Any], payload: Mapping[str, str],
                          source_time: str, business_time: str) -> str:
    envelope = {
        "source_identity": row["source_identity"],
        "schema_version": SCHEMA_VERSION,
        "source_table": row["source_table"],
        "business_key": row["business_key"],
        "operation": row["operation"],
        "source_updated_at": source_time,
        "business_event_at": business_time,
        "payload": dict(payload),
    }
    return hashlib.sha256(_canonical_json(envelope).encode("utf-8")).hexdigest()


def _normalize_event(row: Any) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        converter = getattr(row, "as_dict", None)
        if not callable(converter):
            raise OracleContractError("journal event must be a mapping or expose as_dict()")
        row = converter()
    required = {
        "change_seq", "change_id", "source_table", "business_key",
        "operation", "source_updated_at", "business_event_at", "schema_version",
        "payload_sha256", "event_sha256",
    }
    required.remove("event_sha256")
    if not required.issubset(row):
        raise OracleContractError(f"journal event missing fields: {sorted(required - set(row))}")
    seq = row["change_seq"]
    if type(seq) is not int or seq < 1:
        raise OracleContractError("change_seq must be a positive integer")
    source_identity = row.get("source_identity", SOURCE_IDENTITY)
    if source_identity != SOURCE_IDENTITY:
        raise OracleContractError("unsupported source_identity")
    if type(row["schema_version"]) is int:
        schema_version = row["schema_version"]
    elif isinstance(row["schema_version"], str) and row["schema_version"].isdigit():
        schema_version = int(row["schema_version"])
    else:
        raise OracleContractError("schema_version must be integer 1")
    if schema_version != SCHEMA_VERSION:
        raise OracleContractError("unknown event schema version")
    table, operation = row["source_table"], row["operation"]
    if table not in {"orders", "payment_events"} or operation not in {"I", "U", "D"}:
        raise OracleContractError("unsupported source table or operation")
    business_key = row["business_key"]
    change_id = row["change_id"]
    if not isinstance(business_key, str) or not business_key:
        raise OracleContractError("business_key must be a non-empty string")
    if not isinstance(change_id, str) or not change_id:
        raise OracleContractError("change_id must be a non-empty string")
    source_time = _timestamp(row["source_updated_at"], "source_updated_at")
    business_time = _timestamp(row["business_event_at"], "business_event_at")
    payload = _payload_for(row, table, business_key, operation)
    if operation != "D":
        date_field = "order_date" if table == "orders" else "payment_date"
        if datetime.fromisoformat(business_time.replace("Z", "+00:00")).date().isoformat() \
                != payload[date_field]:
            raise OracleContractError(f"business_event_at does not match {date_field}")
    payload_sha = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    if row["payload_sha256"] != payload_sha or not _SHA_PATTERN.fullmatch(payload_sha):
        raise OracleContractError("payload SHA-256 does not match canonical payload")
    event_sha = _event_content_digest(
        {**row, "source_identity": source_identity}, payload, source_time, business_time
    )
    if row.get("event_sha256") is not None and row["event_sha256"] != event_sha:
        raise OracleContractError("event SHA-256 does not match canonical event")
    return {
        "change_seq": seq,
        "source_identity": source_identity,
        "change_id": change_id,
        "source_table": table,
        "business_key": business_key,
        "operation": operation,
        "source_updated_at": source_time,
        "business_event_at": business_time,
        "schema_version": SCHEMA_VERSION,
        "payload": payload,
        "payload_sha256": payload_sha,
        "event_sha256": event_sha,
    }


def replay_journal(events: Iterable[Any]) -> ReplayResult:
    """Reconstruct state from journal sequence and calculate per-order controls."""
    normalized = [_normalize_event(row) for row in events]
    normalized.sort(key=lambda item: item["change_seq"])
    sequences: set[int] = set()
    identities: dict[str, str] = {}
    orders: dict[str, OrderState] = {}
    payments: dict[str, PaymentState] = {}
    for event in normalized:
        seq = event["change_seq"]
        if seq in sequences:
            raise OracleContractError(f"duplicate change_seq {seq}")
        sequences.add(seq)
        previous_digest = identities.get(event["change_id"])
        if previous_digest is not None:
            raise OracleContractError(
                f"change_id {event['change_id']!r} appears more than once in the journal"
            )
        identities[event["change_id"]] = event["event_sha256"]
        table, key, operation, payload = (
            event["source_table"], event["business_key"], event["operation"], event["payload"]
        )
        if table == "orders":
            prior = orders.get(key)
            if operation == "I":
                if prior is not None and not prior.is_deleted:
                    raise OracleContractError(f"duplicate live order insert for {key!r}")
                orders[key] = OrderState(
                    key, payload["customer_id"], payload["order_date"], payload["province_id"],
                    payload["status"], _money(payload["order_net_amount"], "order_net_amount"),
                    False, seq, event["change_id"], event["payload_sha256"],
                )
            elif operation == "U":
                if prior is None or prior.is_deleted:
                    raise OracleContractError(f"cannot update absent order {key!r}")
                orders[key] = OrderState(
                    key, payload["customer_id"], payload["order_date"], payload["province_id"],
                    payload["status"], _money(payload["order_net_amount"], "order_net_amount"),
                    False, seq, event["change_id"], event["payload_sha256"],
                )
            else:
                if prior is None or prior.is_deleted:
                    raise OracleContractError(f"cannot delete absent order {key!r}")
                orders[key] = OrderState(
                    prior.order_id, prior.customer_id, prior.order_date, prior.province_id,
                    prior.status, prior.order_net_amount, True, seq, event["change_id"],
                    event["payload_sha256"],
                )
        else:
            prior = payments.get(key)
            if operation == "I":
                if prior is not None and not prior.is_deleted:
                    raise OracleContractError(f"duplicate live payment insert for {key!r}")
                payments[key] = PaymentState(
                    key, payload["order_id"], payload["payment_date"],
                    _money(payload["amount"], "amount"), payload["status"], payload["method"],
                    False, seq, event["change_id"], event["payload_sha256"],
                )
            elif operation == "U":
                if prior is None or prior.is_deleted:
                    raise OracleContractError(f"cannot update absent payment event {key!r}")
                payments[key] = PaymentState(
                    key, payload["order_id"], payload["payment_date"],
                    _money(payload["amount"], "amount"), payload["status"], payload["method"],
                    False, seq, event["change_id"], event["payload_sha256"],
                )
            else:
                if prior is None or prior.is_deleted:
                    raise OracleContractError(f"cannot delete absent payment event {key!r}")
                payments[key] = PaymentState(
                    prior.payment_id, prior.order_id, prior.payment_date, prior.amount,
                    prior.status, prior.method, True, seq, event["change_id"],
                    event["payload_sha256"],
                )

    for payment in payments.values():
        if payment.order_id not in orders:
            raise OracleContractError(
                f"orphan payment {payment.payment_id!r} references missing order "
                f"{payment.order_id!r}"
            )

    collected_by_order: dict[str, Decimal] = {}
    for payment in payments.values():
        if not payment.is_deleted and payment.status == "success":
            collected_by_order[payment.order_id] = (
                collected_by_order.get(payment.order_id, Decimal("0.00")) + payment.amount
            )
    controls: dict[str, OrderControl] = {}
    for key, order in sorted(orders.items()):
        delivered = (
            order.order_net_amount
            if not order.is_deleted and order.status == "delivered"
            else Decimal("0.00")
        )
        collected = collected_by_order.get(key, Decimal("0.00"))
        variance = None if order.is_deleted else collected - delivered
        controls[key] = OrderControl(
            key, order.order_date, order.is_deleted, order.status, delivered, collected,
            variance, order.effective_seq, order.change_id, order.payload_sha256,
        )
    return ReplayResult(orders, payments, controls)


def read_parquet_events(path: str | Path) -> tuple[dict[str, Any], ...]:
    """Read portable journal rows without calling the production verifier."""
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Reading exported Parquet requires pyarrow") from exc
    records = pq.read_table(Path(path)).to_pylist()
    normalized = []
    for record in records:
        wire = dict(record)
        wire["source_identity"] = SOURCE_IDENTITY
        if "payload" in wire:
            wire["payload_json"] = wire.pop("payload")
        normalized.append(_normalize_event(wire))
    return tuple(normalized)


def replay_parquet(path: str | Path) -> ReplayResult:
    """Independently read and replay one exported Parquet file."""
    return replay_journal(read_parquet_events(path))
