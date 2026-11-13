# Syllabus Coverage · Weeks 1–7

This map compares the original 12-week internship syllabus with the actual DataForge code and retained evidence. It reports coursework coverage, not job readiness, certification, or production ownership. Its P7.5 status snapshot is taken at the local review gate; use GitHub for the later hosted CI and merge state.

**Scope boundary:** the accepted baseline through P7.4.1 is preserved. P7.5 adds post-Week-7 correctness and portfolio evidence; its current GitHub release state belongs in the PR/checklist. Week 8 has not started.

**Status meanings:** `MET` = the bounded project requirement has evidence; `PARTIAL` = some syllabus requirements or operational proof remain; `NOT_RUN` = no implementation/evidence claimed; `NOT_APPLICABLE` = not part of this portfolio slice; `MENTOR_CONFIRMATION_PENDING` = the required human checkpoint or approval has not been independently documented.

## Week-by-week coverage

| Week | Syllabus requirement | DataForge evidence | Status | Exact boundary / gap |
|---|---|---|---|---|
| 1 · Environment and Git | Linux/shell commands, Git branch/commit/PR workflow, public CSV download, row count, compression, date-based storage, delivery by PR. | [P7.5 Bash script](../scripts/week1_fetch_csv.sh), [usage guide](../scripts/week1/README.md), [fixture tests](../tests/week1/test_week1_fetch_csv.py): 16 offline tests pass. | **PARTIAL at this snapshot** | The code and fixture tests are complete on the P7.5 branch; GitHub PR delivery and hosted CI remain release gates. Later PRs are not retroactively claimed as the Week 1 assignment. |
| 2 · Python for Data Engineering | Python quality, files/APIs, CSV/JSON/Parquet, tests, retry and rate-limit concepts; Mini1. | [Weather adapter](../src/dataforge/weather.py), [unit tests](../tests/test_weather.py), [source provenance](source_provenance.md), and one bounded API-to-Bronze use recorded in the Mini3 receipt. | **MET for the bounded code deliverable** | Course-video completion and broad Polars/Pandas training are not asserted. Open-Meteo API data requires attribution and non-commercial terms. |
| 3 · SQL, modeling, Power BI | Advanced SQL, Kimball star schema, SCD, 10 analyses, Power BI semantic model and report; Mini2. | [Schema and mart SQL](../sql/), [10 analysis queries](../sql/analysis/), [Power BI project](../dashboards/P5/DataForge/DataForge.pbip), [P6.2 release evidence](releases/v1.0-local.md). | **MET for the bounded synthetic Mini2** | Five fact grains are kept separate; fulfilled sales is a proxy. A timed 60-minute checkpoint or mentor code review is not claimed. |
| 4 · Cloud platform | Azure/Fabric resource/IAM concepts, object storage, warehouse, Terraform, Key Vault, cost and budget alert. | GCP project, Terraform, private GCS, BigQuery staging, scoped identities, measured usage and cost estimate: [Week 4 acceptance](cloud/week4_acceptance.md), [syllabus mapping](cloud/syllabus_mapping.md). | **PARTIAL overall** | User reported mentor approval to substitute GCP; no separate written approval artifact. GCP products are not Azure/Fabric equivalents. No budget alert is configured; settled billing is unknown. Secret Manager was not needed for the keyless design. |
| 5 · ETL/ELT and architecture | Batch and medallion design, immutable formats, idempotency, incremental load and backfill. | [Change journal](../src/dataforge/incremental/source.py), [runtime](../src/dataforge/incremental/batch.py), [Week 5 acceptance](cloud/week5/acceptance_matrix.md), [benchmark](cloud/week5/incremental_vs_snapshot_benchmark.md). | **MET for synthetic incremental batch** | The source uses a transactionally sequenced journal, not CDC or streaming. The measured 100K snapshot and 1K-change MERGE each billed 44,040,192 bytes. |
| 6 · Spark | PySpark DataFrame/SQL, joins, partitions, UI/plan reading, NYC Taxi-scale transform, local and managed execution. | [Spark lab](../labs/spark_nyc_taxi/), [final report](cloud/week6/final_report.md), [physical plans and benchmark](cloud/week6/benchmark.md). | **PARTIAL overall** | Local Spark processed 13,069,067 rows and used an independent oracle. Managed Spark was not run or authorized. Broadcast was 19.8% slower by median. |
| 7 · Orchestration and dbt | Airflow DAG/operator/sensor/XCom/schedule/retry/failure, dbt tests/snapshot/docs/lineage, Mini3 daily API-to-Gold flow, mentor checkpoint. | [P7.4 commerce pipeline](cloud/week7/final_report.md); [Mini3 closure](cloud/week7/closure/final_report.md); [Airflow 3 reference](../labs/airflow_reference/); [P7.5 correctness report](cloud/week7/closure/p75_airflow_correctness.md). | **PARTIAL overall** | dbt, publication and bounded GCP orchestration have evidence. One local-Docker Airflow integration run and one separate timed Workflows firing are recorded; no hosted Airflow or recurring schedule remains. The historical sensor ran after a blocking Cloud Run wait; a true asynchronous Airflow sensor wait is not demonstrated. External email was a single controlled Workflows alert; its policy/channel were removed. P7.5 helper tests pass, but the pinned Airflow 3.4 Docker suite is unrun in this environment. |

