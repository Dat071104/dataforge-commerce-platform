"""Opt-in; requires a reachable Docker PostgreSQL and pyarrow/psycopg."""
import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

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
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(test_database)))


def test_end_to_end_postgres(monkeypatch, tmp_path):
    import psycopg
    from psycopg import sql

    from dataforge import database, ingestion
    from dataforge.generator import generate

    def with_database(url: str, name: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in {"postgres", "postgresql"}:
            raise ValueError("PostgreSQL integration requires a PostgreSQL URL")
        return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))

    configured_url = database.database_url()
    admin_url = with_database(configured_url, "postgres")
    test_database = f"dataforge_test_{uuid4().hex[:12]}"
    test_url = with_database(configured_url, test_database)

    # Never truncate the user's configured database. The test owns a uniquely
    # named temporary database and drops it even when an assertion fails.
    with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as admin:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_database)))
    monkeypatch.setattr(database, "database_url", lambda: test_url)

    try:
        src = tmp_path / "source"
        generate(count=300, seed=42, dest=src)
        # Extend every non-order event date before ingestion so date coverage
        # is tested through a real changed source hash and remains compatible
        # with P4's unchanged-hash no-op behavior.
        import pandas as pd

        event_dates = {
            "payments": {"payment_date": "2099-01-02"},
            "shipments": {"ship_date": "2099-01-03", "delivery_date": "2099-01-05"},
            "returns": {"return_date": "2099-01-06"},
            "inventory": {"snapshot_date": "2099-01-07"},
            "weather_daily": {"observation_date": "2099-01-08"},
        }
        for source_name, changes in event_dates.items():
            path = src / f"{source_name}.csv"
            frame = pd.read_csv(path, dtype="string")
            for column, value in changes.items():
                frame.loc[frame.index[0], column] = value
            frame.to_csv(path, index=False)
        monkeypatch.setattr(ingestion, "BRONZE", tmp_path / "bronze")
        monkeypatch.setattr(ingestion, "MANIFESTS", tmp_path / "manifests")
        monkeypatch.setattr(database, "MANIFESTS", tmp_path / "manifests")
        ingestion.ingest(src)
        database.init()
        active_path = database.MANIFESTS / "active.json"
        assert active_path.is_file()
        active_bytes = active_path.read_bytes()
        # The compatibility manifests are used only while the active pointer
        # is absent. Restore it before the authoritative run-manifest load.
        active_path.unlink()
        try:
            legacy_counts = database.load()
        finally:
            active_path.write_bytes(active_bytes)
        assert legacy_counts["orders"] == 300
        counts = database.load()
        assert counts["orders"] == 300
        # Check the date dimension against the non-order event dates above.
        database.build()
        result = database.check(synthetic=True)
        assert all(value == 0 for value in result.values())
        query_names = sorted(path.stem for path in (database.SQL / "analysis").glob("q*.sql"))
        assert len(query_names) == 10
        for query_name in query_names:
            database.query(query_name)
        from decimal import Decimal

        from dataforge.reference import reference_metrics

        oracle = reference_metrics(src)
        with psycopg.connect(database.database_url()) as con:
            with con.cursor() as cur:
                cur.execute((database.SQL / "checks" / "003_independent_metric_comparison.sql")
                            .read_text(encoding="utf-8"))
                for metric, value in cur.fetchall():
                    assert Decimal(str(value)) == Decimal(oracle[metric]), (metric, value)
        # Invalid product references must fail the data-quality gate instead
        # of silently appearing as a successful incomplete mart build.
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT order_item_id, product_id FROM raw.order_items "
                    "ORDER BY order_item_id LIMIT 1"
                )
                test_item_id, original_product_id = cur.fetchone()
                cur.execute(
                    "UPDATE raw.order_items SET product_id = 'MISSING_PRODUCT' "
                    "WHERE order_item_id = %s",
                    (test_item_id,),
                )
                assert cur.rowcount == 1
        database.build()
        with pytest.raises(AssertionError, match="orphan_products"):
            database.check()

        # Non-overlapping synthetic history remains valid; deliberately add
        # overlapping, unreferenced history so the SCD2 check itself is tested.
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute(
                    "UPDATE raw.order_items SET product_id = %s WHERE order_item_id = %s",
                    (original_product_id, test_item_id),
                )
        database.build()
        assert all(value == 0 for value in database.check(synthetic=True).values())
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute(
                    "INSERT INTO raw.customer_segments "
                    "(customer_id, segment, valid_from, valid_to) VALUES "
                    "('C00001', 'Regular', DATE '2020-01-01', DATE '2020-07-01'), "
                    "('C00001', 'VIP', DATE '2020-06-01', DATE '2020-12-01')"
                )
        database.build()
        with pytest.raises(AssertionError, match="customer_version_overlap"):
            database.check()

        # Remove the injected rows directly; an unchanged source hash is an
        # intentional no-op and does not overwrite manual database changes.
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute(
                    "DELETE FROM raw.customer_segments WHERE customer_id = 'C00001' "
                    "AND valid_from IN (DATE '2020-01-01', DATE '2020-06-01')"
                )
        database.build()
        assert all(value == 0 for value in database.check(synthetic=True).values())
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            with admin.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(test_database)))


