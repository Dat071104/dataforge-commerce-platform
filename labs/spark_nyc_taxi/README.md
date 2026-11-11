# Week 6 — NYC TLC Spark lab

**Scope:** standalone local Spark workload. It is deliberately separate from the accepted DataForge commerce Silver/Gold models and their financial definitions.

The full run materialized 13,069,067 official NYC TLC Yellow Taxi rows from January–April 2024. Spark applied a documented NYC local-time and quality policy, compared equivalent DataFrame and Spark SQL aggregates, benchmarked a shuffled versus broadcast zone lookup, wrote `pickup_date`-partitioned Parquet, and demonstrated an isolated Delta append/replay/time-travel transaction.

```text
NYC TLC 2024 Yellow Taxi Parquet + zone lookup
  → local Docker Spark (schema, quality ledger, zone join)
  → pickup_date / pickup_hour / pickup_zone aggregate
  → date-partitioned Parquet + isolated Delta transaction demo
```

## Run locally

From the repository root in PowerShell, acquire the official source data. Raw files remain in ignored local scratch:

```powershell
.\.venv\Scripts\python.exe .\labs\spark_nyc_taxi\download.py `
  --data-dir .\labs\spark_nyc_taxi\data\raw `
  --months 1 2 3 4

docker compose --file labs/spark_nyc_taxi/compose.yaml build
docker compose --file labs/spark_nyc_taxi/compose.yaml run --service-ports --rm spark `
  -m labs.spark_nyc_taxi.job `
  --raw-dir /workspace/labs/spark_nyc_taxi/data/raw `
  --output-root /workspace/labs/spark_nyc_taxi/data/output `
  --run-id week6-local `
  --hold-ui-seconds 300
```

The complete job uses one warmup and five timed repetitions for each join plan. The first Delta-enabled startup needs Maven Central to resolve the pinned Delta JAR. The managed Spark batch is optional and was not authorized or run; this local lab does not write to GCP.

## Deterministic local CI

The fixture suite does not download public TLC data. It covers the source manifest/downloader, independent Decimal oracle, DST cases, quality policy, DataFrame/SQL parity, duplicate zone IDs, corrupt/missing/wrong-schema files, empty output days, stale manifests, bad partition layout, low-memory preflight, Parquet replay, benchmark plans, and percentile tolerance.

```powershell
.\labs\spark_nyc_taxi\ci.ps1
.\.venv\Scripts\ruff.exe check labs/spark_nyc_taxi
.\.venv\Scripts\python.exe -m compileall -q labs/spark_nyc_taxi
```

## Data and result semantics

- TLC publishes timezone-naive meter wall-clock timestamps. The job uses `America/New_York`, rejects gap/fold and offset-crossing trips, requires the pickup date in `[2024-01-01, 2024-05-01)`, and allows a valid dropoff to cross a month boundary.
- Pickup and dropoff IDs must resolve to assigned TLC zones 1–263. IDs 264 (“Unknown”) and 265 (“Outside of NYC”) are rejected.
- Required distance must be finite and positive. Fare and total amounts are decimal cents; negative fares, totals, and adjustments remain included and are flagged for review. No trip is deduplicated by a weak key.
- The hourly aggregate has one row per pickup date, pickup hour, and pickup zone, with borough enrichment, trip count, distance/fare/total sums, and approximate p50/p95 duration.
- Raw source, generated output, event logs, and receipts stay under the ignored `data/` directory. The TLC page cautions that the submitted records are not guaranteed accurate; no named per-file license is asserted.

## Evidence

- [Dataset provenance, hashes, schema, and quality ledger](../../docs/cloud/week6/dataset_provenance.md)
- [Acceptance and benchmark results](../../docs/cloud/week6/acceptance_matrix.md)
- [Final report and remaining limitations](../../docs/cloud/week6/final_report.md)
- [Spark plans, event-log metrics, and UI capture status](../../docs/cloud/week6/spark_ui_evidence.md)
