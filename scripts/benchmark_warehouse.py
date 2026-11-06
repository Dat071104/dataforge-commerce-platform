"""Build an isolated 100K-order warehouse and capture comparable q10 plans."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import re
import statistics
import tempfile
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql

from dataforge import database, ingestion
from dataforge.generator import generate
from dataforge.reference import reference_metrics

ROOT = Path(__file__).resolve().parents[1]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--runs", type=int, default=5, help="measured EXPLAIN runs per phase")
    parser.add_argument("--warmups", type=int, default=2, help="unrecorded warmups per phase")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(tempfile.gettempdir()) / "DataForge" / "warehouse_benchmark_100k.json",
        help="JSON report path (default is outside the repository in the OS temp directory)",
    )
    args = parser.parse_args()
    if args.orders < 1 or args.runs < 1 or args.warmups < 0:
        parser.error("orders/runs must be positive and warmups cannot be negative")
    return args


@contextmanager
def _isolated_database(base_url: str):
    parts = urlsplit(base_url)
    if parts.scheme not in {"postgres", "postgresql"}:
        raise ValueError("Benchmark requires a PostgreSQL URL")
    query = [(key, value) for key, value in parse_qsl(parts.query) if key != "connect_timeout"]
    query.append(("connect_timeout", "10"))
    query_text = urlencode(query)
    maintenance_url = urlunsplit((parts.scheme, parts.netloc, "/postgres", query_text, parts.fragment))
    database_name = f"dataforge_bench_{uuid4().hex[:16]}"
    test_url = urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", query_text, parts.fragment))
    with psycopg.connect(maintenance_url, autocommit=True, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        yield test_url
    finally:
        with psycopg.connect(maintenance_url, autocommit=True, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
                )


def _physical_memory_bytes() -> int | None:
    if os.name != "nt":
        return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return int(status.total_physical)
    return None


def _host_facts() -> dict:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_processors": os.cpu_count(),
        "physical_memory_bytes": _physical_memory_bytes(),
    }


def _q10_select() -> str:
    source = (ROOT / "sql" / "analysis" / "q10_explain_performance.sql").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"(?is)EXPLAIN\s*\(\s*ANALYZE\s*,\s*BUFFERS\s*\)\s*(SELECT\b.*?;)",
        source,
    )
    if not match:
        raise ValueError("Could not extract the SELECT from q10_explain_performance.sql")
    return match.group(1).strip().rstrip(";")


def _explain_json(conn, query: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}")
        result = cur.fetchone()[0]
    if isinstance(result, str):
        result = json.loads(result)
    if isinstance(result, list):
        return result[0]
    if isinstance(result, dict):
        return result
    raise TypeError(f"Unexpected EXPLAIN JSON result: {type(result).__name__}")


def _plan_nodes(root: dict) -> list[dict]:
    nodes: list[dict] = []

    def visit(node: dict, depth: int) -> None:
        nodes.append({
            "depth": depth,
            "node_type": node.get("Node Type"),
            "relation": node.get("Relation Name"),
            "index": node.get("Index Name"),
            "actual_rows": node.get("Actual Rows"),
            "loops": node.get("Actual Loops"),
            "actual_total_time_ms": node.get("Actual Total Time"),
            "shared_hit_blocks": node.get("Shared Hit Blocks"),
            "shared_read_blocks": node.get("Shared Read Blocks"),
            "heap_fetches": node.get("Heap Fetches"),
        })
        for child in node.get("Plans", []):
            visit(child, depth + 1)

    visit(root, 0)
    return nodes


def _measure_phase(test_url: str, query: str, warmups: int, runs: int) -> dict:
    plans = []
    with psycopg.connect(test_url) as conn:
        for run_index in range(warmups + runs):
            document = _explain_json(conn, query)
            if run_index >= warmups:
                plans.append(document)
    executions = [float(plan["Execution Time"]) for plan in plans]
    representative = plans[0]
    root_plan = representative["Plan"]
    return {
        "warmups": warmups,
        "measured_runs": runs,
        "execution_ms": executions,
        "median_execution_ms": statistics.median(executions),
        "min_execution_ms": min(executions),
        "max_execution_ms": max(executions),
        "representative_planning_ms": representative.get("Planning Time"),
        "representative_execution_ms": representative.get("Execution Time"),
        "representative_plan_nodes": _plan_nodes(root_plan),
        "raw_explain_json": plans,
    }


def _relation_sizes(test_url: str) -> dict[str, int]:
    with psycopg.connect(test_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pg_relation_size('dw.fct_order_item'),
                       pg_indexes_size('dw.fct_order_item'),
                       pg_total_relation_size('dw.fct_order_item')
            """)
            table_bytes, index_bytes, total_bytes = cur.fetchone()
    return {
        "table_bytes": int(table_bytes),
        "index_bytes": int(index_bytes),
        "total_bytes": int(total_bytes),
    }


