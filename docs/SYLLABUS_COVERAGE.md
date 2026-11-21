# Canonical syllabus coverage · Weeks 1–7

This matrix follows the exact 45 IDs in the Week 1–7 gap register and records bounded evidence. Snapshot refreshed from the Week 7 execution checklist at 2026-11-18 14:06 +07:00: main baseline 6b256f2; S10/S11 are complete; S12–S14 are pending. The temporary Airflow VM is gone; the syllabus still distinguishes historical evidence from currently retained services and keeps the mentor checkpoint pending.

## Status definitions and count

- **MET** means the bounded requirement has direct artifact and verification evidence. It does not imply a certificate or mentor sign-off.
- **PARTIAL** means only part of the requirement is evidenced, an explicit limitation remains, or the evidence exists on a not-yet-integrated branch.
- **NOT_RUN** means no completion evidence was found.
- **MENTOR_CONFIRMATION_PENDING** means the requirement depends on a real human checkpoint or review that has not been recorded.
- **OUT_OF_SCOPE** means F13 excludes the requirement from this release; it is not tracked as completed.

| Status | Rows |
|---|---:|
| MET | 16 |
| PARTIAL | 19 |
| NOT_RUN | 6 |
| MENTOR_CONFIRMATION_PENDING | 2 |
| OUT_OF_SCOPE | 2 |
| **Total** | **45** |

The count is only a roll-up of this matrix. It does not imply C_CODE_GO, C_CLOUD_DEMO_GO, or W1_TO_W7_FULLY_VERIFIED.

## Week 1 — Working environment and Git

