from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_POSTGRES_TESTS") != "1",
    reason="set RUN_POSTGRES_TESTS=1 to capture q10 plans on an isolated PostgreSQL service",
)

ROOT = Path(__file__).parents[2]
QUERY_PATH = ROOT / "sql" / "analysis" / "q10_explain_performance.sql"
INDEX_PATH = ROOT / "sql" / "performance" / "002_q10_covering_index.sql"


@contextmanager
def _temporary_database_url(base_url: str):
    import psycopg
    from psycopg import sql

    parts = urlsplit(base_url)
    if parts.scheme not in {"postgres", "postgresql"}:
        raise ValueError("PostgreSQL integration requires a PostgreSQL URL")
    query = f"{parts.query}&connect_timeout=5" if parts.query else "connect_timeout=5"
    admin_url = urlunsplit((parts.scheme, parts.netloc, "/postgres", query, parts.fragment))
    name = f"dataforge_explain_{uuid4().hex[:12]}"
    test_url = urlunsplit((parts.scheme, parts.netloc, f"/{name}", query, parts.fragment))
    with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as admin:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield test_url
    finally:
        with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as admin:
            with admin.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def _explain(cursor, query: str) -> str:
    cursor.execute(query)
    return "\n".join(str(row[0]) for row in cursor.fetchall())


def _append_step_summary(before: str, after: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write("\n## Lane D q10 EXPLAIN (ANALYZE, BUFFERS)\n\n")
        for heading, plan in (("Before covering index", before), ("After covering index", after)):
            summary.write(f"### {heading}\n\n```text\n{plan}\n```\n\n")
        summary.write("No speedup is asserted; compare plans under equivalent fixture/statistics.\n")


def test_q10_explain_plans_before_and_after_covering_index(tmp_path: Path) -> None:
    import psycopg

    from dataforge.database import database_url

    with _temporary_database_url(database_url()) as test_url:
        with psycopg.connect(test_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE SCHEMA dw")
                cursor.execute(
                    "CREATE TABLE dw.fct_order_item ("
                    "order_date_key integer NOT NULL, "
                    "product_key integer NOT NULL, "
                    "fulfilled_sales_proxy numeric(18,2) NOT NULL)"
                )
                cursor.execute(
                    "INSERT INTO dw.fct_order_item "
                    "SELECT to_char(date '2018-01-01' + ((n - 1) % 2922), 'YYYYMMDD')::integer, "
                    "((n - 1) % 5000) + 1, ((n - 1) % 100000)::numeric / 100 "
                    "FROM generate_series(1, 150000) AS series(n)"
                )
                cursor.execute(
                    "CREATE INDEX fct_item_order_date_idx "
                    "ON dw.fct_order_item(order_date_key)"
                )
                cursor.execute("ANALYZE dw.fct_order_item")
                before = _explain(cursor, QUERY_PATH.read_text(encoding="utf-8"))

                # Reuse the repository's optional q10 index SQL, stripping its
                # standalone comment lines before executing each statement.
                index_sql = INDEX_PATH.read_text(encoding="utf-8")
                for raw_statement in index_sql.split(";"):
                    statement = "\n".join(
                        line for line in raw_statement.splitlines()
                        if not line.lstrip().startswith("--")
                    ).strip()
                    if statement:
                        cursor.execute(statement)
                after = _explain(cursor, QUERY_PATH.read_text(encoding="utf-8"))
                cursor.execute("SELECT to_regclass('dw.fct_item_q10_covering_idx')")
                assert cursor.fetchone()[0] == "dw.fct_item_q10_covering_idx"

        assert "Limit" in before and "Execution Time" in before and "Buffers" in before
        assert "Limit" in after and "Execution Time" in after and "Buffers" in after
        (tmp_path / "q10_before_covering_index.txt").write_text(before + "\n", encoding="utf-8")
        (tmp_path / "q10_after_covering_index.txt").write_text(after + "\n", encoding="utf-8")
        _append_step_summary(before, after)
        print("Q10_PLAN_BEFORE_COVERING_INDEX\n" + before)
        print("Q10_PLAN_AFTER_COVERING_INDEX\n" + after)
