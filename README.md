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
  subgraph Cloud["Week 4 deployed — verification complete"]
    C -->|11 batches; object integrity verified| G["Private GCS Bronze<br/>dataforge-p7-lab-d0f725-bronze"]
    G -->|generation and hash verified| H["BigQuery raw staging<br/>11 sources"]
    H -->|typed schema, keys, and values verified| I["BigQuery typed staging<br/>us-central1"]
    I -. Week 5 .-> J[Silver MERGE]
    J -. Week 7 .-> K[dbt BigQuery Gold]
  end
  T[Terraform and least-privilege IAM] -->|apply: 11 creates| G
  T --> H
~~~

The verified cloud path ends at typed BigQuery staging. All 11 source replays preserved object generations and matched exact values. The independent controller accepted Week 4 as CLOUD_GO_WEEK4. PostgreSQL stays on the developer machine; a cloud job cannot reach a laptop’s loopback address.

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
| Fabric Warehouse | BigQuery | Raw and typed staging are verified; no Gold warehouse model is claimed. |
| Data Factory | Workflows plus Cloud Run Jobs; Scheduler if needed | Future orchestration work; no job or schedule is running. |
| Spark Notebook | Local PySpark or Managed Service for Apache Spark | Week 6 plan; no Spark execution is claimed. |
| Key Vault | Secret Manager | Not configured for this phase. |
| Terraform with Azure provider / Bicep | Terraform with Google provider | Terraform apply completed; provider resources and behavior differ. |

These are nearest learning analogies, not product equivalence. See the [full syllabus mapping](docs/cloud/syllabus_mapping.md); mentor approval is still required for any Azure-specific assessment.

## Data, security, and cost controls

- All included commerce data is synthetic. Order items, payments, returns, shipments, inventory snapshots, and weather observations keep separate fact grains.
- Fulfilled sales is a synthetic proxy, not recognized revenue. Collections, refunds, and shipment measures use their own event definitions.
- The verified transfer uses immutable manifests, create-only GCS generation preconditions, SHA-256 checks, typed staging, and independent row/schema/value reconciliation.
- BigQuery query limits are 256 MiB billed; staging tables expire after seven days. Terraform state uses an isolated, project-named local workspace.
- Runtime access is scoped: required object reads and queries pass; anonymous GCS access and Gold listing are denied. No static service-account keys are stored in the repository.
- The Week 4 operational cost target is USD 10. It is not a hard cap or spending guarantee; check observed usage before and after cloud operations.
- No Cloud Run Job, dbt model, incremental CDC pipeline, managed Spark cluster, recurring schedule, or cloud BI publication is claimed as running.

## Free Trial and cost notice

A Cloud Console observation on 2026-11-09 showed an active Free Trial with displayed expiry on 2027-01-21. Trial credits, service eligibility, and charges are temporary and account-dependent; this notice does not guarantee free usage or cap spend. Personal credit balances, billing-account identifiers, authentication records, and browser screenshots are not published.

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

- **Week 5 — Incremental batch:** a finite Cloud Run Job, journal-backed changes, BigQuery Silver MERGE, replay/recovery tests, and parity checks.
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
- [Week 4 first-pass transfer receipts](docs/cloud/evidence/transfers/)
- [Week 4 safe-rerun receipts](docs/cloud/evidence/reruns/)
- [Live IAM verification](docs/cloud/evidence/iam_live_verification.json)
- [Terraform and IAM design](docs/cloud/iam_matrix.md)
- [Cloud runbook and safe cleanup](docs/cloud/runbook.md)
- [Detailed Azure/Fabric syllabus mapping](docs/cloud/syllabus_mapping.md)
