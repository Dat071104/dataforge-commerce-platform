from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pyspark.sql.types import DecimalType, StringType, StructField, StructType, TimestampType

from labs.streaming_cdc.windows import build_windowed_revenue


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
