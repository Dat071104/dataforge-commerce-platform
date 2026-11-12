"""Apply deterministic Week-7 changes to the isolated operational simulator.

These events are a documented controlled test of the separate Week-5 journal.
They do not touch the accepted local `dataforge` database or any cloud table.
Each stable change_id makes an exact repeat safe; conflicting reuse fails closed.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from dataforge.incremental.source import JournalEvent, append_change

_UTC = timezone.utc


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 11, 11, hour, minute, second, tzinfo=_UTC)


def apply_scenario(scenario: str) -> tuple[JournalEvent, ...]:
    if scenario == "insert_order_with_two_payments":
        order = append_change(
            "orders",
            "W5O0005",
            "I",
            {
                "order_id": "W5O0005",
                "customer_id": "W5C0005",
                "order_date": "2026-11-10",
                "province_id": "VN-HN",
                "status": "delivered",
                "order_net_amount": "100000.00",
            },
            source_updated_at=_at(8, 10),
            business_event_at=datetime(2026, 11, 10, tzinfo=_UTC),
            change_id="week7-insert-order-w5o0005",
        )
        first_payment = append_change(
            "payment_events",
            "W5P0005",
            "I",
            {
                "payment_id": "W5P0005",
                "order_id": "W5O0005",
                "payment_date": "2026-11-10",
                "amount": "100000.00",
                "status": "success",
                "method": "bank_transfer",
            },
            source_updated_at=_at(8, 10, 1),
            business_event_at=datetime(2026, 11, 10, tzinfo=_UTC),
            change_id="week7-insert-payment-w5p0005",
        )
        second_payment = append_change(
            "payment_events",
            "W5P0006",
            "I",
            {
                "payment_id": "W5P0006",
                "order_id": "W5O0005",
                "payment_date": "2026-11-10",
                "amount": "5000.00",
                "status": "success",
                "method": "card",
            },
            source_updated_at=_at(8, 10, 2),
            business_event_at=datetime(2026, 11, 10, tzinfo=_UTC),
            change_id="week7-insert-payment-w5p0006",
        )
        return order, first_payment, second_payment

    if scenario == "backfill_late_order_and_payment_correction":
        order = append_change(
            "orders",
            "W5O0004",
            "U",
            {
                "order_id": "W5O0004",
                "customer_id": "W5C0004",
                "order_date": "2026-07-30",
                "province_id": "VN-CT",
                "status": "delivered",
                "order_net_amount": "55000.00",
            },
            source_updated_at=_at(8, 20),
            business_event_at=datetime(2026, 7, 30, tzinfo=_UTC),
            change_id="week7-late-correct-order-w5o0004",
        )
        payment = append_change(
            "payment_events",
            "W5P0004",
            "U",
            {
                "payment_id": "W5P0004",
                "order_id": "W5O0004",
                "payment_date": "2026-08-02",
                "amount": "14000.00",
                "status": "failed",
                "method": "bank_transfer",
            },
            source_updated_at=_at(8, 20, 1),
            business_event_at=datetime(2026, 8, 2, tzinfo=_UTC),
            change_id="week7-late-correct-payment-status-w5p0004",
        )
        return order, payment

    if scenario == "normal_payment_recovery_after_backfill":
        payment = append_change(
            "payment_events",
            "W5P0004",
            "U",
            {
                "payment_id": "W5P0004",
                "order_id": "W5O0004",
                "payment_date": "2026-08-02",
                "amount": "15000.00",
                "status": "success",
                "method": "bank_transfer",
            },
            source_updated_at=_at(8, 30),
            business_event_at=datetime(2026, 8, 2, tzinfo=_UTC),
            change_id="week7-normal-payment-catchup-w5p0004",
        )
        return (payment,)

    if scenario == "tombstone_order_and_one_payment":
        payment = append_change(
            "payment_events",
            "W5P0005",
            "D",
            {"payment_id": "W5P0005"},
            source_updated_at=_at(8, 40),
            business_event_at=datetime(2026, 11, 10, tzinfo=_UTC),
            change_id="week7-tombstone-payment-w5p0005",
        )
        order = append_change(
            "orders",
            "W5O0005",
            "D",
            {"order_id": "W5O0005"},
            source_updated_at=_at(8, 40, 1),
            business_event_at=datetime(2026, 11, 10, tzinfo=_UTC),
            change_id="week7-tombstone-order-w5o0005",
        )
        return payment, order

    if scenario == "recovery_payment_update":
        payment = append_change(
            "payment_events",
            "W5P0004",
            "U",
            {
                "payment_id": "W5P0004",
                "order_id": "W5O0004",
                "payment_date": "2026-08-02",
                "amount": "16000.00",
                "status": "success",
                "method": "bank_transfer",
            },
            source_updated_at=_at(8, 50),
            business_event_at=datetime(2026, 8, 2, tzinfo=_UTC),
            change_id="week7-recovery-payment-w5p0004",
        )
        return (payment,)

    if scenario == "publication_pointer_failure_payment_update":
        payment = append_change(
            "payment_events",
            "W5P0004",
            "U",
            {
                "payment_id": "W5P0004",
                "order_id": "W5O0004",
                "payment_date": "2026-08-02",
                "amount": "17000.00",
                "status": "success",
                "method": "bank_transfer",
            },
            source_updated_at=_at(9, 0),
            business_event_at=datetime(2026, 8, 2, tzinfo=_UTC),
            change_id="week7-publish-failure-payment-w5p0004",
        )
        return (payment,)

    raise ValueError(f"unsupported Week-7 operational scenario: {scenario}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenario",
        choices=(
            "insert_order_with_two_payments",
            "backfill_late_order_and_payment_correction",
            "normal_payment_recovery_after_backfill",
            "tombstone_order_and_one_payment",
            "recovery_payment_update",
            "publication_pointer_failure_payment_update",
        ),
    )
    args = parser.parse_args(argv)
    events = apply_scenario(args.scenario)
    result = {
        "status": "APPLIED_OR_EXACT_REPLAY",
        "scenario": args.scenario,
        "source_identity": events[0].source_identity,
        "change_count": len(events),
        "seq_min": min(event.change_seq for event in events),
        "seq_max": max(event.change_seq for event in events),
        "change_ids": [event.change_id for event in events],
        "no_cloud_calls": True,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
