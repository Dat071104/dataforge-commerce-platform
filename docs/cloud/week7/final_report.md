# DataForge Week 7 final report

**Technical verification:** complete, bounded to synthetic Week-5 orders and payment events in project `dataforge-p7-lab-d0f725` (`955038620072`), `us-central1`.
**Independent controller:** `CLOUD_GO_WEEK7`.
**Release:** `RELEASE_BLOCKED`. The feature branch is pushed, but GitHub PR creation returned HTTP 403. No PR exists; hosted PR-head CI has not run.

## Result

Week 7 adds a pinned dbt-bigquery project, an isolated candidate build, validation and reconciliation gates, currentness-fenced Gold publication, Terraform-managed Workflows and IAM, and a local Airflow reference DAG. It does not use the developer's local PostgreSQL as a cloud source and does not add Week 8 work.

The final live state is checkpoint sequence **30**, publication pointer **6** with `publication_is_current=true`, and **5** order-control rows. The published Week-7 Gold view agrees with Week-5 Gold and the independent Decimal oracle: delivered-sales proxy **268,000.00**, successful collections **352,000.00**, **144** field comparisons, and **0** mismatches. The simulator has only orders and payment events; these results do not represent the eleven Week-4 commerce streams.

## Architecture and ownership

The path is:

```text
approved immutable GCS manifest + exact object generation
  -> Cloud Workflows (manifest check, lease, bounded job wait)
  -> existing Week-5 Cloud Run consumer
  -> Week-5 Silver orders/payment events + committed checkpoint
  -> finite dbt Cloud Run Job -> isolated dbt_week7 candidate
  -> dbt tests + independent Week-5 Gold reconciliation
  -> immutable gold_week7 run version + compare-and-set pointer
  -> current-only published view
```

Week-5 `silver.week5_orders`, `silver.week5_payment_events`, and `ops.pipeline_checkpoints` remain the authoritative inputs for this simulator. `gold.week5_order_controls` is the compatibility output. dbt preserves order and payment-event grains, retains tombstones, pre-aggregates payments before joining, and defines delivered sales as an operational proxy rather than accounting revenue. See [architecture and ADR](architecture_and_adr.md), [dbt model contract](dbt_model_contract.md), and [generated lineage](model_lineage.md).

The workflow accepts an approved immutable manifest identity or returns `NO_NEW_BATCH`; it never scans a mutable latest object or attempts to reach localhost. A BigQuery-backed lease prevents overlapping runs from reaching conflicting publication. Lock acquisition marks the published pointer stale. The public view returns zero rows until tests and reconciliation pass and the pointer transaction sets the new version and currentness flag together. A failed run after Silver commits is recovered by replaying the same manifest: Week 5 no-ops its committed batch, then dbt validates and publishes.

## Cloud failure drills

All ten required ORC cases were exercised against the isolated GCP project. The full before/after checkpoints, pointer versions, injected faults, and recovery evidence are in the [acceptance matrix](acceptance_matrix.md) and [failure recovery report](failure_recovery.md).

| Case | Workflow execution(s) | Observed result |
|---|---|---|
| ORC-01 no new batch | `216128e0-871a-4c65-8d0a-df7e8e659961` | `NO_NEW_BATCH`; no data-plane job ran. |
| ORC-02 approved batch | `40f468a2-d81f-4719-9657-5906ce8b8944` | Published checkpoint 23 at pointer 1. |
| ORC-03 identical replay | `07c07a70-a378-42a7-a3b8-841301ba8a1f` | `NO_OP`; checkpoint and pointer unchanged. |
| ORC-04 incomplete manifest | `6e76d649-ed4c-47c4-a228-6f60287cf826` | Rejected before GCS or Cloud Run. |
| ORC-05 wrong object generation | `30b53794-d6cc-4545-9071-b7a24ffc3492` | Exact-generation GCS read returned 404; no data-plane job ran. |
| ORC-06 backfill and bounded retry | `3e2c381f-1ec8-451f-a691-66de45b7a7bd` | Week-5 execution `dataforge-week5-processor-h5ljt` failed once after Silver and succeeded on its bounded retry; pointer advanced once, normal checkpoint stayed 23. |
| ORC-07 dbt failure after Silver | `36fe0bfa-cf5d-4ce9-879d-524fe0146b8a`; recovery `ca40780e-7408-4531-b3d3-13e6742b1c6e` | Injected dbt failure left the view empty and pointer unchanged. After a read-only pointer grant fixed post-publication verification, exact replay returned `NO_OP` and restored currentness. |
| ORC-08 data-quality failure | `6d9615ef-8746-432b-9ba0-573535873f90`; recovery `f35c6983-3efb-48c5-a536-b6dea474e755` | One isolated candidate amount was corrupted; test failed and published Gold stayed unchanged. Full refresh execution `dataforge-week7-dbt-kr5ml` repaired the candidate; replay passed without advancing the pointer. |
| ORC-09 concurrent overlap | Owner `7afb53aa-10bf-4c8c-b978-85a714fe7625`; overlap `ef8136bd-8d9d-449d-b84a-88a714fe7625` | Second execution returned `OVERLAP_SKIPPED` before Week 5. Owner later failed in dbt before publication; no conflicting pointer update occurred. |
| ORC-10 pointer failure after Silver | Failure `e25056c5-11bb-4e76-b73d-5d8d324ad0a2`; recovery `351ffae7-b9cc-48a7-af1e-59e867fdef10` | Failure left pointer 5 stale and the public view empty; exact-manifest retry published pointer 6 and restored the five-row view. |

