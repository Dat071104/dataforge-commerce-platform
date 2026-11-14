"""Dataproc Serverless driver for one isolated 2024-01 TLC Yellow batch.

This driver reuses the local Week-6 quality policy and Spark aggregation code.
It is prepared for later authorized submission; importing it does not contact
Google Cloud or start a Spark session.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import PurePosixPath
from urllib.parse import urlparse

from labs.spark_nyc_taxi.managed.preflight import aggregate_checksum

MONTH_START = date(2024, 1, 1)
MONTH_END = date(2024, 2, 1)
MONTH_FILE = "yellow_tripdata_2024-01.parquet"
ZONE_FILE = "taxi_zone_lookup.csv"
EXPECTED_MONTHLY_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-01.parquet"


class ManagedJobContractError(ValueError):
    """The staged inputs or requested output violate the fixed C7 contract."""


def _require_gcs_uri(value: str, *, name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path.strip("/"):
        raise ManagedJobContractError(f"{name} must be a non-empty gs:// object URI")
    return value


def _read_manifest(spark, uri: str) -> dict:
    rows = spark.read.option("multiLine", "true").json(uri).limit(2).collect()
    if len(rows) != 1:
        raise ManagedJobContractError("source manifest must contain exactly one JSON object")
    manifest = rows[0].asDict(recursive=True)
    if manifest.get("status") != "COMPLETE" or manifest.get("row_counts") != "NOT_RUN":
        raise ManagedJobContractError("source manifest must be COMPLETE with row_counts=NOT_RUN")
    if manifest.get("schema_period") != "2024-01 through 2024-01":
        raise ManagedJobContractError("C7 source manifest must cover only January 2024")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 2:
        raise ManagedJobContractError("C7 source manifest must contain the one month and zone lookup")
    return manifest


def validate_source_contract(
    manifest: dict,
    *,
    trip_uri: str,
    zones_uri: str,
    expected_sha256: str,
    expected_zone_sha256: str,
    expected_generation: str,
    expected_zone_generation: str,
    output_uri: str,
    batch_id: str,
) -> None:
    _require_gcs_uri(trip_uri, name="trip_uri")
    _require_gcs_uri(zones_uri, name="zones_uri")
    _require_gcs_uri(output_uri, name="output_uri")
    _require_gcs_uri(manifest.get("source_manifest_uri", ""), name="source_manifest_uri")
    if PurePosixPath(urlparse(trip_uri).path).name != MONTH_FILE:
        raise ManagedJobContractError("trip_uri must be the fixed 2024-01 Yellow Taxi file")
    if PurePosixPath(urlparse(zones_uri).path).name != ZONE_FILE:
        raise ManagedJobContractError("zones_uri must be the official taxi_zone_lookup.csv")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ManagedJobContractError("expected_sha256 must be a lowercase 64-character SHA-256")
    if not re.fullmatch(r"[1-9][0-9]*", str(expected_generation)):
        raise ManagedJobContractError("expected_generation must be a positive GCS object generation")
    if not re.fullmatch(r"[a-z0-9-]{4,63}", batch_id):
        raise ManagedJobContractError("batch_id must be a 4-63 character lowercase Dataproc ID")
    if "/tlc_managed/2024-01/" not in output_uri or not output_uri.rstrip("/").endswith(batch_id):
        raise ManagedJobContractError("output_uri must be isolated under tlc_managed/2024-01/<batch_id>")

    files = {entry.get("name"): entry for entry in manifest["files"] if isinstance(entry, dict)}
    trip_entry = files.get(MONTH_FILE)
    zone_entry = files.get(ZONE_FILE)
    if trip_entry is None or zone_entry is None:
        raise ManagedJobContractError("source manifest is missing its fixed month or taxi-zone lookup")
    if trip_entry.get("source_url") != EXPECTED_MONTHLY_URL:
        raise ManagedJobContractError("source manifest URL is not the official 2024-01 TLC file")
    if trip_entry.get("sha256") != expected_sha256:
        raise ManagedJobContractError("source SHA-256 differs from the uploaded manifest")
    if str(trip_entry.get("generation")) != str(expected_generation):
        raise ManagedJobContractError("source manifest generation differs from the preflighted object")
    if zone_entry.get("sha256") != expected_zone_sha256:
        raise ManagedJobContractError("zone lookup SHA-256 differs from the uploaded manifest")
    if str(zone_entry.get("generation")) != str(expected_zone_generation):
        raise ManagedJobContractError("zone lookup generation differs from the preflighted object")
    if int(trip_entry.get("bytes", 0)) <= 0 or int(zone_entry.get("bytes", 0)) <= 0:
        raise ManagedJobContractError("manifest source sizes must be positive")


def _aggregate_summary(frame) -> dict[str, object]:
    from pyspark.sql import functions as F

    row = frame.agg(
        F.count(F.lit(1)).alias("aggregate_group_count"),
        F.sum("trip_count").alias("trip_count_sum"),
        F.sum("distance_miles_sum").alias("distance_miles_sum"),
        F.sum("fare_amount_sum").alias("fare_amount_sum"),
        F.sum("total_amount_sum").alias("total_amount_sum"),
    ).first()
    values = row.asDict()
    distance = Decimal(str(values["distance_miles_sum"] or 0)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    fare = Decimal(str(values["fare_amount_sum"] or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    total = Decimal(str(values["total_amount_sum"] or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return {
        "aggregate_group_count": int(values["aggregate_group_count"] or 0),
        "trip_count_sum": int(values["trip_count_sum"] or 0),
        "distance_miles_sum": format(distance, "f"),
        "fare_amount_sum": format(fare, "f"),
        "total_amount_sum": format(total, "f"),
    }


def _verify_oracle(actual: dict, oracle_receipt: dict, *, source_sha256: str, zone_sha256: str) -> None:
    if oracle_receipt.get("source_sha256") != source_sha256:
        raise ManagedJobContractError("local oracle was not computed from the submitted source SHA-256")
    if oracle_receipt.get("zone_sha256") != zone_sha256:
        raise ManagedJobContractError("local oracle did not use the submitted official zone lookup SHA-256")
    oracle = oracle_receipt.get("oracle")
    if not isinstance(oracle, dict):
        raise ManagedJobContractError("local oracle receipt must contain an oracle summary object")
    fields = (
        "input_rows",
        "accepted_rows",
        "rejected_rows",
        "aggregate_group_count",
        "trip_count_sum",
        "distance_miles_sum",
        "fare_amount_sum",
        "total_amount_sum",
        "aggregate_checksum",
    )
    for field in fields:
        if str(actual.get(field)) != str(oracle.get(field)):
            raise ManagedJobContractError(
                f"managed result differs from local oracle for {field}: "
                f"{actual.get(field)!r} != {oracle.get(field)!r}"
            )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--trip-uri", required=True)
    parser.add_argument("--zones-uri", required=True)
    parser.add_argument("--source-manifest-uri", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--zone-sha256", required=True)
    parser.add_argument("--source-generation", required=True)
    parser.add_argument("--zone-generation", required=True)
    parser.add_argument("--local-oracle-uri", required=True)
    parser.add_argument("--output-uri", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _require_gcs_uri(args.source_manifest_uri, name="source_manifest_uri")
    _require_gcs_uri(args.local_oracle_uri, name="local_oracle_uri")

    from pyspark.sql import SparkSession
    from labs.spark_nyc_taxi.quality import apply_quality_policy, validate_tlc_schema, validate_zone_lookup
    from labs.spark_nyc_taxi.transforms import aggregate_dataframe

    spark = (
        SparkSession.builder.appName(f"dataforge-c7-{args.batch_id}")
        .config("spark.sql.session.timeZone", "America/New_York")
        .getOrCreate()
    )
    try:
        manifest = _read_manifest(spark, args.source_manifest_uri)
        # Store the source manifest URI in-memory only for contract validation;
        # no cloud object is modified by the Spark job.
        manifest["source_manifest_uri"] = args.source_manifest_uri
        validate_source_contract(
            manifest,
            trip_uri=args.trip_uri,
            zones_uri=args.zones_uri,
            expected_sha256=args.source_sha256,
            expected_zone_sha256=args.zone_sha256,
            expected_generation=args.source_generation,
            expected_zone_generation=args.zone_generation,
            output_uri=args.output_uri,
            batch_id=args.batch_id,
        )

        raw = spark.read.parquet(args.trip_uri)
        validate_tlc_schema(raw.schema, "managed 2024-01 TLC source")
        zones_raw = (
            spark.read.option("header", "true")
            .option("inferSchema", "true")
            .csv(args.zones_uri)
        )
        if tuple(zones_raw.columns) != ("LocationID", "Borough", "Zone", "service_zone"):
            raise ManagedJobContractError("official taxi-zone lookup schema or column order changed")
        validate_zone_lookup(zones_raw)

        quality = apply_quality_policy(raw, zones_raw, MONTH_START, MONTH_END)
        aggregate = aggregate_dataframe(quality.accepted, zones_raw, broadcast_lookup=True)
        summary = _aggregate_summary(aggregate)
        checksum = aggregate_checksum(
            row.asDict(recursive=True)
            for row in aggregate.orderBy("pickup_date", "pickup_hour", "pickup_zone").toLocalIterator()
        )
        actual = {
            "batch_id": args.batch_id,
            "source_sha256": args.source_sha256,
            "zone_sha256": args.zone_sha256,
            "source_generation": str(args.source_generation),
            "zone_generation": str(args.zone_generation),
            "input_rows": quality.input_rows,
            "accepted_rows": quality.accepted_rows,
            "rejected_rows": quality.rejected_rows,
            **summary,
            "aggregate_checksum": checksum,
        }
        oracle_rows = spark.read.option("multiLine", "true").json(args.local_oracle_uri).limit(2).collect()
        if len(oracle_rows) != 1:
            raise ManagedJobContractError("local oracle receipt must contain exactly one JSON object")
        oracle_receipt = oracle_rows[0].asDict(recursive=True)
        _verify_oracle(
            actual,
            oracle_receipt,
            source_sha256=args.source_sha256,
            zone_sha256=args.zone_sha256,
        )

        output_prefix = args.output_uri.rstrip("/")
        aggregate.write.mode("errorifexists").partitionBy("pickup_date").parquet(
            f"{output_prefix}/aggregate"
        )
        receipt = {
            **actual,
            "status": "PASS",
            "spark_version": spark.version,
            "period_start": MONTH_START.isoformat(),
            "period_end_exclusive": MONTH_END.isoformat(),
            "output_uri": f"{output_prefix}/aggregate",
        }
        spark.createDataFrame([receipt]).coalesce(1).write.mode("errorifexists").json(
            f"{output_prefix}/receipt"
        )
        print(json.dumps(receipt, sort_keys=True, default=str))
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
