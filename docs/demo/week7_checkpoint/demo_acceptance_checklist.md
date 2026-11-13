# Demo acceptance checklist

This checklist helps present the accepted evidence without creating new cloud work or implying an active service.

## Before the session

- [ ] Check the branch and release state: <code>git status --short --branch</code>, <code>git log --oneline -8</code>.
- [ ] Open [README](../../../README.md), the editable [architecture diagram](../../architecture/dataforge_overview.drawio), and [syllabus coverage](../../SYLLABUS_COVERAGE.md).
- [ ] Open existing authentic local Power BI screenshots in [docs/screenshots/v1.0-local](../../screenshots/v1.0-local/).
- [ ] Keep the [P7.4.1 receipts](../../cloud/week7/closure/) and [P7.5 Airflow report](../../cloud/week7/closure/p75_airflow_correctness.md) available as static evidence.
- [ ] Check the current P7.5 execution checklist and GitHub PR/main history before describing its controller verdict, exact-head hosted CI, or merge state.
- [ ] Do not start a cloud job, Terraform apply, alert test, schedule, or billed BigQuery query for the demo.

## Safe read-only project inspection

If the approved local gcloud configuration is already authenticated, these commands only inspect metadata or list resources. Do not run <code>gcloud auth login</code> as part of the demo; if authentication is expired, use the static receipts instead.

~~~powershell
. .\scripts\enter_dataforge_cloud.ps1
$target = Get-Content -Raw .\docs\cloud\target.json | ConvertFrom-Json

gcloud --configuration=$target.configuration config get-value core/project
gcloud --configuration=$target.configuration --project=$target.project_id projects describe $target.project_id --format='value(projectId,projectNumber,lifecycleState)'
gcloud --configuration=$target.configuration --project=$target.project_id scheduler jobs list --location=$target.region
gcloud --configuration=$target.configuration --project=$target.project_id workflows executions list --workflow=dataforge-week7-weather-orchestrator --location=$target.region --limit=10
~~~

These are read/list calls only. They can still reveal project and execution identifiers; keep raw output private. A currently empty scheduler list is consistent with the retained cleanup receipt. Do not expect a recurring job or notification channel.

The P7.4.1 receipt provides a static alternative for the one-time observation: [scheduler_execution_receipt.json](../../cloud/week7/closure/scheduler_execution_receipt.json). The API-to-Gold run is in [api_to_gold_e2e_receipt.json](../../cloud/week7/closure/api_to_gold_e2e_receipt.json). The BigQuery result itself is historical; do not run a live query just to recreate it.

## Demonstration readiness

| Screen | Use this verified source | Accurate claim |
|---|---|---|
| Portfolio and domains | [README](../../../README.md), [diagram](../../architecture/dataforge_overview.drawio) | Four separate workloads with separate data contracts. |
| Local commerce model | [P6.2 release](../../releases/v1.0-local.md), existing PBIP screenshots | Synthetic data, declared fact grains, local Power BI report. |
| Week 4/5 cloud evidence | [Week 4](../../cloud/week4_acceptance.md), [Week 5](../../cloud/week5/acceptance_matrix.md) | Bounded object-to-BigQuery and incremental checkpoint scenarios. |
| Week 6 Spark | [Benchmark](../../cloud/week6/benchmark.md) | Local measured result; broadcast strategy was slower. |
| Week 7 quality/recovery | [Acceptance matrix](../../cloud/week7/acceptance_matrix.md), [recovery](../../cloud/week7/failure_recovery.md) | Ten live failure drills against the isolated synthetic simulator. |
| Mini3 weather | [API-to-Gold receipt](../../cloud/week7/closure/api_to_gold_e2e_receipt.json) | One date, three locations, three rows, weather-only Gold. |
| Airflow | [Historical integration receipt](../../cloud/week7/closure/airflow_integration_receipt.md), [P7.5 fix report](../../cloud/week7/closure/p75_airflow_correctness.md) | One local-Docker integration; no hosted scheduler. The old receipt sensor did not provide a genuine async wait. |
| SCD2 and alert | [SCD2 receipt](../../cloud/week7/closure/dbt_scd2_history_receipt.json), [notification receipt](../../cloud/week7/closure/notification_delivery_receipt.md) | Three synthetic versions; one controlled delivery confirmed, then policy/channel removed. |
| Cost | [Cost and cleanup report](../../cloud/week7/closure/iam_cost_cleanup.md) | Gross usage estimate only; settled bill and account-wide credits are unknown. |

## Do not claim

- [ ] The GCP Scheduler is active now; the accepted one-time job was deleted.
- [ ] Airflow is hosted in GCP or has run for multiple days.
- [ ] The historical Airflow sensor waited asynchronously.
- [ ] A recurring email/Slack alert is active, or the prior one-time approval covers a new notification.
- [ ] The project has a settled $0 bill or a hard spending cap.
- [ ] Managed Spark, Week 8 Kafka, Week 9 Mini4, or Weeks 10–12 AI work are complete.
- [ ] A mentor presentation, signed approval, course completion, or certificate occurred without direct evidence.
- [ ] A screenshot was captured if only a JSON/Markdown receipt exists.

## Accept or defer

- [ ] If mentor requests a hosted scheduler, recurring alert, managed Spark batch, or budget, record exact target, scope, recipient/cadence where applicable, and cost ceiling in a separate approval request before any write.
- [ ] If the mentor accepts the local-first/hybrid evidence, keep the remaining cloud extensions as optional rather than building idle infrastructure.
