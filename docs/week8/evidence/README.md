# Week 8 final exact-head CI evidence

- **Workflow:** [Week 8 CI run 44109255554](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/44109255554)
- **Source-run branch head:** `3a651422faa83e948919617c9bad1f0de06fe68e`
- **Artifact:** `week8-cdc-evidence-35944453f677067a55b4707f9c24e0249ffc1329`
- **Scope:** GitHub Actions ran Ruff, the Week 8 unit suite, Compose startup, T1–T7 integration tests, evidence upload, and stack teardown. The uploaded evidence records a healthy CI stack startup in 193.12 seconds. This is CI evidence; the laptop stack was not started because local RAM was below the preflight threshold.

## T1–T7 results

| Test | Retained evidence | Result |
|---|---|---|
| T1 | [`t1_row_hashes.json`](t1_row_hashes.json) | Postgres source and Silver each contain 4 rows with matching per-row hashes. |
| T2 | [`t2_restart.json`](t2_restart.json) | Restart replay preserves parity with 0 duplicate rows. |
| T3 | [`t3_replay.json`](t3_replay.json) | Replaying batch 3 leaves Silver unchanged. |
| T4 | [`t4_per_key_order.json`](t4_per_key_order.json) | Sixteen increasing LSNs for the tested key are captured on partition 0. |
| T5 | [`t5_watermark.json`](t5_watermark.json) | The recent late event updates its 5-minute window; the synthetic fixture reports exactly 2 rows dropped by the 10-minute watermark. |
| T6 | [`t6_schema_evolution.json`](t6_schema_evolution.json) | The nullable field flows through two schema versions; the incompatible registration returns HTTP 409. |
| T7 | [`t7_offset_comparison.json`](t7_offset_comparison.json), [`t7_consumer_groups.txt`](t7_consumer_groups.txt) | Spark `lastProgress` end offsets match Kafka log-end offsets for partitions 0/1/2: 24/1/3. The probe consumer group reports lag 0 on every partition. |

## Runtime snapshots

- [`silver_progress.json`](silver_progress.json) and [`gold_progress.json`](gold_progress.json) are the captured Spark `lastProgress` snapshots, including batch duration, rows, state, and watermark metrics.
- [`delta_silver_history.json`](delta_silver_history.json) is the captured Silver Delta `DESCRIBE HISTORY` output, including the MERGE and nullable-column evolution.
- [`connector_setup.json`](connector_setup.json) records connector, publication, slot, Avro subjects, and topic partition readiness. [`stack_startup.json`](stack_startup.json) records CI stack health and startup timing.

These small JSON/text files are copied from the final exact-head workflow artifact. Synthetic fixture IDs are retained as emitted. The large Compose log and full progress JSONL were omitted; no credentials or secrets are included.