The Scheduler trigger was force-tested once with `NO_NEW_BATCH`, then the job and Scheduler-only IAM were deleted. The API remains enabled; no recurring job remains. The final Terraform workspace is `p7-dataforge-p7-lab-d0f725`, with 73 state resources and a refreshed plan of zero changes and zero destroys.

## dbt correctness and data quality

- dbt Core **1.11.17** and dbt-bigquery **1.11.3** are pinned; the runtime image is digest-pinned and uses keyless ADC.
- Credential-free parse and keyless dev compile pass. Generated manifest, catalog, model descriptions, tests, contracts, and lineage are included under `artifacts/` and in the model documentation.
- Final dbt data tests: **51 passed, 0 failed, 0 skipped**.
- Full-refresh versus incremental outputs: **5 rows each**, **5 unique order IDs each**, **0 row mismatches**, and identical totals. The bounded comparison billed **20 MiB** and took **2.063 seconds**.
- The controlled batches covered insert/replay, a backfill with a late order correction and payment-status correction at seq 24–25, a later payment catch-up at seq 26, order/payment tombstones at seq 27–28, and payment updates at seq 29–30. The [batch receipts](batch_24_25_backfill.json), [catch-up receipt](batch_24_26_normal.json), [tombstone receipt](batch_27_28_tombstone.json), and [final payment update](batch_30_pointer_failure.json) identify those synthetic events.
- The Decimal oracle independently reconciled 5 orders, 6 payment events, and 29 journal events through seq 30. Tombstoned orders and their successful collections remained visible, with deleted-order variance null.
- The [local Airflow 3 reference](../../../labs/airflow_reference/) imports and runs in network-disabled test mode. Four scenarios and 24 task invocations passed; its invalid-mode case failed as expected. It performs no cloud writes and is not deployed as a second scheduler.

## Security, performance, and cost

IAM uses distinct Workflow, dbt, job-runner, manifest-reader, and CI identities. The runtime job runner has only the required Cloud Run job execution permissions, bucket public access prevention is enforced, and the recorded user-managed service-account key count is zero. GitHub OIDC is constrained to the repository and trusted push refs; PR/fork jobs receive no GCP identity. One evidence limitation remains: applied bindings and key inventory were inspected, but direct impersonated `testIamPermissions` negative probes were not run. Details are in [security and IAM](security_iam.md).

The 2026-11-11 09:00–17:03 UTC inventory recorded **1,274** top-level BigQuery jobs, **19,639,828,480** bytes billed, **71** Cloud Run executions, and **24** Workflow executions with **1,881** step entries. Gross list-price estimates total **$0.247996** for BigQuery query analysis plus Cloud Run compute, before free tiers, storage, and network. Scheduler usage was not included because its temporary job was removed after one forced run. BigQuery billing/export data was not enabled or queried, so settled charges and remaining trial/free-tier credit are unknown. The estimate is not an invoice or hard cap. See [performance and cost](performance_and_cost.md), [BigQuery pricing](https://cloud.google.com/bigquery/pricing), [Cloud Run pricing](https://cloud.google.com/run/pricing), and [Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing).

The dataset contains only five orders and six payment events; no scale or cost-optimization claim is made from the merge strategy. Immutable datasets, manifests, and image tags remain for audit and replay. No destructive teardown was run against prior Week-4/5 resources.

## Local verification

The final local runs passed: **176 offline tests** with 7 expected integration skips; **182 PostgreSQL integration tests** with 1 expected operational-source skip using a disposable tmpfs-backed PostgreSQL container; Ruff, compileall, pip check, dbt parse/compile, Terraform fmt/validate, and a refreshed no-drift plan. The temporary PostgreSQL container was removed after the suite. The complete machine-readable evidence is [`test_receipts.json`](test_receipts.json).

## Release record

- Week 6 prerequisite: PR [#4](https://github.com/Dat071104/dataforge-commerce-platform/pull/4) merged at `dbf41e3968081c768e258645c56fab461e76d695` after both hosted checks passed on `102af420e06150d85b450f003372cf37abe2c5a0`.
- Week 7 feature branch: `feature/p7-week7-dbt-orchestration`, based on the Week-6 merge.
- Independent Week-7 controller verdict: [`CLOUD_GO_WEEK7`](controller_verdict.md).
- The initial release commit `a9f30c18327482fc9c2986e97fcd59e8bae681c8` was pushed to `origin/feature/p7-week7-dbt-orchestration`; the PR attempt used that exact head.
- PR creation: blocked by GitHub API HTTP 403 (`Resource not accessible by integration`); no PR was created and the connector was not retried. A follow-up commit records this release outcome.
- Compare link to create the PR: [main...feature/p7-week7-dbt-orchestration](https://github.com/Dat071104/dataforge-commerce-platform/compare/main...feature/p7-week7-dbt-orchestration?expand=1).
- Hosted CI on a PR head and merge commit: not run because no PR exists.
