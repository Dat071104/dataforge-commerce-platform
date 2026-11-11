# P7.3 / Week 6 — benchmark and tuning receipt

**Status:** `LOCAL_MEASURED`; one local, single-node experiment. It is not a cluster-scale throughput claim.

## Workload and controls

- Input: the same four official 2024 Yellow Taxi Parquet files; Spark materialized 13,069,067 input rows. The quality contract accepted 12,686,794 and rejected 382,273 before aggregation.
- Aggregate: one row per `pickup_date`, `pickup_hour`, and `pickup_zone`, with unique borough enrichment, counts, decimal distance/fare/total sums, and approximate p50/p95 duration.
- Runtime: Python 3.11.18, Java 17.0.21, Spark/PySpark 3.5.9, Delta 3.3.3, Docker `local[4]`, 6 GiB memory limit, AQE enabled, 96 shuffle partitions, `America/New_York` session timezone.
- Same scan, normalized rules, join keys, output schema, summary action, and settings for both candidates. No DataFrame cache was used. Warmup and download/startup/output-write time are outside the timed action.
- Baseline disables automatic broadcast and forces a shuffle (`MERGE`) join. Candidate forces a broadcast of the same 263-row assigned-zone lookup. Plans: [baseline](spark_plan_baseline.txt) and [broadcast candidate](spark_plan_candidate.txt).
- Each variant had one warmup and five timed repetitions. The final receipt recovers each Spark job-group interval from the event log because the original wrapper stopped after all actions when a strict one-row summary equality assertion failed; the precise summary field was not retained. A follow-up distributed comparison passed exact key/count/distance/money checks and a 1.0 minute percentile tolerance; observed p50/p95 differences were both 0.0 minutes.

## Timed results

| Variant | Timed seconds | Median | Min–max | Range |
|---|---|---:|---:|---:|
| Shuffled zone lookup | 297.146, 267.702, 213.924, 210.983, 197.517 | **213.924** | 197.517–297.146 | 99.629 |
| Broadcast zone lookup | 323.406, 312.831, 234.428, 256.307, 220.174 | **256.307** | 220.174–323.406 | 103.232 |

The broadcast candidate was **19.8% slower by median** on this machine. No speedup is claimed. Event-log medians show it reduced shuffle write/read from 260,286,084 to 89,457,162 bytes (65.6%), memory spill from 2,789,988,608 to 1,560,537,280 bytes (44.1%), and disk spill from 469,051,958 to 203,843,133 bytes (56.5%). It moved fewer bytes but took longer; a broadcast strategy is not automatically faster on a resource-constrained local runtime.

Task event metrics across timed runs also show median summed executor run time of 784,502 ms for the baseline versus 957,479 ms for the candidate, and median JVM GC time of 44,726 ms versus 70,161 ms. These are sums of local task metrics, not wall-clock time. The benchmark summary is in [benchmark.json](benchmark.json).

## Plan, shuffle, and skew evidence

The executed baseline plan contains `SortMergeJoin` and `Exchange`; the executed candidate plan contains `BroadcastHashJoin`. Both plans retain the wide aggregate exchange. Event-log task attribution captured 12 successful tasks per timed job group. The runner processed 13,069,330 input records per group including the 263-row zone lookup scan; the trip-record input itself remains 13,069,067 rows.

Real pickup-zone distribution is highly skewed: zone 161 has 607,808 accepted trips versus a median of 1,174 across 259 active zones (max/median 517.7); the top ten zones hold 37.9% of accepted trips. The physical plan shows a local partial hash aggregate before the wide exchange, reducing repeated hot-zone rows before shuffle. This is observed map-side aggregation behavior; the lab does not claim AQE salting or a synthetic benchmark represents TLC traffic.

## Measurement limits

- Timings are recovered from Spark event-log job-group start/end intervals because the in-process timing report was not flushed after the strict summary equality assertion stopped the wrapper. The precise summary field that triggered it was not retained. The intervals omit a small amount of Python setup/teardown around each Spark action.
- The host filesystem cache can warm between runs. The run order alternated candidates; it is not a cold-storage benchmark.
- Windows host free RAM fluctuated below 1 GiB during the run. The Docker container stayed around 1.4–1.9 GiB of its 6 GiB limit, and Spark had no failed task, but the JVM logged `RowBasedKeyValueBatch` spill attempts and a 64 MiB page-allocation retry. Event-log metrics record actual memory/disk spill; this environment limits the interpretation.
- The only controlled change was join strategy. There is no GCP managed-Spark cost, no cluster scaling comparison, and no commerce BigQuery timing comparison.

The benchmark application was `local-1794323176305`; its uncompressed event log hash is recorded in [the UI/event evidence](spark_ui_evidence.md). The separate finalization run verified output correctness and the percentile tolerance after recovering this benchmark.
