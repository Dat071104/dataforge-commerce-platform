# P7.4.1 Week 7 syllabus closure — architecture decision

**Status:** bounded Mini3 implementation and live demonstration completed; independent controller returned `CLOUD_GO_WEEK7_SYLLABUS`; PR #6 merged after exact-head hosted CI passed.
**Date:** 2026-11-12.
**Scope:** one weather observation slice only. Accepted Week 4/5/6/7 pipelines remain separate.

## Decision

Use Cloud Workflows as the bounded GCP control plane for the automatic timed demonstration. Its flow calls a finite Cloud Run API job, waits for an immutable GCS invocation receipt, loads an exact manifest generation into typed BigQuery landing, runs the separate weather dbt job, validates tests, publishes through a versioned pointer, and writes a terminal execution ledger entry.

The only Scheduler job ran at 15:55 Asia/Ho_Chi_Minh on 2026-11-12. It dispatched Workflow execution 5028cbfb-e5a2-4596-b663-6d0d964a8c56, which published version 3. The job was paused after firing and deleted after completion. No recurring schedule remains.

The same finite GCP jobs were also exercised from a distinct Airflow 3.4.0 integration DAG. Airflow ran in a one-shot local Docker container, not Composer or a hosted Airflow service. The DAG sensed the real GCS receipt, performed a separate landing reconciliation, ran dbt build/tests/publication, and verified Gold. The Airflow DagRun was serialized after the Cloud Scheduler execution; the Airflow preflight confirmed that the Scheduler job was absent.

## Data and publication boundary

The source reuses the Mini-project 1 Open-Meteo Historical Weather adapter. Each request is one ERA5 date at the HCM, HN, and DN city-centre coordinates, using Asia/Ho_Chi_Minh and a seven-day settling delay. Raw source responses, typed Parquet, SHA-256 values, exact GCS generations, and a COMPLETE manifest are retained under the private weather prefix.

The typed landing table is partitioned by observation date and keyed by request, province, and observation date. The exact Airflow manifest replay created no duplicate province/date grain. Weather dbt staging and Silver choose the latest verified source generation. A separate full-refresh target matched the incremental target for the demonstrated date.

Gold is a weather-only, immutable version table selected through a singleton current-publication pointer. Publication runs after row-level and source reconciliation checks. A controlled failure after dbt tests but before publication preserved the prior pointer at version 4. No weather relation joins to Week 5 order/payment analytics. The Week 5 source tables, Gold, checkpoint, and accepted commerce Workflow are not part of this pipeline.

## Orchestrator comparison

| Orchestrator | Execution model and sensors | Lineage and operations | Cost and fit here |
|---|---|---|---|
| Airflow 3 | Task DAG; supports scheduled runs, retries, and a reschedule sensor; XCom can carry small task metadata. | Broad ecosystem and task-level history. Requires an always-available scheduler for ongoing operation, unless run as an external one-shot integration. | Local Docker was suitable for the syllabus demonstration. No Composer charge or hosted scheduler was required. |
| Dagster | Asset/job-oriented orchestration with materialization and asset checks; daemon/sensor model supports event-driven work. | Strong asset lineage and software-defined asset model, but would add another runtime and operational surface. | Not deployed. It would not add a required gate beyond Airflow plus existing Workflows. |
| Google Workflows | Stateful serverless steps with retry/catch and explicit HTTP/API calls; Cloud Scheduler provides cron dispatch. | Execution history and structured logs; data lineage is recorded separately in GCS manifests, BigQuery lineage columns, and the ledger. | Chosen for the GCP timed path because it reuses the accepted serverless pattern and has no idle scheduler cost. Scheduler and alert resources were removed after the one-off proofs. |

Only one controller is active at a time. The Cloud Scheduler proof ended before the Airflow DagRun began. The daily schedule is not retained in the project.

## Alternatives rejected

- Existing order/payment Workflow: kept unchanged because it controls accepted commerce state. Weather has a different grain and lifecycle.
- Cloud Composer, GKE, and always-on VM: rejected because persistent infrastructure is unnecessary for this finite batch demonstration.
- Kafka or Cloud SQL: rejected because no streaming or transactional application service is required by the syllabus gap.
- Dagster deployment: rejected as an unnecessary framework addition for this scope.

## Source and licensing boundary

Open-Meteo's free API is for non-commercial use with attribution. This is an educational portfolio workload. The API response and generated dataset preserve provider attribution. The historical ERA5 API documents a five-day delay; the seven-day lag is a conservative batch choice, not a claim that the values are final. A later provider correction should create a new content-addressed request and Bronze generation.

The source-only HTTP smoke returned three HTTP 200 responses and three typed rows for 2026-11-05. Separately, the deployed Cloud Run job executed the real request path and published the API-to-Gold result; exact execution evidence is in api_to_gold_e2e_receipt.json.

## Identity and cost boundary

The weather pipeline uses distinct ingest, dbt, Workflow, Scheduler, and Airflow service accounts with domain-scoped access. The Scheduler's one-permission workflows.executions.create role was project-scoped because Workflows does not support a lower-level IAM resource binding or IAM Conditions resource attribute for an individual Workflow. This role and the temporary Scheduler identity/binding were removed after the timed test. The temporary user-to-Airflow-service-account impersonation grant was removed after the local integration.

The incremental demonstration target was under USD 5 gross. Current cost estimates and inventory are in iam_cost_cleanup.md. The project has no Scheduler job, notification channel, alert policy, Composer environment, GKE cluster, or always-on VM from this work. Small retained BigQuery, GCS, and Artifact Registry objects may still incur storage charges. Actual billing-account charges are unknown.

## Verified evidence

- Manual Cloud Workflows API-to-Gold run: 7e6faf3b-cb65-4347-9c79-ca64ac93cbdb; publication version 2.
- Automatic Scheduler to Workflow run: 5028cbfb-e5a2-4596-b663-6d0d964a8c56; publication version 3.
- Airflow 3.4.0 local Docker cloud integration run: manual__2026-11-12T09:17:10.037023+00:00; publication version 4.
- Isolated full-refresh versus incremental comparison: 3 rows in each relation; zero row differences.
- Exact Airflow manifest replay: 3 landing rows; zero duplicate grains; pointer remained version 4.
- Controlled failure notification: one external email confirmed by the user; pointer remained version 4.
- Refreshed Terraform plan after temporary resource cleanup: no changes.

## Primary references

- Open-Meteo: https://open-meteo.com/en/terms, https://open-meteo.com/en/licence, and https://open-meteo.com/en/docs/historical-weather-api
- Workflows and IAM: https://docs.cloud.google.com/workflows/docs/schedule-workflow, https://docs.cloud.google.com/workflows/docs/access-control, https://docs.cloud.google.com/iam/docs/conditions-resource-attributes
- Cloud pricing: https://cloud.google.com/run/pricing, https://cloud.google.com/bigquery/pricing, https://cloud.google.com/scheduler/pricing, and https://cloud.google.com/workflows/pricing
- Airflow 3: https://airflow.apache.org/docs/apache-airflow/3.4.0/public-airflow-interface.html and https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/tasks.html
