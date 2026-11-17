from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("pyspark", reason="Week 8 CI installs the lane's Spark test dependency")

from pyspark.sql.types import DecimalType, LongType, StringType, StructField, StructType

from labs.streaming_cdc.envelopes import decode_debezium_envelope, to_order_change_row
from labs.streaming_cdc.merge import (
    build_merge_condition,
    build_newer_version_condition,
    merge_order_changes,
    prepare_merge_batch,
)
from labs.streaming_cdc.operations import OP_DELETE, OP_TOMBSTONE, OP_UPSERT

SCHEMA = StructType(
    [
        StructField("order_id", StringType(), False),
        StructField("status", StringType(), True),
        StructField("order_net_amount", DecimalType(18, 2), True),
        StructField("source_lsn", LongType(), True),
        StructField("transaction_order", LongType(), True),
        StructField("op", StringType(), False),
    ]
)


def _row(order_id, status, amount, lsn, txn_order, op):
    parsed_amount = None if amount is None else Decimal(amount)
    return (order_id, status, parsed_amount, lsn, txn_order, op)


def test_merge_builder_uses_pk_and_monotonic_source_version():
    assert build_merge_condition() == "t.order_id = s.order_id"
    version_guard = build_newer_version_condition()
    assert "coalesce(s.source_lsn, -1) > coalesce(t.source_lsn, -1)" in version_guard
    assert "coalesce(s.source_lsn, -1) = coalesce(t.source_lsn, -1)" in version_guard
    assert "coalesce(s.transaction_order, -1) > coalesce(t.transaction_order, -1)" in version_guard


def test_merge_builder_rejects_unsafe_identifiers():
    with pytest.raises(ValueError, match="invalid SQL identifier"):
        build_merge_condition(key_column="order_id OR 1=1")


