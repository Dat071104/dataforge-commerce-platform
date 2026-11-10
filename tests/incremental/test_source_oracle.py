"""Unit and opt-in dedicated-PostgreSQL tests for the P7.2 source lane."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlsplit

import pytest

from dataforge.incremental import oracle, source


def _event(seq, table, key, operation, payload, *, source_at, business_at, change_id):
    canonical_payload = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    payload_sha = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    envelope = {
        "source_identity": "dataforge-operational-v1",
        "schema_version": 1,
        "source_table": table,
        "business_key": key,
        "operation": operation,
        "source_updated_at": source_at,
        "business_event_at": business_at,
        "payload": payload,
    }
    event_sha = hashlib.sha256(json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()
    return {
        "change_seq": seq,
        "source_identity": "dataforge-operational-v1",
        "change_id": change_id,
        "source_table": table,
        "business_key": key,
        "operation": operation,
        "source_updated_at": source_at,
        "business_event_at": business_at,
        "schema_version": 1,
        "payload": payload,
        "payload_sha256": payload_sha,
        "event_sha256": event_sha,
    }


def _order_payload(*, day="2026-10-01", amount="125000.01"):
    return {
        "order_id": "W5O0001", "customer_id": "W5C0001", "order_date": day,
        "province_id": "VN-HN", "status": "delivered", "order_net_amount": amount,
    }


def _payment_payload(*, payment_id="W5P0001", day="2026-10-02", amount="125000.01",
                     status="success"):
    return {
        "payment_id": payment_id, "order_id": "W5O0001", "payment_date": day,
        "amount": amount, "status": status, "method": "bank_transfer",
    }


def _journal_events():
    return [
        _event(1, "orders", "W5O0001", "I", _order_payload(),
               source_at="2026-10-10T00:00:00.000000Z",
               business_at="2026-10-01T00:00:00.000000Z", change_id="oracle-order-insert"),
        _event(2, "payment_events", "W5P0001", "I", _payment_payload(),
               source_at="2026-10-10T00:00:01.000000Z",
               business_at="2026-10-02T00:00:00.000000Z", change_id="oracle-payment-insert"),
        _event(3, "payment_events", "W5P0002", "I",
               _payment_payload(payment_id="W5P0002", amount="10.00", status="failed"),
               source_at="2026-10-10T00:00:02.000000Z",
               business_at="2026-10-02T00:00:00.000000Z", change_id="oracle-payment-failed"),
        _event(4, "payment_events", "W5P0002", "D", {"payment_id": "W5P0002"},
               source_at="2026-10-10T00:00:03.000000Z",
               business_at="2026-10-02T00:00:00.000000Z", change_id="oracle-payment-delete"),
        _event(5, "orders", "W5O0001", "U", _order_payload(day="2026-09-15", amount="130000.00"),
               source_at="2026-08-01T00:00:00.000000Z",
               business_at="2026-09-15T00:00:00.000000Z", change_id="oracle-retroactive-order-a"),
        _event(6, "orders", "W5O0001", "U", _order_payload(day="2026-09-15", amount="131000.00"),
               source_at="2026-08-01T00:00:00.000000Z",
               business_at="2026-09-15T00:00:00.000000Z", change_id="oracle-retroactive-order-b"),
        _event(7, "orders", "W5O0001", "D", {"order_id": "W5O0001"},
               source_at="2026-11-10T00:00:00.000000Z",
               business_at="2026-09-15T00:00:00.000000Z", change_id="oracle-order-delete"),
    ]


def test_oracle_replays_decimal_updates_and_independent_tombstones():
    result = oracle.replay_journal(_journal_events())

    assert result.order_count == 1
    assert result.active_order_count == 0
    assert result.payment_count == 2
    assert result.active_payment_count == 1
    assert result.orders["W5O0001"].order_net_amount == Decimal("131000.00")
    assert result.orders["W5O0001"].order_date == "2026-09-15"
    assert result.orders["W5O0001"].effective_seq == 7
    assert result.orders["W5O0001"].is_deleted
    assert result.payment_events["W5P0001"].is_deleted is False
    assert result.payment_events["W5P0002"].is_deleted is True

    control = result.controls["W5O0001"]
    assert control.delivered_sales_proxy == Decimal("0.00")
    assert control.collections == Decimal("125000.01")
    assert control.collection_variance is None
    assert result.delivered_sales_total == Decimal("0.00")
    assert result.collections_total == Decimal("125000.01")


def test_oracle_fails_closed_on_conflicting_or_corrupt_journal_rows():
    events = _journal_events()
    with pytest.raises(oracle.OracleContractError, match="duplicate change_seq"):
        oracle.replay_journal(events + [events[0]])

    corrupted = [dict(row) for row in events]
    corrupted[0]["payload"] = {**corrupted[0]["payload"], "order_net_amount": "9.00"}
    with pytest.raises(oracle.OracleContractError, match="payload SHA-256"):
        oracle.replay_journal(corrupted)

    unknown = [dict(row) for row in events]
    unknown[0]["schema_version"] = 2
    with pytest.raises(oracle.OracleContractError, match="unknown event schema"):
        oracle.replay_journal(unknown)


def test_oracle_rejects_orphan_payment_and_binary_float_money():
    orphan = _event(
        1, "payment_events", "W5P9999", "I",
        {"payment_id": "W5P9999", "order_id": "MISSING", "payment_date": "2026-10-02",
         "amount": "1.00", "status": "success", "method": "card"},
        source_at="2026-10-10T00:00:00.000000Z",
        business_at="2026-10-02T00:00:00.000000Z", change_id="oracle-orphan",
    )
    with pytest.raises(oracle.OracleContractError, match="orphan payment"):
        oracle.replay_journal([orphan])

    with pytest.raises(source.SourceContractError, match="canonical decimal string"):
        source.append_change(
            "orders", "W5O0001", "I", {**_order_payload(), "order_net_amount": 1.25},
            source_updated_at="2026-10-10T00:00:00Z",
            business_event_at="2026-10-01T00:00:00Z",
        )


def test_source_timestamp_normalization_and_batch_identity_are_deterministic():
    assert source._normalize_timestamp(
        datetime(2026, 10, 10, 7, tzinfo=timezone.utc), "source_updated_at"
    ) == "2026-10-10T07:00:00.000000Z"
    with pytest.raises(source.SourceContractError, match="include a timezone"):
        source._normalize_timestamp(datetime(2026, 10, 10), "source_updated_at")
    digest = "a" * 64
    assert source.batch_identity(1, 4, digest) == source.batch_identity(1, 4, digest)
    assert source.batch_identity(1, 4, digest) != source.batch_identity(1, 5, digest)


def _dedicated_test_dsn() -> str:
    dsn = os.environ.get("DATAFORGE_OPERATIONAL_TEST_DATABASE_URL", "")
    parts = urlsplit(dsn)
    if (parts.scheme not in {"postgres", "postgresql"}
            or parts.hostname not in {"127.0.0.1", "localhost"}
            or parts.port != 55432
            or parts.path.strip("/") != "dataforge_operational_test"
            or parts.username != "dataforge_week5"):
        pytest.fail(
            "integration tests require the dedicated loopback PostgreSQL on port 55432 "
            "with isolated database dataforge_operational_test and user dataforge_week5"
        )
    return dsn


@pytest.mark.skipif(
    os.environ.get("RUN_OPERATIONAL_SOURCE_TESTS") != "1",
    reason="set RUN_OPERATIONAL_SOURCE_TESTS=1 with the isolated week5 source database",
)
def test_dedicated_postgres_source_journal_export_and_oracle(tmp_path):
    import psycopg

    dsn = _dedicated_test_dsn()
    # This guarded integration test owns only the dedicated Week-5 database.
    # Reset its simulator schema so reruns remain deterministic after failures.
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS dataforge_operational CASCADE")
    source.initialize(dsn)
    seed = source.seed_source(dsn=dsn)
    assert source.seed_source(dsn=dsn) == seed
    assert len(seed) == 6

    scenario_rows = []
    for scenario_id in ("INC-03", "INC-04", "INC-05", "INC-06", "INC-09", "INC-08", "INC-10"):
        scenario_rows.extend(source.apply_scenario(scenario_id, dsn=dsn))
    assert len(scenario_rows) == 12

    with pytest.raises(source.IdempotencyConflict, match="different event content"):
        source.append_change(
            "orders", "W5O0001", "U",
            {**_order_payload(day="2026-10-01"), "order_net_amount": "999999.00"},
            source_updated_at="2026-11-01T10:00:00Z",
            business_event_at="2026-10-01T00:00:00Z",
            change_id="inc03-order-w5o0001", dsn=dsn,
        )

    retro_order = next(row for row in scenario_rows if row.change_id == "inc09-retroactive-order")
    assert retro_order.change_seq > max(row.change_seq for row in seed)
    assert retro_order.source_updated_at < seed[0].source_updated_at
    injected_payment = next(
        row for row in scenario_rows if row.change_id == "inc08-after-merge-payment-w5p0004"
    )
    recovery_payment = next(
        row for row in scenario_rows if row.change_id == "inc10-before-publish-payment-w5p0004"
    )
    assert injected_payment.change_seq < recovery_payment.change_seq
    assert injected_payment.payload["amount"] == "13000.00"
    assert recovery_payment.payload["amount"] == "14000.00"
    same_time = [row for row in scenario_rows if row.change_id.startswith("inc06-order-same-timestamp")]
    assert len(same_time) == 2
    assert same_time[0].source_updated_at == same_time[1].source_updated_at
    assert same_time[0].change_seq < same_time[1].change_seq

    bounded = source.read_normal_batch(0, max_events=4, dsn=dsn)
    assert len(bounded.events) == 4
    assert bounded.upper_seq == bounded.events[-1].change_seq
    assert bounded.captured_upper_seq >= bounded.upper_seq
    full_upper = bounded.captured_upper_seq
    backfill = source.read_backfill(1, full_upper, max_events=100, dsn=dsn)
    assert backfill.requested_range == (1, full_upper)
    assert backfill.upper_seq == full_upper
    with pytest.raises(source.SourceContractError, match="more than max_events"):
        source.read_backfill(1, full_upper, max_events=1, dsn=dsn)

    # Exercise rollback after the state UPDATE has run but before the event INSERT.
    trigger_sql = """
        CREATE OR REPLACE FUNCTION dataforge_operational.fail_one_test_event()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.change_id = 'test-atomic-rollback' THEN
            RAISE EXCEPTION 'injected test failure after operational UPDATE';
          END IF;
          RETURN NEW;
        END;
        $$;
        DROP TRIGGER IF EXISTS fail_one_test_event
          ON dataforge_operational.change_journal;
        CREATE TRIGGER fail_one_test_event
        BEFORE INSERT ON dataforge_operational.change_journal
        FOR EACH ROW EXECUTE FUNCTION dataforge_operational.fail_one_test_event();
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(trigger_sql)
    current_order = {
        "order_id": "W5O0001", "customer_id": "W5C0001", "order_date": "2026-09-15",
        "province_id": "VN-HN", "status": "delivered", "order_net_amount": "999999.00",
    }
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="injected test failure"):
            source.append_change(
                "orders", "W5O0001", "U", current_order,
                source_updated_at="2026-11-10T00:00:00Z",
                business_event_at="2026-09-15T00:00:00Z",
                change_id="test-atomic-rollback", dsn=dsn,
            )
    finally:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("DROP TRIGGER IF EXISTS fail_one_test_event "
                            "ON dataforge_operational.change_journal")
                cur.execute("DROP FUNCTION IF EXISTS "
                            "dataforge_operational.fail_one_test_event()")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT order_net_amount FROM dataforge_operational.orders "
                        "WHERE order_id = 'W5O0001'")
            assert cur.fetchone()[0] == Decimal("133000.00")
            cur.execute("SELECT count(*) FROM dataforge_operational.change_journal "
                        "WHERE change_id = 'test-atomic-rollback'")
            assert cur.fetchone()[0] == 0

    pre_gap_upper = full_upper
    gap_update = {
        "order_id": "W5O0003", "customer_id": "W5C0003", "order_date": "2026-10-03",
        "province_id": "VN-DN", "status": "delivered", "order_net_amount": "80000.00",
    }
    source.append_change(
        "orders", "W5O0003", "U", gap_update,
        source_updated_at="2026-11-11T00:00:00Z",
        business_event_at="2026-10-03T00:00:00Z",
        change_id="test-after-sequence-gap", dsn=dsn,
    )
    gap_batch = source.read_normal_batch(pre_gap_upper, max_events=100, dsn=dsn)
    assert gap_batch.requested_range is not None
    assert gap_batch.requested_range[0] == pre_gap_upper + 1
    assert gap_batch.events[0].change_seq > gap_batch.requested_range[0]
    gap_export = source.export_batch(gap_batch, tmp_path / "gap-bronze")
    assert source.verify_manifest(gap_export.manifest_path) == gap_export

    full_upper = gap_batch.upper_seq
    assert full_upper is not None
    complete = source.read_backfill(1, full_upper, max_events=100, dsn=dsn)
    exported = source.export_batch(complete, tmp_path / "bronze")
    assert source.verify_manifest(exported.manifest_path) == exported
    assert source.export_batch(complete, tmp_path / "bronze") == exported

    from dataforge.incremental.batch import extract_batch
    from dataforge.incremental.bronze import serialize_batch

    wire_batch = extract_batch(
        (
            {
                "change_seq": row.change_seq,
                "change_id": row.change_id,
                "source_table": row.source_table,
                "business_key": row.business_key,
                "operation": row.operation,
                "source_updated_at": row.source_updated_at,
                "business_event_at": row.business_event_at,
                "schema_version": row.schema_version,
                "payload": row.payload,
                "payload_sha256": row.payload_sha256,
            }
            for row in complete.events
        ),
        from_seq=1,
        to_seq=full_upper,
        max_events=100,
    )
    assert wire_batch is not None
    assert wire_batch.batch_id == exported.batch_id
    assert wire_batch.row_value_sha256 == exported.row_value_sha256
    assert exported.parquet_path.read_bytes() == serialize_batch(wire_batch)

    incomplete_manifest = tmp_path / "incomplete.json"
    manifest_body = json.loads(exported.manifest_path.read_text(encoding="utf-8"))
    manifest_body["status"] = "STAGED"
    incomplete_manifest.write_text(json.dumps(manifest_body), encoding="utf-8")
    with pytest.raises(source.SourceContractError, match="status must be COMPLETE"):
        source.verify_manifest(incomplete_manifest)

    assert source.verify_parquet(
        exported.parquet_path,
        expected_sha256=exported.parquet_sha256,
        expected_row_value_sha256=exported.row_value_sha256,
    ) == complete.events

    independent = oracle.replay_parquet(exported.parquet_path)
    assert independent.orders["W5O0001"].order_net_amount == Decimal("133000.00")
    assert independent.orders["W5O0002"].is_deleted
    assert independent.payment_events["W5P0002"].is_deleted is False
    assert independent.controls["W5O0002"].collections == Decimal("200000.00")
    assert independent.controls["W5O0002"].collection_variance is None
    assert independent.payment_events["W5P0004"].amount == Decimal("14000.00")
    assert independent.orders["W5O0004"].order_date == "2026-08-01"
    assert independent.controls["W5O0004"].collections == Decimal("14000.00")

    damaged = exported.parquet_path.with_name("damaged.parquet")
    damaged.write_bytes(exported.parquet_path.read_bytes() + b"tamper")
    with pytest.raises(source.SourceContractError, match="Parquet SHA-256"):
        source.verify_parquet(damaged, expected_sha256=exported.parquet_sha256)
