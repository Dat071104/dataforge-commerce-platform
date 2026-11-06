# Local 100K-order warehouse benchmark

**Evidence status:** This is the P5 measurement, not a P6 rerun. P6 did not change the analytics SQL or benchmark harness, so the recorded 100K-order timings and q10 index comparison remain historical measurements for the stated host and workload.

## Scope and method

This is one reproducible **synthetic local measurement**, not a production capacity or speed guarantee. The deterministic seed-42 fixture was generated in a temporary directory and loaded into a UUID-named PostgreSQL database. The benchmark then executed all ten analytics queries and independently compared key VND totals against the CSV `Decimal` oracle. The main source files and `dataforge` database were not modified; temporary data and the benchmark database were removed after the run.

Reproduce from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe .\scripts\benchmark_warehouse.py --orders 100000 --seed 42 --runs 5 --warmups 2 --output "$env:TEMP\DataForge\warehouse_benchmark_100k.json"
```

The run used two warmups and five measured executions per phase. PostgreSQL and operating-system caches were not flushed; measured plans showed zero shared reads. This is a warm-cache comparison. The candidate was evaluated in the temporary benchmark database only.

## Environment and fixture size

| Item | Observed value |
|---|---:|
| Host | Windows build 26200, Acer Nitro AN515-58 |
| Logical processors / host memory | 20 / 16,869,548,032 bytes (~15.7 GiB) |
| Docker VM | 20 CPUs / 8,171,601,920 bytes (~7.6 GiB), no per-container memory cap |
| PostgreSQL | 16.14; `shared_buffers=128MB`; `effective_cache_size=4GB`; `work_mem=4MB` |
| Python / pandas / PyArrow | 3.11.9 / 2.3.3 / 23.0.1 |
| Source CSV bytes | 22,964,021 |
| Bronze Parquet bytes | 6,076,428 |
| Orders / order items | 100,000 / 200,473 |
| Payments / shipments / returns | 96,205 / 86,043 / 4,507 |

Observed phase times were generation 2.206 s, validation/Parquet ingestion 4.693 s, database initialization 0.118 s, raw loading 6.151 s, and mart build 2.533 s. These are local timings for this fixture and host. The output JSON contains the original phase measurements.

## Correctness controls

All synthetic quality-check outputs were zero. The independently calculated totals and PostgreSQL controls matched exactly:

| Metric | Independent CSV `Decimal` oracle | PostgreSQL |
|---|---:|---:|
| Fulfilled sales proxy | 166,533,593,500.00 VND | 166,533,593,500.00 VND |
| Fulfilled COGS proxy | 97,320,140,500.00 VND | 97,320,140,500.00 VND |
| Collected payments | 166,533,593,500.00 VND | 166,533,593,500.00 VND |
| Completed refunds | 4,358,410,500.00 VND | 4,358,410,500.00 VND |
| Collection variance | 0.00 VND | 0.00 VND |

All ten queries returned successfully. `q08_order_payment_reconciliation` returned 100 sampled order rows; its complete reconciliation controls were checked independently at the metric level.

## q10 index comparison

The q10 plan filters January 2022 order lines and aggregates fulfilled sales proxy by product. The baseline used `fct_item_order_date_idx`. The candidate was `fct_item_q10_covering_idx(order_date_key, product_key) INCLUDE (fulfilled_sales_proxy)` from [`002_q10_covering_index.sql`](../sql/performance/002_q10_covering_index.sql).

| Phase | Five warm execution times (ms) | Median | Representative access path |
|---|---|---:|---|
| Baseline | 23.410, 23.850, 21.649, 21.819, 23.060 | 23.060 ms | Bitmap index + heap scan (69,704 qualifying rows), aggregate, top-N sort |
| Covering candidate | 14.686, 13.137, 13.794, 13.111, 13.091 | 13.137 ms | Index-only scan (69,704 qualifying rows; zero heap fetches), aggregate, top-N sort |

On this run, the median was 9.923 ms (43.0%) lower and shared-buffer hits fell from 2,994 to 271 blocks; both phases reported zero shared reads. The table stayed at 24,018,944 bytes. Index size rose from 13,885,440 to 20,234,240 bytes, an added 6,348,800 bytes for the candidate index. The candidate is **not applied to the main `dataforge` database**. No alternative index candidates were measured, so there are no failed optimization measurements to report.

Do not generalize this one warm-cache result to other row counts, hardware, query filters or production workloads. Re-run the same procedure before recommending the additional index for a different workload.

## Raw evidence

The full JSON, source row counts, host settings and per-query plans were retained as local development evidence and are not part of the public portfolio bundle. The selected measurements above are historical P5 results; they are not a performance claim for other hardware, filters or production workloads.
