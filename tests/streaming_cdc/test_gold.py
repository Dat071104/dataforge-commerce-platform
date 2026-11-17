from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

pytest.importorskip("pyspark", reason="Week 8 CI installs the lane's Spark test dependency")
pytest.importorskip("delta", reason="Week 8 CI installs the lane's Delta test dependency")

from pyspark.sql.types import (
    DecimalType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from labs.streaming_cdc.gold import merge_gold_revenue_batch

SCHEMA = StructType(
    [
        StructField("event_time", TimestampType(), False),
        StructField("order_id", StringType(), False),
        StructField("source_lsn", LongType(), True),
        StructField("transaction_order", LongType(), True),
        StructField("op", StringType(), False),
        StructField("before_province_id", StringType(), True),
        StructField("before_order_net_amount", DecimalType(18, 2), True),
        StructField("after_province_id", StringType(), True),
        StructField("after_order_net_amount", DecimalType(18, 2), True),
    ]
)


def _event(
    *,
    order_id: str,
    lsn: int,
    op: str,
    before_province: str | None,
    before_amount: str | None,
    after_province: str | None,
    after_amount: str | None,
):
    return (
        datetime(2026, 11, 17, 10, 1),
        order_id,
        lsn,
        1,
        op,
        before_province,
        None if before_amount is None else Decimal(before_amount),
        after_province,
        None if after_amount is None else Decimal(after_amount),
    )


def test_gold_signed_updates_move_province_and_batch_replay_is_idempotent(spark, tmp_path):
    target = tmp_path / "gold_revenue"
    changes = tmp_path / "gold_revenue_changes"

    create = spark.createDataFrame(
        [
            _event(
                order_id="ord-1",
                lsn=100,
                op="upsert",
                before_province=None,
                before_amount=None,
                after_province="province-a",
                after_amount="10.00",
            )
        ],
        SCHEMA,
    )
    assert merge_gold_revenue_batch(create, target, changes)
    assert merge_gold_revenue_batch(create, target, changes)

    moved = spark.createDataFrame(
        [
            _event(
                order_id="ord-1",
                lsn=101,
                op="upsert",
                before_province="province-a",
                before_amount="10.00",
                after_province="province-b",
                after_amount="15.00",
            )
        ],
        SCHEMA,
    )
    assert merge_gold_revenue_batch(moved, target, changes)

    totals = {
        row.province_id: row.revenue_delta
        for row in spark.read.format("delta").load(str(target)).collect()
    }
    assert totals == {
        "province-a": Decimal("0.00"),
        "province-b": Decimal("15.00"),
    }

    deleted = spark.createDataFrame(
        [
            _event(
                order_id="ord-1",
                lsn=102,
                op="delete",
                before_province="province-b",
                before_amount="15.00",
                after_province=None,
                after_amount=None,
            )
        ],
        SCHEMA,
    )
    assert merge_gold_revenue_batch(deleted, target, changes)
    totals = {
        row.province_id: row.revenue_delta
        for row in spark.read.format("delta").load(str(target)).collect()
    }
    assert totals == {
        "province-a": Decimal("0.00"),
        "province-b": Decimal("0.00"),
    }
    assert spark.read.format("delta").load(str(changes)).count() == 4
