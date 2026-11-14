from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl

from labs.learning.parity_pipeline import run_pandas_pipeline, run_polars_pipeline

FIXTURES = Path(__file__).parents[2] / "labs" / "learning" / "fixtures"


def _canonical(frame: pd.DataFrame | pl.DataFrame) -> list[tuple[str, str, int, float]]:
    if isinstance(frame, pl.DataFrame):
        rows: list[dict[str, Any]] = frame.to_dicts()
    else:
        rows = frame.to_dict(orient="records")
    return [
        (
            str(row["province_id"]),
            str(row["province_name"]),
            int(row["order_count"]),
            round(float(row["amount_total"]), 2),
        )
        for row in rows
    ]


def test_pandas_and_polars_match_after_parquet_round_trip(tmp_path: Path) -> None:
    pandas_result = run_pandas_pipeline(
        FIXTURES / "orders.csv",
        FIXTURES / "provinces.csv",
        tmp_path / "pandas" / "result.parquet",
    )
    polars_result = run_polars_pipeline(
        FIXTURES / "orders.csv",
        FIXTURES / "provinces.csv",
        tmp_path / "polars" / "result.parquet",
    )

    expected = [
        ("P1", "Ho Chi Minh City", 2, 100.00),
        ("P2", "Hanoi", 1, 35.50),
        ("P3", "Da Nang", 2, 100.25),
    ]
    assert _canonical(pandas_result) == expected
    assert _canonical(polars_result) == expected
    assert _canonical(pandas_result) == _canonical(polars_result)
