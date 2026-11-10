# Failure boundaries and recovery evidence

## Publication boundary

The consumer pins both the manifest and Parquet generations, verifies content SHA-256, schema, row count, sequence bounds, and the canonical row-value digest before staging. Staging tables are isolated by batch ID and expire after seven days. The BigQuery publication script uses one transaction for Silver MERGEs, affected-order Gold projection, control assertions, run-state rows, and the normal checkpoint update. Backfill mode publishes affected current state but does not advance the normal checkpoint. GCS creation is outside the BigQuery transaction; a COMPLETE manifest is written only after create-only object upload and byte/generation verification.

The runtime writes durable sanitized lifecycle/failure events. Cloud Run executes with one task and one retry. The ledger preserves earlier attempts; the manual recovery command reuses the exact immutable manifest and generation.

## Observed defects and fixes

| Evidence | Failure | Recovery / impact |
| --- | --- | --- |
| `dataforge-week5-processor-f5qrn` | Initial run-event SQL used `SELECT ... WHERE` without a `FROM`, so the ledger insert failed before manifest download. | Fixed the query with a one-row `UNNEST` source and recorded the failed attempts. No staging, Silver, Gold, or checkpoint mutation occurred. |
| `dataforge-week5-processor-22ldn` | BigQuery `load_table_from_file` rejected the unsupported `retry` argument. | Changed the loader to the SDK’s `num_retries` argument. The attempt did not publish data. |
| `dataforge-week5-processor-56z79` | The publish script’s 256 MiB `maximum_bytes_billed` cap was reached by child BigQuery ASSERTs. Both attempts rolled back; checkpoint stayed zero. | Raised only the bounded publish-script cap to 1 GiB. Normal status, precheck, and staging verification queries remain capped at 256 MiB. Later real runs published successfully. |
| `dataforge-week5-processor-mltlx` | The initial successful seed transaction wrote zero totals into its intermediate `CHECKED` row because totals were assigned afterward. `PUBLISHED` totals and warehouse values were correct. | Moved totals before the `CHECKED` insert in r7. INC-03 and later successful runs show correct `CHECKED` totals. The historical row remains for audit. |

## Required failure and recovery tests

- **INC-07:** A quarantined manifest declared schema version 999. Cloud Run `k8nh5` failed twice with `BATCH_VALIDATION_FAILED`; both attempts had no staging table or publish job. The committed checkpoint remained 18.
- **INC-08:** Cloud Run `sq4s5`, attempt 0, failed immediately after Silver MERGE with `INJECTED_AFTER_SILVER_BEFORE_CHECKPOINT`. The transaction rolled back, leaving checkpoint 18 and prior Gold visible. The platform’s one retry detected the durable failure row, did not repeat the one-shot injection, and published attempt 1 at checkpoint 19. W5O0004 collections became 13,000 exactly once.
- **INC-10:** Cloud Run `cjndm` exhausted both configured attempts at `INJECTED_BEFORE_PUBLISH`. `INC10_before.json` and `INC10_after_failed.json` have identical checkpoint 19 and Gold hash `eb7e7673433cccb30c78bcb7d8af0595dd6b144e03857ce68a869c1f5fac4a28`. Replaying the same manifest without injection in `m7sz4` advanced checkpoint 19→20; only W5O0004 changed, to 14,000 collections. `INC10_after_recovery.json` holds the post-recovery row hash.
- **INC-02:** The same seed manifest and generations produced an observable `NO_OP`, with no stage load or publish.
- **INC-09:** The explicit 15–16 backfill left checkpoint 14. The subsequent normal batch accepted event sequences 15, 16, and 18 within bounds 15–18 and advanced the checkpoint to 18; it did not require a nonexistent sequence 17.

All Cloud Run execution IDs, BigQuery parent/child jobs, attempt history, immutable GCS generations, and Gold before/after snapshots are retained under `docs/cloud/week5/`.
