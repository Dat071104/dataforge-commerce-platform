# P7.3 / Week 6 — Spark lab architecture and ADR

**Status:** `GO_WEEK6_LOCAL` from the one independent final controller. This is a separate NYC Taxi scaling workload; it does not change the accepted commerce pipeline or its financial definitions. Publication is tracked in GitHub.

## Decision

Use a reproducible local Docker/Linux Spark runtime on the Windows host, process official NYC TLC Yellow Taxi Parquet for January–April 2024, and write hourly pickup-zone aggregates to date-partitioned Parquet. Demonstrate one isolated Delta Lake table with a real append, idempotent replay, history inspection, and versioned read. Apache Iceberg is deferred so this phase verifies one transactional format instead of installing two.

The host exposes 20 logical CPUs and 15.7 GiB RAM; Docker exposes 20 CPUs and 7.6 GiB memory. Compose bounds Spark to 4 CPUs and 6 GiB. The raw source set is 220,522,830 bytes; Spark materialized 13,069,067 rows and matched the sum of the four Parquet footer counts.

## Architecture

```text
Official NYC TLC Yellow Taxi Parquet (2024-01..04) + zone lookup CSV
  → pinned local Spark runtime
  → schema and quality ledger (accepted + rejected = input)
  → unique taxi-zone enrichment + hourly pickup date/hour/zone aggregate
  → independently reconciled bounded subset
  → pickup_date-partitioned Parquet + isolated Delta version-history demo
```

The Spark lab remains under `labs/spark_nyc_taxi/`. Raw files, generated aggregates, Delta tables, event logs, and scratch receipts live under its ignored `data/` directory. Only code, small fixtures, and compact evidence are committed. The existing commerce Silver/Gold tables, checkpoints, accepted data, and GCP resources are outside this lab.

## Data and output contract

- Source: TLC Yellow Taxi monthly Parquet for 2024-01 through 2024-04 and the TLC taxi-zone lookup CSV. These four monthly files share a 19-column schema; `cbd_congestion_fee` is absent and 2025+ data is not mixed in.
- Output grain: one row per `pickup_date`, `pickup_hour`, and `pickup_zone`, with optional borough enrichment; trip count, valid trip-distance sum, fare and total-amount sums, and approximate p50/p95 duration.
- The official source timestamps contain local taxi meter wall-clock values without an offset. The job uses `America/New_York`, explicitly rejects records whose local interval cannot be interpreted safely across DST boundaries, and records the selected civil-time/duration rule in the lab runbook. It does not claim a recoverable UTC instant where the source has no offset.
- Pickup and dropoff zones must resolve to the 263 assigned TLC zones. IDs 264 (“Unknown”) and 265 (“Outside of NYC”) are rejected. The lookup is validated for unique IDs before joining.
- Negative monetary values are retained and included in decimal-cent sums; they are flagged for review rather than treated automatically as invalid refunds/adjustments. Non-finite or null required money is rejected. No weak composite key is used to deduplicate trips; duplicate-like signatures are diagnostic only.
- Invalid distance, invalid duration, null critical fields, period mismatch, and unresolved zones are rejected with a reason ledger. `accepted + rejected = input` is a hard reconciliation.
- Full-scale aggregates are reconciled to the accepted count, output key uniqueness, stable monetary totals, and selected bounded partitions. A small deterministic TLC sample is also compared with a separately implemented Python/Decimal oracle.

## Runtime and benchmark decision

The candidate matrix is Python 3.11, Java 17, Apache Spark 3.5.9, and Delta Lake 3.3.3. Spark runs in local mode inside Linux Docker to avoid unverified Windows native Hadoop behavior. The final runtime is accepted only after the container build and the actual Spark and Delta operations succeed; otherwise the evidence records the failure and no compatibility claim is made.

Benchmark baseline and candidate use the same prepared input, schema, quality policy, aggregate, action, AQE setting, and 96 shuffle partitions. The single controlled change is zone-lookup join strategy: a shuffle join versus a broadcast lookup. Event-log timing medians were 213.924 seconds for the baseline and 256.307 seconds for the broadcast candidate. The candidate cut median shuffle write from 260,286,084 to 89,457,162 bytes and reduced measured spill, but its median elapsed time was 19.8% slower. This is a local exploratory result with high run-to-run variation; no speedup is claimed.

The output has 308,833 unique date/hour/pickup-zone rows; summed trip count equals the 12,686,794 accepted source trips. Date-partitioned Parquet contains 121 files in 121 `pickup_date` partitions. A complete January 15 partition was independently checked with a PyArrow/Python Decimal oracle. The isolated Delta table used 20 rows from the real aggregate, then a one-row append, transaction-identity replay, history inspection, and version-0 read; all assertions passed.

## Cloud boundary

Managed Service for Apache Spark is optional and was not authorized for new spending in this execution. No GCP batch, GCS write, IAM change, or cloud resource mutation is part of the local acceptance. Week-6 managed Spark usage is `NOT_RUN`; this is not a statement about prior GCP billing. Any later managed batch requires a separate explicit spending authorization and a bounded cost estimate.

## Source caveats

The TLC page says the trip records are submitted by authorized technology providers and that TLC does not guarantee their accuracy. The page does not identify a separate per-file license in the listing; raw files are used as local inputs and are not committed to this repository. See the [official TLC download page](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page) and its [Yellow Taxi data dictionary](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf).
