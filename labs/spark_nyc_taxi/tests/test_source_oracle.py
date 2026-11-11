from __future__ import annotations

import io
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from labs.spark_nyc_taxi import download, oracle

ZONE_RECORDS = [
    {"LocationID": "1", "Borough": "Manhattan", "Zone": "Test Zone", "service_zone": "Yellow Zone"},
    {"LocationID": "2", "Borough": "Queens", "Zone": "Other Zone", "service_zone": "Yellow Zone"},
    {"LocationID": "264", "Borough": "Unknown", "Zone": None, "service_zone": None},
    {"LocationID": "265", "Borough": None, "Zone": "Outside of NYC", "service_zone": None},
]


def _row(
    pickup: datetime = datetime(2024, 1, 1, 10, 0),
    dropoff: datetime = datetime(2024, 1, 1, 10, 30),
    **overrides,
) -> dict:
    record = {
        "VendorID": 2,
        "tpep_pickup_datetime": pickup,
        "tpep_dropoff_datetime": dropoff,
        "passenger_count": 1,
        "trip_distance": 1.125,
        "RatecodeID": 1,
        "store_and_fwd_flag": "N",
        "PULocationID": 1,
        "DOLocationID": 2,
        "payment_type": 1,
        "fare_amount": 10.0,
        "extra": 0.5,
        "mta_tax": 0.5,
        "tip_amount": 2.0,
        "tolls_amount": 0.0,
        "improvement_surcharge": 0.3,
        "total_amount": 13.3,
        "congestion_surcharge": 0.0,
        "Airport_fee": 0.0,
    }
    record.update(overrides)
    return record


class _Response(io.BytesIO):
    def __init__(self, body: bytes, headers: dict[str, str], status: int = 200):
        super().__init__(body)
        self.headers = headers
        self.status = status

    def getcode(self) -> int:
        return self.status


def test_month_url_is_fixed_to_official_2024_yellow_source():
    assert download.monthly_url(2024, 1) == (
        "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-01.parquet"
    )
    with pytest.raises(ValueError, match="pins Yellow Taxi source schema year 2024"):
        download.monthly_url(2025, 1)
    with pytest.raises(ValueError, match="month must be in 1..12"):
        download.monthly_url(2024, 0)


