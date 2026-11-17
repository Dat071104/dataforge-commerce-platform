"""Bounded event-time revenue aggregation for the Week 8 gold sink."""

from __future__ import annotations

from typing import Any


def deduplicate_cdc_events(
    events_df: Any,
    *,
    event_time_column: str = "event_time",
    watermark_duration: str = "10 minutes",
) -> Any:
    """Bound CDC replay-dedup state by event time and source identity."""
    required = {
        event_time_column,
        "order_id",
        "source_lsn",
        "transaction_order",
    }
    missing = sorted(required - set(events_df.columns))
    if missing:
        raise ValueError(f"CDC event input is missing deduplication columns: {missing}")
    if not watermark_duration.strip():
        raise ValueError("watermark duration must be non-empty")
    return events_df.withWatermark(event_time_column, watermark_duration).dropDuplicatesWithinWatermark(
        ["order_id", "source_lsn", "transaction_order"]
    )


def build_windowed_revenue(
    events_df: Any,
    *,
    event_time_column: str = "event_time",
    revenue_delta_column: str = "revenue_delta",
    window_duration: str = "5 minutes",
    watermark_duration: str = "10 minutes",
) -> Any:
    """Aggregate signed CDC revenue changes into watermark-bounded windows."""
    required = {event_time_column, revenue_delta_column, "province_id"}
    missing = sorted(required - set(events_df.columns))
    if missing:
        raise ValueError(f"revenue input is missing columns: {missing}")
    if not window_duration.strip() or not watermark_duration.strip():
        raise ValueError("window and watermark durations must be non-empty")

    from pyspark.sql import functions as F

    return (
        events_df.withWatermark(event_time_column, watermark_duration)
        .groupBy(
            F.window(F.col(event_time_column), window_duration).alias("window"),
            F.col("province_id"),
        )
        .agg(
            F.sum(F.col(revenue_delta_column)).alias("revenue_delta"),
            F.count(F.lit(1)).alias("change_count"),
        )
    )
