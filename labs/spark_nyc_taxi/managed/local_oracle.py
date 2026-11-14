"""Compute an independent, local Jan-2024 oracle from the exact staged source.

This script performs no downloads or GCP calls. It verifies the existing local
source receipt, streams Parquet record batches into the repository's Python/
Decimal oracle, and writes one JSON comparison receipt for the later batch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

from labs.spark_nyc_taxi.download import MANIFEST_NAME, monthly_url
from labs.spark_nyc_taxi.oracle import load_zone_records, run_oracle
from labs.spark_nyc_taxi.managed.preflight import aggregate_checksum

MONTH_FILE = "yellow_tripdata_2024-01.parquet"
ZONE_FILE = "taxi_zone_lookup.csv"
ZONE_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"
PERIOD_START = date(2024, 1, 1)
PERIOD_END = date(2024, 2, 1)


class LocalOracleContractError(ValueError):
    """Local source files or their acquisition receipt violate the Jan contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _source_receipts(data_dir: Path) -> tuple[Path, Path, dict[str, Any], str, str, str]:
    manifest_path = data_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalOracleContractError(f"source manifest is missing or invalid: {manifest_path}") from exc
    if manifest.get("status") != "COMPLETE" or manifest.get("row_counts") != "NOT_RUN":
        raise LocalOracleContractError("source manifest must be COMPLETE with row_counts=NOT_RUN")

    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != 2:
        raise LocalOracleContractError("Jan-2024 receipt must contain exactly the month and zone lookup")
    by_name = {entry.get("name"): entry for entry in entries if isinstance(entry, dict)}
    trip_path = data_dir / MONTH_FILE
    zone_path = data_dir / ZONE_FILE
    trip_entry = by_name.get(MONTH_FILE)
    zone_entry = by_name.get(ZONE_FILE)
    if trip_entry is None or zone_entry is None:
        raise LocalOracleContractError("source manifest lacks the fixed month or official zone lookup")
    if trip_entry.get("source_url") != monthly_url(2024, 1) or zone_entry.get("source_url") != ZONE_URL:
        raise LocalOracleContractError("source manifest does not point at the official 2024-01 TLC objects")
    for path, entry in ((trip_path, trip_entry), (zone_path, zone_entry)):
        if not path.is_file() or path.stat().st_size <= 0:
            raise LocalOracleContractError(f"source file is missing or empty: {path.name}")
        if int(entry.get("bytes", -1)) != path.stat().st_size or entry.get("sha256") != _sha256(path):
            raise LocalOracleContractError(f"source manifest size/SHA-256 differs for {path.name}")
    return (
        trip_path,
        zone_path,
        manifest,
        trip_entry["sha256"],
        zone_entry["sha256"],
        _sha256(manifest_path),
    )


def _records(trip_path: Path) -> Iterator[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise LocalOracleContractError("pyarrow is required for the local source oracle") from exc
    parquet = pq.ParquetFile(trip_path)
    for batch in parquet.iter_batches(batch_size=50_000):
        yield from batch.to_pylist()


def _summary(result) -> dict[str, Any]:
    distance = sum((row["distance_miles_sum"] for row in result.aggregates), Decimal("0"))
    fare = sum((row["fare_amount_sum"] for row in result.aggregates), Decimal("0"))
    total = sum((row["total_amount_sum"] for row in result.aggregates), Decimal("0"))
    return {
        "input_rows": result.input_rows,
        "accepted_rows": result.accepted_rows,
        "rejected_rows": result.rejected_rows,
        "aggregate_group_count": len(result.aggregates),
        "trip_count_sum": sum(int(row["trip_count"]) for row in result.aggregates),
        "distance_miles_sum": format(distance.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP), "f"),
        "fare_amount_sum": format(fare.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
        "total_amount_sum": format(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
        "aggregate_checksum": aggregate_checksum(result.aggregates),
        "rejection_counts": result.rejection_counts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args(argv)

    data_dir = args.data_dir.expanduser().resolve()
    trip_path, zone_path, manifest, source_sha256, zone_sha256, manifest_sha256 = _source_receipts(data_dir)
    zones = load_zone_records(zone_path)
    result = run_oracle(
        _records(trip_path),
        zones,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )
    receipt = {
        "status": "COMPLETE",
        "period_start": PERIOD_START.isoformat(),
        "period_end_exclusive": PERIOD_END.isoformat(),
        "source_name": MONTH_FILE,
        "source_url": monthly_url(2024, 1),
        "source_bytes": trip_path.stat().st_size,
        "source_sha256": source_sha256,
        "zone_bytes": zone_path.stat().st_size,
        "zone_sha256": zone_sha256,
        "source_manifest_sha256": manifest_sha256,
        "source_manifest_schema_period": manifest.get("schema_period"),
        "oracle": _summary(result),
    }
    _json_atomic(args.output_json.expanduser().resolve(), receipt)
    print(json.dumps({"status": receipt["status"], "output": str(args.output_json), **receipt["oracle"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