def test_invalid_active_runs_fail_before_raw_tables_are_touched(monkeypatch, tmp_path):
    import json

    import psycopg
    from psycopg import sql

    from dataforge import database
    from dataforge.ingestion import contracts

    configured_url = database.database_url()

    def with_database(url: str, name: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in {"postgres", "postgresql"}:
            raise ValueError("PostgreSQL integration requires a PostgreSQL URL")
        return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))

    admin_url = with_database(configured_url, "postgres")
    test_database = f"dataforge_test_{uuid4().hex[:12]}"
    test_url = with_database(configured_url, test_database)
    with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as admin:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_database)))

    monkeypatch.setattr(database, "database_url", lambda: test_url)
    try:
        database.init()
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute(
                    "INSERT INTO raw.geography (province_id, province, region) "
                    "VALUES ('P1_SENTINEL', 'preserve me', 'test')"
                )

        manifests_dir = tmp_path / "manifests"
        runs_dir = manifests_dir / "runs"
        runs_dir.mkdir(parents=True)
        monkeypatch.setattr(database, "MANIFESTS", manifests_dir)
        specs = contracts()
        source_map = {
            name: {
                "source": name,
                "source_sha256": "0" * 64,
                "bronze_file": str(tmp_path / f"missing-{name}.parquet"),
            }
            for name in specs
        }
        # Legacy manifests are deliberately present: an invalid active pointer
        # must fail closed rather than silently falling back to them.
        for name, manifest in source_map.items():
            (manifests_dir / f"{name}.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

        scenarios = (
            ("missing_record", None, "Active run record is missing"),
            (
                "failed_run",
                {"status": "failed", "sources": source_map},
                "not complete",
            ),
            (
                "incomplete_run",
                {"status": "complete", "sources": {
                    name: manifest for name, manifest in source_map.items()
                    if name != "weather_daily"
                }},
                "incomplete sources",
            ),
        )
        for run_id, record, expected_error in scenarios:
            if record is not None:
                (runs_dir / f"{run_id}.json").write_text(
                    json.dumps({"run_id": run_id, **record}), encoding="utf-8"
                )
            (manifests_dir / "active.json").write_text(
                json.dumps({"run_id": run_id}), encoding="utf-8"
            )

            database_url_called = False

            def unexpected_connection() -> str:
                nonlocal database_url_called
                database_url_called = True
                return test_url

            monkeypatch.setattr(database, "database_url", unexpected_connection)
            with pytest.raises((FileNotFoundError, ValueError), match=expected_error):
                database.load()
            assert not database_url_called, "manifest validation must precede database access"

            with psycopg.connect(test_url) as con:
                with con.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM raw.geography WHERE province_id = 'P1_SENTINEL'"
                    )
                    assert cur.fetchone()[0] == 1
    finally:
        with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as admin:
            with admin.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(test_database)))