def _run(args: argparse.Namespace) -> dict:
    base_url = database.database_url()
    query = _q10_select()
    result: dict = {
        "dataset_class": "synthetic",
        "seed": args.seed,
        "orders_requested": args.orders,
        "host": _host_facts(),
        "postgresql": {},
        "method": {
            "query": query,
            "baseline_index_state": "P4 mart indexes only, including fct_item_order_date_idx",
            "candidate_index": "fct_item_q10_covering_idx (order_date_key, product_key) INCLUDE (fulfilled_sales_proxy)",
            "warmups_per_phase": args.warmups,
            "measured_runs_per_phase": args.runs,
            "cache_method": "VACUUM ANALYZE before baseline; warm both phases; no cache flush; report raw runs and buffers",
        },
    }

    original_attributes = {
        "ingestion_bronze": ingestion.BRONZE,
        "ingestion_manifests": ingestion.MANIFESTS,
        "ingestion_quarantine": ingestion.QUARANTINE,
        "database_manifests": database.MANIFESTS,
        "database_url": database.database_url,
    }
    with tempfile.TemporaryDirectory(prefix="dataforge_warehouse_100k_") as scratch:
        temp_root = Path(scratch)
        source_dir = temp_root / "source"
        bronze_dir = temp_root / "bronze"
        manifests_dir = temp_root / "manifests"
        quarantine_dir = temp_root / "quarantine"

        with _isolated_database(base_url) as test_url:
            ingestion.BRONZE = bronze_dir
            ingestion.MANIFESTS = manifests_dir
            ingestion.QUARANTINE = quarantine_dir
            database.MANIFESTS = manifests_dir
            database.database_url = lambda: test_url
            try:
                start = time.perf_counter()
                source_counts = generate(count=args.orders, seed=args.seed, dest=source_dir)
                result["phase_seconds"] = {"generate": time.perf_counter() - start}

                start = time.perf_counter()
                manifests = ingestion.ingest(source_dir)
                result["phase_seconds"]["ingest"] = time.perf_counter() - start
                source_csv_bytes = sum(path.stat().st_size for path in source_dir.glob("*.csv"))
                bronze_bytes = sum(path.stat().st_size for path in bronze_dir.rglob("*.parquet"))
                result["dataset"] = {
                    "source_row_counts": source_counts,
                    "source_csv_bytes": source_csv_bytes,
                    "bronze_parquet_bytes": bronze_bytes,
                    "ingestion_manifest_count": len(manifests),
                }

                start = time.perf_counter()
                database.init()
                result["phase_seconds"]["db_init"] = time.perf_counter() - start
                start = time.perf_counter()
                loaded_counts = database.load()
                result["phase_seconds"]["db_load"] = time.perf_counter() - start
                result["loaded_counts"] = loaded_counts
                start = time.perf_counter()
                database.build()
                result["phase_seconds"]["db_build"] = time.perf_counter() - start
                check_results = database.check(synthetic=True)
                result["quality_checks"] = check_results
                if any(check_results.values()):
                    raise AssertionError(f"warehouse checks failed: {check_results}")

                query_rows = {}
                for path in sorted((ROOT / "sql" / "analysis").glob("q*.sql")):
                    query_rows[path.stem] = len(database.query(path.stem))
                result["analysis_query_row_counts"] = query_rows
                if len(query_rows) != 10:
                    raise AssertionError(f"expected 10 analysis queries, found {len(query_rows)}")

                oracle = reference_metrics(source_dir)
                with psycopg.connect(test_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            (ROOT / "sql" / "checks" / "003_independent_metric_comparison.sql")
                            .read_text(encoding="utf-8")
                        )
                        sql_metrics = dict(cur.fetchall())
                        cur.execute("""
                            SELECT current_setting('server_version'),
                                   current_setting('shared_buffers'),
                                   current_setting('effective_cache_size'),
                                   current_setting('work_mem'),
                                   current_setting('max_parallel_workers_per_gather')
                        """)
                        (version, shared_buffers, effective_cache_size,
                         work_mem, parallel_workers) = cur.fetchone()
                        cur.execute("SELECT count(*) FROM dw.fct_order_item")
                        fact_item_rows = cur.fetchone()[0]
                expected_keys = {
                    "fulfilled_sales_proxy_vnd": "fulfilled_sales_proxy_vnd",
                    "fulfilled_cogs_proxy_vnd": "fulfilled_cogs_proxy_vnd",
                    "collected_vnd": "collected_vnd",
                    "completed_refunds_vnd": "completed_refunds_vnd",
                    "collection_variance_vnd": "collection_variance_vnd",
                }
                mismatches = {}
                for sql_name, oracle_name in expected_keys.items():
                    expected = Decimal(str(oracle[oracle_name]))
                    actual = Decimal(str(sql_metrics[sql_name]))
                    if actual != expected:
                        mismatches[sql_name] = {"oracle": str(expected), "sql": str(actual)}
                if mismatches:
                    raise AssertionError(f"SQL and Decimal oracle disagree: {mismatches}")
                result["metric_reconciliation"] = {
                    name: {"decimal_oracle": str(Decimal(str(oracle[oracle_name]))),
                           "sql": str(Decimal(str(sql_metrics[name])))}
                    for name, oracle_name in expected_keys.items()
                }
                result["dataset"]["fct_order_item_rows"] = int(fact_item_rows)
                result["postgresql"] = {
                    "server_version": version,
                    "shared_buffers": shared_buffers,
                    "effective_cache_size": effective_cache_size,
                    "work_mem": work_mem,
                    "max_parallel_workers_per_gather": parallel_workers,
                }

                # VACUUM makes heap visibility consistent before the baseline;
                # both phases then receive identical warmups and measured runs.
                with psycopg.connect(test_url, autocommit=True) as conn:
                    with conn.cursor() as cur:
                        cur.execute("VACUUM (ANALYZE) dw.fct_order_item")
                result["relation_size_before_candidate"] = _relation_sizes(test_url)
                result["benchmark"] = {
                    "baseline": _measure_phase(test_url, query, args.warmups, args.runs)
                }

                start = time.perf_counter()
                database.run_file(ROOT / "sql" / "performance" / "002_q10_covering_index.sql")
                result["phase_seconds"]["candidate_index_create_and_analyze"] = (
                    time.perf_counter() - start
                )
                result["relation_size_after_candidate"] = _relation_sizes(test_url)
                with psycopg.connect(test_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT pg_relation_size('dw.fct_item_q10_covering_idx')
                        """)
                        result["candidate_index_bytes"] = int(cur.fetchone()[0])
                result["benchmark"]["candidate"] = _measure_phase(
                    test_url, query, args.warmups, args.runs
                )
            finally:
                ingestion.BRONZE = original_attributes["ingestion_bronze"]
                ingestion.MANIFESTS = original_attributes["ingestion_manifests"]
                ingestion.QUARANTINE = original_attributes["ingestion_quarantine"]
                database.MANIFESTS = original_attributes["database_manifests"]
                database.database_url = original_attributes["database_url"]

    baseline_ms = result["benchmark"]["baseline"]["median_execution_ms"]
    candidate_ms = result["benchmark"]["candidate"]["median_execution_ms"]
    result["benchmark"]["median_change_percent"] = (candidate_ms - baseline_ms) / baseline_ms * 100
    return result


def main() -> None:
    args = _arguments()
    result = _run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    summary = {
        "output": str(args.output.resolve()),
        "orders": result["dataset"]["source_row_counts"]["orders"],
        "order_items": result["dataset"]["source_row_counts"]["order_items"],
        "fct_order_item_rows": result["dataset"]["fct_order_item_rows"],
        "source_csv_bytes": result["dataset"]["source_csv_bytes"],
        "bronze_parquet_bytes": result["dataset"]["bronze_parquet_bytes"],
        "metric_reconciliation": "PASS",
        "analysis_queries": len(result["analysis_query_row_counts"]),
        "baseline_median_ms": result["benchmark"]["baseline"]["median_execution_ms"],
        "candidate_median_ms": result["benchmark"]["candidate"]["median_execution_ms"],
        "median_change_percent": result["benchmark"]["median_change_percent"],
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
