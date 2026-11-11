# Week 6 Delta Lake table-format demo

## Selection

This isolated local exercise uses Delta Lake `3.3.3` with Spark `3.5.9`, a pairing listed in Delta's official [Spark compatibility matrix](https://docs.delta.io/releases/). Apache Iceberg is deferred so the lab demonstrates one verified transaction format rather than adding a second catalog and compatibility stack. Partitioned Parquet remains a separate file-output demonstration; a Parquet directory alone is not described as a transactional table.

## Operation sequence

`labs/spark_nyc_taxi/table_format.py::run_delta_table_demo` accepts a small aggregate DataFrame and a new or empty scratch path. It refuses to overwrite a non-empty path, then:

1. writes up to 20 sorted hourly-zone aggregate rows as the initial Delta version;
2. appends one row using `txnAppId` and `txnVersion`;
3. replays that same append with the same transaction identity and checks that the row count and log version do not advance again;
4. reads version 0 with `versionAsOf`, checks the initial row count, and inspects table detail, history and `_delta_log` files.

All data stays under the lab scratch path. This does not touch DataForge commerce Silver/Gold tables, BigQuery, GCS or accepted checkpoints. It demonstrates local Delta transaction behavior; it does not claim Fabric, Databricks or managed Spark interoperability.

## Execution receipt

**Status: `LOCAL_MEASURED` on the full TLC aggregate, plus an earlier two-row runtime smoke.** The full demo used the pinned Docker session and the real 308,833-row aggregate, selected 20 sorted rows for the isolated table, and wrote only under the ignored scratch directory.

### Full aggregate operation

| Check | Observed value |
|---|---|
| Runtime | Python 3.11.18; PySpark/Spark 3.5.9; Delta 3.3.3; Java 17.0.21; `America/New_York` |
| Table path | `labs/spark_nyc_taxi/data/output/evidence/week6-20261110-03/delta_demo` (local ignored scratch) |
| Initial Delta write | 20 rows, version 0 |
| Append | 21 rows, version 1 |
| Idempotent replay | 21 rows; latest version remained 1 |
| Versioned read | `versionAsOf=0` returned 20 rows |
| Metadata | format `delta`, 2 data files, 7,045 bytes, no partition columns; reader protocol 1, writer protocol 2 |
| History | `WRITE` version 0 (`ErrorIfExists`) and version 1 (`Append`), both `Serializable` |
| Schema | Aggregate date/hour/zone/borough, trip count, decimal distance and monetary sums, and p50/p95 duration |
| Assertions | `append_replay_verified=true`; `time_travel_verified=true` |
| Transaction identity | App ID `dataforge-p73-week6-31cc55d476598eea`, transaction version 1 |

The `_delta_log` contains JSON commits for versions 0 and 1. A replay with the same application/version pair did not advance the transaction log or increase the table row count. Apache Iceberg was not installed or claimed.

### Earlier runtime smoke

The pinned container also passed a separate two-row synthetic smoke before the full run: initial 2 rows at version 0, append to 3 rows at version 1, replay remained at 3, and version 0 read back 2 rows. That smoke was only a compatibility check; the full aggregate receipt above is the SPK-11 evidence.

The first Delta-enabled start downloads the pinned JVM connector from Maven Central. No managed Spark batch, GCS write, BigQuery write, or cloud table-format operation occurred.
