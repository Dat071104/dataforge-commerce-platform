"""Independent source-oracle comparisons for Week-5 warehouse receipts."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .oracle import ReplayResult

CSV_FIELDS = ("entity", "business_key", "field", "expected", "actual", "match")


def _display(value: Any) -> str:
    if value is None:
        return "<NULL>"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _matches(expected: Any, actual: Any) -> bool:
    # BigQuery CAST(NUMERIC AS STRING) removes insignificant trailing zeros.
    # Compare NUMERIC values as Decimal so scale formatting cannot create a
    # false mismatch or round a monetary amount through binary float.
    if isinstance(expected, Decimal):
        try:
            return expected == Decimal(str(actual))
        except (InvalidOperation, TypeError, ValueError):
            return False
    return expected == actual


def _compare_entity(
    entity: str,
    expected_rows: Mapping[str, Mapping[str, Any]],
    actual_rows: Mapping[str, Mapping[str, Any]],
    fields: tuple[str, ...],
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for key in sorted(set(expected_rows) | set(actual_rows)):
        expected = expected_rows.get(key)
        actual = actual_rows.get(key)
        if expected is None or actual is None:
            checks.append(
                {
                    "entity": entity,
                    "business_key": key,
                    "field": "__row_presence__",
                    "expected": "present" if expected is not None else "absent",
                    "actual": "present" if actual is not None else "absent",
                    "match": "false",
                }
            )
            continue
        for field in fields:
            expected_value = _display(expected.get(field))
            actual_value = _display(actual.get(field))
            checks.append(
                {
                    "entity": entity,
                    "business_key": key,
                    "field": field,
                    "expected": expected_value,
                    "actual": actual_value,
                    "match": str(_matches(expected.get(field), actual.get(field))).lower(),
                }
            )
    return checks


def compare_warehouse_state(
    expected: ReplayResult,
    *,
    silver_orders: list[Mapping[str, Any]],
    silver_payments: list[Mapping[str, Any]],
    gold_controls: list[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Return field-level evidence without importing production MERGE logic."""
    expected_orders = {
        key: {
            "customer_id": row.customer_id,
            "order_date": row.order_date,
            "province_id": row.province_id,
            "order_status": row.status,
            "order_net_amount": row.order_net_amount,
            "is_deleted": row.is_deleted,
            "effective_seq": row.effective_seq,
            "last_change_id": row.change_id,
            "last_payload_sha256": row.payload_sha256,
        }
        for key, row in expected.orders.items()
    }
    expected_payments = {
        key: {
            "order_id": row.order_id,
            "payment_date": row.payment_date,
            "amount": row.amount,
            "payment_status": row.status,
            "method": row.method,
            "is_deleted": row.is_deleted,
            "effective_seq": row.effective_seq,
            "last_change_id": row.change_id,
            "last_payload_sha256": row.payload_sha256,
        }
        for key, row in expected.payment_events.items()
    }

    payment_counts: Counter[str] = Counter()
    successful_payment_counts: Counter[str] = Counter()
    for payment in expected.payment_events.values():
        if not payment.is_deleted:
            payment_counts[payment.order_id] += 1
            if payment.status == "success":
                successful_payment_counts[payment.order_id] += 1

    expected_gold = {
        key: {
            "order_date": row.order_date,
            "order_status": row.order_status,
            "order_is_deleted": row.order_is_deleted,
            "delivered_sales_proxy": row.delivered_sales_proxy,
            "collected_amount": row.collections,
            "collection_variance": row.collection_variance,
            "active_payment_count": payment_counts[key],
            "successful_payment_count": successful_payment_counts[key],
            "order_effective_seq": row.effective_seq,
        }
        for key, row in expected.controls.items()
    }

    def keyed(rows: list[Mapping[str, Any]], field: str, entity: str) -> dict[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            key = str(row[field])
            if key in result:
                raise ValueError(f"{entity} contains duplicate key {key}")
            result[key] = row
        return result

    return (
        _compare_entity(
            "silver_orders",
            expected_orders,
            keyed(silver_orders, "order_id", "Silver orders"),
            (
                "customer_id", "order_date", "province_id", "order_status",
                "order_net_amount", "is_deleted", "effective_seq", "last_change_id",
                "last_payload_sha256",
            ),
        )
        + _compare_entity(
            "silver_payment_events",
            expected_payments,
            keyed(silver_payments, "payment_id", "Silver payment events"),
            (
                "order_id", "payment_date", "amount", "payment_status", "method",
                "is_deleted", "effective_seq", "last_change_id", "last_payload_sha256",
            ),
        )
        + _compare_entity(
            "gold_order_controls",
            expected_gold,
            keyed(gold_controls, "order_id", "Gold order controls"),
            (
                "order_date", "order_status", "order_is_deleted", "delivered_sales_proxy",
                "collected_amount", "collection_variance", "active_payment_count",
                "successful_payment_count", "order_effective_seq",
            ),
        )
    )
