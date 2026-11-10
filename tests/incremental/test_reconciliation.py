from __future__ import annotations

from decimal import Decimal

import pytest

from dataforge.incremental import reconciliation
from dataforge.incremental.oracle import replay_journal
from tests.incremental.test_source_oracle import _journal_events


def _warehouse_rows(result):
    orders = [
        {
            "order_id": row.order_id,
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
        for row in result.orders.values()
    ]
    payments = [
        {
            "payment_id": row.payment_id,
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
        for row in result.payment_events.values()
    ]
    controls = []
    for row in result.controls.values():
        linked = [payment for payment in result.payment_events.values() if payment.order_id == row.order_id]
        active = [payment for payment in linked if not payment.is_deleted]
        controls.append(
            {
                "order_id": row.order_id,
                "order_date": row.order_date,
                "order_status": row.order_status,
                "order_is_deleted": row.order_is_deleted,
                "delivered_sales_proxy": row.delivered_sales_proxy,
                "collected_amount": row.collections,
                "collection_variance": row.collection_variance,
                "active_payment_count": len(active),
                "successful_payment_count": sum(payment.status == "success" for payment in active),
                "order_effective_seq": row.effective_seq,
            }
        )
    return orders, payments, controls


def test_independent_reconciliation_matches_all_silver_and_gold_grains():
    expected = replay_journal(_journal_events())
    orders, payments, controls = _warehouse_rows(expected)
    for row in orders:
        row["order_net_amount"] = format(row["order_net_amount"], "f").rstrip("0").rstrip(".")
    for row in payments:
        row["amount"] = format(row["amount"], "f").rstrip("0").rstrip(".")
    for row in controls:
        for field in ("delivered_sales_proxy", "collected_amount", "collection_variance"):
            if row[field] is not None:
                row[field] = format(row[field], "f").rstrip("0").rstrip(".")

    checks = reconciliation.compare_warehouse_state(
        expected,
        silver_orders=orders,
        silver_payments=payments,
        gold_controls=controls,
    )

    assert checks
    assert all(row["match"] == "true" for row in checks)
    assert expected.orders["W5O0001"].order_net_amount == Decimal("131000.00")


def test_independent_reconciliation_detects_mismatch_duplicate_and_missing_rows():
    expected = replay_journal(_journal_events())
    orders, payments, controls = _warehouse_rows(expected)
    duplicate_test_orders = list(orders)
    controls[0]["collected_amount"] += Decimal("0.01")
    orders.pop()

    checks = reconciliation.compare_warehouse_state(
        expected,
        silver_orders=orders,
        silver_payments=payments,
        gold_controls=controls,
    )

    failures = [row for row in checks if row["match"] != "true"]
    assert any(row["field"] == "collected_amount" for row in failures)
    assert any(row["field"] == "__row_presence__" for row in failures)
    with pytest.raises(ValueError, match="duplicate key"):
        reconciliation.compare_warehouse_state(
            expected,
                silver_orders=duplicate_test_orders + [duplicate_test_orders[0]],
            silver_payments=payments,
            gold_controls=_warehouse_rows(expected)[2],
        )
