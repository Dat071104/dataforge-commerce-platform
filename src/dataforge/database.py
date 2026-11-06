"""Transactional PostgreSQL loading / mart building / SQL assertion checks."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from .ingestion import contracts, read_verified_bronze
from .settings import MANIFESTS, SQL, database_url


def _psycopg():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("PostgreSQL integration requires psycopg; run `pip install -e .[dev]`") from exc
    return psycopg


def run_file(sql_path: Path) -> None:
    psycopg = _psycopg()
    with psycopg.connect(database_url()) as conn:
        # Each SQL script executes in a transaction. Raises => rolls back.
        with conn.cursor() as cur:
            cur.execute(sql_path.read_text(encoding="utf-8"))


def init() -> None:
    run_file(SQL / "schema" / "001_init.sql")


def _read_json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _source_manifests(specs: dict[str, dict[str, list[str]]]) -> dict[str, dict]:
    """Resolve one complete manifest set before opening a transaction or truncating raw."""
    active_path = MANIFESTS / "active.json"
    if active_path.is_file():
        active = _read_json_object(active_path)
        run_id = active.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id
        ):
            raise ValueError(f"Invalid run_id in {active_path}")

        run_path = MANIFESTS / "runs" / f"{run_id}.json"
        if not run_path.is_file():
            raise FileNotFoundError(f"Active run record is missing: {run_path}")
        run = _read_json_object(run_path)
        recorded_run_id = run.get("run_id")
        if recorded_run_id != run_id:
            raise ValueError(
                f"Active run pointer {run_id!r} does not match record {recorded_run_id!r}"
            )
        if run.get("status") != "complete":
            raise ValueError(
                f"Active ingestion run {run_id!r} is not complete "
                f"(status={run.get('status')!r})"
            )

        sources = run.get("sources")
        if not isinstance(sources, dict):
            raise ValueError(f"Active ingestion run {run_id!r} has no sources map")
        expected, actual = set(specs), set(sources)
        missing, unexpected = sorted(expected - actual), sorted(actual - expected)
        if missing or unexpected:
            raise ValueError(
                f"Active ingestion run {run_id!r} has incomplete sources "
                f"(missing={missing}, unexpected={unexpected})"
            )
        manifests = sources
    else:
        # Backwards compatibility for workspaces created before run manifests.
        manifests = {}
        for name in specs:
            filename = MANIFESTS / f"{name}.json"
            if not filename.is_file():
                raise FileNotFoundError(f"Missing {filename}. Run `dataforge ingest` first")
            manifests[name] = _read_json_object(filename)

    for name, manifest in manifests.items():
        if not isinstance(manifest, dict):
            raise ValueError(f"Manifest for {name} must be a JSON object")
        if manifest.get("source") != name:
            raise ValueError(f"Manifest source mismatch for {name}")
        source_sha = manifest.get("source_sha256")
        if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha):
            raise ValueError(f"Manifest for {name} has an invalid source_sha256")
        bronze_sha = manifest.get("bronze_sha256")
        if not isinstance(bronze_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", bronze_sha):
            raise ValueError(
                f"Manifest for {name} uses a legacy format without a valid bronze_sha256; "
                "run `dataforge ingest` without a source filter to validate and migrate "
                "the Parquet artifacts before `dataforge db-load`"
            )
        expected_rows = manifest.get("rows_accepted")
        if type(expected_rows) is not int or expected_rows <= 0:
            raise ValueError(f"Manifest for {name} has an invalid rows_accepted count")
        bronze_file = manifest.get("bronze_file")
        if not isinstance(bronze_file, str) or not bronze_file:
            raise ValueError(f"Manifest for {name} is missing bronze_file")
        try:
            read_verified_bronze(
                bronze_file,
                source=name,
                expected_sha256=bronze_sha,
                expected_columns=specs[name]["required_columns"],
                expected_rows=expected_rows,
            )
        except ValueError as exc:
            raise ValueError(f"Invalid Bronze artifact for {name}: {exc}") from exc
    return manifests


def _stage_snapshot(cur, sql, name: str, spec: dict, manifest: dict) -> tuple[str, int]:
    columns = spec["required_columns"]
    df = read_verified_bronze(
        manifest["bronze_file"],
        source=name,
        expected_sha256=manifest["bronze_sha256"],
        expected_columns=columns,
        expected_rows=manifest["rows_accepted"],
    )

    stage_name = f"dataforge_stage_{name}"
    target = sql.Identifier("raw", name)
    stage = sql.Identifier("pg_temp", stage_name)
    cur.execute(
        sql.SQL("CREATE TEMP TABLE {} (LIKE {} INCLUDING ALL) ON COMMIT DROP").format(
            sql.Identifier(stage_name), target
        )
    )
    copy_command = sql.SQL("COPY {} ({}) FROM STDIN").format(
        stage, sql.SQL(", ").join(map(sql.Identifier, columns))
    )
    with cur.copy(copy_command) as copy:
        for row in df.itertuples(index=False, name=None):
            copy.write_row(tuple(None if pd.isna(value) or value == "" else str(value)
                                 for value in row))
    return stage_name, len(df)


def _raw_reference_failures(cur) -> dict[str, int]:
    cur.execute("""
        SELECT 'orphan_order_customers' AS check_name, count(*) AS failures
          FROM raw.orders o LEFT JOIN raw.customers c USING (customer_id)
          WHERE c.customer_id IS NULL
        UNION ALL
        SELECT 'orphan_order_geography', count(*)
          FROM raw.orders o LEFT JOIN raw.geography g USING (province_id)
          WHERE g.province_id IS NULL
        UNION ALL
        SELECT 'orphan_customer_geography', count(*)
          FROM raw.customers c LEFT JOIN raw.geography g USING (province_id)
          WHERE g.province_id IS NULL
        UNION ALL
        SELECT 'orphan_customer_segments', count(*)
          FROM raw.customer_segments s LEFT JOIN raw.customers c USING (customer_id)
          WHERE c.customer_id IS NULL
        UNION ALL
        SELECT 'customer_current_version_count', count(*)
          FROM raw.customers c
          LEFT JOIN (
            SELECT customer_id, count(*) AS current_versions
            FROM raw.customer_segments
            WHERE valid_to IS NULL
            GROUP BY customer_id
          ) s USING (customer_id)
          WHERE coalesce(s.current_versions, 0) <> 1
        UNION ALL
        SELECT 'customer_current_segment_mismatch', count(*)
          FROM raw.customers c
          LEFT JOIN raw.customer_segments s
            ON s.customer_id = c.customer_id AND s.valid_to IS NULL
          WHERE s.customer_id IS NULL OR s.segment IS DISTINCT FROM c.segment
        UNION ALL
        SELECT 'customer_order_segment_match_count', count(*)
          FROM raw.orders o
          WHERE (
            SELECT count(*)
            FROM raw.customer_segments s
            WHERE s.customer_id = o.customer_id
              AND o.order_date >= s.valid_from
              AND (s.valid_to IS NULL OR o.order_date < s.valid_to)
          ) <> 1
        UNION ALL
        SELECT 'customer_segment_overlap', count(*)
          FROM raw.customer_segments a
          JOIN raw.customer_segments b
            ON a.customer_id = b.customer_id
           AND a.valid_from < b.valid_from
           AND a.valid_from < coalesce(b.valid_to, 'infinity'::date)
           AND b.valid_from < coalesce(a.valid_to, 'infinity'::date)
        UNION ALL
        SELECT 'orphan_order_items_orders', count(*)
          FROM raw.order_items i LEFT JOIN raw.orders o USING (order_id)
          WHERE o.order_id IS NULL
        UNION ALL
        SELECT 'orphan_order_items_products', count(*)
          FROM raw.order_items i LEFT JOIN raw.products p USING (product_id)
          WHERE p.product_id IS NULL
        UNION ALL
        SELECT 'orphan_payments_orders', count(*)
          FROM raw.payments p LEFT JOIN raw.orders o USING (order_id)
          WHERE o.order_id IS NULL
        UNION ALL
        SELECT 'orphan_shipments_orders', count(*)
          FROM raw.shipments s LEFT JOIN raw.orders o USING (order_id)
          WHERE o.order_id IS NULL
        UNION ALL
        SELECT 'orphan_returns_order_items', count(*)
          FROM raw.returns r LEFT JOIN raw.order_items i USING (order_item_id)
          WHERE i.order_item_id IS NULL
        UNION ALL
        SELECT 'orphan_inventory_products', count(*)
          FROM raw.inventory i LEFT JOIN raw.products p USING (product_id)
          WHERE p.product_id IS NULL
        UNION ALL
        SELECT 'orphan_weather_geography', count(*)
          FROM raw.weather_daily w LEFT JOIN raw.geography g USING (province_id)
          WHERE g.province_id IS NULL
    """)
    return {name: int(failures) for name, failures in cur.fetchall() if failures}


def load() -> dict[str, int]:
    """Stage and transactionally merge complete source snapshots by their primary keys."""
    psycopg = _psycopg()
    from psycopg import sql

    specs = contracts()
    manifests = _source_manifests(specs)
    counts = {}
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (source) source, sha256, row_count
                FROM audit.load_runs
                ORDER BY source, loaded_at DESC, run_id DESC
            """)
            last_applied = {
                source: (source_hash, int(row_count))
                for source, source_hash, row_count in cur.fetchall()
            }
            changed = [
                name for name in specs
                if last_applied.get(name, (None, 0))[0] != manifests[name]["source_sha256"]
            ]

            # Every changed source is staged before any raw table is modified.
            # A COPY, schema, or duplicate-key failure therefore rolls back the
            # entire batch without exposing a partially merged source set.
            staged: dict[str, tuple[str, int]] = {}
            for name in changed:
                staged[name] = _stage_snapshot(cur, sql, name, specs[name], manifests[name])

            for name, spec in specs.items():
                if name not in staged:
                    counts[name] = last_applied[name][1]
                    continue

                stage_name, row_count = staged[name]
                table = sql.Identifier("raw", name)
                stage = sql.Identifier("pg_temp", stage_name)
                columns = spec["required_columns"]
                primary_key = spec["primary_key"]
                non_key_columns = [column for column in columns if column not in primary_key]
                key_match = sql.SQL(" AND ").join(
                    sql.SQL("target.{} = staged.{}").format(
                        sql.Identifier(column), sql.Identifier(column)
                    )
                    for column in primary_key
                )

                if non_key_columns:
                    set_values = sql.SQL(", ").join(
                        sql.SQL("{} = staged.{}").format(
                            sql.Identifier(column), sql.Identifier(column)
                        )
                        for column in non_key_columns
                    )
                    differs = sql.SQL(" OR ").join(
                        sql.SQL("target.{} IS DISTINCT FROM staged.{}").format(
                            sql.Identifier(column), sql.Identifier(column)
                        )
                        for column in non_key_columns
                    )
                    cur.execute(
                        sql.SQL("""
                            UPDATE {} AS target
                            SET {}
                            FROM {} AS staged
                            WHERE {} AND ({})
                        """).format(table, set_values, stage, key_match, differs)
                    )
                    rows_updated = cur.rowcount
                else:
                    rows_updated = 0

                target_columns = sql.SQL(", ").join(map(sql.Identifier, columns))
                staged_columns = sql.SQL(", ").join(
                    sql.SQL("staged.{}").format(sql.Identifier(column)) for column in columns
                )
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {} ({})
                        SELECT {}
                        FROM {} AS staged
                        WHERE NOT EXISTS (
                            SELECT 1 FROM {} AS target WHERE {}
                        )
                    """).format(table, target_columns, staged_columns, stage, table, key_match)
                )
                rows_inserted = cur.rowcount

                cur.execute(
                    sql.SQL("""
                        DELETE FROM {} AS target
                        WHERE NOT EXISTS (
                            SELECT 1 FROM {} AS staged WHERE {}
                        )
                    """).format(table, stage, key_match)
                )
                rows_deleted = cur.rowcount

                cur.execute("""
                    INSERT INTO audit.load_runs
                      (source, sha256, row_count, operation,
                       rows_inserted, rows_updated, rows_deleted)
                    VALUES (%s, %s, %s, 'snapshot_merge', %s, %s, %s)
                    ON CONFLICT (source, sha256, operation)
                    DO UPDATE SET loaded_at = now(), row_count = EXCLUDED.row_count,
                      rows_inserted = EXCLUDED.rows_inserted,
                      rows_updated = EXCLUDED.rows_updated,
                      rows_deleted = EXCLUDED.rows_deleted
                """, (
                    name, manifests[name]["source_sha256"], row_count,
                    rows_inserted, rows_updated, rows_deleted,
                ))
                counts[name] = row_count

            reference_failures = _raw_reference_failures(cur)
            if reference_failures:
                raise ValueError(f"Snapshot batch violates raw references: {reference_failures}")
    return counts


def build() -> None:
    run_file(SQL / "build" / "010_marts.sql")


def check(synthetic: bool = False) -> dict[str, int]:
    psycopg = _psycopg()
    results = {}
    scripts = [SQL / "checks" / "001_checks.sql"]
    if synthetic:
        scripts.append(SQL / "checks" / "002_synthetic_only.sql")
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            for path in scripts:
                cur.execute(path.read_text(encoding="utf-8"))
                results.update({name: int(fails) for name, fails in cur.fetchall()})
    failing = {k: v for k, v in results.items() if v}
    if failing:
        raise AssertionError(f"Database quality checks failed: {failing}")
    return results


def query(query_name: str) -> list[tuple]:
    psycopg = _psycopg()
    available = {p.stem: p for p in (SQL / "analysis").glob("q*.sql")}
    if query_name not in available:
        raise ValueError(f"Query must be one of {sorted(available)}")
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(available[query_name].read_text(encoding="utf-8"))
            return cur.fetchall() if cur.description else []
