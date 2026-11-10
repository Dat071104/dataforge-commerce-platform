# DataForge P7.2 Week-5 final report

**Engineering verification date:** 2026-11-10 (Asia/Bangkok)<br>
**Target:** `dataforge-p7-lab-d0f725` / `955038620072`, `us-central1`<br>
**Branch:** `feature/p7-week5-incremental`<br>
**Release verdict:** `CLOUD_GO_WEEK5` from the one independent final controller review. Exact-head hosted CI remains pending.

## Delivered

- Added a separate PostgreSQL operational simulator with a transactionally written `change_seq` journal, stable event IDs, tombstones, typed Parquet, immutable GCS manifests, and bounded explicit backfill.
- Added a digest-pinned, keyless Cloud Run Job that reads exact GCS generations, validates and stages batches, performs sequence-aware BigQuery Silver MERGEs, publishes an affected-order Gold control projection, and commits the normal checkpoint in one BigQuery transaction.
- Ran all INC-01 through INC-10 in the target project. The Cloud Run ledger, execution/image receipts, GCS generations, and BigQuery parent/child job statistics are retained under `docs/cloud/week5/`.
- The final checkpoint is 20. The independent Decimal source oracle and Silver/Gold reconciliation matched 108 fields with zero mismatches: 4 orders, 4 payment events, delivered-sales proxy `263000.00`, and collections `344000.00` including collections for the tombstoned order.
- The synthetic benchmark compared a 100,000-row full snapshot with a 1,000-event (1%) increment. Both matched the same oracle. The snapshot and MERGE each billed 44,040,192 bytes; the measured jobs show no meaningful billed-byte advantage for the incremental operation at this unpartitioned scale.
- Local and PostgreSQL verification passed. The final aggregate results are in `incremental_test_receipts.json`.

## Preserved and bounded

- P6.2 GO LOCAL and P7.1 CLOUD_GO_WEEK4 remain unchanged. Week-4 objects/tables were not deleted.
- Runtime IAM stays inside the approved project; the job has no service-account key and the bucket remains private. Billing was not upgraded and the Billing API remains disabled.
- Gross measured BigQuery + Cloud Run compute is about USD 0.077 before free tiers, trial credits, and unmetered storage; the prior Week-4 estimate was under USD 0.02. Settled charges remain unknown and the USD 10 project target is not a hard cap.
- Nine temporary Week-5 staging tables and benchmark scratch objects were deleted. Superseded Artifact Registry image tags remain because the repository enforces immutable tags; that policy was not weakened.
- Week 6 Spark and Week 7 orchestration/dbt were not started.

## Release gate

The independent controller returned `CLOUD_GO_WEEK5`. The feature-branch push and PR are authorized; hosted CI must pass on the exact PR head and there must be no blocking review finding before merge. The merge and main-branch CI/synchronization are not yet complete.
