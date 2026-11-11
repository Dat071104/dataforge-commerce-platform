# Week 6 Spark UI and event evidence

## Observed status

**`LOCAL_TESTED` for live Spark UI REST and event logs; no screenshot was captured.** The driver started Spark UI on port 4040 inside the Docker container. While the application ran, the Spark REST endpoint inside the container returned the live application and stage data. A Windows-host request to `127.0.0.1:4040` timed out despite the Compose port mapping, and the computer-use helper stopped before navigation because it could not verify Chrome's current URL. I therefore do not claim a screenshot.

The Spark UI and logs are generated from real Spark applications, not synthetic plan output:

| Application | Purpose | Event log | Bytes | SHA-256 |
|---|---|---|---:|---|
| `local-1794323176305` | 13.07M-row benchmark (one warmup and five timed runs per join plan) | `labs/spark_nyc_taxi/data/eventlogs/local-1794323176305` | 16,821,264 | `a5f9ab22eccfe6d552bb36b305087c06cf67cf6dc21117c19d4c02e1389f6533` |
| `local-1794329076657` | Final quality, parity, Parquet, oracle, and Delta run | `labs/spark_nyc_taxi/data/eventlogs/local-1794329076657` | 17,857,397 | `4c0f38ffb97d94c9f430029a1473eb6e891c21f51b5a4593c883911c3f32b648` |

The full event logs remain untracked in the ignored lab data directory. The compact, event-log-derived task metrics and plan evidence are retained in [`benchmark.json`](benchmark.json), [`spark_plan_baseline.txt`](spark_plan_baseline.txt), and [`spark_plan_candidate.txt`](spark_plan_candidate.txt).

## Observed UI and task metrics

- The in-container UI API returned application `local-1794323176305`, name `dataforge-week6-week6-20261110-02`, Spark 3.5.9. It showed the benchmark's grouped jobs, stages, tasks, shuffle read/write, and spill metrics.
- Each benchmark action created four Spark jobs and 12 successful tasks. Event-log group receipts cover the warmups and all five timed runs for both variants.
- Median task-level shuffle read/write was 260,286,084 bytes for the shuffled baseline and 89,457,162 bytes for the broadcast candidate. Median task memory spill was about 2,789,988,608 vs 1,560,537,280 bytes; median disk spill was about 469,051,958 vs 203,843,133 bytes.
- The baseline plan has `SortMergeJoin`, `Exchange`, and partial aggregation. The candidate plan has `BroadcastHashJoin` and partial aggregation. AQE and 96 shuffle partitions were shared.
- The JVM emitted `RowBasedKeyValueBatch` spill warnings and one 64 MiB page-allocation retry during the run. Spark recorded task-level spills; no task failed. These local memory conditions and high timing variability limit performance conclusions.

## Manual screenshot steps

1. Start a full lab run with `docker compose --file labs/spark_nyc_taxi/compose.yaml run --service-ports --rm spark -m labs.spark_nyc_taxi.job ... --hold-ui-seconds 300`.
2. If Docker Desktop forwards the port to Windows, open `http://localhost:4040` before the hold expires.
3. Capture the SQL/DataFrame plan, completed Stages, and Executors tabs. Confirm the baseline shows `SortMergeJoin` and the candidate `BroadcastHashJoin`.
4. Record the application ID and task counts. Keep the full event log out of Git; publish only reviewed screenshots and compact metrics.

In this execution, the host-side URL probe timed out and no screenshot was obtained. The event log, actual formatted plans, and in-container REST evidence are the available UI/metrics receipts.
