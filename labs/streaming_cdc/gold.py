"""Replay-safe Delta materialization for CDC revenue-window contributions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_signed_revenue_legs(events_df: Any) -> Any:
    """Expand each order CDC event into signed before/after revenue legs."""
    required = {
        "event_time",
        "order_id",
        "source_lsn",
        "transaction_order",
        "op",
        "before_province_id",
        "before_order_net_amount",
        "after_province_id",
        "after_order_net_amount",
    }
    missing = sorted(required - set(events_df.columns))
    if missing:
        raise ValueError(f"CDC event input is missing revenue columns: {missing}")

    from pyspark.sql import functions as F

    before = (
        events_df.filter(
            F.col("before_province_id").isNotNull()
            & F.col("before_order_net_amount").isNotNull()
        )
        .select(
            "event_time",
            "order_id",
            "source_lsn",
            "transaction_order",
            F.lit("before").alias("leg"),
            F.col("before_province_id").alias("province_id"),
            (-F.col("before_order_net_amount")).alias("revenue_delta"),
        )
    )
    after = (
        events_df.filter(
            F.col("after_province_id").isNotNull()
            & F.col("after_order_net_amount").isNotNull()
        )
        .select(
            "event_time",
            "order_id",
            "source_lsn",
            "transaction_order",
            F.lit("after").alias("leg"),
            F.col("after_province_id").alias("province_id"),
            F.col("after_order_net_amount").alias("revenue_delta"),
        )
    )
    legs = before.unionByName(after)
    identity = F.struct(
        "order_id",
        "source_lsn",
        "transaction_order",
        "event_time",
        "leg",
        "province_id",
        "revenue_delta",
    )
    return legs.withColumn("event_id", F.sha2(F.to_json(identity), 256))


def merge_gold_revenue_batch(
    batch_df: Any,
    target_path: str | Path,
    changes_path: str | Path,
    *,
    window_duration: str = "5 minutes",
) -> bool:
    """Merge recomputed window totals by (window, province), safely on replay.

    The Delta change ledger is merged by deterministic event-leg ID first. The
    aggregate is then recomputed for affected windows and written as a replace
    value, so replaying a batch cannot add its revenue twice.
    """
    from delta.tables import DeltaTable
    from pyspark.sql import functions as F

    legs = build_signed_revenue_legs(batch_df).dropDuplicates(["event_id"])
    if legs.rdd.isEmpty():
        return False

    spark = legs.sparkSession
    target = str(target_path)
    changes = str(changes_path)
    if not DeltaTable.isDeltaTable(spark, changes):
        legs.limit(0).write.format("delta").mode("errorifexists").save(changes)
    (
        DeltaTable.forPath(spark, changes)
        .alias("t")
        .merge(legs.alias("s"), "t.event_id = s.event_id")
        .whenNotMatchedInsertAll()
        .execute()
    )

    windowed_legs = (
        legs.withColumn("window_start", F.window("event_time", window_duration).getField("start"))
        .withColumn("window_end", F.window("event_time", window_duration).getField("end"))
    )
    affected = windowed_legs.select("window_start", "window_end", "province_id").distinct()
    all_legs = (
        spark.read.format("delta")
        .load(changes)
        .withColumn("window_start", F.window("event_time", window_duration).getField("start"))
        .withColumn("window_end", F.window("event_time", window_duration).getField("end"))
    )
    totals = (
        all_legs.alias("e")
        .join(
            affected.alias("a"),
            (F.col("e.window_start") == F.col("a.window_start"))
            & (F.col("e.window_end") == F.col("a.window_end"))
            & (F.col("e.province_id") == F.col("a.province_id")),
            "inner",
        )
        .groupBy(
            F.col("e.window_start").alias("window_start"),
            F.col("e.window_end").alias("window_end"),
            F.col("e.province_id").alias("province_id"),
        )
        .agg(
            F.sum("e.revenue_delta").alias("revenue_delta"),
            F.count("e.event_id").cast("long").alias("change_count"),
        )
    )
    if totals.rdd.isEmpty():
        return False
    if not DeltaTable.isDeltaTable(spark, target):
        totals.limit(0).write.format("delta").mode("errorifexists").save(target)

    update_columns = ["window_start", "window_end", "province_id", "revenue_delta", "change_count"]
    values = {column: f"s.`{column}`" for column in update_columns}
    condition = (
        "t.window_start = s.window_start AND t.window_end = s.window_end "
        "AND t.province_id = s.province_id"
    )
    (
        DeltaTable.forPath(spark, target)
        .alias("t")
        .merge(totals.alias("s"), condition)
        .whenMatchedUpdate(set=values)
        .whenNotMatchedInsert(values=values)
        .execute()
    )
    return True
