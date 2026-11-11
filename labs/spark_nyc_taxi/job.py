"""Run the reproducible local Week-6 NYC TLC Spark lab."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from . import download
from .benchmark import BenchmarkSettings, _compare_aggregate_frames, run_benchmark
from .oracle import run_oracle
from .quality import (
    QualityContractError,
    QualityFrames,
    apply_quality_policy,
    diagnose_duplicate_like_rows,
    validate_zone_lookup,
)
from .spark_session import create_spark
from .table_format import run_delta_table_demo
from .transforms import aggregate_dataframe, aggregate_spark_sql

PERIOD_START = date(2024, 1, 1)
PERIOD_END = date(2024, 5, 1)
DEFAULT_MONTHS = (1, 2, 3, 4)
TIME_ZONE = "America/New_York"
EXPECTED_COLUMNS = (
    "VendorID",
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "passenger_count",
    "trip_distance",
    "RatecodeID",
    "store_and_fwd_flag",
    "PULocationID",
    "DOLocationID",
    "payment_type",
    "fare_amount",
    "extra",
    "mta_tax",
    "tip_amount",
    "tolls_amount",
    "improvement_surcharge",
    "total_amount",
    "congestion_surcharge",
    "Airport_fee",
)
EXPECTED_TYPES = {
    "VendorID": "int",
    "tpep_pickup_datetime": "timestamp_ntz",
    "tpep_dropoff_datetime": "timestamp_ntz",
    "passenger_count": "bigint",
    "trip_distance": "double",
    "RatecodeID": "bigint",
    "store_and_fwd_flag": "string",
    "PULocationID": "int",
    "DOLocationID": "int",
    "payment_type": "bigint",
    "fare_amount": "double",
    "extra": "double",
    "mta_tax": "double",
    "tip_amount": "double",
    "tolls_amount": "double",
    "improvement_surcharge": "double",
    "total_amount": "double",
    "congestion_surcharge": "double",
    "Airport_fee": "double",
}
OUTPUT_KEYS = ("pickup_date", "pickup_hour", "pickup_zone")


class SourceContractError(ValueError):
    """Raised when a source file or receipt violates the pinned TLC contract."""


class OutputContractError(ValueError):
    """Raised when an output is incomplete, stale, or not partitioned as expected."""


class MemoryBudgetError(ValueError):
    """Raised before Spark starts when the selected workload exceeds its memory cap."""


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "asDict"):
        return {key: _json_value(item) for key, item in value.asDict(recursive=True).items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _normalize_spark_output_row(row: Any) -> dict[str, Any]:
    """Convert Spark's DateType key to the Oracle's ISO-date representation."""

    values = row.asDict(recursive=True) if hasattr(row, "asDict") else dict(row)
    pickup_date = values.get("pickup_date")
    if isinstance(pickup_date, datetime):
        values["pickup_date"] = pickup_date.date().isoformat()
    elif isinstance(pickup_date, date):
        values["pickup_date"] = pickup_date.isoformat()
    return values


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    body = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def expected_source_paths(
    raw_dir: str | Path, months: Iterable[int] = DEFAULT_MONTHS
) -> tuple[list[Path], Path]:
    """Return fixed 2024 source paths, failing early for missing/empty files."""

    root = Path(raw_dir).expanduser().resolve()
    selected = tuple(months)
    if selected != tuple(sorted(set(selected))) or not selected:
        raise SourceContractError("months must be a sorted, non-empty, unique sequence")
    trip_paths: list[Path] = []
    for month in selected:
        name = f"yellow_tripdata_2024-{month:02d}.parquet"
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f"required TLC source file is missing: {path}")
        if path.stat().st_size == 0:
            raise SourceContractError(f"required TLC source file is empty: {path}")
        trip_paths.append(path)
    zone_path = root / "taxi_zone_lookup.csv"
    if not zone_path.is_file():
        raise FileNotFoundError(f"required official TLC zone lookup is missing: {zone_path}")
    if zone_path.stat().st_size == 0:
        raise SourceContractError(f"official TLC zone lookup is empty: {zone_path}")
    return trip_paths, zone_path


def validate_source_manifest(
    raw_dir: str | Path,
    trip_paths: list[Path],
    zone_path: Path,
) -> tuple[dict[str, Any], str]:
    """Rehash downloaded inputs against the atomic local acquisition manifest."""

    root = Path(raw_dir).expanduser().resolve()
    manifest_path = root / download.MANIFEST_NAME
    if not manifest_path.is_file():
        raise SourceContractError(
            f"official source acquisition receipt is missing: {manifest_path}; "
            "run download.py or create a receipt from a verified acquisition"
        )
    raw_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise SourceContractError(f"source manifest is invalid JSON: {manifest_path}") from exc
    if manifest.get("status") != "COMPLETE":
        raise SourceContractError("source manifest status must be COMPLETE")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise SourceContractError("source manifest must contain a files array")
    entries_by_name = {entry.get("name"): entry for entry in entries if isinstance(entry, dict)}
    required_paths = [*trip_paths, zone_path]
    expected_count = len(required_paths)
    if len(entries_by_name) != expected_count:
        raise SourceContractError(
            f"source manifest must contain exactly {expected_count} selected files"
        )

    for path in required_paths:
        entry = entries_by_name.get(path.name)
        if entry is None:
            raise SourceContractError(f"source manifest is missing {path.name}")
        expected_url = (
            download.ZONE_LOOKUP_URL
            if path.name == "taxi_zone_lookup.csv"
            else download.monthly_url(2024, int(Path(path.name).stem.split("-")[-1]))
        )
        if entry.get("source_url") != expected_url:
            raise SourceContractError(f"unexpected source URL for {path.name}")
        actual_size = path.stat().st_size
        if int(entry.get("bytes", -1)) != actual_size:
            raise SourceContractError(f"source manifest byte count differs for {path.name}")
        actual_sha = _sha256_file(path)
        if entry.get("sha256") != actual_sha:
            raise SourceContractError(f"source manifest SHA-256 differs for {path.name}")
        if entry.get("row_count", "NOT_RUN") not in ("NOT_RUN", None):
            # The acquisition manifest is immutable source evidence. Spark's
            # materialized count belongs in the run receipt, not this file.
            raise SourceContractError(
                f"source manifest row_count must remain NOT_RUN for {path.name}"
            )

    return manifest, _canonical_json_sha256(raw_bytes)


def schema_receipt(schema: Any) -> list[dict[str, str]]:
    return [{"name": field.name, "type": field.dataType.simpleString()} for field in schema.fields]


def arrow_schema_receipt(schema: Any) -> list[dict[str, str]]:
    return [{"name": field.name, "type": str(field.type)} for field in schema]


def validate_tlc_schema(schema: Any, source_name: str = "TLC Parquet") -> None:
    """Fail closed on missing columns, unexpected fields, or 2025 schema drift."""

    observed_names = tuple(field.name for field in schema.fields)
    if observed_names != EXPECTED_COLUMNS:
        missing = sorted(set(EXPECTED_COLUMNS).difference(observed_names))
        extra = sorted(set(observed_names).difference(EXPECTED_COLUMNS))
        raise SourceContractError(
            f"unexpected {source_name} field set/order; missing={missing}, extra={extra}, "
            f"observed={observed_names}"
        )
    observed_types = {field.name: field.dataType.simpleString() for field in schema.fields}
    mismatches = {
        name: {"expected": expected, "observed": observed_types[name]}
        for name, expected in EXPECTED_TYPES.items()
        if observed_types[name] != expected
    }
    if mismatches:
        raise SourceContractError(f"unexpected {source_name} column types: {mismatches}")


def read_tlc_sources(spark: Any, trip_paths: list[Path]) -> Any:
    """Inspect each Parquet footer, require schema equality, then build one DataFrame."""

    reference_schema = None
    for path in trip_paths:
        try:
            schema = spark.read.parquet(str(path)).schema
        except Exception as exc:
            raise SourceContractError(f"cannot read Parquet schema from {path.name}: {exc}") from exc
        validate_tlc_schema(schema, path.name)
        if reference_schema is None:
            reference_schema = schema
        elif schema.json() != reference_schema.json():
            raise SourceContractError(f"monthly schema differs from first file: {path.name}")
    try:
        frame = spark.read.parquet(*[str(path) for path in trip_paths])
    except Exception as exc:
        raise SourceContractError(f"Spark could not read the selected TLC Parquet files: {exc}") from exc
    validate_tlc_schema(frame.schema)
    return frame


def read_zone_lookup(spark: Any, zone_path: Path) -> Any:
    """Read the bounded official CSV lookup and validate it before any trip join."""

    try:
        frame = (
            spark.read.option("header", "true")
            .option("inferSchema", "true")
            .csv(str(zone_path))
        )
        columns = tuple(frame.columns)
        if columns != ("LocationID", "Borough", "Zone", "service_zone"):
            raise SourceContractError(f"unexpected official zone lookup columns: {columns}")
        validated = validate_zone_lookup(frame)
        return frame, validated
    except SourceContractError:
        raise
    except Exception as exc:
        raise SourceContractError(f"could not read official taxi-zone lookup: {exc}") from exc


def load_zone_records(path: Path) -> list[dict[str, str | None]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def cgroup_memory_limit_gib(path: str | Path = "/sys/fs/cgroup/memory.max") -> float | None:
    """Read the Linux container memory limit without assuming a fixed Docker cap."""

    try:
        raw = Path(path).read_text(encoding="ascii").strip()
    except OSError:
        return None
    if raw == "max":
        return None
    try:
        return int(raw) / (1024**3)
    except ValueError:
        return None


def validate_memory_budget(available_gib: float, required_gib: float) -> None:
    if available_gib <= 0 or required_gib <= 0:
        raise MemoryBudgetError("memory limits must be positive GiB values")
    if required_gib > available_gib:
        raise MemoryBudgetError(
            f"requested Spark workload envelope {required_gib:.2f} GiB exceeds "
            f"container limit {available_gib:.2f} GiB; refusing to start"
        )


def assert_frame_parity(left: Any, right: Any, *, label: str) -> dict[str, Any]:
    """Compare distributed outputs in both directions without collecting rows."""

    if left.schema.json() != right.schema.json():
        raise AssertionError(
            f"{label} schema mismatch: {left.schema.simpleString()} != {right.schema.simpleString()}"
        )
    left_only = left.exceptAll(right).limit(1).count()
    right_only = right.exceptAll(left).limit(1).count()
    receipt = {
        "label": label,
        "status": "PASS" if left_only == 0 and right_only == 0 else "FAIL",
        "left_only_rows": left_only,
        "right_only_rows": right_only,
        "checked_distributed": True,
    }
    if receipt["status"] != "PASS":
        raise AssertionError(f"{label} output mismatch: {receipt}")
    return receipt


def aggregate_summary(frame: Any) -> dict[str, Any]:
    from pyspark.sql import functions as F

    row = frame.agg(
        F.count(F.lit(1)).alias("aggregate_group_count"),
        F.sum("trip_count").alias("trip_count_sum"),
        F.sum("distance_miles_sum").alias("distance_miles_sum"),
        F.sum("fare_amount_sum").alias("fare_amount_sum"),
        F.sum("total_amount_sum").alias("total_amount_sum"),
        F.min("pickup_date").alias("min_pickup_date"),
        F.max("pickup_date").alias("max_pickup_date"),
    ).first()
    return {key: _json_value(value) for key, value in row.asDict().items()}


def _check_aggregate_key_uniqueness(frame: Any) -> int:
    from pyspark.sql import functions as F

    return (
        frame.groupBy(*OUTPUT_KEYS)
        .count()
        .filter(F.col("count") > 1)
        .limit(1)
        .count()
    )


def _check_partition_layout(root: Path) -> dict[str, Any]:
    parquet_files = sorted(root.rglob("*.parquet"))
    if not parquet_files:
        raise OutputContractError(f"no Parquet data files found under {root}")
    partition_dates: set[str] = set()
    file_sizes: list[int] = []
    for path in parquet_files:
        relative = path.relative_to(root)
        if len(relative.parts) != 2 or not relative.parts[0].startswith("pickup_date="):
            raise OutputContractError(
                f"Parquet file is not stored under one pickup_date partition: {relative}"
            )
        value = relative.parts[0].split("=", maxsplit=1)[1]
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise OutputContractError(f"invalid pickup_date partition name: {value}") from exc
        partition_dates.add(value)
        file_sizes.append(path.stat().st_size)
    unexpected = [
        child.name
        for child in root.iterdir()
        if child.is_dir() and not child.name.startswith("pickup_date=")
    ]
    if unexpected:
        raise OutputContractError(f"unexpected output directories: {unexpected}")
    return {
        "partition_count": len(partition_dates),
        "partition_dates": sorted(partition_dates),
        "parquet_file_count": len(parquet_files),
        "parquet_bytes": sum(file_sizes),
        "average_file_bytes": round(sum(file_sizes) / len(file_sizes), 2),
        "minimum_file_bytes": min(file_sizes),
        "maximum_file_bytes": max(file_sizes),
    }


def _verified_existing_output(
    final_dir: Path,
    *,
    run_id: str,
    source_manifest_sha256: str,
    input_rows: int,
    accepted_rows: int,
    expected_schema: list[dict[str, str]],
) -> dict[str, Any]:
    manifest_path = final_dir / "MANIFEST.json"
    if not manifest_path.is_file():
        raise OutputContractError(f"existing output has no complete manifest: {final_dir}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OutputContractError(f"existing output manifest is invalid: {manifest_path}") from exc
    if manifest.get("status") != "COMPLETE":
        raise OutputContractError("existing output manifest status must be COMPLETE")
    if manifest.get("run_id") != run_id:
        raise OutputContractError("existing output manifest run_id does not match requested run")
    if manifest.get("source_manifest_sha256") != source_manifest_sha256:
        raise OutputContractError("existing output is stale for the current source manifest")
    if int(manifest.get("input_rows", -1)) != input_rows:
        raise OutputContractError("existing output input row count differs from the current run")
    if int(manifest.get("accepted_rows", -1)) != accepted_rows:
        raise OutputContractError("existing output accepted row count differs from the current run")
    if manifest.get("schema") != expected_schema:
        raise OutputContractError("existing output schema differs from the current aggregate")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise OutputContractError("existing output manifest has no Parquet file receipt")
    for entry in files:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise OutputContractError("output manifest contains an unsafe relative file path")
        path = final_dir / relative
        if not path.is_file():
            raise OutputContractError(f"output manifest file is missing: {relative}")
        if path.stat().st_size != int(entry["bytes"]) or _sha256_file(path) != entry["sha256"]:
            raise OutputContractError(f"output manifest file digest differs: {relative}")
    data_directory = manifest.get("data_directory", "parquet")
    if data_directory != "parquet":
        raise OutputContractError("existing output data_directory is unsupported")
    layout = _check_partition_layout(final_dir / data_directory)
    if layout["partition_count"] != manifest.get("partition_count"):
        raise OutputContractError("existing output partition layout differs from manifest")
    return {**manifest, "replay_status": "VERIFIED_NO_OP"}


def publish_partitioned_parquet(
    spark: Any,
    aggregate_df: Any,
    output_root: str | Path,
    *,
    run_id: str,
    source_manifest_sha256: str,
    input_rows: int,
    accepted_rows: int,
    output_partitions: int = 16,
) -> tuple[Path, dict[str, Any]]:
    """Write once to a staging directory, validate, then atomically publish a run."""

    if output_partitions < 1:
        raise ValueError("output_partitions must be positive")
    root = Path(output_root).expanduser().resolve()
    runs_dir = root / "runs"
    staging_dir = root / "staging" / f"{run_id}.partial"
    final_dir = runs_dir / run_id
    if final_dir.exists():
        return final_dir, _verified_existing_output(
            final_dir,
            run_id=run_id,
            source_manifest_sha256=source_manifest_sha256,
            input_rows=input_rows,
            accepted_rows=accepted_rows,
            expected_schema=schema_receipt(aggregate_df.schema),
        )
    if staging_dir.exists():
        raise OutputContractError(
            f"stale or partial output staging path exists; inspect it before retry: {staging_dir}"
        )
    runs_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        staging_data_dir = staging_dir / "parquet"
        (
            aggregate_df.repartition(output_partitions, "pickup_date")
            .write.mode("errorifexists")
            .option("compression", "snappy")
            .partitionBy("pickup_date")
            .parquet(str(staging_data_dir))
        )
        layout = _check_partition_layout(staging_data_dir)
        staged_df = spark.read.parquet(str(staging_data_dir)).select(*aggregate_df.columns)
        if schema_receipt(staged_df.schema) != schema_receipt(aggregate_df.schema):
            raise OutputContractError("staged Parquet schema differs from aggregate schema")
        staged_summary = aggregate_summary(staged_df)
        if int(staged_summary["trip_count_sum"] or 0) != accepted_rows:
            raise OutputContractError(
                "staged Parquet trip_count sum differs from accepted input rows: "
                f"{staged_summary['trip_count_sum']} != {accepted_rows}"
            )
        duplicate_keys = _check_aggregate_key_uniqueness(staged_df)
        if duplicate_keys:
            raise OutputContractError("staged Parquet contains duplicate aggregate keys")

        file_entries = []
        for path in sorted(staging_data_dir.rglob("*.parquet")):
            file_entries.append(
                {
                    "path": path.relative_to(staging_dir).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
        manifest = {
            "status": "COMPLETE",
            "run_id": run_id,
            "source_manifest_sha256": source_manifest_sha256,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_rows": input_rows,
            "accepted_rows": accepted_rows,
            "aggregate_rows": int(staged_summary["aggregate_group_count"] or 0),
            "aggregate_trip_count_sum": int(staged_summary["trip_count_sum"] or 0),
            "aggregates": staged_summary,
            "schema": schema_receipt(staged_df.schema),
            "data_directory": "parquet",
            "partition_column": "pickup_date",
            "partition_count": layout["partition_count"],
            "partition_dates": layout["partition_dates"],
            "file_count": layout["parquet_file_count"],
            "parquet_bytes": layout["parquet_bytes"],
            "average_file_bytes": layout["average_file_bytes"],
            "files": file_entries,
        }
        _atomic_json(staging_dir / "MANIFEST.json", manifest)
        if final_dir.exists():
            raise OutputContractError(f"output path appeared during publication: {final_dir}")
        os.replace(staging_dir, final_dir)
        _atomic_json(root / "LATEST.json", {"status": "COMPLETE", "run_id": run_id})
        return final_dir, {**manifest, "replay_status": "PUBLISHED"}
    except Exception:
        # Leave a failed staging directory in place as evidence. A retry with
        # the same run id fails closed instead of deleting partial output.
        raise


def _write_plan(frame: Any, path: Path, mode: str) -> str:
    from contextlib import redirect_stdout
    from io import StringIO

    output = StringIO()
    with redirect_stdout(output):
        frame.explain(mode=mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output.getvalue(), encoding="utf-8")
    return output.getvalue()


def _pyarrow_day_rows(path: Path, target_day: date) -> list[dict[str, Any]]:
    """Read one bounded date partition from a monthly Parquet source independently."""

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    column_index = parquet.schema_arrow.get_field_index("tpep_pickup_datetime")
    start = datetime.combine(target_day, datetime.min.time())
    end = datetime.combine(target_day + timedelta(days=1), datetime.min.time())
    start_scalar = pa.scalar(start, type=pa.timestamp("us"))
    end_scalar = pa.scalar(end, type=pa.timestamp("us"))
    output: list[dict[str, Any]] = []
    for index in range(parquet.metadata.num_row_groups):
        stats = parquet.metadata.row_group(index).column(column_index).statistics
        if stats is not None and stats.has_min_max:
            if stats.max < start or stats.min >= end:
                continue
        table = parquet.read_row_group(index)
        pickup = table.column("tpep_pickup_datetime")
        mask = pc.and_(pc.greater_equal(pickup, start_scalar), pc.less(pickup, end_scalar))
        output.extend(table.filter(mask).to_pylist())
    return output


def verify_bounded_partition_oracle(
    spark: Any,
    output_path: Path,
    month_path: Path,
    zone_path: Path,
    zones_df: Any,
    target_day: date,
    period_start: date = PERIOD_START,
    period_end: date = PERIOD_END,
) -> dict[str, Any]:
    """Cross-check one complete real pickup-date partition using Python/Decimal."""

    from pyspark.sql import functions as F

    raw_records = _pyarrow_day_rows(month_path, target_day)
    if not raw_records:
        raise AssertionError(f"independent Parquet reader found no source rows for {target_day}")
    zone_records = load_zone_records(zone_path)
    oracle = run_oracle(
        raw_records,
        zone_records,
        period_start=target_day,
        period_end=target_day + timedelta(days=1),
        timezone_name=TIME_ZONE,
    )
    spark_output = (
        spark.read.parquet(str(output_path / "parquet"))
        .filter(F.col("pickup_date") == F.lit(target_day.isoformat()).cast("date"))
        .orderBy(*OUTPUT_KEYS)
    )
    spark_rows = [_normalize_spark_output_row(row) for row in spark_output.collect()]
    oracle_rows = list(oracle.aggregates)
    if len(spark_rows) != len(oracle_rows):
        raise AssertionError(
            f"bounded Oracle output group count differs for {target_day}: "
            f"Spark={len(spark_rows)}, Python={len(oracle_rows)}"
        )

    money_distance_fields = (
        "distance_miles_sum",
        "fare_amount_sum",
        "total_amount_sum",
    )
    duration_fields = ("duration_p50_minutes", "duration_p95_minutes")
    max_duration_error = 0.0
    for spark_row, oracle_row in zip(spark_rows, oracle_rows, strict=True):
        for key in (*OUTPUT_KEYS, "pickup_borough", "trip_count"):
            if spark_row[key] != oracle_row[key]:
                raise AssertionError(
                    f"bounded Oracle key/value mismatch on {key}: "
                    f"Spark={spark_row[key]!r}, Python={oracle_row[key]!r}"
                )
        for key in money_distance_fields:
            if spark_row[key] != oracle_row[key]:
                raise AssertionError(
                    f"bounded Oracle exact decimal mismatch on {key}: "
                    f"Spark={spark_row[key]!r}, Python={oracle_row[key]!r}"
                )
        for key in duration_fields:
            difference = abs(float(spark_row[key]) - float(oracle_row[key]))
            max_duration_error = max(max_duration_error, difference)
            if difference > 0.001:
                raise AssertionError(
                    f"bounded Oracle duration mismatch on {key}: "
                    f"Spark={spark_row[key]!r}, Python={oracle_row[key]!r}"
                )

    partition_trip_count = sum(int(row["trip_count"]) for row in spark_rows)
    return {
        "status": "PASS",
        "source_reader": "PyArrow row-group scan with in-memory pickup-date filter; TLC timestamp row-group min/max statistics were absent",
        "pickup_date": target_day.isoformat(),
        "source_input_rows": len(raw_records),
        "independent_accepted_rows": oracle.accepted_rows,
        "independent_rejected_rows": oracle.rejected_rows,
        "independent_negative_amount_rows": oracle.negative_adjustment_rows,
        "accepted_plus_rejected": oracle.accepted_rows + oracle.rejected_rows,
        "spark_aggregate_rows": len(spark_rows),
        "spark_partition_trip_count_sum": partition_trip_count,
        "exact_decimal_fields": list(money_distance_fields),
        "duration_percentile_tolerance_minutes": 0.001,
        "maximum_observed_duration_error_minutes": max_duration_error,
        "oracle_rejection_counts": oracle.rejection_counts,
        "oracle_duplicate_like_rows_diagnostic_only": oracle.exact_full_row_duplicate_like_rows,
        "correctness": "all keys, counts, exact decimal sums, and p50/p95 tolerances passed",
    }


def _skew_diagnostic(aggregate_df: Any) -> dict[str, Any]:
    from pyspark.sql import functions as F

    by_zone = (
        aggregate_df.groupBy("pickup_zone")
        .agg(F.sum("trip_count").alias("trip_count"))
        .orderBy(F.col("trip_count").desc(), F.col("pickup_zone"))
    )
    rows = [(int(row["pickup_zone"]), int(row["trip_count"])) for row in by_zone.collect()]
    counts = sorted(count for _, count in rows)
    median = statistics.median(counts) if counts else 0
    total = sum(counts)
    max_count = max(counts) if counts else 0
    top_ten = sum(count for _, count in rows[:10])
    plan = aggregate_df._jdf.queryExecution().executedPlan().toString()
    partial_aggregate = "partial_" in plan.casefold() and "aggregate" in plan.casefold()
    ratio = max_count / median if median else None
    return {
        "status": "MEASURED",
        "source": "real accepted 2024 Yellow Taxi trips, aggregated by pickup zone",
        "zone_count": len(rows),
        "total_trips": total,
        "median_zone_trips": median,
        "max_zone_id": rows[0][0] if rows else None,
        "max_zone_trips": max_count,
        "max_to_median_ratio": ratio,
        "top_10_zone_share": top_ten / total if total else None,
        "partial_hash_aggregate_in_plan": partial_aggregate,
        "mitigation": (
            "Spark's map-side partial aggregation reduces repeated hot-zone rows before the wide exchange."
            if partial_aggregate
            else "No partial-aggregate operator was found; skew mitigation is not claimed."
        ),
        "top_zones": [{"pickup_zone": zone, "trip_count": count} for zone, count in rows[:10]],
    }


def _partition_pruning_receipt(
    spark: Any,
    published_path: Path,
    target_day: date,
    plan_path: Path,
) -> dict[str, Any]:
    from pyspark.sql import functions as F

    output = spark.read.parquet(str(published_path / "parquet"))
    selected = output.filter(F.col("pickup_date") == F.lit(target_day.isoformat()).cast("date"))
    plan = _write_plan(selected, plan_path, "formatted")
    if "PartitionFilters" not in plan:
        raise AssertionError("Spark scan plan does not expose a pickup_date PartitionFilter")
    summary = selected.agg(
        F.count(F.lit(1)).alias("aggregate_rows"),
        F.sum("trip_count").alias("trip_count_sum"),
    ).first()
    return {
        "status": "PASS",
        "partition_column": "pickup_date",
        "selected_date": target_day.isoformat(),
        "aggregate_rows": int(summary["aggregate_rows"] or 0),
        "trip_count_sum": int(summary["trip_count_sum"] or 0),
        "partition_filter_present_in_plan": True,
        "plan_file": str(plan_path),
    }


def _reuse_measured_benchmark(
    benchmark_file: str | Path,
    destination: Path,
    *,
    source_manifest_sha256: str,
    input_rows: int,
    spark_version: str,
    shuffle_partitions: int,
    warmups: int,
    repetitions: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reuse a completed benchmark only when its immutable context matches."""

    source_path = Path(benchmark_file).expanduser().resolve()
    context_path = source_path.with_name("benchmark_context.json")
    if not source_path.is_file() or not context_path.is_file():
        raise OutputContractError(
            "benchmark reuse requires both benchmark.json and benchmark_context.json"
        )
    try:
        report = json.loads(source_path.read_text(encoding="utf-8"))
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OutputContractError(f"benchmark reuse receipt is invalid: {exc}") from exc

    required_context = {
        "status": "COMPLETE",
        "source_manifest_sha256": source_manifest_sha256,
        "input_rows": input_rows,
        "spark_version": spark_version,
        "shuffle_partitions": shuffle_partitions,
        "warmups": warmups,
        "repetitions": repetitions,
        "session_timezone": TIME_ZONE,
        "master": "local[4]",
    }
    mismatches = {
        key: {"expected": value, "observed": context.get(key)}
        for key, value in required_context.items()
        if context.get(key) != value
    }
    if mismatches:
        raise OutputContractError(f"benchmark reuse context does not match this run: {mismatches}")
    if report.get("status") != "LOCAL_MEASURED":
        raise OutputContractError("reused benchmark status must be LOCAL_MEASURED")
    parity = report.get("experiment", {}).get("correctness_parity", {})
    if parity.get("status") not in (
        "PASS",
        "PENDING_TOLERANCE_CHECK",
        "PENDING_TOLERANCE_RECHECK",
    ):
        raise OutputContractError("reused benchmark has an unsupported parity state")
    plans = report.get("experiment", {}).get("physical_plan_evidence", {})
    if not plans.get("candidate_broadcast_hash_join_present") or plans.get(
        "baseline_broadcast_hash_join_present"
    ):
        raise OutputContractError("reused benchmark does not prove the intended join strategies")
    for variant, result in report.get("variants", {}).items():
        if len(result.get("timed_runs_seconds", [])) != repetitions:
            raise OutputContractError(f"reused benchmark has an unexpected run count for {variant}")
        if result.get("warmup_count") != warmups:
            raise OutputContractError(f"reused benchmark has an unexpected warmup count for {variant}")

    destination.mkdir(parents=True, exist_ok=True)
    for name in ("benchmark.json", "spark_plan_baseline.txt", "spark_plan_candidate.txt"):
        source_file = source_path.parent / name
        if not source_file.is_file():
            raise OutputContractError(f"reused benchmark artifact is missing: {source_file}")
        shutil.copy2(source_file, destination / name)
    shutil.copy2(context_path, destination / context_path.name)
    reuse_receipt = {
        "status": "REUSED_VERIFIED",
        "benchmark_file": str(source_path),
        "context_file": str(context_path),
        "source_run_id": context.get("run_id"),
        "source_application_id": report.get("runtime", {}).get("application_id"),
        "source_manifest_sha256": source_manifest_sha256,
        "full_result_parity": parity,
    }
    return report, reuse_receipt