## Mini-project mapping

| Syllabus project | Implementation and evidence | Status | Limitation |
|---|---|---|---|
| Mini1 · Public API → clean data → Parquet + unit tests | [Open-Meteo adapter](../src/dataforge/weather.py), [tests](../tests/test_weather.py), [source provenance](source_provenance.md). A bounded one-date/three-location path is included in [API-to-Gold evidence](cloud/week7/closure/api_to_gold_e2e_receipt.json). | **MET for the bounded adapter** | No continuous ingestion service. API terms and attribution still apply. |
| Mini2 · Retail star schema + PostgreSQL + SQL + Power BI | [Local data architecture](architecture.md), [metric contract](metric_contract.md), [SQL](../sql/), [Power BI PBIP](../dashboards/P5/DataForge/DataForge.pbip), [P6.2 report](releases/v1.0-local.md). | **MET for synthetic commerce scope** | No production business data; proxy metrics are not accounting results. |
| Mini3 · Daily API → Bronze → dbt Silver/Gold → failure alert | [Mini3 acceptance matrix](cloud/week7/closure/acceptance_matrix.md), [scheduler receipt](cloud/week7/closure/scheduler_execution_receipt.json), [Airflow integration receipt](cloud/week7/closure/airflow_integration_receipt.md), [notification record](cloud/week7/closure/notification_delivery_receipt.md). | **PARTIAL** | One timed Workflows run and one local Airflow integration were observed. Airflow was not hosted, its sensor did not asynchronously wait, and the single alert policy was removed. No new alert is authorized by this closure. |
| Mini4 · Fault-injected quality tests + CI alert | Week 7's dbt quality gates, 10 live recovery cases, local tests, and GitHub CI are useful related evidence. | **PARTIAL** | The distinct Week 9 Mini4 assignment has not been performed as a new syllabus deliverable; no persistent alert is active. |

## Later weeks and checkpoints

| Requirement | Status | Notes |
|---|---|---|
| Week 3 SQL / Mini1+2 checkpoint | **MENTOR_CONFIRMATION_PENDING** | Code and release records exist; no timed mentor checkpoint receipt is claimed. |
| Week 7 demo before team/mentor and cost/design review | **MENTOR_CONFIRMATION_PENDING** | This repository prepares a walkthrough and supporting evidence; no presentation or sign-off is claimed. |
| Week 8 Kafka, Schema Registry, CDC, and streaming | **NOT_RUN** | Explicitly outside P7.5; Week 8 has not started. |
| Week 9 governance, observability, data catalog, personal-data controls, and Mini4 | **PARTIAL** | Some data tests, failure drills, CI, and IAM practices exist. The full Week 9 stack and Mini4 are not complete. |
| Week 9 mentor-reviewed RFC | **NOT_RUN** | A P7.5 architecture/tradeoff note is prepared for handoff; it is not a mentor review or signed RFC. |
| Weeks 10–12 ML, feature store, MLOps, RAG/LLM, AI-assisted DE capstone | **NOT_RUN** | Not started. No capstone or AI-course completion is claimed. |
| Course videos and certifications | **NOT_RUN / NOT VERIFIED** | No course-completion or certification receipts were found or fabricated. |
| Persistent GCP budget alert / settled bill | **PARTIAL** | Cost usage and gross estimates are documented; a budget alert is not configured and actual billing totals remain unknown. |
| Managed Spark / hosted Airflow / recurring failure notification | **NOT_RUN** | Optional cloud actions require separately scoped approval. |

## What to say about the Azure/Fabric substitution

The user reported that the mentor approved GCP as the Azure/Fabric substitute on 12 November 2026. The repository records that as user-reported approval, not as a signed mentor artifact. The implementation demonstrates nearby learning concepts—projects and IAM, Cloud Storage, BigQuery, Terraform, Cloud Run, Workflows, and dbt-bigquery—but does not claim service equivalence with Azure or Microsoft Fabric.

For code, receipts, safe validation commands and explanations by week, use the [Evidence Index](EVIDENCE_INDEX.md). The persistent P7.5 gate-by-gate record is the [execution checklist](cloud/week7/closure/p75_execution_checklist.md).
