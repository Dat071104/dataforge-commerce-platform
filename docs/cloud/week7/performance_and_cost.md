# Week 7 performance and cost

## Measured result

Inventory window: **2026-11-11 09:00–17:03 UTC**, project `dataforge-p7-lab-d0f725`, region `us-central1`. The complete receipt is [`performance_inventory.json`](performance_inventory.json).

| Workload | Observed usage | Gross list estimate |
|---|---:|---:|
| BigQuery, top-level jobs | 1,274 jobs; 175,006,115 bytes processed; 19,639,828,480 bytes billed; 881,671 slot-ms | $0.111639 at $6.25/TiB |
| Cloud Run Jobs | 13 Week 5 executions and 58 dbt executions; 6,232.8 task-runtime seconds; 6,886 conservative billable seconds at 1 vCPU / 0.5–1 GiB | $0.136357 before free tier |
| Workflows | 24 executions; 1,881 step entries; 12 succeeded and 12 failed | Usage recorded; no separate charge estimate included |
| **Measured compute + analysis** |  | **$0.247996** |

The Cloud Run estimate uses job `createTime` to `completionTime`, a 60-second minimum per task, 1 vCPU, and the configured memory. This includes time before task start and is a conservative upper estimate, not billed-instance telemetry. Failed executions include expected failure drills and the early workflow/model defects; all ten scenarios ultimately passed after recovery. BigQuery errors are not billed under on-demand pricing; most small successful statements incurred the 10 MiB/query billing floor.

The count of billed bytes exceeds processed bytes because the project ran many small dbt tests and bounded control queries. The final full-refresh versus incremental comparison billed 20 MiB in 2.063 seconds for 5 rows, with 0 mismatches. The independent Week 5 Decimal replay read 29 journal events through seq 30, checked 144 source/Silver/Gold fields, and found 0 mismatches. The published Week 7 reconciliation billed 30 MiB, matched all 5 Week 5 Gold rows, and preserved the tombstoned-order collection control.

## Limits and cost controls

- Week 5 Cloud Run: one task, one retry, 1 vCPU, 512 MiB, 600-second timeout. Its single publish script has a separate 1 GiB billed-byte cap; other Week 5 queries use 256 MiB caps.
- Week 7 dbt Cloud Run: one task, no task retry, 1 vCPU, 1 GiB, 240-second timeout. dbt BigQuery jobs use a 256 MiB maximum-billed cap.
- Control/reconciliation probes use 64 MiB caps; all test queries use the approved project and `us-central1`.
- Workflows holds one 2,400-second publication lease across Week 5, dbt tests, pointer publication, and lock release. The workflow has no unbounded retry loop.
- Cloud Scheduler uses a fixed `NO_NEW_BATCH` body. It was created paused, temporarily enabled for one forced execution after the paused `jobs.run` attempt returned HTTP 400, then deleted with its service account and IAM bindings. No Scheduler job remains; the service API stays enabled.
- No Composer, GKE, Cloud SQL, always-on VM, public bucket, service-account key, or recurring job remains.
- The digest-pinned r4 dbt image’s Linux/amd64 manifest is 227,550,371 bytes. Immutable r1–r4 tags remain because Artifact Registry tag immutability is enabled. Layer deduplication and settled storage billing were not measured.

Cloud Scheduler bills per job, and paused jobs count as jobs; beyond the billing account's three-job free tier, one job is $0.10 per 31 days, prorated per day. The verification job was removed before its next 02:00 UTC schedule. [Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing)

BigQuery on-demand query pricing for `us-central1` is $6.25/TiB with a shared 1 TiB monthly free tier; this estimate does not subtract free usage or credits. [BigQuery pricing](https://cloud.google.com/bigquery/pricing)

Cloud Run Jobs use instance-based billing, with the current `us-central1` rate and free tier shown in the official pricing table. This receipt reports a gross estimate before free usage. [Cloud Run pricing](https://cloud.google.com/run/pricing)

## Billing limit and retained resources

The measured BigQuery plus Cloud Run list estimate is about **$0.25**, well below the USD 5 Week 7 target before storage and network charges. Billing export/API was not enabled or queried, and no settled current-month DataForge charge was collected. Exact billed dollars and the billing account's remaining free tier/trial credits are therefore unknown; this is an estimate, not an invoice or cap.

The live commerce slice is only five orders and six payment events, so a merge-versus-alternative benchmark would not be meaningful. The range partition and stable order bucket were selected for access-pattern correctness; no measured cost or speed improvement is claimed.

Week 7 retains the four protected BigQuery datasets, control tables, immutable Bronze manifests/Parquet objects, and immutable Artifact Registry images for audit/replay. `dbt_week7_full` remains protected for the parity receipt. Teardown is intentionally not run against these retained datasets or immutable images. The temporary Scheduler job and all Scheduler-only IAM were removed. To disable the optional job in future plans, keep `week7_scheduler_enabled = false`; the default is false and paused is true.
