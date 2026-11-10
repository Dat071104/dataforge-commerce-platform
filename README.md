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
- **Syllabus:** GCP remains a functional mapping. Mentor approval is pending; GCP work does not automatically satisfy an Azure-specific checkpoint.
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
  TF[Terraform and least-privilege IAM] -->|apply: 11 creates| G
  TF --> H
~~~

Week 4’s accepted snapshot path ends at typed staging. Week 5 is a separate incremental learning reference that reaches per-order Gold controls and a transactionally committed checkpoint. All Week-4 replay generations remain intact. Week-5 source PostgreSQL stays on the developer machine; Cloud Run consumes only uploaded GCS generations and cannot reach the laptop’s loopback address.

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
| Data Factory | Cloud Run Jobs; Workflows/Scheduler for future orchestration | A finite manual Week-5 job is live-tested; no schedule or orchestration workflow is running. |
| Spark Notebook | Local PySpark or Managed Service for Apache Spark | Week 6 plan; no Spark execution is claimed. |
| Key Vault | Secret Manager | Not configured for this phase. |
| Terraform with Azure provider / Bicep | Terraform with Google provider | Terraform apply completed; provider resources and behavior differ. |

These are nearest learning analogies, not product equivalence. See the [full syllabus mapping](docs/cloud/syllabus_mapping.md); mentor approval is still required for any Azure-specific assessment.

## Data, security, and cost controls

- All included commerce data is synthetic. Order items, payments, returns, shipments, inventory snapshots, and weather observations keep separate fact grains.
- Fulfilled sales is a synthetic proxy, not recognized revenue. Collections, refunds, and shipment measures use their own event definitions.
- The verified transfer uses immutable manifests, create-only GCS generation preconditions, SHA-256 checks, typed staging, and independent row/schema/value reconciliation.
- Standard BigQuery queries are capped at 256 MiB billed; the multi-statement publish script is capped at 1 GiB and its child jobs are captured. Staging tables expire after seven days. Terraform state uses an isolated, project-named local workspace.
- Runtime access is scoped: required object reads and queries pass; anonymous GCS access and Gold listing are denied. No static service-account keys are stored in the repository.
- The operational target is USD 10 with a Week-5 aim of at most USD 5 in additional usage. It is not a hard cap. Gross measured compute was estimated below USD 0.08 before unmetered storage/free-tier effects; settled charges remain unknown.
- The Week-5 job is manual and finite. No dbt model, managed Spark cluster, recurring schedule, or cloud BI publication is running.

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
- **Week 6 — Spark:** local PySpark with a licensed public fixture, explain plans, and measured benchmarks. Managed Spark is optional and needs a separate cost decision.
- **Week 7 — Orchestration and modeling:** dbt-bigquery tests/lineage, manual Workflows end-to-end, Cloud Scheduler only after manual recovery passes, and a local Airflow reference DAG.

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
- [Week 4 first-pass transfer receipts](docs/cloud/evidence/transfers/)
- [Week 4 safe-rerun receipts](docs/cloud/evidence/reruns/)
- [Live IAM verification](docs/cloud/evidence/iam_live_verification.json)
- [Terraform and IAM design](docs/cloud/iam_matrix.md)
- [Cloud runbook and safe cleanup](docs/cloud/runbook.md)
- [Detailed Azure/Fabric syllabus mapping](docs/cloud/syllabus_mapping.md)
