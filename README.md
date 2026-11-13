# DataForge — Synthetic Commerce Analytics

**Local acceptance: GO LOCAL** (v1.0-local / P6.2).
**GCP Week 4: CLOUD_GO_WEEK4 — independent final controller accepted.**

DataForge is an educational, synthetic-first order-to-cash analytics portfolio. It preserves the accepted local ingestion, PostgreSQL, Kimball, SQL, and Power BI baseline while adding a bounded GCP learning path. It is not a production service or accounting system.

## Current status

- **Local:** accepted P6.2 GO LOCAL baseline; see the release record for evidence.
- **GCP target:** project `dataforge-p7-lab-d0f725` (number `955038620072`), region `us-central1`, private bucket `dataforge-p7-lab-d0f725-bronze`.
- **Week 4:** Terraform apply completed (11 creates, 0 updates, 0 destroys). All 11 synthetic source batches passed first-pass GCS integrity and BigQuery raw/typed schema, key, and value checks: 16,259 rows and 235,910 Parquet bytes.
- **Reruns:** all 11 source receipts passed. Every replay preserved GCS and manifest generations, reused completed load/cast jobs, and matched exact raw and typed values.
- **Live IAM:** the runtime service account read the source object and queried eight unique geography keys. Anonymous object access and runtime Gold listing returned HTTP 403; positive/negative IAM checks passed, and no static service-account key was created.
- **Final gate:** the independent controller returned [CLOUD_GO_WEEK4](docs/cloud/controller_verdict.md); hosted CI must pass before merge.
- **Week 5 (P7.2):** the separate operational journal → immutable GCS → Cloud Run Job → BigQuery Silver/Gold/checkpoint path passed live INC-01–INC-10 tests and a 100K-row synthetic snapshot/MERGE benchmark. The independent controller returned CLOUD_GO_WEEK5; exact-head hosted CI and main-branch CI passed, and implementation PR [#2](https://github.com/Dat071104/dataforge-commerce-platform/pull/2) merged.
- **Week 6 (P7.3):** the separate local Docker Spark lab processed 13,069,067 official NYC TLC Yellow Taxi rows, with DataFrame/SQL parity, an independent daily oracle, a measured join experiment, partitioned Parquet, and a verified Delta operation. The independent controller returned `GO_WEEK6_LOCAL`; PR [#4](https://github.com/Dat071104/dataforge-commerce-platform/pull/4) merged after both hosted checks passed. Managed Spark was not run. See the [Week 6 release report](docs/cloud/week6/final_report.md).
- **Week 7 (P7.4):** live dbt-bigquery, Workflows/Cloud Run, currentness fencing, all ten failure drills, local Airflow reference, and full-refresh parity are verified. The latest pointer is version 6 at source seq 30; the 5-row Gold view matches Week 5 and the Decimal oracle with zero mismatches. Gross BigQuery + Cloud Run list estimate is about USD 0.25; settled billing remains unknown. The independent controller returned `CLOUD_GO_WEEK7`; PR [#5](https://github.com/Dat071104/dataforge-commerce-platform/pull/5) was created in Chrome after the GitHub app API returned 403, and both PR-head workflows passed. The linked PR is the merge record. See [Week 7 evidence](docs/cloud/week7/final_report.md).
- **Week 7 syllabus closure (P7.4.1):** the separate three-province Mini-project 3 weather API → GCS Bronze → BigQuery → dbt Gold slice ran live. A real Airflow 3.4.0 local-Docker DagRun and one automatic Cloud Scheduler firing each completed API-to-Gold; isolated SCD2 history produced three valid versions; one controlled failure alert was delivered and user-confirmed. The one-shot schedule and alert resources were removed. The independent controller returned `CLOUD_GO_WEEK7_SYLLABUS`; PR [#6](https://github.com/Dat071104/dataforge-commerce-platform/pull/6) merged after exact-head CI reported 12/12 successful or skipped (11 pass, one policy skip). Several live fault injections remain partial, and cost is an estimate, not settled billing. See [closure evidence](docs/cloud/week7/closure/).
- **Syllabus:** the user reported that the mentor approved GCP as the Azure/Fabric alternative on 2026-11-12. No separate written approval artifact was supplied. The mapping records this approval without claiming Azure product equivalence.
- **Legacy services:** any superseded-project inventory is read-only and documented separately.

## Architecture

~~~mermaid
flowchart LR
  subgraph Local["Accepted local baseline"]
    A[Synthetic CSV] --> B[Contracts and validation]
    B --> C[Immutable Parquet and manifest]
    C --> D[PostgreSQL raw and audit]
    D --> E[Kimball marts and SQL]
    E --> F[Power BI Desktop]
  end
  subgraph Cloud["Week 4 snapshot baseline"]
    C -->|11 batches; object integrity verified| G["Private GCS Bronze<br/>dataforge-p7-lab-d0f725-bronze"]
    G -->|generation and hash verified| H["BigQuery raw staging<br/>11 sources"]
    H -->|typed schema, keys, and values verified| I["BigQuery typed staging<br/>us-central1"]
  end
  subgraph Week5["Week 5 incremental reference — live tests passed"]
    O["Operational PostgreSQL journal<br/>orders + payment events"] --> P["Sequence extractor<br/>Decimal oracle"]
    P --> Q["Typed Parquet + COMPLETE manifest"]
    Q --> G
    G -->|explicit manifest generation| R["Cloud Run Job<br/>digest-pinned, keyless"]
    R --> S["BigQuery batch staging"]
    S --> T["Silver MERGE<br/>sequence-aware I/U/D"]
    T --> U["Gold per-order controls<br/>+ ops checkpoint transaction"]
  end
  subgraph Spark["Week 6 local NYC TLC lab — separate workload"]
    NYC["Official 2024 Yellow Taxi Parquet"] --> SP["Docker Spark<br/>quality + hourly/zone aggregate"]
    SP --> PP["Date-partitioned Parquet"]
    SP --> DL["Isolated Delta<br/>append + history + time travel"]
  end
  subgraph Week7["Week 7 dbt + orchestration — live verified"]
    SCH["Temporary Scheduler trigger<br/>NO_NEW_BATCH; removed"] -.-> WF[Workflows]
    G -->|approved manifest generation| WF
    WF --> R
    U --> DBT["Finite Cloud Run Job<br/>dbt-bigquery r4"]
    DBT --> CAND["dbt_week7 candidate"]
    CAND --> TESTS["dbt tests + reconciliation"]
    TESTS --> PUB["Immutable Gold version<br/>pointer + currentness fence"]
    PUB --> VIEW["Current published view<br/>empty while stale"]
  end
  TF[Terraform and least-privilege IAM] -->|apply: 11 creates| G
  TF --> H
~~~

Week 4’s accepted snapshot path ends at typed staging. Week 5 is a separate incremental learning reference that reaches per-order Gold controls and a transactionally committed checkpoint. All Week-4 replay generations remain intact. Week-5 source PostgreSQL stays on the developer machine; Cloud Run consumes only uploaded GCS generations and cannot reach the laptop’s loopback address.

Week 6 processes public TLC data in a standalone local workload; it does not feed or change commerce Silver/Gold. See the [Spark lab runbook](labs/spark_nyc_taxi/README.md) and [Week 6 report](docs/cloud/week6/final_report.md).

Accepted P7.4 continues to read only the Week 5 orders/payment simulator; it does not claim the eleven Week 4 commerce streams. P7.4.1 adds a separate weather domain that does not join to commerce or payment facts. Its Airflow 3.4.0 runner was local Docker while its integration tasks used the real GCP data plane. The P7.4 order publication pointer and the separate weather Gold pointer remain independent.

## Local quickstart

Requirements: Windows, Python 3.11, and Docker Desktop.

~~~powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Set a private local password in .env.
.\scripts\bootstrap_windows.ps1
docker compose up -d --wait
.\scripts\demo_windows.ps1
.\.venv\Scripts\dataforge.exe reference-metrics
~~~

The demo creates deterministic synthetic data, validates source contracts, writes Parquet, loads PostgreSQL, builds marts, checks financial controls, and verifies safe reruns. It does not need cloud credentials.

## Week 5 incremental quickstart

The source simulator uses its own PostgreSQL container, database, and loopback port; it does not reset the accepted application database. Cloud writes require the approved isolated gcloud configuration.

~~~powershell
docker compose --project-name dataforge-week5-source `
  --file labs/operational_source/compose.yaml up -d --wait
. .\scripts\enter_dataforge_cloud.ps1
.\.venv\Scripts\python.exe .\scripts\week5_incremental.py source-init
.\.venv\Scripts\python.exe .\scripts\week5_incremental.py seed
.\scripts\week5_incremental.ps1 batch --max-events 1000
~~~

The default batch command is local/dry-run. For an authorized upload, add `--execute`; pass the returned manifest URI and generation to `week5_run_job.ps1`, then inspect `status` and run `reconcile`. The complete evidence and failure/recovery commands are in [the Week-5 runbook](docs/cloud/week5/runbook.md). To repeat the bounded 100K-row comparison, run `.\scripts\week5_benchmark.ps1 -Execute`.

## Week 7 dbt and orchestration quickstart

Parse dbt without cloud credentials, then upload a complete Week 5 batch and pass its immutable manifest identity to Workflows:

~~~powershell
& .\dbt\dataforge\.venv\Scripts\dbt.exe parse `
  --project-dir .\dbt\dataforge --profiles-dir .\dbt\dataforge --target offline
. .\scripts\enter_dataforge_cloud.ps1
& .\.venv\Scripts\python.exe .\scripts\week5_incremental.py batch --max-events 1000 --execute
# Use the returned manifest_uri, exact manifest_generation, and batch_id:
& .\.venv\Scripts\python.exe .\scripts\week7_run_workflow.py `
  --manifest-uri '<approved-gs-uri>' --manifest-generation <generation> `
  --batch-id <manifest-sha256> --run-mode normal
~~~

The accepted P7.4 Scheduler demonstration was a forced `NO_NEW_BATCH` check. Separately, P7.4.1 observed one genuine time-based Scheduler firing for the weather pipeline; that temporary job was deleted after success. See the [Week 7 runbook](docs/cloud/week7/orchestration_runbook.md), [P7.4.1 acceptance matrix](docs/cloud/week7/closure/acceptance_matrix.md), and [closure report](docs/cloud/week7/closure/final_report.md).

## Cloud preflight and smoke

Cloud preflight and dry-run are local-only. Dot-source the helper to select the shared isolated gcloud/ADC root; it reads the canonical target metadata and starts no login flow.

~~~powershell
.\.venv\Scripts\python.exe -m dataforge.cli cloud-preflight --source geography

. .\scripts\enter_dataforge_cloud.ps1
$target = Get-Content -Raw .\docs\cloud\target.json | ConvertFrom-Json
$config = $target.configuration
$project = $target.project_id
$activeProject = gcloud --configuration=$config config get-value core/project
if ($activeProject -ne $project) { throw "Unexpected active project: $activeProject" }

.\.venv\Scripts\python.exe -m dataforge.cli cloud-transfer `
  --source geography `
  --project $project `
  --bucket $target.bucket `
  --dataset staging `
  --region $target.region `
  --bucket-location $target.region `
  --dataset-location $target.region `
  --dry-run
~~~

After checking the reviewed infrastructure, IAM, location, and cost receipts, install the optional GCP clients and run the bounded geography example:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gcp]"
.\.venv\Scripts\python.exe -m dataforge.cli cloud-transfer `
  --source geography `
  --project $project `
  --expected-project-number $target.project_number `
  --bucket $target.bucket `
  --dataset staging `
  --region $target.region `
  --execute
~~~

The execute flag writes remote objects and tables. The same-source replay is verified as a no-op for the completed geography batch; receipts for all 11 source replays are available under docs/cloud/evidence/reruns. See the [cloud runbook](docs/cloud/runbook.md).

## Azure/Fabric to GCP concept map

| Azure or Fabric concept | Closest GCP concept | Difference or current status |
|---|---|---|
| Subscription and resource group | Organization/folder/project hierarchy | This lab uses one active project; GCP has no exact resource-group equivalent. |
| Entra ID and Azure RBAC | Google identity and Cloud IAM | Runtime IAM has live positive/negative verification; policy semantics differ. |
| ADLS Gen2 | Cloud Storage | Private GCS bucket deployed and source objects verified; object and filesystem behavior differ. |
| OneLake | Cloud Storage plus BigQuery | Separate services, not a unified cross-engine lake. |
| Fabric Lakehouse | Cloud Storage plus BigLake/BigQuery interoperability | No equivalent transaction layer is deployed; native BigQuery staging is not Delta/Iceberg. |
| Fabric Warehouse | BigQuery | Week 5 has Silver and a small per-order Gold control reference; it is not an accounting mart or full Fabric Warehouse replacement. |
| Data Factory pipelines/triggers | Cloud Scheduler + Workflows + Cloud Run Jobs | P7.4 remains manifest-driven; P7.4.1 demonstrated one automatic time-based weather run, then deleted the temporary schedule. |
| dbt on Fabric/Synapse | dbt-bigquery on Cloud Run Jobs | Incremental models, contracts, tests, and full-refresh parity are verified for the Week 5 simulator. |
| Airflow | Local Airflow 3 integration | One Airflow 3.4.0 local-Docker DagRun executed the live Mini3 GCP data plane; Composer is not deployed and no hosted Airflow claim is made. |
| Spark Notebook | Local PySpark or Managed Service for Apache Spark | Local Spark lab is verified; a managed batch is optional, `CLOUD_SPARK_NOT_AUTHORIZED`, and `NOT_RUN`. |
| Key Vault | Secret Manager | Not configured for this phase. |
| Terraform with Azure provider / Bicep | Terraform with Google provider | Terraform apply completed; provider resources and behavior differ. |

These are nearest learning analogies, not product equivalence. See the [full syllabus mapping](docs/cloud/syllabus_mapping.md), which records the user's report of mentor approval for the GCP substitution.

## Data, security, and cost controls

- All included commerce data is synthetic. Order items, payments, returns, shipments, inventory snapshots, and weather observations keep separate fact grains.
- Week 6 uses public NYC TLC Yellow Taxi records in a separate local Spark lab; those records do not feed the commerce marts, and raw files stay out of Git.
- Fulfilled sales is a synthetic proxy, not recognized revenue. Collections, refunds, and shipment measures use their own event definitions.
- The verified transfer uses immutable manifests, create-only GCS generation preconditions, SHA-256 checks, typed staging, and independent row/schema/value reconciliation.
- Standard BigQuery reads are capped at 256 MiB billed; the Week-5 multi-statement publish is separately capped at 1 GiB. The dbt job is 1 vCPU/1 GiB, single-task, 240-second timeout, and zero automatic retries. Terraform state uses an isolated project-named workspace.
- Runtime access is scoped and policy-inspected: Workflows can run only the two approved jobs and read its control tables; the dbt identity writes Week-7 datasets; public GCS access is prevented; user-managed service-account key inventory is zero.
- The Week-7 USD 5 target is not a hard cap. The measured gross BigQuery + Cloud Run list estimate is about USD 0.25 before free tiers and unmetered storage. Billing API remains disabled and settled charges are unknown.
- Week 5, P7.4, and P7.4.1 use finite jobs and isolated data domains. The P7.4.1 timed schedule and one-off alert resources were removed after demonstration; no recurring schedule, Composer, managed Spark, always-on VM, or cloud BI publication remains.

## Free Trial and cost notice

A Cloud Console observation during Week-5 preflight showed an active Free Trial and no DataForge current-month project row. Trial credits and settled charges remain unknown; there is no hard budget cap. No billing upgrade was made. Personal credit balances, billing-account identifiers, authentication records, and browser screenshots are not published.

## Local validation

~~~powershell
$env:RUN_POSTGRES_TESTS = "0"
.\.venv\Scripts\python.exe -m pytest -q tests dashboards/P5/tests
.\.venv\Scripts\ruff.exe check src tests scripts dashboards/P5
.\.venv\Scripts\python.exe -m compileall -q src tests scripts dashboards/P5
.\.venv\Scripts\python.exe -m pip check
~~~

PostgreSQL integration tests are enabled separately with RUN_POSTGRES_TESTS=1 and use isolated temporary databases. See the [v1.0-local release record](docs/releases/v1.0-local.md) and [cloud phase summary](docs/cloud/phase_summary.md) for recorded evidence and open gates.

## Weeks 5–7 roadmap

- **Week 5 — Incremental batch:** live tests, benchmark, independent controller verdict, exact-head hosted CI, and merge complete; see the [final report](docs/cloud/week5/final_report.md).
- **Week 6 — Spark:** local GO, PR #4 merged after hosted checks; managed Spark remains optional and unrun.
- **Week 7 — P7.4 accepted:** live dbt, Workflows/Cloud Run, full-refresh parity, currentness fencing, local Airflow reference, and ORC-01–ORC-10 recovery drills are complete; PR #5 is merged. **P7.4.1:** the Mini3 API-to-Gold path, Airflow integration, timed cloud firing, one delivered alert, and isolated SCD2 proof have live receipts. The independent controller returned `CLOUD_GO_WEEK7_SYLLABUS`; PR #6 merged after exact-head hosted CI passed.

Each phase must earn its own evidence. No always-on VM, Cloud SQL, GKE, Composer, or recurring paid job is part of the current foundation.

## Documentation

- [Local architecture and grain register](docs/architecture.md)
- [Metric contract](docs/metric_contract.md)
- [P6.2 local release evidence](docs/releases/v1.0-local.md)
- [Cloud target metadata](docs/cloud/target.json)
- [Cloud phase summary](docs/cloud/phase_summary.md)
- [Week 4 acceptance matrix](docs/cloud/week4_acceptance.md)
- [Week 5 acceptance matrix](docs/cloud/week5/acceptance_matrix.md)
- [Week 5 final report](docs/cloud/week5/final_report.md)
- [Week 6 acceptance matrix](docs/cloud/week6/acceptance_matrix.md)
- [Week 6 final report](docs/cloud/week6/final_report.md)
- [Week 7 final report](docs/cloud/week7/final_report.md)
- [Week 7 architecture and ADR](docs/cloud/week7/architecture_and_adr.md)
- [Week 7 dbt contract and generated lineage](docs/cloud/week7/dbt_model_contract.md), [lineage](docs/cloud/week7/model_lineage.md), [artifacts](docs/cloud/week7/artifacts/)
- [Week 7 acceptance matrix](docs/cloud/week7/acceptance_matrix.md), [orchestration runbook](docs/cloud/week7/orchestration_runbook.md), [failure recovery](docs/cloud/week7/failure_recovery.md)
- [Week 7 performance/cost](docs/cloud/week7/performance_and_cost.md), [security/IAM](docs/cloud/week7/security_iam.md), [test receipts](docs/cloud/week7/test_receipts.json)
- [Week 4 first-pass transfer receipts](docs/cloud/evidence/transfers/)
- [Week 4 safe-rerun receipts](docs/cloud/evidence/reruns/)
- [Live IAM verification](docs/cloud/evidence/iam_live_verification.json)
- [Terraform and IAM design](docs/cloud/iam_matrix.md)
- [Cloud runbook and safe cleanup](docs/cloud/runbook.md)
- [Detailed Azure/Fabric syllabus mapping](docs/cloud/syllabus_mapping.md)
