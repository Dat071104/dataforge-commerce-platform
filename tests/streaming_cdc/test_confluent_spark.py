from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("pyspark", reason="Week 8 CI installs the lane's Spark test dependency")

from labs.streaming_cdc.stream import _confluent_frame_columns, _normalized_order_changes


def test_confluent_spark_frame_extracts_schema_id_and_binary_payload(spark):
    framed_value = b"\x00\x00\x00\x00\x2aavro"
    source = spark.createDataFrame([(framed_value,)], ["value"])
    schema_id, payload = _confluent_frame_columns()

    decoded = source.select(schema_id.alias("schema_id"), payload.alias("payload")).first()

    assert decoded.schema_id == 42
    assert decoded.payload == b"avro"


def test_normalized_order_changes_converts_debezium_date_days_to_spark_date(spark):
    from pyspark.sql.types import (
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    order_record = StructType(
        [
            StructField("order_id", StringType(), True),
            StructField("order_date", IntegerType(), True),
        ]
    )
    event = StructType(
        [
            StructField("op", StringType(), True),
            StructField("before", order_record, True),
            StructField("after", order_record, True),
            StructField(
                "source",
                StructType(
                    [
                        StructField("lsn", LongType(), True),
                        StructField("ts_ms", LongType(), True),
                    ]
                ),
                True,
            ),
            StructField(
                "transaction",
                StructType([StructField("total_order", LongType(), True)]),
                True,
            ),
        ]
    )
    source = spark.createDataFrame(
        [
            (
                {
                    "op": "c",
                    "before": None,
                    "after": {"order_id": "w8-date-001", "order_date": 20774},
                    "source": {"lsn": 1, "ts_ms": 1_794_904_320_000},
                    "transaction": {"total_order": 1},
                },
            )
        ],
        StructType([StructField("event", event, True)]),
    )

    normalized = _normalized_order_changes(source)
    row = normalized.first()

    assert normalized.schema["order_date"].dataType.typeName() == "date"
    assert row.order_date == date(2026, 11, 17)