def test_downloader_writes_atomic_files_and_rehashes_against_manifest(tmp_path: Path):
    payloads = [b"one-parquet-placeholder", b"official-zone-csv"]

    def fake_urlopen(request, timeout):
        payload = payloads.pop(0)
        return _Response(payload, {"Content-Length": str(len(payload)), "ETag": '"fixed"'})

    with patch.object(download, "urlopen", side_effect=fake_urlopen):
        receipt = download.download_sources(tmp_path, months=(1,))
    assert receipt["status"] == "COMPLETE"
    assert receipt["row_counts"] == "NOT_RUN"
    assert len(receipt["files"]) == 2
    assert all(entry["status"] == "DOWNLOADED" for entry in receipt["files"])
    assert all(not Path(entry["local_path"] + ".partial").exists() for entry in receipt["files"])
    assert all(entry["row_count"] == "NOT_RUN" for entry in receipt["files"])
    manifest = json.loads((tmp_path / download.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["files"] == receipt["files"]

    with patch.object(download, "urlopen", side_effect=AssertionError("should skip good files")):
        repeated = download.download_sources(tmp_path, months=(1,))
    assert all(entry["status"] == "EXISTING_REHASHED" for entry in repeated["files"])

    parquet_path = tmp_path / "yellow_tripdata_2024-01.parquet"
    parquet_path.write_bytes(b"tampered")
    error_on_download = AssertionError("mismatch must fail before GET")
    with patch.object(download, "urlopen", side_effect=error_on_download):
        with pytest.raises(download.DownloadError, match="digest differs"):
            download.download_sources(tmp_path, months=(1,))


def test_downloader_resumes_a_partial_response_then_replaces_atomically(tmp_path: Path):
    target = tmp_path / "sample.bin"
    target.with_name(target.name + ".partial").write_bytes(b"ab")
    response = _Response(
        b"cde",
        {"Content-Range": "bytes 2-4/5", "Content-Length": "3"},
        status=206,
    )
    with patch.object(download, "urlopen", return_value=response) as open_url:
        receipt = download._download_atomic("https://example.test/sample.bin", target)
    request = open_url.call_args.args[0]
    assert request.get_header("Range") == "bytes=2-"
    assert target.read_bytes() == b"abcde"
    assert receipt.bytes == 5
    assert receipt.status == "DOWNLOADED"
    assert not target.with_name(target.name + ".partial").exists()


def test_oracle_keeps_negative_money_and_identical_full_rows_without_deduping():
    negative = _row(fare_amount=Decimal("-2.50"), tip_amount=Decimal("-1.00"), total_amount=-3.5)
    result = oracle.run_oracle([negative, dict(negative)], ZONE_RECORDS)

    assert result.input_rows == 2
    assert result.accepted_rows == 2
    assert result.rejected_rows == 0
    assert result.accepted_rows + result.rejected_rows == result.input_rows
    assert result.negative_adjustment_rows == 2
    assert result.negative_amount_field_counts == {
        "fare_amount": 2,
        "tip_amount": 2,
        "total_amount": 2,
    }
    assert result.exact_full_row_duplicate_like_rows == 1
    row = result.aggregates[0]
    assert row["trip_count"] == 2
    assert row["pickup_date"] == "2024-01-01"
    assert row["pickup_hour"] == 10
    assert row["pickup_zone"] == 1
    assert row["pickup_borough"] == "Manhattan"
    assert row["distance_miles_sum"] == Decimal("2.250")
    assert row["fare_amount_sum"] == Decimal("-5.00")
    assert row["total_amount_sum"] == Decimal("-7.00")
    assert result.to_dict()["accepted_plus_rejected"] == 2


def test_oracle_rejection_ledger_is_exclusive_and_covers_time_zone_and_quality_cases():
    rows = [
        _row(PULocationID=None),
        _row(pickup=datetime(2023, 12, 31, 23, 50), dropoff=datetime(2024, 1, 1, 0, 5)),
        _row(pickup=datetime(2024, 3, 10, 2, 15), dropoff=datetime(2024, 3, 10, 2, 45)),
        _row(pickup=datetime(2024, 3, 10, 1, 30), dropoff=datetime(2024, 3, 10, 3, 30)),
        _row(pickup=datetime(2024, 1, 1, 10, 30), dropoff=datetime(2024, 1, 1, 10, 30)),
        _row(DOLocationID=264),
        _row(trip_distance=0.0),
        _row(total_amount=float("nan")),
        _row(),
    ]
    result = oracle.run_oracle(rows, ZONE_RECORDS)

    assert result.input_rows == 9
    assert result.accepted_rows == 1
    assert result.rejected_rows == 8
    assert result.accepted_rows + result.rejected_rows == result.input_rows
    assert result.rejection_counts == {
        "null_critical": 1,
        "invalid_timestamp": 0,
        "out_of_period": 1,
        "dst_nonexistent": 1,
        "dst_ambiguous": 0,
        "dst_crossing": 1,
        "invalid_duration": 1,
        "unknown_zone": 1,
        "invalid_distance": 1,
        "invalid_money": 1,
    }


def test_oracle_rejects_fall_back_ambiguous_local_time():
    result = oracle.run_oracle(
        [_row(pickup=datetime(2024, 11, 3, 1, 30), dropoff=datetime(2024, 11, 3, 1, 45))],
        ZONE_RECORDS,
        period_start=date(2024, 11, 1),
        period_end=date(2024, 12, 1),
    )
    assert result.rejected_rows == 1
    assert result.rejection_counts["dst_ambiguous"] == 1


def test_negative_amounts_remain_a_review_flag_even_when_another_policy_rejects_row():
    result = oracle.run_oracle(
        [_row(PULocationID=264, fare_amount=-1.0, total_amount=-1.0)],
        ZONE_RECORDS,
    )
    assert result.accepted_rows == 0
    assert result.rejected_rows == 1
    assert result.rejection_counts["unknown_zone"] == 1
    assert result.negative_adjustment_rows == 1
    assert result.negative_amount_field_counts == {"fare_amount": 1, "total_amount": 1}


def test_oracle_allows_valid_dropoff_across_source_month_boundary():
    result = oracle.run_oracle(
        [
            _row(
                pickup=datetime(2024, 4, 30, 23, 50),
                dropoff=datetime(2024, 5, 1, 0, 10),
            )
        ],
        ZONE_RECORDS,
    )
    assert result.accepted_rows == 1
    assert result.rejected_rows == 0
    assert result.aggregates[0]["pickup_date"] == "2024-04-30"
    assert result.aggregates[0]["duration_p50_minutes"] == Decimal("20.000")


def test_oracle_percentiles_use_nearest_rank_for_bounded_fixture():
    rows = [
        _row(dropoff=datetime(2024, 1, 1, 10, 10)),
        _row(dropoff=datetime(2024, 1, 1, 10, 30)),
        _row(dropoff=datetime(2024, 1, 1, 11, 0)),
    ]
    row = oracle.run_oracle(rows, ZONE_RECORDS).aggregates[0]
    assert row["duration_p50_minutes"] == Decimal("30.000")
    assert row["duration_p95_minutes"] == Decimal("60.000")


def test_zone_lookup_duplicate_id_is_rejected_before_join():
    duplicate = ZONE_RECORDS + [ZONE_RECORDS[0]]
    with pytest.raises(oracle.OracleContractError, match="duplicate LocationID 1"):
        oracle.run_oracle([], duplicate)
