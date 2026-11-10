# P7.2 operational source simulator

This is a separate PostgreSQL 16 project. Its compose project, named volume,
database, and loopback port are independent from the accepted DataForge
PostgreSQL service.

Start only this service from the repository root:

```powershell
docker compose --project-name dataforge-week5-source `
  --file labs/operational_source/compose.yaml up --detach --wait
```

Use the dedicated default connection string in `DATAFORGE_OPERATIONAL_DATABASE_URL`:

```powershell
$env:DATAFORGE_OPERATIONAL_DATABASE_URL = `
  'postgresql://dataforge_week5:week5_local_only@127.0.0.1:55432/dataforge_operational'
```

Initialize and seed with Python:

```powershell
python -c "from dataforge.incremental.source import initialize, seed_source; initialize(); seed_source()"
```

The Python writer takes one PostgreSQL transaction-scoped advisory lock before
changing current state and inserting its journal event. It commits both writes
as one transaction. Use `read_normal_batch` for checkpoint-based extraction or
`read_backfill` for an explicit bounded replay; `export_batch` writes a local
Parquet file and a COMPLETE manifest after checksum verification. Nothing in
this lab writes to `data/source/` or contacts a cloud service.

The journal and event IDs are deterministic for the supplied seed and scenario
events. Monetary fields are exact decimal strings validated as
`NUMERIC(18,2)`. The independent `dataforge.incremental.oracle` module replays
the exported journal and calculates order controls with `Decimal`.

Integration tests use a separate database within the same dedicated PostgreSQL
container so their schema reset cannot alter the operational source journal:

```powershell
$env:DATAFORGE_OPERATIONAL_TEST_DATABASE_URL = `
  'postgresql://dataforge_week5:week5_local_only@127.0.0.1:55432/dataforge_operational_test'
$env:RUN_OPERATIONAL_SOURCE_TESTS = '1'
pytest tests/incremental/test_source_oracle.py
```

The test guard accepts only loopback port `55432` and database
`dataforge_operational_test`; it never uses the operational source database,
baseline `.env`, or `DATABASE_URL`. Create the test database once with
`CREATE DATABASE dataforge_operational_test OWNER dataforge_week5` before
running the opt-in integration test.
