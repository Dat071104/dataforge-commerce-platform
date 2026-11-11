"""Small deterministic checks for the controlled Spark benchmark harness."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    BooleanType,
    DateType,
    DecimalType,
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampNTZType,
)

from labs.spark_nyc_taxi.benchmark import (
    BenchmarkSettings,
    _compare_aggregate_frames,
    run_benchmark,
)


@pytest.fixture(scope="session")
def spark() -> SparkSession:
    session = (
        SparkSession.builder.master("local[2]")
        .appName("dataforge-week6-benchmark-tests")
        .config("spark.sql.session.timeZone", "America/New_York")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.autoBroadcastJoinThreshold", "-1")
        .config("spark.sql.adaptive.autoBroadcastJoinThreshold", "-1")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()


def test_benchmark_runs_both_join_plans_and_records_job_group_metrics(
    spark: SparkSession, tmp_path
):
    accepted_schema = StructType(
        [
            StructField("pickup_ts", TimestampNTZType(), True),
            StructField("dropoff_ts", TimestampNTZType(), True),
            StructField("pickup_date", DateType(), True),
            StructField("pickup_hour", IntegerType(), True),
            StructField("pickup_zone", IntegerType(), True),
            StructField("dropoff_zone", IntegerType(), True),
            StructField("trip_distance_miles", DecimalType(18, 3), True),
            StructField("fare_amount", DecimalType(18, 2), True),
            StructField("total_amount", DecimalType(18, 2), True),
            StructField("duration_minutes", DoubleType(), True),
            StructField("negative_amount_flag", BooleanType(), True),
        ]
    )
    accepted = spark.createDataFrame(
        [
            (
                None,
                None,
                date(2024, 1, 15),
                10,
                1,
                2,
                Decimal("1.200"),
                Decimal("10.00"),
                Decimal("12.00"),
                10.0,
                False,
            ),
            (
                None,
                None,
                date(2024, 1, 15),
                10,
                1,
                3,
                Decimal("2.300"),
                Decimal("20.00"),
                Decimal("24.00"),
                15.0,
                False,
            ),
        ],
        accepted_schema,
    )
    zones = spark.createDataFrame(
        [
            (location_id, "Manhattan" if location_id == 1 else "Queens")
            for location_id in range(1, 264)
        ],
        ["LocationID", "Borough"],
    )

    report = run_benchmark(
        spark,
        accepted,
        zones,
        tmp_path / "benchmark",
        settings=BenchmarkSettings(warmups=1, repetitions=1, shuffle_partitions=2),
    )

    assert report["experiment"]["correctness_parity"]["status"] == "PASS"
    assert report["experiment"]["physical_plan_evidence"][
        "candidate_broadcast_hash_join_present"
    ]
    assert not report["experiment"]["physical_plan_evidence"][
        "baseline_broadcast_hash_join_present"
    ]
    assert report["variants"]["baseline"]["warmup_count"] == 1
    assert report["variants"]["broadcast_candidate"]["warmup_count"] == 1
    assert len(report["variants"]["baseline"]["timed_runs_seconds"]) == 1
    assert len(report["variants"]["broadcast_candidate"]["timed_runs_seconds"]) == 1
    assert (tmp_path / "benchmark" / "benchmark.json").is_file()


def test_benchmark_parity_keeps_exact_money_and_tolerates_approximate_percentiles(
    spark: SparkSession,
):
    schema = StructType(
        [
            StructField("pickup_date", DateType(), False),
            StructField("pickup_hour", IntegerType(), False),
            StructField("pickup_zone", IntegerType(), False),
            StructField("pickup_borough", StringType(), False),
            StructField("trip_count", LongType(), False),
            StructField("distance_miles_sum", DecimalType(18, 3), True),
            StructField("fare_amount_sum", DecimalType(18, 2), True),
            StructField("total_amount_sum", DecimalType(18, 2), True),
            StructField("duration_p50_minutes", DoubleType(), True),
            StructField("duration_p95_minutes", DoubleType(), True),
        ]
    )
    baseline = spark.createDataFrame(
        [(date(2024, 1, 15), 10, 1, "Manhattan", 2, Decimal("3.500"), Decimal("30.00"), Decimal("36.00"), 10.0, 20.0)],
        schema,
    )
    candidate_with_tolerable_percentiles = spark.createDataFrame(
        [(date(2024, 1, 15), 10, 1, "Manhattan", 2, Decimal("3.500"), Decimal("30.00"), Decimal("36.00"), 10.5, 20.9)],
        schema,
    )
    candidate_with_wrong_money = spark.createDataFrame(
        [(date(2024, 1, 15), 10, 1, "Manhattan", 2, Decimal("3.500"), Decimal("30.01"), Decimal("36.00"), 10.5, 20.9)],
        schema,
    )

    tolerated = _compare_aggregate_frames(
        baseline,
        candidate_with_tolerable_percentiles,
        duration_tolerance_minutes=1.0,
    )
    failed_exact_money = _compare_aggregate_frames(
        baseline,
        candidate_with_wrong_money,
        duration_tolerance_minutes=1.0,
    )
    assert tolerated["status"] == "PASS"
    assert tolerated["max_duration_p95_minutes_delta_minutes"] == pytest.approx(0.9)
    assert failed_exact_money["status"] == "FAIL"
    assert failed_exact_money["exact_metric_mismatch_rows"] == 1