def test_snapshot_merge_and_persistent_dimension_keys(monkeypatch, tmp_path):
    import hashlib
    import json

    import pandas as pd
    import psycopg

    from dataforge import database, ingestion
    from dataforge.generator import generate

    with _temporary_database_url(database.database_url()) as test_url:
        monkeypatch.setattr(database, "database_url", lambda: test_url)
        src = tmp_path / "source"
        generate(count=300, seed=42, dest=src)
        monkeypatch.setattr(ingestion, "BRONZE", tmp_path / "bronze")
        monkeypatch.setattr(ingestion, "MANIFESTS", tmp_path / "manifests")
        monkeypatch.setattr(database, "MANIFESTS", tmp_path / "manifests")
        ingestion.ingest(src)
        database.init()
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute(
                    "ALTER TABLE audit.load_runs DROP COLUMN rows_inserted, "
                    "DROP COLUMN rows_updated, DROP COLUMN rows_deleted"
                )
        database.init()
        counts = database.load()
        assert counts["orders"] == 300
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                # Emulate the audit operation written by the pre-P4 loader.
                cur.execute("UPDATE audit.load_runs SET operation = 'full_replace'")

        # Seed dimensions with the old baseline's row-number keys to verify an
        # in-place upgrade preserves existing values rather than rebuilding them.
        legacy_dimension_sql = """
            CREATE TABLE dw.dim_date AS
            SELECT (to_char(d, 'YYYYMMDD'))::integer AS date_key,
                   d::date AS calendar_date,
                   extract(year FROM d)::integer AS year,
                   extract(month FROM d)::integer AS month,
                   date_trunc('month', d)::date AS month_start,
                   extract(quarter FROM d)::integer AS quarter
            FROM generate_series(
              (SELECT min(order_date)::timestamp FROM raw.orders),
              (SELECT (greatest((SELECT max(order_date) FROM raw.orders),
                               (SELECT max(return_date) FROM raw.returns),
                               (SELECT max(delivery_date) FROM raw.shipments)) + 40)::timestamp),
              interval '1 day'
            ) AS dates(d);
            ALTER TABLE dw.dim_date ADD PRIMARY KEY (date_key);
            CREATE UNIQUE INDEX dim_date_calendar_idx ON dw.dim_date(calendar_date);

            CREATE TABLE dw.dim_product AS
            SELECT row_number() OVER (ORDER BY product_id)::integer AS product_key,
                   product_id, category, subcategory, base_price, unit_cogs
            FROM raw.products;
            ALTER TABLE dw.dim_product ADD PRIMARY KEY (product_key);
            CREATE UNIQUE INDEX dim_product_business_idx ON dw.dim_product(product_id);

            CREATE TABLE dw.dim_geography AS
            SELECT row_number() OVER (ORDER BY province_id)::integer AS geography_key,
                   province_id, province, region
            FROM raw.geography;
            ALTER TABLE dw.dim_geography ADD PRIMARY KEY (geography_key);
            CREATE UNIQUE INDEX dim_geo_business_idx ON dw.dim_geography(province_id);

            CREATE TABLE dw.dim_customer AS
            SELECT row_number() OVER (ORDER BY s.customer_id, s.valid_from)::integer AS customer_key,
                   s.customer_id, s.segment, s.valid_from, s.valid_to,
                   (s.valid_to IS NULL) AS is_current, c.signup_date,
                   g.geography_key, g.region AS customer_region
            FROM raw.customer_segments s
            JOIN raw.customers c ON c.customer_id = s.customer_id
            JOIN dw.dim_geography g ON g.province_id = c.province_id;
            ALTER TABLE dw.dim_customer ADD PRIMARY KEY (customer_key);
            CREATE UNIQUE INDEX dim_customer_history_idx ON dw.dim_customer(customer_id, valid_from);
        """
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute(legacy_dimension_sql)
                cur.execute("SELECT product_id, product_key FROM dw.dim_product")
                old_product_keys = dict(cur.fetchall())
                cur.execute("SELECT province_id, geography_key FROM dw.dim_geography")
                old_geography_keys = dict(cur.fetchall())
                cur.execute("SELECT customer_id, valid_from, customer_key FROM dw.dim_customer")
                old_customer_keys = {
                    (customer_id, valid_from): customer_key
                    for customer_id, valid_from, customer_key in cur.fetchall()
                }
                cur.execute("SELECT calendar_date, date_key FROM dw.dim_date")
                old_date_keys = dict(cur.fetchall())

        database.build()
        assert all(value == 0 for value in database.check(synthetic=True).values())

        # An identical snapshot must not change raw-row or audit evidence.
        def order_load_marker():
            with psycopg.connect(test_url) as con:
                with con.cursor() as cur:
                    cur.execute("SELECT xmin::text FROM raw.orders WHERE order_id = 'O0000001'")
                    row_xmin = cur.fetchone()[0]
                    cur.execute("""
                        SELECT loaded_at FROM audit.load_runs
                        WHERE source = 'orders'
                        ORDER BY loaded_at DESC, run_id DESC LIMIT 1
                    """)
                    loaded_at = cur.fetchone()[0]
            return row_xmin, loaded_at

        marker_before = order_load_marker()
        unchanged_counts = database.load()
        marker_after = order_load_marker()
        assert unchanged_counts["orders"] == 300
        assert marker_after == marker_before

        # Change several complete source snapshots: an order is backfilled,
        # dimensions receive earlier-sorting keys, one weather row is deleted,
        # and customer history gains a genuine new SCD2 version.
        orders = pd.read_csv(src / "orders.csv", dtype="string")
        order_mask = orders["order_id"].eq("O0000001")
        assert int(order_mask.sum()) == 1
        orders.loc[order_mask, "order_date"] = "2021-12-31"
        orders.to_csv(src / "orders.csv", index=False)

        products = pd.read_csv(src / "products.csv", dtype="string")
        products = pd.concat([products, pd.DataFrame([{
            "product_id": "P0000", "category": "New", "subcategory": "New / Added",
            "base_price": "100000", "unit_cogs": "50000",
        }])], ignore_index=True)
        products.to_csv(src / "products.csv", index=False)
        valid_products = products.copy()

        geography = pd.read_csv(src / "geography.csv", dtype="string")
        geography = pd.concat([geography, pd.DataFrame([{
            "province_id": "AAA", "province": "Test Province", "region": "Test",
        }])], ignore_index=True)
        geography.to_csv(src / "geography.csv", index=False)

        customers = pd.read_csv(src / "customers.csv", dtype="string")
        segments = pd.read_csv(src / "customer_segments.csv", dtype="string")
        current_mask = segments["customer_id"].eq("C00001") & segments["valid_to"].isna()
        assert int(current_mask.sum()) == 1
        prior_segment = segments.loc[current_mask, "segment"].iloc[0]
        next_segment = "VIP" if prior_segment != "VIP" else "Regular"
        segments.loc[current_mask, "valid_to"] = "2022-04-01"
        segments = pd.concat([segments, pd.DataFrame([{
            "customer_id": "C00001", "segment": next_segment,
            "valid_from": "2022-04-01", "valid_to": "",
        }])], ignore_index=True)
        segments.to_csv(src / "customer_segments.csv", index=False)
        customers.loc[customers["customer_id"].eq("C00001"), "segment"] = next_segment
        customers.to_csv(src / "customers.csv", index=False)

        weather = pd.read_csv(src / "weather_daily.csv", dtype="string")
        removed_weather_key = tuple(weather.iloc[0][["province_id", "observation_date"]])
        weather = weather.iloc[1:].copy()
        weather.to_csv(src / "weather_daily.csv", index=False)

        changed_sources = [
            "orders", "products", "geography", "customer_segments", "customers", "weather_daily"
        ]
        changed_manifests = ingestion.ingest(src, sources=changed_sources)
        merged_counts = database.load()
        assert merged_counts["orders"] == 300
        assert merged_counts["products"] == 61
        assert merged_counts["geography"] == 9
        assert merged_counts["customer_segments"] == len(segments)
        assert merged_counts["weather_daily"] == len(weather)

        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute("SELECT order_date FROM raw.orders WHERE order_id = 'O0000001'")
                assert cur.fetchone()[0].isoformat() == "2021-12-31"
                cur.execute(
                    "SELECT count(*) FROM raw.weather_daily "
                    "WHERE province_id = %s AND observation_date = %s",
                    removed_weather_key,
                )
                assert cur.fetchone()[0] == 0
                cur.execute("SELECT rows_inserted, rows_updated, rows_deleted FROM audit.load_runs "
                            "WHERE source = 'products' AND sha256 = %s AND operation = 'snapshot_merge'",
                            (changed_manifests["products"]["source_sha256"],))
                assert cur.fetchone() == (1, 0, 0)
                cur.execute("SELECT rows_inserted, rows_updated, rows_deleted FROM audit.load_runs "
                            "WHERE source = 'orders' AND sha256 = %s AND operation = 'snapshot_merge'",
                            (changed_manifests["orders"]["source_sha256"],))
                assert cur.fetchone() == (0, 1, 0)
                cur.execute("SELECT rows_inserted, rows_updated, rows_deleted FROM audit.load_runs "
                            "WHERE source = 'customer_segments' AND sha256 = %s "
                            "AND operation = 'snapshot_merge'",
                            (changed_manifests["customer_segments"]["source_sha256"],))
                assert cur.fetchone() == (1, 1, 0)
                cur.execute("SELECT rows_inserted, rows_updated, rows_deleted FROM audit.load_runs "
                            "WHERE source = 'weather_daily' AND sha256 = %s "
                            "AND operation = 'snapshot_merge'",
                            (changed_manifests["weather_daily"]["source_sha256"],))
                assert cur.fetchone() == (0, 0, 1)

        database.build()
        assert all(value == 0 for value in database.check(synthetic=True).values())
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute("SELECT product_id, product_key FROM dw.dim_product")
                new_product_keys = dict(cur.fetchall())
                cur.execute("SELECT province_id, geography_key FROM dw.dim_geography")
                new_geography_keys = dict(cur.fetchall())
                cur.execute("SELECT customer_id, valid_from, customer_key FROM dw.dim_customer")
                new_customer_keys = {
                    (customer_id, valid_from): customer_key
                    for customer_id, valid_from, customer_key in cur.fetchall()
                }
                cur.execute("SELECT calendar_date, date_key FROM dw.dim_date")
                new_date_keys = dict(cur.fetchall())

        assert all(new_product_keys[key] == value for key, value in old_product_keys.items())
        assert all(new_geography_keys[key] == value for key, value in old_geography_keys.items())
        assert all(new_customer_keys[key] == value for key, value in old_customer_keys.items())
        assert all(new_date_keys[key] == value for key, value in old_date_keys.items())
        assert new_product_keys["P0000"] > max(old_product_keys.values())
        assert new_geography_keys["AAA"] > max(old_geography_keys.values())
        new_customer_key = new_customer_keys[("C00001", pd.Timestamp("2022-04-01").date())]
        assert new_customer_key > max(old_customer_keys.values())
        assert new_date_keys[pd.Timestamp("2021-12-31").date()] == 20211231

        # High-water state must survive deleting the current maximum member;
        # reintroducing that natural key must allocate a fresh larger key.
        original_reintroduced_key = new_product_keys["P0000"]
        products_without_new_member = valid_products.loc[
            valid_products["product_id"] != "P0000"
        ].copy()
        products_without_new_member.to_csv(src / "products.csv", index=False)
        ingestion.ingest(src, sources=["products"])
        database.load()
        database.build()
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute("SELECT count(*) FROM dw.dim_product WHERE product_id = 'P0000'")
                assert cur.fetchone()[0] == 0

        valid_products.to_csv(src / "products.csv", index=False)
        ingestion.ingest(src, sources=["products"])
        database.load()
        database.build()
        assert all(value == 0 for value in database.check(synthetic=True).values())
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute("SELECT product_key FROM dw.dim_product WHERE product_id = 'P0000'")
                reintroduced_key = cur.fetchone()[0]
        assert reintroduced_key > original_reintroduced_key

        # Staging corruption after another source staged must roll back all raw
        # changes and audit rows in the single load transaction.
        active_pointer = json.loads((database.MANIFESTS / "active.json").read_text(encoding="utf-8"))
        run_path = database.MANIFESTS / "runs" / f"{active_pointer['run_id']}.json"
        original_run = run_path.read_bytes()
        run_record = json.loads(original_run)
        weather_path = Path(run_record["sources"]["weather_daily"]["bronze_file"])
        weather_frame = pd.read_parquet(weather_path)
        duplicate_weather = pd.concat([weather_frame, weather_frame.iloc[[0]]], ignore_index=True)
        corrupt_path = tmp_path / "duplicate-weather.parquet"
        duplicate_weather.to_parquet(corrupt_path, engine="pyarrow", index=False)
        product_probe_hash, weather_probe_hash = "e" * 64, "f" * 64
        run_record["sources"]["products"]["source_sha256"] = product_probe_hash
        run_record["sources"]["weather_daily"]["source_sha256"] = weather_probe_hash
        run_record["sources"]["weather_daily"]["bronze_file"] = str(corrupt_path)
        run_record["sources"]["weather_daily"]["bronze_sha256"] = hashlib.sha256(
            corrupt_path.read_bytes()
        ).hexdigest()
        run_record["sources"]["weather_daily"]["rows_accepted"] = len(duplicate_weather)
        run_path.write_text(json.dumps(run_record), encoding="utf-8")

        def raw_row_counts():
            from psycopg import sql

            counts = {}
            with psycopg.connect(test_url) as con:
                with con.cursor() as cur:
                    for name in ingestion.contracts():
                        cur.execute(
                            sql.SQL("SELECT count(*) FROM raw.{}").format(sql.Identifier(name))
                        )
                        counts[name] = cur.fetchone()[0]
            return counts

        counts_before_failure = raw_row_counts()
        try:
            with pytest.raises(psycopg.errors.UniqueViolation):
                database.load()
        finally:
            run_path.write_bytes(original_run)
        assert raw_row_counts() == counts_before_failure
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute("SELECT count(*) FROM audit.load_runs WHERE source = 'products' "
                            "AND sha256 = %s", (product_probe_hash,))
                assert cur.fetchone()[0] == 0
                cur.execute("SELECT count(*) FROM audit.load_runs WHERE source = 'weather_daily' "
                            "AND sha256 = %s", (weather_probe_hash,))
                assert cur.fetchone()[0] == 0

        # A parent deletion with remaining child rows is rejected and rolled
        # back, rather than committing raw state that would drop mart facts.
        order_items = pd.read_csv(src / "order_items.csv", dtype="string")
        referenced_product = order_items.iloc[0]["product_id"]
        products_without_parent = valid_products.loc[
            valid_products["product_id"] != referenced_product
        ].copy()
        products_without_parent.to_csv(src / "products.csv", index=False)
        refused_manifest = ingestion.ingest(src, sources=["products"])["products"]
        with pytest.raises(ValueError, match="orphan_order_items_products"):
            database.load()
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute("SELECT count(*) FROM raw.products WHERE product_id = %s",
                            (referenced_product,))
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT count(*) FROM audit.load_runs WHERE source = 'products' "
                            "AND sha256 = %s", (refused_manifest["source_sha256"],))
                assert cur.fetchone()[0] == 0


