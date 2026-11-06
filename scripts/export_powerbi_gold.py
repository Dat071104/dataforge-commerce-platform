"""Export a consistent PostgreSQL Gold snapshot for credential-free Power BI import.

Power BI can refresh these CSV files after the export command is rerun. The
manifest records exactly which Gold tables and row counts were exported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg

from dataforge.settings import database_url

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "powerbi_gold_export"

# Explicit whitelist and stable ordering make exports reviewable and prevent
# accidental exposure of raw/audit tables or credentials.
TABLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("dw", "dim_date", ("date_key",)),
    ("dw", "dim_customer", ("customer_key",)),
    ("dw", "dim_product", ("product_key",)),
    ("dw", "dim_geography", ("geography_key",)),
    ("dw", "fct_order_item", ("order_item_id",)),
    ("dw", "fct_payment", ("payment_id",)),
    ("dw", "fct_return", ("return_id",)),
    ("dw", "fct_shipment", ("shipment_id",)),
    ("dw", "fct_inventory_snapshot", ("snapshot_date_key", "product_key")),
    ("dw", "fct_weather_daily", ("date_key", "geography_key")),
    ("analytics", "vw_order_reconciliation", ("order_id",)),
)


def _excel_value(value: object) -> object:
    """Convert PostgreSQL scalar values to Excel-supported cell values."""
    if isinstance(value, Decimal):
        return float(value)
    return value


def export_gold(output: Path = DEFAULT_OUTPUT, *, excel: bool = False) -> dict[str, object]:
    """Write a repeatable CSV snapshot and manifest from one read-only DB snapshot."""
    output.mkdir(parents=True, exist_ok=True)
    tables: list[dict[str, object]] = []

    with psycopg.connect(database_url()) as conn:
        conn.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        server_version = conn.execute("SHOW server_version").fetchone()[0]
        database_name = conn.execute("SELECT current_database()").fetchone()[0]

        workbook = None
        if excel:
            try:
                from openpyxl import Workbook
            except ImportError as exc:
                raise SystemExit(
                    "Excel export requires the optional dependency; install with "
                    "`python -m pip install -e '.[powerbi]'`."
                ) from exc
            workbook = Workbook(write_only=True)

        for schema, table, order_by in TABLES:
            filename = f"{table}.csv"
            target = output / filename
            temporary = output / f".{target.stem}.{uuid4().hex}{target.suffix}"
            quoted_table = f'"{schema}"."{table}"'
            order_clause = ", ".join(f'"{column}"' for column in order_by)
            copy_sql = (
                f"COPY (SELECT * FROM {quoted_table} ORDER BY {order_clause}) "
                "TO STDOUT WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')"
            )
            try:
                with temporary.open("wb") as stream, conn.cursor().copy(copy_sql) as copy:
                    for chunk in copy:
                        stream.write(chunk)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)

            row_count = conn.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()[0]
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if workbook is not None:
                sheet = workbook.create_sheet(table)
                select_sql = (
                    f"SELECT * FROM {quoted_table} ORDER BY {order_clause}"
                )
                with conn.cursor(name=f"pbi_{schema}_{table}") as cursor:
                    cursor.execute(select_sql)
                    sheet.append([column.name for column in cursor.description])
                    for row in cursor:
                        sheet.append([_excel_value(value) for value in row])
            tables.append(
                {
                    "schema": schema,
                    "table": table,
                    "file": filename,
                    "row_count": row_count,
                    "bytes": target.stat().st_size,
                    "sha256": digest,
                }
            )

        excel_metadata: dict[str, object] | None = None
        if workbook is not None:
            excel_path = output / "DataForgeGold.xlsx"
            temporary_excel = output / f".DataForgeGold.{uuid4().hex}.xlsx"
            try:
                workbook.save(temporary_excel)
                os.replace(temporary_excel, excel_path)
            finally:
                temporary_excel.unlink(missing_ok=True)
            excel_metadata = {
                "file": excel_path.name,
                "bytes": excel_path.stat().st_size,
                "sha256": hashlib.sha256(excel_path.read_bytes()).hexdigest(),
                "sheets": [table for _, table, _ in TABLES],
            }

    manifest: dict[str, object] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "PostgreSQL Gold-layer snapshot",
        "endpoint": "127.0.0.1:5433",
        "database": database_name,
        "server_version": server_version,
        "data_classification": "synthetic demo; no personal or third-party data",
        "tables": tables,
    }
    if excel_metadata is not None:
        manifest["excel_workbook"] = excel_metadata
    manifest_path = output / "manifest.json"
    temporary_manifest = output / f".manifest.{uuid4().hex}.json"
    try:
        temporary_manifest.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary_manifest, manifest_path)
    finally:
        temporary_manifest.unlink(missing_ok=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"directory for CSV snapshots (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--excel",
        action="store_true",
        help="also write DataForgeGold.xlsx (requires the `powerbi` extra)",
    )
    args = parser.parse_args()
    manifest = export_gold(args.output.resolve(), excel=args.excel)
    for item in manifest["tables"]:
        assert isinstance(item, dict)
        print(f"{item['schema']}.{item['table']}: {item['row_count']} rows -> {item['file']}")
    print(f"Manifest: {args.output.resolve() / 'manifest.json'}")


if __name__ == "__main__":
    main()
