# Week-7 operational failure drills

**Execution status:** completed against the isolated GCP project. All ten scenarios have live receipts; expected injected failures failed before publication, and exact-manifest recovery was verified. See the [acceptance matrix](acceptance_matrix.md) for the consolidated result.

## Protected baseline and controlled source scope

Before any new operational journal event, the live state was:

- `ops.pipeline_checkpoints`: `dataforge-operational-v1` committed sequence **20**; last committed batch `a107b47471ff130cece65af2dea2f97d2731ecb0b4ca543b83ba3f5019226c63`.
- `silver.week5_orders`: 4 current rows, 1 tombstone, max `effective_seq=18`.
- `silver.week5_payment_events`: 4 current rows, 1 tombstone, 3 active successful payments, max `effective_seq=20`.
- `gold.week5_order_controls`: 4 per-order rows; total delivered-sales proxy `263000` and collections `344000`.
- Week-7 pointer: one seeded singleton at `pointer_version=0`, no published run. Week-7 lock: one seeded row, no owner, `lock_version=0`.
- Local operational journal: 19 rows through sequence 20 (one rolled-back allocation gap); a 10,465-byte PostgreSQL dump is stored outside the repository with SHA-256 `3b17e2dc6c246cba041066e86d11edcdd21123ed21d9a346a632596b18c083b7`.

The accepted `dataforge` PostgreSQL database, Week-5 checkpoint, and Week-4 snapshot sources are not used for this test. New deterministic events are appended only to the already separate `dataforge_operational` source. The scripts preserve the append-only journal and are safe to replay by stable `change_id`.

Controlled journal sequence plan:

| Sequence | Event | Purpose |
|---:|---|---|
| 21 | Insert delivered order `W5O0005` for `100000.00` | Insert and new order grain. |
| 22 | Insert successful payment `W5P0005` for `100000.00` | Independent payment insert. |
| 23 | Insert successful payment `W5P0006` for `5000.00` | Verify multiple payments are aggregated before the order join. |
| 24 | Correct `W5O0004` to order date `2026-07-30`, amount `55000.00` | Late business-date correction and order update. |
| 25 | Set `W5P0004` to failed | Changed payment status arriving after the order update. |
| 26 | Restore `W5P0004` as successful for `15000.00` | Normal extraction replays the backfilled 24–25 range and advances checkpoint. |
| 27 | Tombstone `W5P0005` | Payment soft-delete. |
| 28 | Tombstone `W5O0005` | Order soft-delete while `W5P0006` remains successful, proving tombstone collection preservation. |
| 29 | Update `W5P0004` to `16000.00` | Real Week-5 commit followed by injected dbt build failure and exact-manifest recovery. |
| 30 | Update `W5P0004` to `17000.00` | Candidate build passes; injected failure occurs before publication CAS, then exact-manifest recovery. |

The versioned Week-7 pointer is the only public Week-7 “current Gold” marker. Candidate table mutations or validation failures must leave its version and referenced immutable rows unchanged.

## Scenario definitions

| ID | Initial state and fault/input | Expected outcome | Verification fields |
|---|---|---|---|
| ORC-01 | No manifest supplied. | `NO_NEW_BATCH`; no Cloud Run, dbt, checkpoint, candidate, or pointer mutation. | Workflow execution name/result; checkpoint; pointer version. |
| ORC-02 | Normal manifest for seq 21–23. | Week-5 Silver and Gold update; checkpoint 20→23; dbt tests/reconciliation pass; pointer publishes one five-order version. | Manifest SHA/generation, Cloud Run execution, BigQuery jobs/bytes, counts, checksum, pointer revision. |
| ORC-03 | Same manifest URI and GCS generation replayed. | Week-5 `NO_OP`; dbt converges; no additional published version or effective rows. | Checkpoint and pointer before/after; batch ID; output checksum. |
| ORC-04 | Incomplete workflow input omits generation or batch. | Workflow rejects input before GCS or Cloud Run. | Execution state/error; source checkpoint and pointer unchanged. |
| ORC-05 | Correct manifest URI with wrong immutable generation. | GCS exact-generation read fails; Week-5 is not invoked. | Execution/job IDs; checkpoint and pointer unchanged. |
| ORC-06 | Seq 21–23 manifest with `test_fail_after_merge_once=true`. | One Week-5 task attempt fails at the existing rollback injection; the job's single retry publishes the same batch once; downstream dbt succeeds. | Attempt IDs/statuses, checkpoint 20→23, one effective output, pointer revision. |
| ORC-07 | Seq 29 manifest with `test_fail_dbt_build=true`. | Week-5 commits checkpoint 28→29; dbt compile/build fails; Workflow releases the lock and does not publish. Retry the exact manifest without the flag: Week-5 `NO_OP`, dbt passes, pointer advances. | Failure code, lock events, checkpoint and pointer before/after both attempts, final checksum. |
| ORC-08 | After a successful publish, corrupt one row in the isolated `dbt_week7` candidate table. | Replayed workflow fails a dbt quality/parity test and preserves the prior pointer/view. Rebuild the candidate with full refresh and retry to confirm the old published view remains correct. | Injected BigQuery job ID, dbt failure/test name, pointer version/hash, repair job and final candidate parity. |
| ORC-09 | Start two runs of the same manifest; first holds the lock for 30 seconds. | Exactly one execution owns the lease; the other returns `OVERLAP_SKIPPED` before Week-5. No duplicate checkpoint advancement or pointer version. | Both execution names, lock ledger rows, checkpoint and pointer before/after. |
| ORC-10 | Seq 30 manifest with `test_fail_before_publish=true`. | Week-5 commits through seq 30; dbt candidate validation succeeds; the publication transaction rolls back before version insertion/pointer CAS. Retry exact manifest without the flag: Week-5 `NO_OP`, immutable version is published once. | Checkpoint 29→30, failure and recovery Workflow/Cloud Run IDs, pointer stays unchanged then advances, row count/hash. |

