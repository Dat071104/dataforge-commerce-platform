# DataForge P7.3 / Week 6 — final report

**Execution window:** 2026-11-10 to 2026-11-11 (Asia/Bangkok)
**Base:** `main` / `origin/main` `839f7a5a2e39f3fec6c071d8a8a04a1c07ea70a4`
**Working branch:** `feature/p7-week6-spark-nyc-taxi`
**Local engineering result:** `LOCAL_MEASURED`
**Independent controller:** `GO_WEEK6_LOCAL`
**Managed Spark:** `CLOUD_SPARK_NOT_AUTHORIZED`; no batch submitted

## Delivered

- Added a reproducible Linux Docker runtime on Windows: Python 3.11.18, OpenJDK 17, Apache Spark 3.5.9, Delta Lake 3.3.3, PyArrow 23.0.1, and pytest 9.2.0. The 6 GiB / 4 CPU Compose limit was selected for this host.
- Downloaded and verified the official NYC TLC Yellow Taxi Parquet files for January–April 2024 and the official taxi-zone lookup. Raw inputs are local, ignored, and excluded from Git.
- Spark materialized **13,069,067 source rows**. Quality policy accepted **12,686,794** and rejected **382,273**, exactly reconciling to input. The full output has **308,833** unique pickup-date/hour/zone rows and sums to 12,686,794 trips.
- Implemented full DataFrame and Spark SQL equivalents; their two-way distributed comparison returned zero differing rows. A full January 15 output partition matched a separate PyArrow/Python Decimal oracle over all 77,033 raw rows for that date.
- Wrote and replay-verified date-partitioned Parquet: 121 `pickup_date` partitions/files, 8,330,057 bytes total, 68,843 bytes average. Predicate pruning showed `PartitionFilters` for a selected pickup date.
- Demonstrated a real local Delta table using rows from the full aggregate: initial 20 rows at version 0; append to 21 at version 1; idempotent replay remained 21/version 1; version-0 read returned 20; format metadata/history were inspected.
- Added deterministic local tests, a dedicated GitHub Actions workflow that never downloads TLC data, a runbook, provenance, acceptance matrix, physical plans, event-log metrics, and run receipts.

## Data quality and semantics

The four files share the same 19-column 2024 schema. The 2025 `cbd_congestion_fee` field is absent and no years or taxi types were mixed. TLC timestamps are timezone-naive NYC meter wall clocks; the lab uses `America/New_York`, applies the selected period to pickup time, allows a valid month-crossing dropoff, and rejects DST gaps/folds/offset-crossing intervals and durations over 24 hours.

The lookup had 265 unique IDs; assigned IDs 1–263 were complete. IDs 264/265 were rejected as Unknown/Outside NYC. Negative fares, totals, and adjustments were retained and flagged. A full-row fingerprint found one duplicate-like extra row; no trip was deduplicated.

The TLC source page warns that trip records are submitted by authorized providers and does not guarantee their accuracy. The source dictionary and terms caveats are recorded in [dataset_provenance.md](dataset_provenance.md). This is a learning lab, not official transportation statistics or a production data product.

## Benchmark and Spark evidence

The controlled change was join strategy only. With the same 13.07M input, AQE, 96 shuffle partitions, and action, the shuffled baseline median was **213.924 s** and the broadcast candidate median was **256.307 s** across five event-log-timed repetitions. Broadcast reduced shuffle write/read by 65.6% and measured memory/disk spill by 44.1%/56.5%, but was **19.8% slower** by median. It did not improve elapsed time on this machine; no speedup is claimed.

The real pickup-zone distribution was skewed: zone 161 had 607,808 trips versus a median 1,174 across 259 active zones. The plan showed Spark map-side partial aggregation before the wide exchange. Full task counts, spill, CPU/GC, physical plans, measurement method, and limitations are in [benchmark.md](benchmark.md) and [spark_ui_evidence.md](spark_ui_evidence.md).

The event log showed `RowBasedKeyValueBatch` spill warnings and one 64 MiB page-allocation retry during the benchmark; no task failed. Docker stayed around 1.4–1.9 GiB of its 6 GiB limit, while free Windows RAM fluctuated below 1 GiB at points. These results are local and exploratory; run-to-run ranges are wide and the host file cache warms.

One benchmark harness attempt completed all measured runs but stopped before writing its receipt when a strict one-row summary equality assertion failed. The precise summary field was not retained. The job-group event log was preserved and used to recover elapsed intervals, plans, and task metrics. A finalization run then compared outputs by key: counts and monetary/distance sums matched exactly, and p50/p95 differences were zero under the declared 1.0 minute tolerance. The code now contains this row-level tolerance check and regression tests.

## Local verification and safety

- Week-6 local CI script: pinned Docker image build succeeded; **30 fixture tests passed in 25.31 seconds**. The suite uses only deterministic small fixtures and makes no TLC data download.
- Existing offline commerce suite: **155 passed, 7 expected database-gated skips** in 20.17 seconds.
- Existing PostgreSQL-enabled commerce suite: **161 passed, 1 expected Week-5 operational-source DB skip** in 31.50 seconds. Tests created/dropped uniquely named temporary databases; the accepted `dataforge` database/volume was not reset.
- Ruff: **PASS** across the lab and existing application, test, script, and dashboard code. `compileall`, `pip check`, `git diff --check`, and the Power BI source-pack validator: **PASS**.

Existing P6.2 GO LOCAL, P7.1 CLOUD_GO_WEEK4, and P7.2 CLOUD_GO_WEEK5 code, metrics, checkpoints, data, and controller decisions remain unchanged. No Week 7 dbt/orchestration code was started.

No GCP batch, GCS/BigQuery write, IAM change, Terraform change, or cloud resource mutation occurred in Week 6. This does not assert zero account spend; earlier project billing settlement remains unknown. See [cost_iam_cleanup.md](cost_iam_cleanup.md).

The Spark UI REST API was reachable inside the container, but Windows-host port 4040 timed out and the computer-use helper could not determine Chrome’s current URL. No screenshot is claimed. Event-log metrics and explicit manual capture steps are supplied. The lab build context also lacks a `.dockerignore`; no raw file is copied into the image, and raw data remains git-ignored, but an explicit ignore file would guard future broad `COPY` instructions. Exact local commands and exit results are in [validation_receipt.md](validation_receipt.md).

## Release gate

The one independent controller returned `GO_WEEK6_LOCAL`, authorizing the feature-branch commit, push, and PR. Hosted CI must pass on the exact PR head with no blocking findings before merge; afterward, synchronize local `main` and record the release SHAs and run IDs. The optional managed Spark batch remains out of scope without separate explicit spending authorization.