def run_week6_job(
    *,
    raw_dir: str | Path,
    output_root: str | Path,
    run_id: str,
    benchmark_repetitions: int = 5,
    benchmark_warmups: int = 1,
    shuffle_partitions: int = 96,
    output_partitions: int = 16,
    hold_ui_seconds: int = 0,
    memory_required_gib: float = 4.0,
    reuse_benchmark: str | Path | None = None,
) -> dict[str, Any]:
    """Execute the complete, bounded local Spark syllabus against official TLC data."""

    import pyarrow.parquet as pq
    from pyspark.sql import functions as F

    if not run_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
        raise ValueError("run_id may contain only letters, digits, hyphens, and underscores")
    trip_paths, zone_path = expected_source_paths(raw_dir)
    source_manifest, source_manifest_sha256 = validate_source_manifest(
        raw_dir, trip_paths, zone_path
    )
    memory_limit = cgroup_memory_limit_gib()
    if memory_limit is None:
        memory_limit = memory_required_gib
    validate_memory_budget(memory_limit, memory_required_gib)

    source_files = []
    footer_total = 0
    for path in trip_paths:
        footer = pq.ParquetFile(path)
        metadata = {
            "file": path.name,
            "source_url": download.monthly_url(
                2024, int(Path(path.name).stem.split("-")[-1])
            ),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
            "footer_rows": footer.metadata.num_rows,
            "row_groups": footer.metadata.num_row_groups,
            "schema": arrow_schema_receipt(pq.read_schema(path)),
        }
        source_files.append(metadata)
        footer_total += footer.metadata.num_rows

    output_root = Path(output_root).expanduser().resolve()
    run_dir = output_root / "evidence" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    spark = create_spark(
        app_name=f"dataforge-week6-{run_id}",
        event_log_dir=Path(raw_dir).expanduser().resolve().parent / "eventlogs",
        shuffle_partitions=shuffle_partitions,
        adaptive_enabled=True,
        enable_delta=True,
    )

    started_at = datetime.now(timezone.utc)
    try:
        raw = read_tlc_sources(spark, trip_paths)
        zones_raw, zones = read_zone_lookup(spark, zone_path)
        zone_counts = {
            "source_rows": zones_raw.count(),
            "assigned_rows": zones.count(),
            "unique_assigned_ids": zones.select("LocationID").distinct().count(),
        }
        if zone_counts != {"source_rows": 265, "assigned_rows": 263, "unique_assigned_ids": 263}:
            raise QualityContractError(f"official taxi-zone lookup receipt differs: {zone_counts}")

        quality: QualityFrames = apply_quality_policy(
            raw, zones_raw, PERIOD_START, PERIOD_END
        )
        if quality.input_rows != footer_total:
            raise SourceContractError(
                f"Spark full scan count {quality.input_rows} differs from Parquet footer total "
                f"{footer_total}"
            )
        if quality.accepted_rows + quality.rejected_rows != quality.input_rows:
            raise QualityContractError("accepted + rejected does not equal Spark input count")
        if quality.input_rows != sum(item["footer_rows"] for item in source_files):
            raise SourceContractError("Spark source total does not reconcile to monthly footer counts")

        quality_ledger = [
            {key: _json_value(value) for key, value in row.asDict().items()}
            for row in quality.ledger.orderBy("category", "metric").collect()
        ]
        duplicate_diagnostic = diagnose_duplicate_like_rows(raw).first().asDict()
        accepted = quality.accepted

        # Independent run against a complete bounded real pickup-date partition.
        bounded_day = date(2024, 1, 15)
        bounded_source = trip_paths[0]

        dataframe_result = aggregate_dataframe(accepted, zones_raw, broadcast_lookup=False)
        sql_result = aggregate_spark_sql(spark, accepted, zones_raw, broadcast_lookup=False)
        sql_parity = assert_frame_parity(
            dataframe_result, sql_result, label="full TLC DataFrame versus Spark SQL"
        )
        _write_plan(dataframe_result, run_dir / "spark_plan_logical_and_physical.txt", "extended")

        benchmark_reuse_receipt = None
        if reuse_benchmark is None:
            benchmark_report = run_benchmark(
                spark,
                accepted,
                zones_raw,
                run_dir / "benchmark",
                settings=BenchmarkSettings(
                    warmups=benchmark_warmups,
                    repetitions=benchmark_repetitions,
                    shuffle_partitions=shuffle_partitions,
                    adaptive_enabled=True,
                ),
            )
            _atomic_json(
                run_dir / "benchmark" / "benchmark_context.json",
                {
                    "status": "COMPLETE",
                    "run_id": run_id,
                    "source_manifest_sha256": source_manifest_sha256,
                    "input_rows": quality.input_rows,
                    "spark_version": spark.version,
                    "shuffle_partitions": shuffle_partitions,
                    "warmups": benchmark_warmups,
                    "repetitions": benchmark_repetitions,
                    "session_timezone": spark.conf.get("spark.sql.session.timeZone"),
                    "master": spark.sparkContext.master,
                },
            )
        else:
            benchmark_report, benchmark_reuse_receipt = _reuse_measured_benchmark(
                reuse_benchmark,
                run_dir / "benchmark",
                source_manifest_sha256=source_manifest_sha256,
                input_rows=quality.input_rows,
                spark_version=spark.version,
                shuffle_partitions=shuffle_partitions,
                warmups=benchmark_warmups,
                repetitions=benchmark_repetitions,
            )
            baseline_for_parity = aggregate_dataframe(
                accepted, zones_raw, broadcast_lookup=False
            )
            candidate_aggregate = aggregate_dataframe(
                accepted, zones_raw, broadcast_lookup=True
            )
            _write_plan(
                baseline_for_parity,
                run_dir / "benchmark" / "spark_plan_baseline.txt",
                "formatted",
            )
            _write_plan(
                candidate_aggregate,
                run_dir / "benchmark" / "spark_plan_candidate.txt",
                "formatted",
            )
            parity = _compare_aggregate_frames(
                baseline_for_parity,
                candidate_aggregate,
                duration_tolerance_minutes=1.0,
            )
            if parity["status"] != "PASS":
                raise AssertionError(f"reused baseline/candidate parity failed: {parity}")
            benchmark_report.setdefault("experiment", {})["correctness_parity"] = parity
            benchmark_report["experiment"]["parity_recheck_run_id"] = run_id
            benchmark_report["experiment"]["parity_rechecked_after_eventlog_recovery"] = True
            median_ratio = float(
                benchmark_report["experiment"].get(
                    "median_baseline_over_candidate_ratio", 0
                )
            )
            if median_ratio > 0 and median_ratio < 1:
                candidate_slower_percent = round((1 / median_ratio - 1) * 100, 1)
                benchmark_report["experiment"]["candidate_slower_percent"] = (
                    candidate_slower_percent
                )
                benchmark_report["experiment"]["speedup_claim"] = (
                    "NO SPEEDUP: the broadcast candidate median was "
                    f"{candidate_slower_percent:.1f}% slower in this local run. It reduced "
                    "shuffle and spill metrics; that did not reduce elapsed time here."
                )
            elif median_ratio >= 1:
                benchmark_report["experiment"]["speedup_claim"] = (
                    "The broadcast candidate median was lower in this local run; treat the "
                    "difference as exploratory given single-machine variability."
                )
            metric_fields = (
                "shuffle_read_bytes",
                "shuffle_write_bytes",
                "memory_bytes_spilled",
                "disk_bytes_spilled",
                "executor_run_time_ms",
                "executor_cpu_time_ns",
                "jvm_gc_time_ms",
            )
            metric_medians: dict[str, dict[str, float]] = {}
            for variant in ("baseline", "broadcast_candidate"):
                timed_receipts = [
                    receipt
                    for receipt in benchmark_report["variants"][variant]["run_receipts"]
                    if "-warmup-" not in receipt["group_id"]
                ]
                metric_medians[variant] = {
                    field: statistics.median(
                        receipt["spark_event_metrics"]["sum_task_metrics"][field]
                        for receipt in timed_receipts
                    )
                    for field in metric_fields
                }
            benchmark_report["experiment"]["eventlog_task_metric_medians"] = metric_medians
            baseline_shuffle = metric_medians["baseline"]["shuffle_write_bytes"]
            candidate_shuffle = metric_medians["broadcast_candidate"]["shuffle_write_bytes"]
            baseline_memory_spill = metric_medians["baseline"]["memory_bytes_spilled"]
            candidate_memory_spill = metric_medians["broadcast_candidate"]["memory_bytes_spilled"]
            baseline_disk_spill = metric_medians["baseline"]["disk_bytes_spilled"]
            candidate_disk_spill = metric_medians["broadcast_candidate"]["disk_bytes_spilled"]
            benchmark_report["experiment"]["shuffle_write_reduction_percent"] = round(
                (1 - candidate_shuffle / baseline_shuffle) * 100, 1
            ) if baseline_shuffle else None
            benchmark_report["experiment"]["memory_spill_reduction_percent"] = round(
                (1 - candidate_memory_spill / baseline_memory_spill) * 100, 1
            ) if baseline_memory_spill else None
            benchmark_report["experiment"]["disk_spill_reduction_percent"] = round(
                (1 - candidate_disk_spill / baseline_disk_spill) * 100, 1
            ) if baseline_disk_spill else None
            benchmark_report["limitations"] = [
                item
                for item in benchmark_report.get("limitations", [])
                if "percentile parity is pending" not in str(item).casefold()
            ]
            if benchmark_reuse_receipt is not None:
                benchmark_reuse_receipt["status"] = "REUSED_AND_RECHECKED"
                benchmark_reuse_receipt["full_result_parity"] = parity
            _atomic_json(run_dir / "benchmark" / "benchmark.json", benchmark_report)
        if reuse_benchmark is None:
            candidate_aggregate = aggregate_dataframe(
                accepted, zones_raw, broadcast_lookup=True
            )
        business_summary = aggregate_summary(candidate_aggregate)
        if int(business_summary["trip_count_sum"] or 0) != quality.accepted_rows:
            raise AssertionError(
                "aggregate trip count does not reconcile to accepted source rows: "
                f"{business_summary['trip_count_sum']} != {quality.accepted_rows}"
            )
        if _check_aggregate_key_uniqueness(candidate_aggregate):
            raise AssertionError("hourly-by-zone aggregate contains duplicate output keys")

        # This second independent aggregate over the accepted rows checks the
        # full-scale monetary identities before the publication write.
        accepted_totals_row = accepted.agg(
            F.sum("trip_distance_miles").alias("distance_miles_sum"),
            F.sum("fare_amount").alias("fare_amount_sum"),
            F.sum("total_amount").alias("total_amount_sum"),
        ).first()
        accepted_totals = {
            key: _json_value(value) for key, value in accepted_totals_row.asDict().items()
        }
        for field in ("distance_miles_sum", "fare_amount_sum", "total_amount_sum"):
            if business_summary[field] != accepted_totals[field]:
                raise AssertionError(
                    f"full-scale {field} fails aggregate reconciliation: "
                    f"grouped={business_summary[field]!r}, accepted={accepted_totals[field]!r}"
                )

        skew = _skew_diagnostic(candidate_aggregate)
        if not skew["partial_hash_aggregate_in_plan"]:
            raise AssertionError("Spark's map-side partial aggregate was not visible in the plan")

        output_path, output_manifest = publish_partitioned_parquet(
            spark,
            candidate_aggregate,
            output_root,
            run_id=run_id,
            source_manifest_sha256=source_manifest_sha256,
            input_rows=quality.input_rows,
            accepted_rows=quality.accepted_rows,
            output_partitions=output_partitions,
        )
        output_path_replay, output_replay = publish_partitioned_parquet(
            spark,
            candidate_aggregate,
            output_root,
            run_id=run_id,
            source_manifest_sha256=source_manifest_sha256,
            input_rows=quality.input_rows,
            accepted_rows=quality.accepted_rows,
            output_partitions=output_partitions,
        )
        if output_path != output_path_replay or output_replay["replay_status"] != "VERIFIED_NO_OP":
            raise OutputContractError("same-run Parquet publication did not converge to a no-op")

        partition_pruning = _partition_pruning_receipt(
            spark,
            output_path,
            bounded_day,
            run_dir / "partition_pruning_plan.txt",
        )
        oracle_receipt = verify_bounded_partition_oracle(
            spark,
            output_path,
            bounded_source,
            zone_path,
            zones_raw,
            bounded_day,
        )
        if oracle_receipt["accepted_plus_rejected"] != oracle_receipt["source_input_rows"]:
            raise AssertionError("bounded Python Oracle does not reconcile its daily input")

        delta_receipt = run_delta_table_demo(
            spark,
            spark.read.parquet(str(output_path / "parquet")),
            run_dir / "delta_demo",
        ).to_dict()

        ended_at = datetime.now(timezone.utc)
        receipt = {
            "status": "LOCAL_MEASURED",
            "run_id": run_id,
            "started_at_utc": started_at.isoformat(),
            "ended_at_utc": ended_at.isoformat(),
            "elapsed_seconds_this_application": round(
                (ended_at - started_at).total_seconds(), 3
            ),
            "source": {
                "source_page_url": source_manifest.get("source_page_url"),
                "source_manifest_sha256": source_manifest_sha256,
                "files": source_files,
                "footer_total_rows": footer_total,
                "spark_total_rows": quality.input_rows,
                "spark_count_matches_footer": quality.input_rows == footer_total,
                "zone_lookup": zone_counts,
                "schema": schema_receipt(raw.schema),
                "selected_period": {
                    "pickup_start_inclusive": PERIOD_START.isoformat(),
                    "pickup_end_exclusive": PERIOD_END.isoformat(),
                    "dropoff_may_cross_end_if_valid": True,
                },
            },
            "runtime": {
                "spark_version": spark.version,
                "master": spark.sparkContext.master,
                "application_id": spark.sparkContext.applicationId,
                "session_timezone": spark.conf.get("spark.sql.session.timeZone"),
                "shuffle_partitions": spark.conf.get("spark.sql.shuffle.partitions"),
                "adaptive_enabled": spark.conf.get("spark.sql.adaptive.enabled"),
                "container_memory_limit_gib": memory_limit,
                "memory_envelope_gib": memory_required_gib,
                "topology": "single Docker Linux container; one local Spark driver/executor process",
            },
            "quality": {
                "input_rows": quality.input_rows,
                "accepted_rows": quality.accepted_rows,
                "rejected_rows": quality.rejected_rows,
                "accepted_plus_rejected": quality.accepted_rows + quality.rejected_rows,
                "reconciliation_status": "PASS",
                "ledger": quality_ledger,
                "duplicate_like_full_row_fingerprint": _json_value(duplicate_diagnostic),
                "deduplication_applied": False,
            },
            "dataframe_sql_parity": sql_parity,
            "full_scale_reconciliation": {
                "grouped": business_summary,
                "accepted_rows_summed_independently": accepted_totals,
                "trip_count_equals_accepted": int(business_summary["trip_count_sum"] or 0)
                == quality.accepted_rows,
                "money_and_distance_sums_match": all(
                    business_summary[field] == accepted_totals[field]
                    for field in (
                        "distance_miles_sum",
                        "fare_amount_sum",
                        "total_amount_sum",
                    )
                ),
                "output_keys_unique": True,
            },
            "benchmark": benchmark_report,
            "benchmark_reuse": benchmark_reuse_receipt,
            "benchmark_application_id": benchmark_report.get("runtime", {}).get(
                "application_id"
            ),
            "skew": skew,
            "parquet": {
                "path": str(output_path),
                "manifest": output_manifest,
                "same_run_replay": output_replay["replay_status"],
                "partition_pruning": partition_pruning,
            },
            "independent_oracle": oracle_receipt,
            "delta": delta_receipt,
            "logical_plan_file": str(run_dir / "spark_plan_logical_and_physical.txt"),
            "spark_ui": {
                "url": "http://localhost:4040",
                "available_until_spark_stop": True,
                "hold_seconds_after_completion": hold_ui_seconds,
                "screenshot_capture": "separate UI capture step",
            },
            "cloud": {
                "managed_spark_status": "CLOUD_SPARK_NOT_AUTHORIZED",
                "gcp_batch_submitted": False,
                "gcp_resource_mutation": False,
            },
        }
        _atomic_json(run_dir / "run_receipt.json", receipt)
        if hold_ui_seconds > 0:
            time.sleep(hold_ui_seconds)
        return receipt
    finally:
        spark.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "raw",
        help="directory holding four TLC Parquet files, the zone CSV, and source_manifest.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "output",
        help="ignored local scratch output directory",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--shuffle-partitions", type=int, default=96)
    parser.add_argument("--output-partitions", type=int, default=16)
    parser.add_argument("--hold-ui-seconds", type=int, default=0)
    parser.add_argument("--memory-required-gib", type=float, default=4.0)
    parser.add_argument(
        "--reuse-benchmark",
        type=Path,
        default=None,
        help="reuse a completed benchmark.json with matching benchmark_context.json after output recovery",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.run_id is None:
        args.run_id = "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        receipt = run_week6_job(
            raw_dir=args.raw_dir,
            output_root=args.output_root,
            run_id=args.run_id,
            benchmark_repetitions=args.repetitions,
            benchmark_warmups=args.warmups,
            shuffle_partitions=args.shuffle_partitions,
            output_partitions=args.output_partitions,
            hold_ui_seconds=args.hold_ui_seconds,
            memory_required_gib=args.memory_required_gib,
            reuse_benchmark=args.reuse_benchmark,
        )
    except (FileNotFoundError, SourceContractError, OutputContractError, MemoryBudgetError) as exc:
        parser.error(str(exc))
    print(json.dumps(_json_value(receipt), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
