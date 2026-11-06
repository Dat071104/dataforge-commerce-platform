"""Compare the current synthetic CSV Decimal oracle with PostgreSQL Gold controls."""
from __future__ import annotations

import json
from decimal import Decimal

import psycopg

from dataforge.reference import reference_metrics
from dataforge.settings import SQL, database_url

METRICS = (
    "fulfilled_sales_proxy_vnd",
    "fulfilled_cogs_proxy_vnd",
    "collected_vnd",
    "completed_refunds_vnd",
    "collection_variance_vnd",
)


def main() -> None:
    oracle = reference_metrics()
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(
                (SQL / "checks" / "003_independent_metric_comparison.sql").read_text(
                    encoding="utf-8"
                )
            )
            sql_metrics = {name: Decimal(str(value)) for name, value in cur.fetchall()}

    if set(sql_metrics) != set(METRICS) or not set(METRICS).issubset(oracle):
        raise SystemExit(
            "Metric set mismatch: "
            f"SQL={sorted(sql_metrics)}, oracle={sorted(oracle)}"
        )

    comparisons = {
        name: {
            "decimal_oracle_vnd": str(Decimal(str(oracle[name]))),
            "postgres_vnd": str(sql_metrics[name]),
            "match": Decimal(str(oracle[name])) == sql_metrics[name],
        }
        for name in METRICS
    }
    print(json.dumps(comparisons, indent=2, sort_keys=True))
    mismatches = [name for name, values in comparisons.items() if not values["match"]]
    if mismatches:
        raise SystemExit(f"CSV Decimal oracle and PostgreSQL differ for: {mismatches}")


if __name__ == "__main__":
    main()
