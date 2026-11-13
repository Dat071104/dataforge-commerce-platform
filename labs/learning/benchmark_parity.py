"""Repeated, non-gating local timings for the small parity fixture."""

from __future__ import annotations

import json
import statistics
import tempfile
import time
from pathlib import Path

import pandas as pd
import polars as pl
from parity_pipeline import run_pandas_pipeline, run_polars_pipeline

FIXTURES = Path(__file__).parent / "fixtures"
REPEATS = 7


def _measure(function, output_root: Path) -> list[float]:
    # One untimed warm-up avoids treating first-use setup as a steady-state run.
    function(output_root / "warmup.parquet")
    samples: list[float] = []
    for index in range(REPEATS):
        start = time.perf_counter()
        function(output_root / f"run-{index}.parquet")
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="dataforge-parity-") as temp_dir:
        temp = Path(temp_dir)
        pandas = _measure(
            lambda output: run_pandas_pipeline(
                FIXTURES / "orders.csv", FIXTURES / "provinces.csv", output
            ),
            temp / "pandas",
        )
        polars = _measure(
            lambda output: run_polars_pipeline(
                FIXTURES / "orders.csv", FIXTURES / "provinces.csv", output
            ),
            temp / "polars",
        )
    print(
        json.dumps(
            {
                "fixture_orders": 8,
                "timed_repeats": REPEATS,
                "timing_unit": "milliseconds",
                "pandas_version": pd.__version__,
                "polars_version": pl.__version__,
                "pandas_median_ms": round(statistics.median(pandas), 3),
                "pandas_population_sd_ms": round(statistics.pstdev(pandas), 3),
                "polars_median_ms": round(statistics.median(polars), 3),
                "polars_population_sd_ms": round(statistics.pstdev(polars), 3),
                "note": "Tiny fixture only; no speedup claim or migration recommendation.",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
