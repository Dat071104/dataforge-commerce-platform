from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

pytest.importorskip("pyspark", reason="Week 8 CI installs the lane's Spark test dependency")

from pyspark.sql.types import (
    DecimalType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from labs.streaming_cdc.windows import build_windowed_revenue, deduplicate_cdc_events


def test_static_dataframe_aggregates_tumbling_revenue_windows(spark):
    schema = StructType(
        [
            StructField("event_time", TimestampType(), False),
            StructField("province_id", StringType(), False),
            StructField("revenue_delta", DecimalType(18, 2), False),
        ]
    )
    events = spark.createDataFrame(
        [
            (datetime(2026, 11, 17, 10, 0, 10, tzinfo=timezone.utc), "province-1", Decimal("10.00")),
            (datetime(2026, 11, 17, 10, 4, 59, tzinfo=timezone.utc), "province-1", Decimal("2.50")),
            (datetime(2026, 11, 17, 10, 5, 0, tzinfo=timezone.utc), "province-1", Decimal("7.00")),
        ],
        schema,
    )

    actual = build_windowed_revenue(events).orderBy("window.start").collect()

    assert len(actual) == 2
    assert actual[0].window.start == datetime(2026, 11, 17, 10, 0)
    assert actual[0].revenue_delta == Decimal("12.50")
    assert actual[0].change_count == 2
    assert actual[1].window.start == datetime(2026, 11, 17, 10, 5)
    assert actual[1].revenue_delta == Decimal("7.00")
    assert actual[1].change_count == 1


def test_streaming_watermark_deduplicates_cdc_and_reports_late_drops(spark, tmp_path):
    schema = StructType(
        [
            StructField("event_time", TimestampType(), False),
            StructField("order_id", StringType(), False),
            StructField("source_lsn", LongType(), True),
            StructField("transaction_order", LongType(), True),
            StructField("payload", StringType(), False),
        ]
    )
    source_dir = tmp_path / "watermark_events"
    source_dir.mkdir()
    query_name = f"w8_watermark_{uuid4().hex}"
    source = (
        spark.readStream.schema(schema)
        .option("maxFilesPerTrigger", 1)
        .json(str(source_dir))
    )
    query = (
        deduplicate_cdc_events(source, watermark_duration="10 minutes")
        .writeStream.format("memory")
        .queryName(query_name)
        .outputMode("append")
        .start()
    )

    def write_batch(filename: str, events: list[dict]):
        (source_dir / filename).write_text(json.dumps(events), encoding="utf-8")
        query.processAllAvailable()

    try:
        anchor = {
            "event_time": "2026-11-17T10:00:00Z",
            "order_id": "anchor",
            "source_lsn": 101,
            "transaction_order": 1,
            "payload": "first",
        }
        write_batch("01-anchor.json", [anchor])
        write_batch(
            "02-replay-and-within.json",
            [
                {**anchor, "payload": "replay"},
                {
                    "event_time": "2026-11-17T09:55:00Z",
                    "order_id": "within",
                    "source_lsn": 102,
                    "transaction_order": 1,
                    "payload": "within",
                },
            ],
        )
        write_batch(
            "03-beyond.json",
            [
                {
                    "event_time": "2026-11-17T09:39:00Z",
                    "order_id": "beyond",
                    "source_lsn": 103,
                    "transaction_order": 1,
                    "payload": "beyond",
                }
            ],
        )

        rows = {
            row.order_id: row.payload
            for row in spark.sql(f"SELECT order_id, payload FROM `{query_name}`").collect()
        }
        assert rows == {"anchor": "first", "within": "within"}
        progress = query.lastProgress or {}
        dropped = [
            int(operator.get("numRowsDroppedByWatermark", 0))
            for operator in progress.get("stateOperators", [])
        ]
        assert any(count > 0 for count in dropped)
    finally:
        query.stop()
