# P7.3 / Week 6 — acceptance matrix

**Execution:** local Docker Spark 3.5.9 / Delta 3.3.3; run `week6-20261110-03`. The managed Spark batch is optional and was not authorized (`CLOUD_SPARK_NOT_AUTHORIZED`). Full receipts are in [output_reconciliation.json](output_reconciliation.json), [benchmark.json](benchmark.json), and the detailed [final report](final_report.md).

| Gate | Result | Evidence |
|---|---|---|
| SPK-01 Official source and schema | **PASS** | Four official 2024 Yellow Taxi files plus official zone lookup; SHA-256/bytes/footer rows recorded in [dataset provenance](dataset_provenance.md). Spark materialized 13,069,067 rows and matched the sum of all four footers; all four 19-column schemas matched. |
| SPK-02 Quality ledger | **PASS** | 12,686,794 accepted + 382,273 rejected = 13,069,067 input. Nulls, DST/period/duration/zone/distance categories, per-field negative amounts, and duplicate-like fingerprint are recorded. Negative monetary rows are retained and flagged. |
| SPK-03 Grain and join cardinality | **PASS** | One row per pickup date/hour/zone; 263 assigned zone IDs validated unique before join; output keys unique; summed output `trip_count` equals accepted rows. |
| SPK-04 DataFrame and SQL parity | **PASS** | Full 13.07M-row workload; two-way distributed comparison returned zero differing rows. |
| SPK-05 Independent Oracle | **PASS** | Full 2024-01-15 pickup-date partition read through PyArrow row groups and independently aggregated in Python/Decimal. 77,033 input rows; 74,680 accepted; 2,353 rejected; all keys/counts/exact monetary and distance sums matched; p50/p95 difference was at most 0.00034 minute. |
| SPK-06 Replay and failure-safe publication | **PASS** | Date-partitioned Parquet was staged, validated, and published with a complete manifest; same-run replay verified the manifest and returned `VERIFIED_NO_OP`. Negative tests cover missing/corrupt/wrong-schema inputs, partial/stale manifests, and bad output layout. |
| SPK-07 Plans, UI, and event metrics | **PASS with screenshot limitation** | Actual executed baseline/candidate plans and 16.8 MB event log retained by hash; Spark UI REST returned live jobs/stages inside the container. Windows host port forwarding timed out and the computer-use helper could not verify the Chrome URL, so no screenshot is claimed. Manual capture steps are in [spark_ui_evidence.md](spark_ui_evidence.md). |
| SPK-08 Controlled benchmark | **PASS; exploratory result** | Same 13.07M input, action, AQE and 96 shuffle partitions; one warmup plus five timed runs per plan; exact counts/money and 1.0-minute percentile tolerance passed. Broadcast reduced shuffle/spill but was 19.8% slower by median, so no speedup is claimed. See [benchmark.md](benchmark.md). |
| SPK-09 Skew | **PASS** | Real pickup-zone skew measured: 607,808 trips in the hottest zone versus a 1,174-trip median across 259 active zones (517.7×); physical plan shows map-side partial aggregation before exchange. |
| SPK-10 Partitioned Parquet | **PASS** | 308,833 aggregate rows in 121 `pickup_date` partitions/files, 8,330,057 bytes; a selected-day read showed a `PartitionFilter` and returned the independent Oracle's 74,680 trip count. Average Parquet file is 68,843 bytes; file-size trade-off is documented. |
| SPK-11 Table format | **PASS** | Real TLC aggregate Delta demo: version 0 held 20 rows; append reached 21 at version 1; idempotent replay remained 21/version 1; history and version-0 read returned 20. Metadata and schema are in [table_format_demo.md](table_format_demo.md). |
| SPK-12 Local CI, security, and cloud boundary | **PASS** | Pinned local image, 30 fixture tests pass without downloading TLC data in CI; Ruff, compileall, pip check, and Power BI source-pack validation pass. Existing commerce regression: 155 offline passes / 7 DB-gated skips; PostgreSQL suite: 161 passes / 1 separate Week-5 operational-DB skip using uniquely named temporary databases. Raw data, outputs and event logs are ignored. No GCP batch/resource/IAM mutation occurred. |

## Negative test coverage

| Failure case | Evidence |
|---|---|
| Missing source file | `test_missing_source_file_fails_before_spark_read` |
| Corrupt Parquet | `test_corrupt_parquet_fails_closed` |
| Wrong schema / 2025 drift | `test_wrong_schema_and_unexpected_schema_version_fail_closed` |
| Duplicate or incomplete zone lookup | `test_zone_lookup_rejects_duplicate_or_incomplete_dimension` |
| Bad session timezone and DST gap/fold/crossing | `test_quality_policy_requires_new_york_session_timezone`, `test_quality_ledger_rejects_anomalies_but_keeps_negative_amounts`, and `test_quality_policy_rejects_fall_back_ambiguous_local_time` |
| Empty output day | `test_partitioned_parquet_is_staged_idempotent_and_handles_empty_day` |
| Partial/stale output manifest | `test_partial_or_stale_output_manifest_is_rejected`; stale source hash covered in the partition publication test |
| Bad partition layout | `test_bad_partition_layout_is_rejected` |
| Low-memory guard | `test_low_memory_budget_refuses_to_start_without_oom`; refuses before Spark starts rather than provoking an OOM |
| Repeated publication | `test_partitioned_parquet_is_staged_idempotent_and_handles_empty_day` |
| Benchmark event log and tolerance | `test_eventlog_recovery_emits_run_receipts_and_real_plans`, `test_reuse_benchmark_requires_matching_context_and_preserves_eventlog_plans`, and `test_benchmark_parity_keeps_exact_money_and_tolerates_approximate_percentiles` |

## Verdict gate

**Independent verdict: `GO_WEEK6_LOCAL`.** The verdict authorizes a feature-branch commit, push, and PR. Merge remains gated on hosted CI passing on the exact PR head with no blocking findings. Managed cloud execution is not a prerequisite for this local verdict.