def test_invalid_scd2_snapshots_roll_back_before_raw_commit(monkeypatch, tmp_path):
    import pandas as pd
    import psycopg

    from dataforge import database, ingestion
    from dataforge.generator import generate

    with _temporary_database_url(database.database_url()) as test_url:
        monkeypatch.setattr(database, "database_url", lambda: test_url)
        src = tmp_path / "source"
        generate(count=300, seed=42, dest=src)
        monkeypatch.setattr(ingestion, "BRONZE", tmp_path / "bronze")
        monkeypatch.setattr(ingestion, "MANIFESTS", tmp_path / "manifests")
        monkeypatch.setattr(database, "MANIFESTS", tmp_path / "manifests")
        ingestion.ingest(src)
        database.init()
        database.load()

        baseline_customers = pd.read_csv(src / "customers.csv", dtype="string")
        baseline_segments = pd.read_csv(src / "customer_segments.csv", dtype="string")
        baseline_hashes = {}
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                # A source can have multiple audit rows. Select the same
                # deterministic latest-row ordering used by the rollback
                # assertion below instead of relying on scan order.
                cur.execute(
                    """
                    SELECT DISTINCT ON (source) source, sha256
                    FROM audit.load_runs
                    ORDER BY source, loaded_at DESC, run_id DESC
                    """
                )
                baseline_hashes = dict(cur.fetchall())
                cur.execute("SELECT count(*) FROM raw.customer_segments")
                baseline_segment_count = cur.fetchone()[0]

        def assert_failed_snapshot(source_name, attempted_manifest, expected_check):
            with pytest.raises(ValueError, match=expected_check):
                database.load()
            with psycopg.connect(test_url) as con:
                with con.cursor() as cur:
                    cur.execute("SELECT count(*) FROM raw.customer_segments")
                    assert cur.fetchone()[0] == baseline_segment_count
                    cur.execute("SELECT sha256 FROM audit.load_runs WHERE source = %s "
                                "ORDER BY loaded_at DESC, run_id DESC LIMIT 1",
                                (source_name,))
                    assert cur.fetchone()[0] == baseline_hashes[source_name]
                    cur.execute("SELECT count(*) FROM audit.load_runs WHERE source = %s "
                                "AND sha256 = %s", (source_name, attempted_manifest["source_sha256"]))
                    assert cur.fetchone()[0] == 0

        # A current customer-segment attribute must agree with customers.csv.
        customers = baseline_customers.copy()
        customer_id = customers.iloc[0]["customer_id"]
        old_segment = customers.loc[customers["customer_id"].eq(customer_id), "segment"].iloc[0]
        customers.loc[customers["customer_id"].eq(customer_id), "segment"] = (
            "VIP" if old_segment != "VIP" else "Regular"
        )
        customers.to_csv(src / "customers.csv", index=False)
        attempted = ingestion.ingest(src, sources=["customers"])["customers"]
        assert_failed_snapshot("customers", attempted, "customer_current_segment_mismatch")
        baseline_customers.to_csv(src / "customers.csv", index=False)
        ingestion.ingest(src, sources=["customers"])
        database.load()

        # Remove all versions for a customer with orders; this creates both a
        # missing current version and zero as-of matches for its orders.
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute("SELECT customer_id FROM raw.orders ORDER BY customer_id LIMIT 1")
                ordered_customer = cur.fetchone()[0]
        gap_segments = baseline_segments.loc[
            ~baseline_segments["customer_id"].eq(ordered_customer)
        ].copy()
        gap_segments.to_csv(src / "customer_segments.csv", index=False)
        attempted = ingestion.ingest(src, sources=["customer_segments"])["customer_segments"]
        assert_failed_snapshot("customer_segments", attempted, "customer_current_version_count")
        baseline_segments.to_csv(src / "customer_segments.csv", index=False)
        ingestion.ingest(src, sources=["customer_segments"])
        database.load()

        # An overlap outside all order dates still violates the SCD2 contract.
        with psycopg.connect(test_url) as con:
            with con.cursor() as cur:
                cur.execute("""
                    SELECT c.customer_id, s.valid_from, s.segment
                    FROM raw.customers c
                    JOIN raw.customer_segments s USING (customer_id)
                    WHERE s.valid_to IS NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM raw.orders o WHERE o.customer_id = c.customer_id
                      )
                    ORDER BY c.customer_id LIMIT 1
                """)
                no_order_customer, valid_from, segment = cur.fetchone()
        overlap_start = (pd.Timestamp(valid_from) - pd.Timedelta(days=2)).date().isoformat()
        overlap_end = (pd.Timestamp(valid_from) + pd.Timedelta(days=2)).date().isoformat()
        overlap_segments = pd.concat([baseline_segments, pd.DataFrame([{
            "customer_id": no_order_customer,
            "segment": segment,
            "valid_from": overlap_start,
            "valid_to": overlap_end,
        }])], ignore_index=True)
        overlap_segments.to_csv(src / "customer_segments.csv", index=False)
        attempted = ingestion.ingest(src, sources=["customer_segments"])["customer_segments"]
        assert_failed_snapshot("customer_segments", attempted, "customer_segment_overlap")
