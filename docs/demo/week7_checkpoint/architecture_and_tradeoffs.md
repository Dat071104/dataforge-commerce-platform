# Architecture and tradeoffs

## Objective and scope

DataForge aims to demonstrate repeatable batch ingestion, typed data contracts, dimensional modeling, safe recovery, testing, and clear evidence on small bounded workloads. The portfolio contains four deliberately separate domains: the accepted local synthetic commerce project, GCP Weeks 4–7 commerce exercises, a local NYC TLC Spark lab, and the Mini3 weather project.

It is an educational portfolio, not an operated production service. The GCP substitution for Azure/Fabric is recorded as the user's report of mentor approval; no separate written approval artifact is available. The mapping describes learning analogies rather than product equivalence.

## Chosen boundaries

| Domain | Chosen path | Reason |
|---|---|---|
| Local commerce | Synthetic CSV → Python validation → content-addressed Parquet and manifest → PostgreSQL raw/audit → Kimball marts → SQL/Power BI | Preserves a low-cost, portable Mini1/Mini2 baseline and makes local tests easy to run. |
| Week 4 cloud snapshot | Synthetic source extracts → private GCS Bronze → raw and typed BigQuery staging | Demonstrates object integrity, explicit schemas, key checks, IAM, and Terraform with a finite isolated workload. |
| Week 5/7 commerce | Separate PostgreSQL change journal → immutable GCS manifest → Cloud Run consumer → BigQuery Silver/checkpoint → dbt candidate/reconciliation → versioned Gold pointer | Makes sequence ordering, replay, bounded backfill, and publish recovery explicit. It reads only the small Week 5 simulator; it does not transform all Week 4 sources. |
| Week 6 Spark | Public NYC TLC files → local Docker/PySpark → quality ledger and hourly/zone aggregate → partitioned Parquet and local Delta example | Exercises Spark plans and table/version behavior without managed-cluster cost. |
| Mini3 weather | Open-Meteo ERA5 → separate Cloud Run ingest → immutable weather Bronze → BigQuery weather landing → isolated dbt models → weather Gold versions/pointer | Keeps API observations out of order/payment facts and records exact source and manifest identity. |

See the editable [architecture diagram](../../architecture/dataforge_overview.drawio). GCP data-plane resources are GCS, BigQuery, and finite Cloud Run Jobs. Workflows is the GCP control plane for bounded execution. Airflow 3.4 ran once in local Docker against the weather data plane; it is not hosted. The one time-based Cloud Scheduler firing and the single controlled alert policy were removed after their demonstrations.

## Correctness and publication

The local commerce design keeps each fact at its own grain and defines proxy metrics in a metric contract. The Week 5 simulator uses a transactionally written sequence journal so events with the same <code>updated_at</code> remain ordered. Manifests and immutable object generations provide replay identities. BigQuery landing MERGE and versioned publication macros make no-op behavior testable.

Week 7 builds a dbt candidate and runs its selected quality tests before the publication step. The commerce path uses a pointer/currentness fence so a failed candidate is not exposed as current; recovery replays the same immutable manifest. Weather Mini3 has separate tables, models, and a separate pointer. Its one-date demo produced three rows, so it is a constrained transformation example rather than a long-history analytics mart.

P7.5 fixed the Airflow scheduled empty-conf contract and separated permission to touch cloud from the run's requested mode/date. Cloud access defaults OFF. The Cloud Run operation poll is synchronous and bounded; the old receipt sensor ran only after this wait, so the updated DAG removes it. Airflow's contract code passes local helper tests, but the pinned Airflow 3.4 image suite and native scheduler retry transition were not run in this host. Do not claim a hosted or unattended scheduler.

## Security and operations

The project uses fixed project/resource allowlists, keyless identities, scoped service accounts, immutable inputs, and bounded BigQuery bytes for the documented workloads. No static service-account key was created. Cloud scheduler and alert resources were temporary; the retained receipts state they were removed. No recurring schedule or notification remains. The one-time email approval is consumed.

Retries may resubmit a Cloud Run job after an ambiguous transport timeout. Stable invocation identity, immutable writes, content hashes, MERGE semantics, and publication no-ops reduce duplicate data effects, but the design does not guarantee exactly-once execution or exactly-once provider requests.

## FinOps and limits

Week-specific usage records estimate gross compute and billed bytes. They are not settled invoices and do not include all account-level free-tier/credit effects. The project target in earlier reports was an operational target, not a hard cap. No project budget alert is configured. Storage, APIs, Workflows, logging, and account-wide free tier have separate constraints.

Managed Spark, hosted Airflow, a persistent notification channel, and remote Terraform state were not needed to demonstrate the current bounded code patterns. They remain deferred because each adds cost, permissions, or ongoing operations. Week 8–12 syllabus work has not started.

## Next decision

Show the accepted evidence first and ask the mentor whether the hybrid local-Airflow/GCP data-plane demonstration satisfies the Week 7 checkpoint. If it does, stop before adding idle infrastructure. If the mentor requires hosted Airflow, a recurring alert, a budget, or managed Spark, prepare a separate target-specific request with the exact permission, duration, cost bound, teardown plan, and evidence objective before deployment.
