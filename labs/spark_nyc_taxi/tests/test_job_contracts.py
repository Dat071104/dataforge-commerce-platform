"""Deterministic local Spark job and publication contract tests."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    DateType,
    DecimalType,
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
)

LAB_DIR = Path(__file__).resolve().parents[1]
if str(LAB_DIR) not in sys.path:
    sys.path.insert(0, str(LAB_DIR))

from labs.spark_nyc_taxi import download  # noqa: E402
from labs.spark_nyc_taxi.job import (  # noqa: E402
    MemoryBudgetError,
    OutputContractError,
    SourceContractError,
    _check_partition_layout,
    _normalize_spark_output_row,
    _reuse_measured_benchmark,
    _verified_existing_output,
    expected_source_paths,
    publish_partitioned_parquet,
    read_tlc_sources,
    validate_memory_budget,
    validate_source_manifest,
    validate_tlc_schema,
)


@pytest.fixture(scope="session")
def spark() -> SparkSession:
    session = (
        SparkSession.builder.master("local[2]")
        .appName("dataforge-week6-job-contract-tests")
        .config("spark.sql.session.timeZone", "America/New_York")
        .config("spark.sql.parquet.inferTimestampNTZ.enabled", "true")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()


@pytest.fixture
def aggregate_schema() -> StructType:
    return StructType(
        [
            StructField("pickup_date", DateType(), nullable=False),
            StructField("pickup_hour", IntegerType(), nullable=False),
            StructField("pickup_zone", IntegerType(), nullable=False),
            StructField("pickup_borough", StringType(), nullable=False),
            StructField("trip_count", LongType(), nullable=False),
            StructField("distance_miles_sum", DecimalType(18, 3), nullable=True),
            StructField("fare_amount_sum", DecimalType(18, 2), nullable=True),
            StructField("total_amount_sum", DecimalType(18, 2), nullable=True),
            StructField("duration_p50_minutes", DoubleType(), nullable=True),
            StructField("duration_p95_minutes", DoubleType(), nullable=True),
        ]
    )


def _manifest_entry(path: Path, url: str) -> dict[str, object]:
    return {
        "name": path.name,
        "source_url": url,
        "local_path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "status": "CAPTURED_FOR_TEST",
        "row_count": "NOT_RUN",
    }


def test_missing_source_file_fails_before_spark_read(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="required TLC source file is missing"):
        expected_source_paths(tmp_path)


def test_corrupt_parquet_fails_closed(spark: SparkSession, tmp_path: Path):
    corrupt = tmp_path / "yellow_tripdata_2024-01.parquet"
    corrupt.write_bytes(b"not a Parquet footer")
    with pytest.raises(SourceContractError, match="cannot read Parquet schema"):
        read_tlc_sources(spark, [corrupt])


def test_wrong_schema_and_unexpected_schema_version_fail_closed(spark: SparkSession):
    wrong = spark.createDataFrame([(1,)], ["VendorID"])
    with pytest.raises(SourceContractError, match="unexpected TLC Parquet field set/order"):
        validate_tlc_schema(wrong.schema)


def test_source_manifest_hash_and_schema_period_are_verified(tmp_path: Path):
    trip_paths = []
    entries = []
    for month in (1, 2, 3, 4):
        trip_path = tmp_path / f"yellow_tripdata_2024-{month:02d}.parquet"
        trip_path.write_bytes(f"verified-fixture-{month}".encode())
        trip_paths.append(trip_path)
        entries.append(
            _manifest_entry(trip_path, download.monthly_url(2024, month))
        )
    zone_path = tmp_path / "taxi_zone_lookup.csv"
    zone_path.write_text("LocationID,Borough,Zone,service_zone\n", encoding="utf-8")
    entries.append(_manifest_entry(zone_path, download.ZONE_LOOKUP_URL))
    (tmp_path / download.MANIFEST_NAME).write_text(
        json.dumps(
            {
                "status": "COMPLETE",
                "source_page_url": download.TLC_PAGE_URL,
                "schema_period": "2024-01 through 2024-04",
                "files": entries,
            }
        ),
        encoding="utf-8",
    )

    manifest, manifest_hash = validate_source_manifest(tmp_path, trip_paths, zone_path)
    assert manifest["status"] == "COMPLETE"
    assert len(manifest_hash) == 64

    trip_paths[2].write_bytes(b"changed source bytes")
    with pytest.raises(SourceContractError, match="byte count differs|SHA-256 differs"):
        validate_source_manifest(tmp_path, trip_paths, zone_path)


def test_low_memory_budget_refuses_to_start_without_oom():
    with pytest.raises(MemoryBudgetError, match="exceeds container limit"):
        validate_memory_budget(available_gib=1.0, required_gib=4.0)
    validate_memory_budget(available_gib=6.0, required_gib=4.0)


def test_spark_date_keys_normalize_for_independent_oracle_comparison():
    row = _normalize_spark_output_row({"pickup_date": date(2024, 1, 15), "trip_count": 1})
    assert row == {"pickup_date": "2024-01-15", "trip_count": 1}


def test_bad_partition_layout_is_rejected(tmp_path: Path):
    (tmp_path / "part-00000.parquet").write_bytes(b"not inspected by layout check")
    with pytest.raises(OutputContractError, match="not stored under one pickup_date partition"):
        _check_partition_layout(tmp_path)


def test_partitioned_parquet_is_staged_idempotent_and_handles_empty_day(
    spark: SparkSession, aggregate_schema: StructType, tmp_path: Path
):
    source = spark.createDataFrame(
        [
            (
                date(2024, 1, 15),
                10,
                1,
                "Manhattan",
                2,
                Decimal("3.250"),
                Decimal("20.00"),
                Decimal("24.00"),
                10.0,
                20.0,
            ),
            (
                date(2024, 1, 16),
                11,
                2,
                "Queens",
                1,
                Decimal("1.500"),
                Decimal("7.00"),
                Decimal("9.00"),
                4.0,
                6.0,
            ),
        ],
        aggregate_schema,
    )
    output_path, receipt = publish_partitioned_parquet(
        spark,
        source,
        tmp_path / "output",
        run_id="fixture-run-1",
        source_manifest_sha256="a" * 64,
        input_rows=3,
        accepted_rows=3,
        output_partitions=2,
    )
    assert receipt["status"] == "COMPLETE"
    assert receipt["partition_count"] == 2
    assert receipt["file_count"] == 2

    replay_path, replay_receipt = publish_partitioned_parquet(
        spark,
        source,
        tmp_path / "output",
        run_id="fixture-run-1",
        source_manifest_sha256="a" * 64,
        input_rows=3,
        accepted_rows=3,
        output_partitions=2,
    )
    assert replay_path == output_path
    assert replay_receipt["replay_status"] == "VERIFIED_NO_OP"

    empty_day_count = (
        spark.read.parquet(str(output_path / "parquet"))
        .filter("pickup_date = DATE '2024-01-17'")
        .count()
    )
    assert empty_day_count == 0

    with pytest.raises(OutputContractError, match="stale for the current source manifest"):
        publish_partitioned_parquet(
            spark,
            source,
            tmp_path / "output",
            run_id="fixture-run-1",
            source_manifest_sha256="b" * 64,
            input_rows=3,
            accepted_rows=3,
            output_partitions=2,
        )


def test_partial_or_stale_output_manifest_is_rejected(tmp_path: Path):
    output = tmp_path / "runs" / "partial-run"
    output.mkdir(parents=True)
    (output / "MANIFEST.json").write_text(
        json.dumps({"status": "IN_PROGRESS", "run_id": "partial-run"}),
        encoding="utf-8",
    )
    with pytest.raises(OutputContractError, match="status must be COMPLETE"):
        _verified_existing_output(
            output,
            run_id="partial-run",
            source_manifest_sha256="a" * 64,
            input_rows=1,
            accepted_rows=1,
            expected_schema=[],
        )


def test_reuse_benchmark_requires_matching_context_and_preserves_eventlog_plans(
    tmp_path: Path,
):
    source = tmp_path / "source" / "benchmark.json"
    source.parent.mkdir(parents=True)
    context = {
        "status": "COMPLETE",
        "run_id": "source-run",
        "source_manifest_sha256": "a" * 64,
        "input_rows": 100,
        "spark_version": "3.5.9",
        "shuffle_partitions": 96,
        "warmups": 1,
        "repetitions": 2,
        "session_timezone": "America/New_York",
        "master": "local[4]",
    }
    report = {
        "status": "LOCAL_MEASURED",
        "runtime": {"application_id": "local-source"},
        "experiment": {
            "correctness_parity": {"status": "PENDING_TOLERANCE_RECHECK"},
            "physical_plan_evidence": {
                "candidate_broadcast_hash_join_present": True,
                "baseline_broadcast_hash_join_present": False,
            },
        },
        "variants": {
            "baseline": {"warmup_count": 1, "timed_runs_seconds": [1.0, 2.0]},
            "broadcast_candidate": {
                "warmup_count": 1,
                "timed_runs_seconds": [1.5, 2.5],
            },
        },
    }
    source.write_text(json.dumps(report), encoding="utf-8")
    (source.parent / "benchmark_context.json").write_text(
        json.dumps(context), encoding="utf-8"
    )
    (source.parent / "spark_plan_baseline.txt").write_text("SortMergeJoin", encoding="utf-8")
    (source.parent / "spark_plan_candidate.txt").write_text(
        "BroadcastHashJoin", encoding="utf-8"
    )

    recovered, receipt = _reuse_measured_benchmark(
        source,
        tmp_path / "destination",
        source_manifest_sha256="a" * 64,
        input_rows=100,
        spark_version="3.5.9",
        shuffle_partitions=96,
        warmups=1,
        repetitions=2,
    )
    assert recovered["status"] == "LOCAL_MEASURED"
    assert receipt["status"] == "REUSED_VERIFIED"
    assert (tmp_path / "destination" / "spark_plan_baseline.txt").read_text() == "SortMergeJoin"

    context["source_manifest_sha256"] = "b" * 64
    (source.parent / "benchmark_context.json").write_text(
        json.dumps(context), encoding="utf-8"
    )
    with pytest.raises(OutputContractError, match="context does not match"):
        _reuse_measured_benchmark(
            source,
            tmp_path / "other",
            source_manifest_sha256="a" * 64,
            input_rows=100,
            spark_version="3.5.9",
            shuffle_partitions=96,
            warmups=1,
            repetitions=2,
        )
