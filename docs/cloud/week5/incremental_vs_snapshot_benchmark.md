# Full snapshot vs incremental benchmark

## Fixture and oracle

The benchmark used 100,000 synthetic orders and a deterministic Decimal source oracle. It changed 1,000 rows (1%) with exact `NUMERIC` post-images and changed sequence values. The full-snapshot target and the incremental target both matched the same final state: 100,000 rows, amount total `10,500,750.00`, and zero row-level mismatches. This 100K fixture is large enough to show the target scan cost; the small live pipeline fixture is not used to claim a speedup.

The incremental target began with the same 100,000-row baseline. A 1,000-row delta was merged into it. The full-snapshot path replaced its target from the 100,000-row final snapshot. Both used unpartitioned, unclustered scratch tables, so the MERGE still scanned most of the target.

## Measured results

| Measure | Full snapshot | Incremental update |
| --- | ---: | ---: |
| Rows in final target | 100,000 | 100,000 |
| Changed events applied | 100,000-row final snapshot | 1,000 (1%) |
| Main BigQuery operation | CTAS | MERGE |
| BigQuery job runtime (job start to end) | 2.190 s | 1.921 s |
| Local client round-trip (submission through result polling) | 3.063 s | 2.768 s |
| Bytes processed | 43,301,000 | 43,734,004 |
| Bytes billed | 44,040,192 | 44,040,192 |
| Final amount total | 10,500,750.00 | 10,500,750.00 |
| Row-level mismatches vs Decimal oracle | 0 | 0 |
| Parquet/GCS input size | 20,772,018 bytes | 208,472 bytes |

The incremental Parquet object was about 99.6 times smaller than the full snapshot object. The comparison used seven BigQuery jobs: three bounded Parquet load jobs, one full-snapshot CTAS, one baseline copy job, one incremental MERGE, and one shared equality validation query. The baseline copy is setup, not counted as the incremental update operation. The three query jobs together processed 216,938,004 bytes and billed 218,103,808 bytes; at the gross $6.25/TiB list rate that is about **$0.00124** before any free tier or trial credit. Job runtime comes from persisted BigQuery `start_time`/`end_time`; client round-trip includes SDK and control-plane polling time.

Local Parquet generation took 4.009 seconds; uploading the full snapshot and delta objects to the approved GCS bucket took 13.48 seconds. The scratch GCS objects used create-only generation preconditions. BigQuery loaded the exact generated Parquet bytes from the local operator process for this isolated query comparison; the production Week-5 Cloud Run path separately verified GCS-generation reads end to end.

## Interpretation and limits

The MERGE job ran 0.269 seconds less in this single run, but both operations billed the same 44,040,192 bytes. This does **not** establish a meaningful speed or cost advantage: the unpartitioned target scan and BigQuery’s per-query billing floor dominate at this scale. A larger target with effective partition pruning and selective keys may change the result; this benchmark did not test partitioning, clustering, concurrency, or a production-size dataset. The actual values, job IDs, hashes, GCS generations, and cleanup outcomes are in `performance_benchmark.json`.
