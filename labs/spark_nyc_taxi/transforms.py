"""Hourly pickup-zone aggregates implemented with Spark DataFrames and Spark SQL."""

from __future__ import annotations

from uuid import uuid4

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

try:
    from .quality import QualityContractError, validate_zone_lookup
except ImportError:  # Support direct `python job.py` execution from this directory.
    from quality import QualityContractError, validate_zone_lookup

_AGGREGATE_INPUT_COLUMNS = (
    "pickup_date",
    "pickup_hour",
    "pickup_zone",
    "trip_distance_miles",
    "fare_amount",
    "total_amount",
    "duration_minutes",
)


def _validate_aggregate_input(accepted: DataFrame) -> None:
    missing = [name for name in _AGGREGATE_INPUT_COLUMNS if name not in accepted.columns]
    if missing:
        raise QualityContractError(
            f"accepted trip frame is missing canonical columns: {', '.join(missing)}"
        )


def aggregate_dataframe(
    accepted: DataFrame,
    zone_lookup: DataFrame,
    broadcast_lookup: bool = False,
) -> DataFrame:
    """Join trips to the unique pickup-zone dimension, then aggregate by local hour.

    ``broadcast_lookup=False`` applies a Spark ``MERGE`` hint so the benchmark
    can compare a shuffle join against an explicitly broadcast candidate even
    when the lookup would otherwise fit the automatic broadcast threshold.
    """

    _validate_aggregate_input(accepted)
    zones = validate_zone_lookup(zone_lookup).select(
        F.col("LocationID").alias("_p73_location_id"),
        F.col("Borough").alias("pickup_borough"),
    )
    zones = F.broadcast(zones) if broadcast_lookup else zones.hint("MERGE")
    trips = accepted.alias("trip")
    lookup = zones.alias("zone")
    joined = trips.join(
        lookup,
        F.col("trip.pickup_zone") == F.col("zone._p73_location_id"),
        "inner",
    )
    percentile_values = F.percentile_approx(
        F.col("trip.duration_minutes"), [0.50, 0.95], 10_000
    )
    return (
        joined.groupBy(
            F.col("trip.pickup_date"),
            F.col("trip.pickup_hour"),
            F.col("trip.pickup_zone"),
            F.col("zone.pickup_borough"),
        )
        .agg(
            F.count(F.lit(1)).cast("long").alias("trip_count"),
            F.sum(F.col("trip.trip_distance_miles")).alias("distance_miles_sum"),
            F.sum(F.col("trip.fare_amount")).alias("fare_amount_sum"),
            F.sum(F.col("trip.total_amount")).alias("total_amount_sum"),
            percentile_values.getItem(0).alias("duration_p50_minutes"),
            percentile_values.getItem(1).alias("duration_p95_minutes"),
        )
        .select(
            "pickup_date",
            "pickup_hour",
            "pickup_zone",
            "pickup_borough",
            "trip_count",
            "distance_miles_sum",
            "fare_amount_sum",
            "total_amount_sum",
            "duration_p50_minutes",
            "duration_p95_minutes",
        )
    )


def aggregate_spark_sql(
    spark: SparkSession,
    accepted: DataFrame,
    zone_lookup: DataFrame,
    broadcast_lookup: bool = False,
) -> DataFrame:
    """Spark SQL equivalent of :func:`aggregate_dataframe` over the same frames."""

    _validate_aggregate_input(accepted)
    zones = validate_zone_lookup(zone_lookup).select(
        F.col("LocationID").alias("LocationID"),
        F.col("Borough").alias("Borough"),
    )
    trip_view = f"p73_trips_{uuid4().hex}"
    zone_view = f"p73_zones_{uuid4().hex}"
    accepted.createOrReplaceTempView(trip_view)
    zones.createOrReplaceTempView(zone_view)
    hint = "BROADCAST(z)" if broadcast_lookup else "MERGE(z)"
    return spark.sql(
        f"""
        SELECT /*+ {hint} */
            t.pickup_date AS pickup_date,
            t.pickup_hour AS pickup_hour,
            t.pickup_zone AS pickup_zone,
            z.Borough AS pickup_borough,
            COUNT(1) AS trip_count,
            SUM(t.trip_distance_miles) AS distance_miles_sum,
            SUM(t.fare_amount) AS fare_amount_sum,
            SUM(t.total_amount) AS total_amount_sum,
            percentile_approx(t.duration_minutes, 0.50, 10000)
                AS duration_p50_minutes,
            percentile_approx(t.duration_minutes, 0.95, 10000)
                AS duration_p95_minutes
        FROM `{trip_view}` AS t
        INNER JOIN `{zone_view}` AS z
            ON t.pickup_zone = z.LocationID
        GROUP BY
            t.pickup_date,
            t.pickup_hour,
            t.pickup_zone,
            z.Borough
        """
    )
