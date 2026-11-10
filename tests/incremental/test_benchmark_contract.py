import io
from decimal import Decimal

import pyarrow.parquet as pq

from scripts import week5_benchmark as benchmark


def test_synthetic_benchmark_fixture_has_exact_delta_and_decimal_amounts():
    changed = [
        benchmark._record(index, final=True)
        for index in range(0, benchmark.ROW_COUNT, benchmark.CHANGE_INTERVAL)
    ]
    unchanged = benchmark._record(1, final=True)
    base = benchmark._record(0, final=False)

    assert len(changed) == 1_000
    assert changed[0]["order_id"] == "W5BENCH000000"
    assert changed[0]["amount"] == base["amount"] + Decimal("1.25")
    assert changed[0]["effective_seq"] == benchmark.ROW_COUNT + 1
    assert unchanged["status"] == "paid"
    assert unchanged["effective_seq"] == 1
    assert benchmark._payload(0, "base") != benchmark._payload(0, "updated")


def test_benchmark_parquet_round_trip_preserves_decimal_and_payload():
    payload = benchmark._write_parquet(
        [benchmark._record(0, final=False), benchmark._record(0, final=True)]
    )
    rows = pq.read_table(io.BytesIO(payload)).to_pylist()

    assert rows[0]["amount"] == Decimal("100.00")
    assert rows[1]["amount"] == Decimal("101.25")
    assert rows[0]["payload"] != rows[1]["payload"]
    assert rows[1]["effective_seq"] == benchmark.ROW_COUNT + 1


def test_benchmark_query_cost_aggregates_query_jobs_not_load_or_copy_jobs():
    processed, billed, cost = benchmark._aggregate_query_usage(
        [
            {"job_type": "query", "bytes_processed": 20, "bytes_billed": 10},
            {"job_type": "QUERY", "bytes_processed": 30, "bytes_billed": 20},
            {"job_type": "load", "bytes_processed": 900, "bytes_billed": 800},
            {"job_type": "copy", "bytes_processed": 700, "bytes_billed": 600},
        ]
    )

    assert processed == 50
    assert billed == 30
    assert cost > 0
