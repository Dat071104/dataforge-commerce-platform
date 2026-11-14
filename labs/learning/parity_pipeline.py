"""Small, deterministic Pandas/Polars parity fixture for learning exercises."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import polars as pl


def run_pandas_pipeline(
    orders_path: Path,
    provinces_path: Path,
    output_path: Path,
) -> pd.DataFrame:
    orders = pd.read_csv(orders_path, dtype={"order_id": "string", "province_id": "string", "status": "string"})
    provinces = pd.read_csv(provinces_path, dtype={"province_id": "string", "province_name": "string"})
    delivered = orders.loc[orders["status"].eq("delivered")]
    joined = delivered.merge(provinces, on="province_id", how="inner", validate="many_to_one")
    result = (
        joined.groupby(["province_id", "province_name"], as_index=False, sort=True)
        .agg(order_count=("order_id", "nunique"), amount_total=("amount", "sum"))
        .sort_values("province_id", kind="stable")
        .reset_index(drop=True)
    )
    result["amount_total"] = result["amount_total"].round(2)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)
    return pd.read_parquet(output_path)


def run_polars_pipeline(
    orders_path: Path,
    provinces_path: Path,
    output_path: Path,
) -> pl.DataFrame:
    orders = pl.read_csv(orders_path)
    provinces = pl.read_csv(provinces_path)
    result = (
        orders.filter(pl.col("status") == "delivered")
        .join(provinces, on="province_id", how="inner", validate="m:1")
        .group_by(["province_id", "province_name"])
        .agg(
            pl.col("order_id").n_unique().alias("order_count"),
            pl.col("amount").sum().alias("amount_total"),
        )
        .with_columns(pl.col("amount_total").round(2))
        .sort("province_id")
        .select("province_id", "province_name", "order_count", "amount_total")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.write_parquet(output_path)
    return pl.read_parquet(output_path)
