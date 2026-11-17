from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("pyspark", reason="Week 8 CI installs the lane's Spark test dependency")

from labs.streaming_cdc.stream import (
    _confluent_frame_columns,
    _gold_event_records,
    _normalized_order_changes,
)


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


def test_gold_event_records_use_debezium_source_ts_ms_not_envelope_ts_ms(spark):
    from decimal import Decimal

    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        DecimalType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    source_ts_ms = 1_760_000_000_000
    envelope_ts_ms = source_ts_ms + 5_000
    order_record = StructType(
        [
            StructField("order_id", StringType(), True),
            StructField("province_id", StringType(), True),
            StructField("order_net_amount", DecimalType(18, 2), True),
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
            StructField("ts_ms", LongType(), True),
        ]
    )
    source = spark.createDataFrame(
        [
            (
                {
                    "op": "u",
                    "before": {
                        "order_id": "w8-source-time-001",
                        "province_id": "province-a",
                        "order_net_amount": Decimal("10.00"),
                    },
                    "after": {
                        "order_id": "w8-source-time-001",
                        "province_id": "province-b",
                        "order_net_amount": Decimal("12.50"),
                    },
                    "source": {"lsn": 10, "ts_ms": source_ts_ms},
                    "transaction": {"total_order": 1},
                    "ts_ms": envelope_ts_ms,
                },
            )
        ],
        StructType([StructField("event", event, True)]),
    )

    normalized = _gold_event_records(source)
    event_time_epoch = normalized.select(F.col("event_time").cast("long")).first()[0]

    assert event_time_epoch == source_ts_ms // 1000
    assert event_time_epoch != envelope_ts_ms // 1000
