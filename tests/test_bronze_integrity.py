"""PostgreSQL rollback and immutability checks for tampered Bronze artifacts."""
import json
import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pandas as pd
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_POSTGRES_TESTS") != "1",
    reason="set RUN_POSTGRES_TESTS=1 after `docker compose up -d --wait`",
)


@contextmanager
def _temporary_database_url(base_url):
    import psycopg
    from psycopg import sql

    parts = urlsplit(base_url)
    if parts.scheme not in {"postgres", "postgresql"}:
        raise ValueError("PostgreSQL integration requires a PostgreSQL URL")
    query = f"{parts.query}&connect_timeout=5" if parts.query else "connect_timeout=5"
    admin_url = urlunsplit((parts.scheme, parts.netloc, "/postgres", query, parts.fragment))
    test_database = f"dataforge_test_{uuid4().hex[:12]}"
    test_url = urlunsplit((parts.scheme, parts.netloc, f"/{test_database}", query, parts.fragment))
    with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as admin:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_database)))
    try:
        yield test_url
    finally:
        with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as admin:
            with admin.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(test_database))
                )


@pytest.mark.parametrize("corruption", ["valid-looking", "truncated"])
def test_parquet_tampering_fails_before_database_connection_and_preserves_raw(
    monkeypatch, tmp_path, corruption
):
    import psycopg
    from psycopg import sql

    from dataforge import database, ingestion
    from dataforge.generator import generate

    configured_url = database.database_url()
    with _temporary_database_url(configured_url) as test_url:
        monkeypatch.setattr(database, "database_url", lambda: test_url)
        source = tmp_path / "source"
        generate(count=300, seed=42, dest=source)
        manifests = tmp_path / "manifests"
        monkeypatch.setattr(ingestion, "BRONZE", tmp_path / "bronze")
        monkeypatch.setattr(ingestion, "MANIFESTS", manifests)
        monkeypatch.setattr(database, "MANIFESTS", manifests)

        ingestion.ingest(source)
        database.init()
        database.load()
        pointer = json.loads((manifests / "active.json").read_text(encoding="utf-8"))
        run_path = manifests / "runs" / f"{pointer['run_id']}.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        parquet_path = Path(run["sources"]["orders"]["bronze_file"])

        def raw_state():
            with psycopg.connect(test_url) as con:
                with con.cursor() as cur:
                    cur.execute(
                        "SELECT count(*), min(status), max(status) FROM raw.orders"
                    )
                    orders = cur.fetchone()
                    cur.execute("SELECT table_name FROM information_schema.tables "
                                "WHERE table_schema = 'raw' ORDER BY table_name")
                    table_names = [row[0] for row in cur.fetchall()]
                    raw_counts = {}
                    for table_name in table_names:
                        cur.execute(
                            sql.SQL("SELECT count(*) FROM raw.{}").format(sql.Identifier(table_name))
                        )
                        raw_counts[table_name] = cur.fetchone()[0]
                    cur.execute(
                        "SELECT source, sha256, row_count FROM audit.load_runs "
                        "ORDER BY source"
                    )
                    audit = cur.fetchall()
            return orders, raw_counts, audit

        before = raw_state()
        if corruption == "valid-looking":
            frame = pd.read_parquet(parquet_path)
            frame.loc[0, "status"] = "tampered-but-valid"
            frame.to_parquet(parquet_path, engine="pyarrow", index=False)
            assert list(pd.read_parquet(parquet_path).columns) == ingestion.contracts()["orders"][
                "required_columns"
            ]
        else:
            original = parquet_path.read_bytes()
            parquet_path.write_bytes(original[:24])

        database_connection_attempted = False

        def forbidden_database_connection():
            nonlocal database_connection_attempted
            database_connection_attempted = True
            raise AssertionError("tamper validation must finish before database connection")

        monkeypatch.setattr(database, "database_url", forbidden_database_connection)
        with pytest.raises(ValueError, match="SHA-256 mismatch"):
            database.load()
        assert not database_connection_attempted
        assert raw_state() == before