| ID | Requirement | Evidence and verification | Status |
|---|---|---|---|
| W1-01 | Linux navigation, pipes, grep/awk/sed, permissions, cron, and SSH | The merged Lane D shell fixture uses pipe/grep/awk/sed, permissions, and a local CSV. Its README has an illustrative crontab entry and SSH security explanation. PR [#13](https://github.com/Dat071104/dataforge-commerce-platform/pull/13) and its [exact-head Week 7 run](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43584910006) passed; an earlier [base CI](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43569053596) also records the Linux CLI test. The syllabus minimum does not require a real cron schedule or SSH host. | **MET** |
| W1-02 | Branch, conventional commit, PR, review, and conflict | Repository history and PRs [#8](https://github.com/Dat071104/dataforge-commerce-platform/pull/8), [#10](https://github.com/Dat071104/dataforge-commerce-platform/pull/10), [#11](https://github.com/Dat071104/dataforge-commerce-platform/pull/11), [#9](https://github.com/Dat071104/dataforge-commerce-platform/pull/9), and [#13](https://github.com/Dat071104/dataforge-commerce-platform/pull/13) show branch/PR work. A dedicated safe conflict-resolution exercise and independent reviewer verdict are not recorded. | **PARTIAL** |
| W1-03 | VS Code, venv/uv, and Docker | The repository has a [Windows bootstrap](../scripts/bootstrap_windows.ps1), [operations runbook](operations_runbook.md), and Docker-based labs. An exact VS Code/uv setup or doctor/version receipt is not retained. | **PARTIAL** |
| W1-04 | Explain Data Engineer vs Analyst/DS/ML Engineer and modern data stack | No concise verified explain-back or tool-role table was found in the reviewed artifacts. | **NOT_RUN** |
| W1-05 | Public CSV fetch, row count, gzip, date folder, and PR | [Fetch script](../scripts/week1_fetch_csv.sh) and [fixture tests](../tests/week1/test_week1_fetch_csv.py) verify HTTPS URL rules, row counts, gzip, date partitioning, provenance, replay, and failure behavior. Tests serve a loopback fixture; no retained receipt proves a public fetch during the lane. PR [#8](https://github.com/Dat071104/dataforge-commerce-platform/pull/8) is merged. | **PARTIAL** |
| W1-06 | MIT Missing Semester lessons | The [course tracker](course_tracker.md) has the official course link and intentionally empty completion/evidence cells. No completion is claimed. | **NOT_RUN** |

## Week 2 — Python for Data Engineering

| ID | Requirement | Evidence and verification | Status |
|---|---|---|---|
| W2-01 | Python, typing, classes, exception handling, and logging | Typed Python packages, structured modules, and unit/integration tests exist under [src](../src/) and [tests](../tests/). Repository CI includes the Python regression suite. This is bounded code evidence, not course completion. | **MET** |
| W2-02 | CSV/JSON/Parquet, APIs, pagination, retries, and rate limits | The [weather adapter](../src/dataforge/weather.py), [tests](../tests/test_weather.py), and [Mini3 API contract](cloud/week7/closure/mini3_api_contract.md) cover typed API responses, bounded retries, CSV/Parquet use, and JSON provenance. Pagination and a rate-limit fixture are not demonstrated for the selected API. | **PARTIAL** |
| W2-03 | Pandas vs Polars read/write/filter/join/groupby and trade-offs | Merged Lane D parity code reads CSV, filters, joins, groups, and round-trips Parquet in both libraries. The deterministic parity test passed in PR [#13](https://github.com/Dat071104/dataforge-commerce-platform/pull/13) exact-head CI; [Week 7 attempt 2](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43584910006) passed eight jobs with one expected keyless-compile skip. Timings use an eight-row fixture and are not a speedup claim. | **MET** |
| W2-04 | Ruff, pytest, and project structure | The project has configured source/tests and CI quality checks. Merge-SHA base CI [43606510616](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43606510616) and Week 7 merge-SHA CI [43606510673](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43606510673) passed on f4d340f. | **MET** |
| W2-05 | Mini1 public API to cleaned Parquet with unit tests | [Weather adapter tests](../tests/test_weather.py) cover the reusable Mini1 client; [Mini3 contract](cloud/week7/closure/mini3_api_contract.md) and [API-to-Gold receipt](cloud/week7/closure/api_to_gold_e2e_receipt.json) record its bounded reuse for one historical date and three locations. This does not imply a recurring API service. | **MET** |
| W2-06 | Python for Data Engineers video playlist | The [course tracker](course_tracker.md) has a supplemental official Python reference; the exact video playlist and completion evidence are absent. | **NOT_RUN** |

## Week 3 — SQL, modeling, and Power BI

| ID | Requirement | Evidence and verification | Status |
|---|---|---|---|
| W3-01 | PostgreSQL CTE/window/subquery/index/EXPLAIN | Existing SQL analyses and indexes are in [sql](../sql/). Merged Lane D's disposable PostgreSQL 16 test captured before/after q10 EXPLAIN plans; base Postgres job 132417202516 includes those plans. The planner kept using the baseline index, so no causal speedup is claimed. [PR #13](https://github.com/Dat071104/dataforge-commerce-platform/pull/13) and [exact-head checks](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43584910006). | **MET** |
| W3-02 | 1NF–3NF vs denormalization; OLTP vs OLAP | [Modeling decisions](MODELING_DECISIONS.md), [architecture](architecture.md), and the normalized [SQL schema](../sql/schema/001_init.sql) compare 3NF transactional design with dimensional analytics. The prose does not explicitly walk through 1NF and 2NF. | **PARTIAL** |
| W3-03 | Kimball facts/dimensions, star/snowflake, SCD1/SCD2 | The local commerce model separates fact grains; the [Week 7 dbt contract](cloud/week7/dbt_model_contract.md) and [SCD2 receipt](cloud/week7/closure/dbt_scd2_history_receipt.json) show three observed synthetic order-state versions. The snapshot is observation history, not a customer dimension; an SCD1 example has not been separately audited. | **PARTIAL** |
| W3-04 | Data Vault and One Big Table comparison | [Modeling decisions](MODELING_DECISIONS.md) records trade-offs and why Kimball marts are used for this bounded commerce portfolio. | **MET** |
| W3-05 | Power BI cardinality, direction, inactive/role-playing dates, bridge, and RLS | Merged Lane D's read-only [TMDL audit report](https://github.com/Dat071104/dataforge-commerce-platform/blob/3d3b4e47c015fe20b8f1e1e987bdca7388c48fc0/docs/process/lanes/d.md) found 15 relationships, an inactive delivery-date relationship, USERELATIONSHIP measures, one RLS role, and no bridge. Cardinality/direction are not explicitly declared, so full feature coverage is not claimed. [Exact-head Week 7 run](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43584910006) passed. | **PARTIAL** |
| W3-06 | Mini2 retail star, PostgreSQL, ten queries, and Power BI revenue report | [P6.2 release record](releases/v1.0-local.md), [SQL analyses](../sql/analysis/), [PBIP project](../dashboards/P5/DataForge/DataForge.pbip), and retained screenshots evidence the synthetic Mini2. Fulfilled sales is a proxy, not accounting revenue. | **MET** |
| W3-07 | 60-minute SQL test and mentor Mini1/Mini2 review | No timed-test result, mentor attendance, or review record was found. | **MENTOR_CONFIRMATION_PENDING** |
| W3-08 | SQL/Power BI videos and Kimball reading | Links are in the [course tracker](course_tracker.md); no completion evidence is present. | **NOT_RUN** |

## Week 4 — Cloud platform and GCP mapping

| ID | Requirement | Evidence and verification | Status |
|---|---|---|---|
| W4-01 | Project/resource boundary, IAM/RBAC, and network | Historical [Week 4 acceptance](cloud/week4_acceptance.md), [target](cloud/target.json), and [IAM matrix](cloud/iam_matrix.md) describe the GCP scope. Current read-only inventory and IAM state were not reverified in this lane because the checklist records a gcloud reauthentication blocker. This is not an Azure equivalence claim. | **PARTIAL** |
| W4-02 | Map Azure/Fabric Lakehouse, Notebook, Warehouse, Pipelines, and Databricks to GCP/Spark | [Syllabus mapping](cloud/syllabus_mapping.md) and [architecture](architecture.md) compare Azure/Fabric concepts with GCS, BigQuery, Workflows, Cloud Run, and local Spark, and record explicit differences. Databricks is not separately compared and no Fabric or Databricks service was deployed. | **PARTIAL** |
| W4-03 | Terraform cloud foundation | Terraform configuration, historical apply/refresh evidence, and static checks are retained in [cloud/terraform](../cloud/terraform/) and [Week 4 acceptance](cloud/week4_acceptance.md). A current read-only plan was not run in Lane E. | **PARTIAL** |
| W4-04 | Key Vault/managed identity and least privilege | [IAM matrix](cloud/iam_matrix.md), [Week 7 security notes](cloud/week7/security_iam.md), and [security receipt](cloud/week7/security_iam_receipt.json) record keyless identities and scoped roles. No Secret Manager secret was needed for the retained keyless design; current effective permissions were not live-audited here. | **PARTIAL** |
| W4-05 | Mini1 Parquet to object storage and query in a warehouse | The [Mini3 API-to-Gold receipt](cloud/week7/closure/api_to_gold_e2e_receipt.json) records a real bounded weather request, immutable GCS Parquet/manifest, BigQuery landing, dbt, and three-row Gold result. This proves one historical slice, not a recurring service. | **MET** |
| W4-06 | Cost model and budget alert | Historical usage and gross estimates are in [Week 7 cost and cleanup](cloud/week7/closure/iam_cost_cleanup.md) and [demo cost table](demo/week7_checkpoint/cost_table.md). No budget alert or settled billing export is claimed. | **PARTIAL** |
| W4-07 | AZ/DP learning material or adjacent cloud study | The [course tracker](course_tracker.md) includes a GCP-adjacent official learning path. No training completion or certification is recorded. | **NOT_RUN** |

## Week 5 — ETL/ELT and data architecture

| ID | Requirement | Evidence and verification | Status |
|---|---|---|---|
| W5-01 | ETL/ELT, batch/microbatch/stream, lake/warehouse/lakehouse, Medallion | [Week 5 architecture and ADR](cloud/week5/architecture_and_adr.md) and [Week 5 acceptance](cloud/week5/acceptance_matrix.md) describe the bounded batch and Bronze/Silver/Gold paths. Streaming and a live lakehouse service are not implemented. | **PARTIAL** |
| W5-02 | Parquet, Avro, ORC, Delta, and Iceberg | Parquet is used by the ingestion/Spark work; a local Delta operation is recorded in [table-format demo](cloud/week6/table_format_demo.md). Avro, ORC, and Iceberg are not demonstrated. | **PARTIAL** |
| W5-03 | Partitioning, idempotency, incremental processing, and backfill | [Week 5 acceptance](cloud/week5/acceptance_matrix.md), recovery reports, and batch receipts record partitioned immutable data, sequence-based incremental loads, replay, tombstones, and backfill scenarios. | **MET** |
| W5-04 | PostgreSQL updated_at incremental flow to date-partitioned Parquet/GCP Bronze | Merged Lane D's same-timestamp [cursor counterexample](https://github.com/Dat071104/dataforge-commerce-platform/pull/13) shows why the accepted path uses monotonic change_seq. The updated_at baseline and full date-partitioned output are not complete as a literal syllabus exercise. | **PARTIAL** |
| W5-05 | Kimball ETL Toolkit/freeCodeCamp learning materials | Resources are listed in the [course tracker](course_tracker.md); no completion evidence is recorded. | **NOT_RUN** |

## Week 6 — Spark

| ID | Requirement | Evidence and verification | Status |
|---|---|---|---|
| W6-01 | Driver/executor, lazy evaluation, DAG, partitions, and Spark SQL/DataFrame | [Spark lab](../labs/spark_nyc_taxi/), [runtime report](cloud/week6/runtime_and_environment.md), and [final report](cloud/week6/final_report.md) record the local Docker/PySpark workload, plans, and output reconciliation. | **MET** |
| W6-02 | Broadcast/shuffle, skew/cache, partition tuning, and Spark UI | [Benchmark](cloud/week6/benchmark.md) records the measured broadcast result: 19.8% slower by median despite lower shuffle bytes. Event/plan evidence is retained; no authentic Spark UI screenshot is claimed, and skew/cache are not fully demonstrated. | **PARTIAL** |
| W6-03 | NYC Taxi at scale, hour/zone aggregate, and Delta/Iceberg output | The local workload processed 13,069,067 rows, reconciled outputs, and wrote partitioned Parquet plus a local Delta example. Managed execution is tracked separately. [Final report](cloud/week6/final_report.md). | **MET** |
| W6-04 | Run Spark locally and on a managed service | Local Spark acceptance plus the separately authorized S7-R Dataproc a4 batch: 2,964,624 input / 2,875,519 accepted / 89,105 rejected / 72,604 groups; checksum 1f298ea714cf125aa3f3bea601308baf74ee45222155fd892ff8528f1de50732. Driver/history, receipt and usage estimates are in [S7-R evidence](cloud/week6/evidence/c7-s7-a4-result-20261118.md), [cost log](cloud/week6/evidence/c7-s7-a4-cost-20261118.log), and [driver output](cloud/week6/evidence/c7-s7-a4-driver-history-summary.md). Invoice unavailable. | **MET** |
| W6-05 | PySpark video courses | Courses/certificates excluded by F13; not tracked. | **OUT_OF_SCOPE** |

## Week 7 — Airflow, dbt, Mini3, and checkpoint

| ID | Requirement | Evidence and verification | Status |
|---|---|---|---|
| W7-01 | Airflow DAG/operator/sensor/XCom/schedule/retry | Airflow 3.4 no-egress CI harness covers retry, 403, gate-off, failures, deadline and backfill. Natural scheduled DagRun scheduled__2026-11-18T02:00:00+00:00 succeeded 16/16; S6 manual retry try1 made no Cloud Run POST and try2 succeeded with the same invocation ID. Five UI captures are in [S10 evidence](cloud/week7/evidence/s10-airflow-ui-capture-20261118.md). VM is now torn down; this records bounded historical execution. | **MET** |
| W7-02 | SLA and alerts | C3 policies remain enabled. Monitoring recorded 8 PIPELINE_FAILED and 5 PIPELINE_DEADLINE_MISSED incidents; 2 user receipts are confirmed and 11 are unconfirmed. No deliberate terminal drill was run (0/2). | **PARTIAL** |
| W7-03 | Dagster comparison | [Week 7 architecture and ADR](cloud/week7/closure/architecture_and_adr.md) compares Dagster, Airflow, and Workflows and records why Dagster was not deployed. | **MET** |
| W7-04 | dbt models/tests/snapshot/docs/lineage | The dbt project, lineage and SCD2 receipt are retained. Live dbt build/tests passed 49/49; Gold publication and same-run NO_OP evidence are recorded in Week 7 receipts. Warehouse catalog/Pages publication is not claimed. | **PARTIAL** |
| W7-05 | Airflow orchestrates dbt | The 18/11 natural scheduled run completed the Airflow-to-Cloud Run dbt build and Gold publication; the S6 run and retry are also evidenced. The temporary VM was destroyed after acceptance; no current Airflow host is claimed. | **MET** |
| W7-06 | Daily Mini3 Airflow wholly on GCP, with real error notification | One natural scheduled run plus the S3/S4 backfill and S6 retry completed on the temporary GCP VM; Monitoring incidents and receipt status are summarized in W7-02. The VM is torn down, so no recurring daily hosted Airflow is claimed. | **PARTIAL** |
| W7-07 | Astronomer Airflow 101 and dbt Fundamentals | Courses and certificates are excluded by F13 and are not tracked. | **OUT_OF_SCOPE** |
| W7-08 | Final mentor/team demo, architecture, and cost review | The walkthrough, technical defense and updated [cost table](demo/week7_checkpoint/cost_table.md) are ready with measured usage and a conservative gross estimate. No mentor/team presentation or feedback is recorded. | **MENTOR_CONFIRMATION_PENDING** |

## Cross-cutting limits

- HR business-domain work is not added. The syllabus gap register says not to create an HR ETL solely for this objective; ask the mentor whether the domain mapping satisfies the checkpoint.
- CI, receipts, and synthetic records support engineering claims only within their tested scopes. They do not establish production uptime, customer data quality, a real SLO, or recognized accounting revenue.
- Courses/certificates are excluded by F13. Week 8–12 Kafka, Mini-project 4, and AI work run in separate sessions.
- The GCP-for-Azure/Fabric approval is user-reported; there is no signed mentor artifact in the repository. GCP services are not described as exact Azure/Fabric equivalents.
- The integrator checklist at D:\DATA_ENGINEER\DataForge_D_Week7_Final\03_CHECKLIST.md is local and unversioned; it is the current operational record for release and live-state status.

## Week 8 — Streaming with Kafka

| ID | Requirement | Evidence and verification | Status |
|---|---|---|---|
| W8-01 | Kafka topics, partitions, offsets, consumer groups, and delivery semantics | The [Week 8 lab](week8/README.md) configures three topic partitions. Exact-head [T1–T7 CI](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/44109255554) verifies restart replay without duplicate Silver rows (T2), idempotent sink replay (T3), and zero consumer-group lag after catch-up (T7); [retained evidence](week8/evidence/README.md) includes partition offsets. This demonstrates replay-safe at-least-once handling; exactly-once delivery is not claimed. | **PARTIAL** |
| W8-02 | Schema Registry with Avro/Protobuf and Debezium CDC | The [Week 8 ADR](week8/adr_cdc_streaming.md) and exact-head [T1–T7 CI](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/44109255554) verify Debezium Avro subjects, a nullable schema addition flowing through Spark/Delta, and rejection of a breaking schema (T6). Protobuf is not implemented. | **PARTIAL** |
| W8-03 | Spark Structured Streaming or introductory Flink, including window, watermark, and state | T5 evidence in exact-head [T1–T7 CI](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/44109255554) records the 5-minute revenue window, 10-minute watermark, state operators, and exactly two rows dropped by the watermark in this synthetic fixture. Spark Structured Streaming is used; Flink is not part of this exercise. | **MET** |
| W8-04 | Postgres CDC through Debezium, Kafka, Spark Streaming, and Delta/Iceberg with near-real-time updates | Exact-head [T1–T7 CI](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/44109255554) verifies Postgres-to-Silver row-hash parity (T1), restart/replay behavior (T2–T3), per-key LSN ordering (T4), windowed Gold updates (T5), schema evolution (T6), and matched Spark/Kafka offsets with lag-free catch-up (T7). [Retained evidence](week8/evidence/README.md) records the outcomes. This is a bounded local Compose exercise in CI, not a production service. | **MET** |

## Week 9 — Data quality, observability, governance, DataOps (Mini-project 4, Checkpoint GĐ3)

Evidence index: [RFC-001](week9/RFC-001-weather-pipeline-reliability.md) · [fault matrix](week9/evidence/fault_matrix.md) · [PII proof](week9/evidence/g3-g4-pii-proof-20261121.md) · [lineage](week9/evidence/g7-lineage-w9-drill.md) · [cost ledger](week9/cost_ledger.md). All W9 gates run only on the isolated `w9_drill` / `dbt_ci_pr_*` datasets; production enablement is a follow-up (RFC §4). W9 roll-up (7 rows, separate from the W1–W7 count above): MET 5 (W9-01, 02, 03, 05, 06), PARTIAL 1 (W9-04), MENTOR_CONFIRMATION_PENDING 1 (W9-07). AF12 close-out on 2026-11-21 deleted `w9_drill` and every `dbt_ci_pr_*` and paused the trusted PR cloud checks (`W9_WIF_PR_TARGET_ENABLED=false`); the runs linked here remain the evidence.

| ID | Requirement | Evidence and verification | Status |
|---|---|---|---|
| W9-01 | dbt tests, Great Expectations/Soda, data contract between producer and consumer | GX Core 1.25.0 G1 gate + dbt G2 tests/model contract; ODCS v3.2.0 contracts with `datacontract lint`/`breaking` on every PR. Fault fixtures F01–F12, F05b, F09, F-T1, F-N0 PASS on #52 exact head (run [44867546904](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/44867546904)); F07/F10 PASS on isolated BigQuery (run [44872770442](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/44872770442)); F14 contract break blocked (PR #55). | **MET** |
| W9-02 | Observability (freshness, volume, schema drift) and alerting via Slack/email | `dq_results` + monitors (freshness, volume, schema drift, distribution); log-based metrics and three P1 Monitoring policies to email; Slack webhook from Secret Manager with dedup/resolve. F-N0 live precision: 12 PASS events, 0 alerts. Live drill H-W9-3 (F06, 2026-11-21): gate blocked 26 s after injection, alert event at 58 s, Slack ≤ 98 s, email received (user-confirmed, not timed), restore + RESOLVED 1 min 58 s / 3 min 49 s ([drill evidence](week9/evidence/h-w9-3-f06-live-drill.md)). Dead-man policy disabled after the W7 VM teardown. | **MET** |
| W9-03 | Catalog and lineage (DataHub/OpenMetadata) | OpenMetadata 2.0.7 ephemeral in CI (run [44864861534](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/44864861534), dbt manifest 11 records/0 errors); BigQuery Data Lineage: weather 5 links + synthetic-PII 2 links; API disabled after capture. OpenMetadata is not a persistent server. | **MET** |
| W9-04 | PII classification and masking; NĐ 13/2023 | 351/351 columns classified; HMAC pseudonymisation; policy tags + masking; access tests both ways PASS (run [44866987378](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/44866987378) + G4); PII-leak guard blocks F13 (local exit 1; CI blocked one step earlier). NĐ 13/2023 is repealed from 01/01/2026 by NĐ 356/2025; mapping uses Law 91/2025 Art. 20/39. Breach-notification article remains `LEGAL_UNVERIFIED`; synthetic data only. | **PARTIAL** |
| W9-05 | Docker/compose; GitHub Actions running lint, test, `dbt build` on PRs | Pinned DataOps toolbox image; `week9-dataops.yml` lint/tests/fault fixtures on every PR; keyless WIF `dbt build` into `dbt_ci_pr_<n>` on trusted PRs while `W9_WIF_PR_TARGET_ENABLED=true` (green end to end: #56 run [44882607355](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/44882607355); earlier #57 runs such as 44873779562 built successfully but ended `failure` at run level because of R-19, fixed in #57); cleanup on PR close. The cloud build is paused since AF12 (2026-11-21 15:14). | **MET** |
| W9-06 | Mini-project 4: tests + CI/CD for the W7 pipeline, inject bad data, prove detection and alerting | [Fault matrix](week9/evidence/fault_matrix.md): F01–F12, F05b, F09, F-T1, F-N0 offline PASS; F07/F10 live PASS; F13 PII leak and F14 contract break blocked; F15 logic shift caught by the slim-CI data diff (`prod_only=6`, `ci_only=6`, run [44882607355](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/44882607355)). Live drill H-W9-3 PASS (data restored 1 min 58 s, gate green and RESOLVED 3 min 49 s); blind game day 001 PASS (F02, MTTD 2 min 18 s, MTTR 6 min 56 s, [postmortem-001](week9/postmortem-001.md)). Evidence is on the isolated `w9_drill` dataset, not on production. | **MET** |
| W9-07 | Checkpoint GĐ3: 1–2 page design doc reviewed by the mentor like an RFC | RFC-001 v0.3 In review; pre-review by a mentor-persona reviewer answered in the decision log. Real mentor review (H-W9-2) not yet held. | **MENTOR_CONFIRMATION_PENDING** |
