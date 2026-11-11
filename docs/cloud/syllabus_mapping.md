# Azure/Fabric to GCP syllabus mapping

**Assessment status:** GCP is a functional learning mapping, not an exact product replacement. Mentor approval for an Azure/Fabric substitution remains pending; this document does not certify Azure-specific competency.

**Current Week 4 evidence:** Project `dataforge-p7-lab-d0f725` (number `955038620072`), region `us-central1`, and private bucket `dataforge-p7-lab-d0f725-bronze`; see the [canonical target metadata](target.json). Terraform apply completed with 11 creates, 0 updates, and 0 destroys. All 11 synthetic source transfers and reruns passed: 16,259 rows / 235,910 Parquet bytes; GCS generations were unchanged and raw/typed values matched exactly. Live IAM positive/negative checks passed. The independent controller returned CLOUD_GO_WEEK4.

**Week 6 local evidence:** a separate Docker Spark lab materialized 13,069,067 official NYC TLC Yellow Taxi rows with parity, independent Oracle, plans/event logs, benchmark, partitioned Parquet, and a real local Delta operation. This verifies local Spark fundamentals only; no managed Spark batch or GCP write occurred. See [Week 6 final report](week6/final_report.md). Mentor acceptance of GCP/Fabric equivalence remains pending.

## Concept mapping

| Azure or Fabric checkpoint | Closest GCP concept | DataForge status | Important difference |
|---|---|---|---|
| Azure subscription | GCP project linked to a Cloud Billing account | Target project is ACTIVE with billing enabled; Week 4 resources are deployed | Billing account and project are separate. Project scope and Azure subscription policy semantics differ. |
| Azure resource group | No direct equivalent; use project boundaries, folders, and labels for grouping | No separate resource-group-style boundary | GCP has no ARM resource-group lifecycle boundary with the same scope and behavior. |
| Entra ID and Azure RBAC | Google identity or Cloud Identity for principals; Cloud IAM for authorization | School CLI/ADC and runtime IAM behavior were verified | Principal, role, condition, inheritance, and policy evaluation differ. Azure roles do not map one-to-one to IAM roles. |
| ADLS Gen2 | Cloud Storage | Private GCS bucket is deployed; all 11 source batches and replays verified object integrity | GCS is object storage. Hierarchical namespace, ACL, filesystem, and data-lake behaviors are not identical. |
| OneLake | No single equivalent; combine Cloud Storage with BigQuery as needed | GCS and BigQuery are separate deployed services | The services have separate storage, governance, access, and lifecycle boundaries; there is no unified OneLake surface across engines. |
| Fabric Lakehouse | Cloud Storage with BigLake/BigQuery interoperability | Native BigQuery raw and typed staging tables are verified; no lakehouse format is deployed | A bucket plus native BigQuery tables does not provide Delta/Iceberg transaction semantics or Fabric Lakehouse behavior. |
| Fabric Warehouse | BigQuery analytics warehouse | BigQuery raw and typed staging are verified; no Gold model is claimed | Both support analytical SQL, but storage, compute, capacity, security, and operational models differ. |
| Data Factory | Workflows orchestrating finite Cloud Run Jobs; Cloud Scheduler may trigger a workflow | Future Week 5/7 work; no job or schedule is running | Workflow orchestration is assembled from separate services and is not a feature-equivalent Data Factory replacement. |
| Spark Notebook | Local PySpark for the Week 6 lab; Managed Service for Apache Spark is an optional cloud path | Local Docker Spark is verified; managed Spark is `CLOUD_SPARK_NOT_AUTHORIZED` and `NOT_RUN` | Notebook authoring, cluster/runtime management, integrations, and pricing differ. Managed Spark needs a separate spending authorization. |
| Key Vault | Secret Manager | Not configured for this phase | Secret lifecycle, access policies, rotation, integrations, and regional behavior differ. No secrets are copied between clouds by this mapping. |
| Terraform / AzureRM provider / Bicep | Terraform with the Google provider | Terraform apply completed against the new project | Terraform is shared tooling, but provider resources and semantics differ; Bicep is a separate IaC language and has no direct GCP equivalent. |

## How to interpret this mapping

A mapping identifies a nearby capability for learning. It does not prove service equivalence, portability, or mentor acceptance. In particular:

- GCS is not a drop-in ADLS Gen2 filesystem, and native BigQuery tables are not a complete lakehouse.
- BigQuery staging is not evidence that a Fabric Warehouse or Lakehouse has been configured.
- Cloud Run Jobs plus Workflows are a design choice for finite batch execution, not a complete Data Factory clone.
- A local PySpark lab demonstrates Spark fundamentals; it does not establish managed Spark operations.
- IAM implementation in one cloud does not establish Azure RBAC experience.
- The operational cost target is USD 10, not a cap or guarantee; this mapping makes no measured-cost claim.

## DataForge phase boundaries

- **Week 4:** deployed GCS and BigQuery staging; 11/11 first-pass transfers and 11/11 safe reruns passed. The final independent controller verdict is CLOUD_GO_WEEK4.
- **Week 5:** add journal-backed incremental batches, a finite Cloud Run Job, BigQuery Silver merge, replay, failure recovery, and parity evidence.
- **Week 6:** local Spark lab is completed with official TLC data, measured plans/benchmarks, Parquet, and a Delta table operation; the optional managed batch was not authorized or run.
- **Week 7:** add dbt-bigquery tests/lineage, a manually triggered workflow, safe recovery, and a local Airflow reference DAG. Add a scheduler only after the manual flow passes.

No Cloud Run Job, dbt model, incremental CDC pipeline, managed Spark batch, schedule, or cloud BI publication is claimed from Week 6. Do not use a GCP phase result as proof of an Azure-specific syllabus checkpoint without explicit mentor acceptance.
