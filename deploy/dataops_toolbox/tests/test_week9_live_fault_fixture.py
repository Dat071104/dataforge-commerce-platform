"""R-18: the live F07/F10 fixture must load into BigQuery with a TIMESTAMP landed_at."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOLBOX = ROOT / "deploy" / "dataops_toolbox"
sys.path.insert(0, str(TOOLBOX))

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from week9_live_faults import bigquery_ready_parquet  # noqa: E402

FIXTURE = ROOT / "tests" / "week9" / "faults" / "weather_7date_slice.parquet"


def test_fixture_timestamps_are_narrowed_to_microseconds() -> None:
    original = pq.read_table(FIXTURE)
    converted = pq.read_table(bigquery_ready_parquet(FIXTURE))

    assert original.schema.field("landed_at").type.unit == "ns"
    landed_at = converted.schema.field("landed_at").type
    assert pa.types.is_timestamp(landed_at)
    assert landed_at.unit == "us"
    assert landed_at.tz == original.schema.field("landed_at").type.tz
    assert converted.num_rows == original.num_rows
    assert converted.column("landed_at").cast(pa.int64()).to_pylist() == [
        value // 1000 for value in original.column("landed_at").cast(pa.int64()).to_pylist()
    ]
    assert converted.drop(["landed_at"]).equals(original.drop(["landed_at"]))
