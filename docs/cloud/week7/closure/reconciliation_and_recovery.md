# Mini-project 3 reconciliation and recovery

## Verified current state

After the final exact-manifest replay and the controlled failure:

- Weather Gold pointer: version 4; publication run airflow-44dcf9562a79445bf7bf460a0508164beecca0bc1833b3bcaef62f668b45ac82.
- Published view for 2026-11-05: 3 rows, 3 provinces, zero invalid metric rows.
- Controlled failure ledger row: FAILED with error category controlled_failure_test; no publication version.
- Replayed Airflow manifest generation 1794475149037958: 3 landing rows, 3 province/date grains, zero duplicate grains.
- Week 5 order/payment tables and the accepted commerce publication pointer were not read for writes or modified.

## Fault and recovery matrix

| Scenario | Expected control | Observed evidence | Status and recovery |
|---|---|---|---|
| Open-Meteo timeout, 429, or 5xx | Bounded retries and timeout; no COMPLETE manifest or Gold publish on incomplete source data. | Offline Mini3 job tests use mocked provider failures. Actual provider requests for HCM/HN/DN returned HTTP 200. No live provider fault was injected. | PARTIAL for live provider failure injection. Retry only the same settled observation date after provider recovery; inspect the Cloud Run execution first. |
| Missing, duplicate, unexpected, or out-of-order dates | Reject before typed Parquet and manifest publication. | Offline tests cover malformed and incomplete responses. A live Cloud Run request for unsettled date 2026-11-12 failed before provider access and created no GCS invocation receipt; execution dataforge-week7-weather-ingest-g4mml. | PASS for live settling-date rejection; PARTIAL for malformed provider payload injection. |
| GCS generation/hash mismatch | Read the exact generation and fail closed on mismatched generation, hash, schema, or path. | A live verify execution against the correct Airflow manifest URI requested generation 1794475149037959 while the object was generation 1794475149037958. Cloud Run execution dataforge-week7-weather-ingest-6xx87 failed; Cloud Logging recorded that the requested generation does not exist. Local tests cover hash/schema corruption. No stored object was modified. | PASS for exact-generation mismatch rejection and replay; PARTIAL for object tampering. Preserve all immutable generations. |
| BigQuery landing schema or merge mismatch | Verify schema and source fields, partition-bound the merge, and reconcile exact keys/values. | Live Airflow reconciliation verified the loaded 3-row manifest. Replaying the same exact manifest left 3 rows and zero duplicate grains. Mock tests cover invalid schema/row contracts. | PASS for live reconcile/replay; PARTIAL for injecting a bad schema. The protected landing schema was not changed. |
| dbt quality failure | Candidate tests and the publisher guard fail closed without advancing the pointer. | The live controlled alert run completed dbt build/tests, then injected a failure before publication; pointer remained at version 4. Offline tests cover data-quality assertions. No malformed candidate was sent to the live Gold publisher. | PASS for post-test failure preservation; PARTIAL for a live failing dbt quality test. Correct data in isolated candidate relations before publishing. |
| Airflow transient retry or sensor timeout | Single active DagRun, bounded retries, reschedule sensor, fixed task/run timeouts, identifiers-only XCom. | Live Airflow DagRun succeeded with a real GCS receipt and GCP tasks. An earlier ordering defect failed before publication and was fixed. Airflow contract tests verified retry bounds and sensor behavior; no transient GCP failure was injected to observe retry. | PARTIAL for live retry/failure injection. Inspect the task and Cloud Run operation; only retry after the current execution is terminal. |
| Concurrent Airflow and Cloud Scheduler | Only one controller may invoke the pipeline at a time. | The timed cloud run completed before the local Airflow DagRun. The Airflow preflight reported Scheduler ABSENT. There was no overlap. | PASS for serialized operation. The temporary Scheduler job is deleted; do not enable both controllers concurrently. |
| Duplicate/replayed manifest | Same immutable manifest generation should be safe to reload without duplicate landing grain. | Exact Airflow manifest replay Cloud Run execution dataforge-week7-weather-ingest-c8rcx completed. BigQuery returned 3 rows, 3 distinct province/date grains, zero duplicates, and the Gold pointer stayed at version 4. | PASS for landing replay. This does not claim a production-scale multi-date backfill test. |
| NO_NEW_BATCH or source settling | Treat normal no-batch/source-not-ready as non-failure; never publish or alert. | Control flow and mock alert tests cover normal statuses; no Mini3 no-batch cloud execution was injected. | PARTIAL for live no-batch behavior. Wait for the seven-day HCM settling window; do not retry a normal no-batch as an error. |
| Controlled failure alert | One explicit failure marker opens a rate-limited incident and sends one external notification before publication. | Workflow execution 355edf21-c024-4749-af17-c8e53c746581 failed after dbt tests and before publish. Monitoring incident opened, and the user confirmed the one email arrived. Current pointer remained version 4. | PASS. Temporary channel and policy were removed after the single delivery; see notification_delivery_receipt.md. |
| SCD2 status update, unchanged replay, and tombstone | Isolated snapshots capture versions with non-overlapping valid-time windows, one current state, tombstone, and no extra row on unchanged replay. | dbt_scd2_history_receipt.json records three synthetic versions, zero overlaps, one current version, and unchanged replay with no added version. | PASS for isolated synthetic history. This is observation-time history, not a claim that unseen intermediate business-effective states can be reconstructed. |

## Recovery defects found during live execution

The following integration issues were found and repaired before acceptance:

1. The first reconciliation SQL referenced a MERGE alias outside its scope. The CTE now exposes the destination columns directly and local contract tests cover it.
2. The dbt identity initially lacked BigQuery table update permission for candidate relations. The isolated weather model-writer role now includes the required table update permission; it does not grant Week 5 or commerce access.
3. dbt staging initially scanned a partitioned landing source without a required date filter. The orchestrators now pass the exact settled observation date, and the source model filters that partition.
4. The publication macro initially shadowed request_id in a validation union. Renaming the union key restored the correct checks.
5. The workflow could publish a version but could not verify it because the published Gold view and Workflow reader binding were missing. Terraform now creates the view and table-scoped reader access.
6. The Airflow DAG initially attempted reconciliation before landing. The stage order is now load, reconcile, dbt build/test, publish, then Gold verification.
7. The local Airflow runner initially inherited the image entrypoint, causing argument parsing to fail. The runner now invokes the Airflow CLI explicitly.
8. SCD2 proof updates initially used streaming insert, which made a follow-up update unavailable while the row was in the streaming buffer. The proof now uses a bounded BigQuery load job.

The first accepted weather Gold version was created before the publication view was available, so its Workflow ended as a failure even though its dbt publication step had completed. After adding the view and permissions, the manual Workflow succeeded at version 2. The final controlled failure was intentionally injected after tests and did not update version 4.

## Reconciliation boundary

The final current Gold version is reconciled to its exact request ID, immutable GCS manifest generation, provider SHA-256, and row count. The full-refresh target and incremental target returned identical three-row relation contents for 2026-11-05 using a bidirectional EXCEPT DISTINCT comparison. A repeated landing operation against the Airflow manifest caused no duplicate province/date grain.

The source is an ERA5 reanalysis/model estimate, not an official station truth oracle. A provider correction should create a new content-addressed request and immutable Bronze version; dbt Silver selects the highest verified manifest generation for each province/date/source/model. Past Gold versions remain queryable. Weather is not causally joined to Week 5 financial analytics.