def test_static_dataframe_dedupes_by_lsn_and_delta_merge_is_replay_safe(spark, tmp_path):
    batch = spark.createDataFrame(
        [
            _row("ord-1", "created", "10.00", 101, 1, OP_UPSERT),
            _row("ord-1", "paid", "12.00", 110, 2, OP_UPSERT),
            _row("ord-1", "stale", "11.00", 109, 1, OP_UPSERT),
            _row("ord-2", "created", "30.00", 200, 1, OP_UPSERT),
            _row("ord-2", "deleted", "30.00", 201, 1, OP_DELETE),
            _row("ord-3", None, None, 202, 1, OP_TOMBSTONE),
        ],
        SCHEMA,
    )
    prepared = prepare_merge_batch(batch).collect()
    assert len(prepared) == 2
    assert {row.order_id: row.source_lsn for row in prepared} == {"ord-1": 110, "ord-2": 201}
    assert {row.order_id: row.op for row in prepared} == {
        "ord-1": OP_UPSERT,
        "ord-2": OP_DELETE,
    }

    target = tmp_path / "silver_orders"
    assert merge_order_changes(batch, target, batch_id=0, transaction_app_id="unit-silver")
    table = spark.read.format("delta").load(str(target))
    table_rows = {row.order_id: row for row in table.collect()}
    assert table_rows["ord-1"].status == "paid"
    assert table_rows["ord-1"].order_net_amount == Decimal("12.00")
    assert table_rows["ord-1"].is_deleted is False
    assert table_rows["ord-2"].is_deleted is True
    assert [row.order_id for row in spark.table("silver_orders_cdc_current").collect()] == [
        "ord-1"
    ]

    # The txn identity skips a replay of the same micro-batch.
    assert not merge_order_changes(batch, target, batch_id=0, transaction_app_id="unit-silver")
    # A Kafka redelivery in a later micro-batch is still state-idempotent by LSN.
    assert merge_order_changes(batch, target, batch_id=1, transaction_app_id="unit-silver")
    assert spark.read.format("delta").load(str(target)).count() == 2
    assert spark.table("silver_orders_cdc_current").count() == 1

    delete = spark.createDataFrame(
        [_row("ord-1", "paid", "12.00", 111, 1, OP_DELETE)],
        SCHEMA,
    )
    assert merge_order_changes(delete, target, batch_id=2, transaction_app_id="unit-silver")
    assert spark.read.format("delta").load(str(target)).filter("order_id = 'ord-1'").first().is_deleted

    stale_insert = spark.createDataFrame(
        [_row("ord-1", "stale-after-delete", "13.00", 110, 4, OP_UPSERT)],
        SCHEMA,
    )
    assert merge_order_changes(
        stale_insert, target, batch_id=3, transaction_app_id="unit-silver"
    )
    deleted = spark.read.format("delta").load(str(target)).filter("order_id = 'ord-1'").first()
    assert deleted.is_deleted is True
    assert deleted.source_lsn == 111
    assert not any(
        row.order_id == "ord-1" for row in spark.table("silver_orders_cdc_current").collect()
    )

    snapshot = spark.createDataFrame(
        [_row("ord-4", "created", "1.00", None, None, OP_UPSERT)],
        SCHEMA,
    )
    assert merge_order_changes(snapshot, target, batch_id=4, transaction_app_id="unit-silver")
    update = spark.createDataFrame(
        [_row("ord-4", "paid", "2.00", 300, 1, OP_UPSERT)],
        SCHEMA,
    )
    assert merge_order_changes(update, target, batch_id=5, transaction_app_id="unit-silver")
    row = spark.read.format("delta").load(str(target)).filter("order_id = 'ord-4'").first()
    assert row.order_id == "ord-4"
    assert row.status == "paid"
    assert row.order_net_amount == Decimal("2.00")

    null_order = spark.createDataFrame(
        [_row("ord-4", "stale-null-order", "3.00", 300, None, OP_UPSERT)],
        SCHEMA,
    )
    assert merge_order_changes(
        null_order, target, batch_id=6, transaction_app_id="unit-silver"
    )
    assert (
        spark.read.format("delta")
        .load(str(target))
        .filter("order_id = 'ord-4'")
        .first()
        .status
        == "paid"
    )

    new_query_batch_zero = spark.createDataFrame(
        [_row("ord-5", "fresh-checkpoint", "5.00", 400, 1, OP_UPSERT)],
        SCHEMA,
    )
    assert merge_order_changes(
        new_query_batch_zero, target, batch_id=0, transaction_app_id="fresh-query-id"
    )
    assert (
        spark.read.format("delta")
        .load(str(target))
        .filter("order_id = 'ord-5'")
        .first()
        .status
        == "fresh-checkpoint"
    )


def test_decoded_delete_flows_through_shared_operation_into_soft_delete(spark, tmp_path):
    source_row = {
        "order_id": "ord-decoded-delete",
        "status": "paid",
        "order_net_amount": Decimal("15.00"),
    }
    change = decode_debezium_envelope(
        {
            "op": "d",
            "before": source_row,
            "after": None,
            "source": {"lsn": 900, "ts_ms": 1_760_000_000_000},
            "transaction": {"total_order": 2},
        },
        key={"order_id": "ord-decoded-delete"},
    )
    normalized = to_order_change_row(change)
    assert normalized["op"] == OP_DELETE
    row = tuple(normalized[column] for column in SCHEMA.fieldNames() if column in normalized)
    schema = StructType([field for field in SCHEMA.fields if field.name in normalized])
    batch = spark.createDataFrame([row], schema)

    target = tmp_path / "decoded-delete"
    assert merge_order_changes(
        batch, target, batch_id=0, transaction_app_id="decoded-query-id"
    )
    stored = spark.read.format("delta").load(str(target)).first()
    assert stored.order_id == "ord-decoded-delete"
    assert stored.is_deleted is True
    assert spark.table("silver_orders_cdc_current").count() == 0