ORC-04 and ORC-05 are negative contract checks; ORC-06 and ORC-09 exercise bounded retry/concurrency; ORC-07/08/10 verify failed downstream work does not publish incorrect Gold. Backfill rows 24–25 do not advance the normal checkpoint; normal range 24–26 then commits through sequence 26.

## Actual execution evidence

| Scenario | Actual result | Checkpoint and pointer evidence | Recovery / receipt |
|---|---|---|---|
| ORC-01 | `NO_NEW_BATCH`, workflow succeeded in 1.437s. | Baseline checkpoint 20, pointer 0, lock free. | [`no_new_batch_workflow.json`](no_new_batch_workflow.json) |
| ORC-02 | Batch seq 21–23 published after the exact manifest was replayed with r3. | Checkpoint 20→23; pointer 0→1; five candidate rows. | [`dbt_failure_and_recovery.json`](dbt_failure_and_recovery.json), [`orc02_recovered_success.json`](orc02_recovered_success.json) |
| ORC-03 | Exact seq 21–23 replay returned `NO_OP`. | Checkpoint 23 and pointer 1 remained unchanged. | [`orc03_same_batch_replay.json`](orc03_same_batch_replay.json), [`state_after_orc03_replay.json`](state_after_orc03_replay.json) |
| ORC-04 | Incomplete manifest failed with `INVALID_WEEK7_WORKFLOW_INPUT` before GCS or Cloud Run. | No lock acquisition or data-plane step. | [`orc04_incomplete_manifest.json`](orc04_incomplete_manifest.json) |
| ORC-05 | Generation `1794390619113736` failed with GCS 404 before Week 5. | No lock acquisition or data-plane step. | [`orc05_generation_mismatch.json`](orc05_generation_mismatch.json) |
| ORC-06 | Seq 24–25 backfill attempt 0 failed with the injected rollback code; bounded attempt 1 published; full Workflow returned `PUBLISHED`. | Normal checkpoint stayed 23; pointer 1→2, upper sequence 25. | [`week5_batch_24_25_retry_ledger.json`](week5_batch_24_25_retry_ledger.json), [`orc06_backfill_success.json`](orc06_backfill_success.json), [`state_after_orc06_backfill.json`](state_after_orc06_backfill.json) |
| ORC-07 | Seq 29 committed, injected dbt build failed, pointer stayed 4 and currentness stayed false. Exact replay later returned `NO_OP` after publication and pointer read permissions were corrected. | Checkpoint 28→29; pointer 4→5 only on the successful first publication; final retry preserved pointer 5/currentness true. | [`orc07_dbt_failure.json`](orc07_dbt_failure.json), [`state_after_orc07_failure.json`](state_after_orc07_failure.json), [`state_orc07_status_permission_failure.json`](state_orc07_status_permission_failure.json), [`orc07_recovery.json`](orc07_recovery.json), [`currentness_after_orc07_recovery.json`](currentness_after_orc07_recovery.json) |
| ORC-08 | Candidate `W5O0004` was changed from 15,000 to 15,001; dbt validation failed. Full refresh repaired it; exact replay returned `NO_OP`. | Pointer stayed at 3; current published view remained 15,000 during the candidate fault and was restored after repair. | [`orc08_corruption.json`](orc08_corruption.json), [`orc08_quality_failure.json`](orc08_quality_failure.json), [`orc08_full_refresh_repair.json`](orc08_full_refresh_repair.json), [`orc08_repair_verification.json`](orc08_repair_verification.json), [`orc08_recovery.json`](orc08_recovery.json) |
| ORC-09 | Two overlapping manual executions shared one manifest; the second returned `OVERLAP_SKIPPED`. | The owner held the lease; the second did not call Week 5; no pointer version was created by the overlap. | [`orc09_overlap.json`](orc09_overlap.json), [`state_concurrent_orc06_runs.json`](state_concurrent_orc06_runs.json) |
| ORC-10 | Seq 30 committed; injected failure before publication failed; exact replay returned `PUBLISHED`. | Checkpoint 29→30; pointer 5 remained not-current on failure, then pointer advanced once to 6/current. | [`orc10_pointer_failure.json`](orc10_pointer_failure.json), [`state_after_orc10_failure.json`](state_after_orc10_failure.json), [`orc10_recovery.json`](orc10_recovery.json), [`currentness_after_orc10_recovery.json`](currentness_after_orc10_recovery.json) |

The Week-7 pointer status is explicitly fail-closed. The lock acquisition sets `publication_is_current=false`; `gold_week7.published_order_reconciliation` returns no rows until publication commits. Receipts [`currentness_fail_closed.json`](currentness_fail_closed.json), [`currentness_after_orc07_failure.json`](currentness_after_orc07_failure.json), and [`currentness_after_orc10_failure.json`](currentness_after_orc10_failure.json) show the empty view while the source checkpoint is ahead. Successful transactions restore the flag and expose the validated immutable version.
