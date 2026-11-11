"""Small deterministic Spark tests; the lead runs these in the pinned container."""

from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StructField,
    StructType,
    TimestampNTZType,
)

LAB_DIR = Path(__file__).resolve().parents[1]
if str(LAB_DIR) not in sys.path:
    sys.path.insert(0, str(LAB_DIR))

from quality import (  # noqa: E402
    QualityContractError,
    apply_quality_policy,
    diagnose_duplicate_like_rows,
    validate_zone_lookup,
)
from transforms import aggregate_dataframe, aggregate_spark_sql  # noqa: E402


@pytest.fixture(scope="session")
def spark() -> SparkSession:
    session = (
        SparkSession.builder.master("local[2]")
        .appName("dataforge-week6-transform-tests")
        .config("spark.sql.session.timeZone", "America/New_York")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()


@pytest.fixture
def zones(spark: SparkSession):
    rows = [
        (location_id, "Manhattan" if location_id % 2 else "Queens")
        for location_id in range(1, 264)
    ]
    return spark.createDataFrame(rows, ["LocationID", "Borough"])


@pytest.fixture
def raw_schema() -> StructType:
    return StructType(
        [
            StructField("VendorID", IntegerType(), True),
            StructField("tpep_pickup_datetime", TimestampNTZType(), True),
            StructField("tpep_dropoff_datetime", TimestampNTZType(), True),
            StructField("passenger_count", IntegerType(), True),
            StructField("trip_distance", DoubleType(), True),
            StructField("PULocationID", IntegerType(), True),
            StructField("DOLocationID", IntegerType(), True),
            StructField("fare_amount", DoubleType(), True),
            StructField("total_amount", DoubleType(), True),
            StructField("extra", DoubleType(), True),
            StructField("Airport_fee", DoubleType(), True),
        ]
    )


def _row(
    pickup: datetime | None,
    dropoff: datetime | None,
    *,
    pickup_zone: int | None = 1,
    dropoff_zone: int | None = 2,
    distance: float | None = 1.0,
    fare: float | None = 10.0,
    total: float | None = 12.0,
    extra: float | None = 0.0,
) -> tuple[object, ...]:
    def as_double(value: float | int | None) -> float | None:
        return None if value is None else float(value)

    return (
        2,
        pickup,
        dropoff,
        1,
        as_double(distance),
        pickup_zone,
        dropoff_zone,
        as_double(fare),
        as_double(total),
        as_double(extra),
        0.0,
    )


def _policy(spark: SparkSession, rows: list[tuple[object, ...]], raw_schema, zones):
    raw = spark.createDataFrame(rows, schema=raw_schema)
    return apply_quality_policy(raw, zones, "2024-01-01", "2024-05-01")


def test_quality_ledger_rejects_anomalies_but_keeps_negative_amounts(
    spark, raw_schema, zones
):
    frames = _policy(
        spark,
        [
            _row(datetime(2024, 1, 10, 10), datetime(2024, 1, 10, 10, 30), distance=1.25),
            _row(
                datetime(2024, 1, 10, 10, 15),
                datetime(2024, 1, 10, 10, 45),
                distance=2.0,
                fare=-2.50,
                total=-1.25,
                extra=-0.50,
            ),
            _row(
                datetime(2024, 1, 10, 11),
                datetime(2024, 1, 10, 11, 10),
                distance=0,
            ),
            _row(
                datetime(2024, 1, 10, 11),
                datetime(2024, 1, 10, 11, 10),
                pickup_zone=264,
            ),
            _row(
                datetime(2023, 12, 31, 23, 50),
                datetime(2024, 1, 1, 0, 5),
            ),
            _row(datetime(2024, 3, 10, 1, 50), datetime(2024, 3, 10, 3, 10)),
            _row(datetime(2024, 3, 10, 2, 30), datetime(2024, 3, 10, 3, 30)),
            _row(datetime(2024, 11, 3, 1, 30), datetime(2024, 11, 3, 2, 30)),
            _row(
                datetime(2024, 1, 11, 10),
                datetime(2024, 1, 11, 10, 30),
                total=None,
            ),
        ],
        raw_schema,
        zones,
    )

    assert frames.input_rows == 9
    assert frames.accepted_rows == 2
    assert frames.rejected_rows == 7
    assert frames.accepted_rows + frames.rejected_rows == frames.input_rows

    accepted_rows = frames.accepted.orderBy("pickup_ts").collect()
    assert accepted_rows[0]["negative_amount_flag"] is False
    assert accepted_rows[1]["negative_amount_flag"] is True
    assert accepted_rows[1]["fare_amount"] == Decimal("-2.50")
    assert accepted_rows[1]["total_amount"] == Decimal("-1.25")

    first_reasons = {
        record["metric"].removeprefix("first_"): int(record["row_count"])
        for record in frames.ledger.collect()
        if record["category"] == "exclusive_rejection_reason"
    }
    assert first_reasons["nonpositive_distance"] == 1
    assert first_reasons["unknown_zone"] == 1
    assert first_reasons["outside_pickup_period"] == 2
    assert first_reasons["dst_gap_fold_or_crossing"] == 2
    assert first_reasons["missing_critical"] == 1

    ledger = {row["metric"]: int(row["row_count"]) for row in frames.ledger.collect()}
    assert ledger["negative_amount_review_rows"] == 1
    assert ledger["accepted_plus_rejected"] == ledger["input_rows"]


def test_df_and_sql_aggregates_match_and_do_not_multiply_rows(spark, raw_schema, zones):
    frames = _policy(
        spark,
        [
            _row(datetime(2024, 1, 10, 10), datetime(2024, 1, 10, 10, 30), distance=1.25),
            _row(
                datetime(2024, 1, 10, 10, 15),
                datetime(2024, 1, 10, 10, 45),
                distance=2.0,
                fare=-2.50,
                total=-1.25,
                extra=-0.50,
            ),
            _row(datetime(2024, 1, 10, 10, 20), datetime(2024, 1, 10, 10, 50)),
        ],
        raw_schema,
        zones,
    )

    dataframe_result = aggregate_dataframe(frames.accepted, zones, broadcast_lookup=False)
    sql_result = aggregate_spark_sql(spark, frames.accepted, zones, broadcast_lookup=False)
    df_rows = [row.asDict() for row in dataframe_result.orderBy("pickup_date", "pickup_hour", "pickup_zone").collect()]
    sql_rows = [row.asDict() for row in sql_result.orderBy("pickup_date", "pickup_hour", "pickup_zone").collect()]

    assert df_rows == sql_rows
    assert len(df_rows) == 1
    output = df_rows[0]
    assert output["trip_count"] == frames.accepted_rows == 3
    assert output["pickup_borough"] == "Manhattan"
    assert output["distance_miles_sum"] == Decimal("4.250")
    assert output["fare_amount_sum"] == Decimal("17.50")
    assert output["total_amount_sum"] == Decimal("22.75")


def test_zone_lookup_rejects_duplicate_or_incomplete_dimension(spark, zones):
    duplicate = zones.unionByName(spark.createDataFrame([(1, "Brooklyn")], zones.schema))
    with pytest.raises(QualityContractError, match="duplicate LocationID"):
        validate_zone_lookup(duplicate)

    incomplete = zones.filter("LocationID != 263")
    with pytest.raises(QualityContractError, match="each assigned LocationID 1..263"):
        validate_zone_lookup(incomplete)


def test_quality_policy_requires_new_york_session_timezone(spark, raw_schema, zones):
    previous = spark.conf.get("spark.sql.session.timeZone")
    raw = spark.createDataFrame([], raw_schema)
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    try:
        with pytest.raises(QualityContractError, match="session time zone must be America/New_York"):
            apply_quality_policy(raw, zones, "2024-01-01", "2024-05-01")
    finally:
        spark.conf.set("spark.sql.session.timeZone", previous)


def test_quality_policy_rejects_fall_back_ambiguous_local_time(spark, raw_schema, zones):
    raw = spark.createDataFrame(
        [
            _row(
                datetime(2024, 11, 3, 1, 30),
                datetime(2024, 11, 3, 1, 45),
            )
        ],
        schema=raw_schema,
    )
    frames = apply_quality_policy(raw, zones, "2024-11-01", "2024-12-01")
    assert frames.input_rows == 1
    assert frames.accepted_rows == 0
    assert frames.rejected_rows == 1
    reasons = {row["metric"]: row["row_count"] for row in frames.ledger.collect()}
    assert reasons["first_dst_gap_fold_or_crossing"] == 1


def test_pickup_period_allows_valid_dropoff_across_month_boundary(spark, raw_schema, zones):
    frames = _policy(
        spark,
        [
            _row(
                datetime(2024, 4, 30, 23, 55),
                datetime(2024, 5, 1, 0, 5),
            )
        ],
        raw_schema,
        zones,
    )
    assert frames.input_rows == 1
    assert frames.accepted_rows == 1
    assert frames.rejected_rows == 0
    accepted = frames.accepted.first()
    assert str(accepted["pickup_date"]) == "2024-04-30"
    assert accepted["duration_minutes"] == pytest.approx(10.0)


def test_full_row_duplicate_fingerprint_is_diagnostic_only(spark, raw_schema):
    row = _row(datetime(2024, 1, 10, 10), datetime(2024, 1, 10, 10, 30))
    raw = spark.createDataFrame([row, row], raw_schema)
    diagnostic = diagnose_duplicate_like_rows(raw).first()
    assert raw.count() == 2
    assert diagnostic["duplicate_like_extra_rows"] == 1
    assert diagnostic["duplicate_like_group_members"] == 2
    assert diagnostic["duplicate_like_signature_groups"] == 1
