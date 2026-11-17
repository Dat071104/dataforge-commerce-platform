from __future__ import annotations

from decimal import Decimal

from pyspark.sql.types import DecimalType, LongType, StringType, StructField, StructType

from labs.streaming_cdc.merge import (
    build_merge_condition,
    build_newer_version_condition,
    merge_order_changes,
    prepare_merge_batch,
)

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
    import pytest

    with pytest.raises(ValueError, match="invalid SQL identifier"):
        build_merge_condition(key_column="order_id OR 1=1")


def test_static_dataframe_dedupes_by_lsn_and_delta_merge_is_replay_safe(spark, tmp_path):
    batch = spark.createDataFrame(
        [
            _row("ord-1", "created", "10.00", 101, 1, "c"),
            _row("ord-1", "paid", "12.00", 110, 2, "u"),
            _row("ord-1", "stale", "11.00", 109, 1, "u"),
            _row("ord-2", "created", "30.00", 200, 1, "c"),
            _row("ord-2", "deleted", "30.00", 201, 1, "d"),
            _row("ord-3", None, None, 202, 1, "tombstone"),
        ],
        SCHEMA,
    )
    prepared = prepare_merge_batch(batch).collect()
    assert len(prepared) == 2
    assert {row.order_id: row.source_lsn for row in prepared} == {"ord-1": 110, "ord-2": 201}

    target = tmp_path / "silver_orders"
    assert merge_order_changes(batch, target, batch_id=0, transaction_app_id="unit-silver")
    table = spark.read.format("delta").load(str(target))
    assert [(row.order_id, row.status, row.order_net_amount) for row in table.collect()] == [
        ("ord-1", "paid", Decimal("12.00"))
    ]

    # The txn identity skips a replay of the same micro-batch.
    assert not merge_order_changes(batch, target, batch_id=0, transaction_app_id="unit-silver")
    # A Kafka redelivery in a later micro-batch is still state-idempotent by LSN.
    assert merge_order_changes(batch, target, batch_id=1, transaction_app_id="unit-silver")
    assert spark.read.format("delta").load(str(target)).count() == 1
    assert spark.read.format("delta").load(str(target)).first().order_net_amount == Decimal("12.00")

    delete = spark.createDataFrame(
        [_row("ord-1", "paid", "12.00", 111, 1, "d")],
        SCHEMA,
    )
    assert merge_order_changes(delete, target, batch_id=2, transaction_app_id="unit-silver")
    assert spark.read.format("delta").load(str(target)).count() == 0

    snapshot = spark.createDataFrame(
        [_row("ord-4", "created", "1.00", None, None, "r")],
        SCHEMA,
    )
    assert merge_order_changes(snapshot, target, batch_id=3, transaction_app_id="unit-silver")
    update = spark.createDataFrame(
        [_row("ord-4", "paid", "2.00", 300, 1, "u")],
        SCHEMA,
    )
    assert merge_order_changes(update, target, batch_id=4, transaction_app_id="unit-silver")
    row = spark.read.format("delta").load(str(target)).first()
    assert row.order_id == "ord-4"
    assert row.status == "paid"
    assert row.order_net_amount == Decimal("2.00")
