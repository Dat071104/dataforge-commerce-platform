# Demo acceptance checklist

This checklist is for presenting retained evidence. It does not create cloud evidence or an active service.

## Before the session

- [ ] Read the current integrator checklist and remote PR/CI state. The snapshot in the docs is historical.
- [ ] Check local branch and files with <code>git status --short --branch</code> and <code>git log --oneline -8</code>.
- [ ] Open the [README](../../../README.md), [architecture diagram](../../architecture/dataforge_overview.drawio), [canonical coverage](../../SYLLABUS_COVERAGE.md), and [evidence index](../../EVIDENCE_INDEX.md).
- [ ] Review [engineering decisions](../../ENGINEERING_DECISIONS.md); first-person author review remains pending.
- [ ] Open retained Power BI images under [v1.0-local screenshots](../../screenshots/v1.0-local/).
- [ ] Keep the [P7.4.1 receipts](../../cloud/week7/closure/) and [P7.5 closure](../../cloud/week7/closure/p75_airflow_correctness.md) available as static evidence.
- [ ] Keep the [cost table](cost_table.md) open and state the project billed total and current VM inventory are unknown.
- [ ] Do not start a cloud job, Terraform operation, alert test, schedule, or billed BigQuery query for the demo.

## Demonstration readiness

| Screen / artifact | Evidence source | Accurate claim |
|---|---|---|
| Portfolio and domains | [README](../../../README.md), [diagram](../../architecture/dataforge_overview.drawio) | Separate local commerce, bounded cloud, local Spark, and weather workloads. |
| Local commerce | [P6.2 release](../../releases/v1.0-local.md), existing PBIP screenshots | Synthetic data and separate fact grains; fulfilled sales is a proxy. |
| Week 4/5 cloud evidence | [Week 4 acceptance](../../cloud/week4_acceptance.md), [Week 5 matrix](../../cloud/week5/acceptance_matrix.md) | Retained bounded GCS/BigQuery transfer and change-journal recovery scenarios. |
| Week 6 Spark | [Benchmark](../../cloud/week6/benchmark.md) | Local measured result; broadcast was slower by median; managed Spark was not run. |
| Week 7 publication | [Acceptance matrix](../../cloud/week7/acceptance_matrix.md), [recovery report](../../cloud/week7/failure_recovery.md) | Synthetic candidate validation and guarded publication evidence. |
| Mini3 weather | [API-to-Gold receipt](../../cloud/week7/closure/api_to_gold_e2e_receipt.json) | One settled date, three locations, three rows, weather-only Gold. |
| Airflow | [Historical integration](../../cloud/week7/closure/airflow_integration_receipt.md), [P7.5 closure](../../cloud/week7/closure/p75_airflow_correctness.md) | One earlier local-Docker integration and no-egress code harness; no hosted scheduler. Check latest combined-head CI before describing release status. |
| SCD2 and notification | [SCD2 receipt](../../cloud/week7/closure/dbt_scd2_history_receipt.json), [redacted notification receipt](../../cloud/week7/closure/notification_delivery_receipt.md) | Three synthetic observed versions and one historical controlled delivery, then temporary policy/channel removal. |
| Cost | [Cost table](cost_table.md), [cost and cleanup report](../../cloud/week7/closure/iam_cost_cleanup.md) | Gross estimate only; total billed spend and current inventory are unknown. |

## Do not claim

- [ ] Cloud Scheduler or an Airflow schedule is active now.
- [ ] Airflow is hosted in GCP or has run unattended for multiple days.
- [ ] The old Airflow sensor provided an asynchronous wait.
- [ ] A recurring email/Slack alert is active or the old approval covers another notification.
- [ ] The project has a settled USD 0 bill, a complete worst-case cost bound, or a hard spending cap.
- [ ] A managed Spark batch was run.
- [ ] A mentor presentation, signed approval, course completion, or certificate occurred without direct evidence.
- [ ] A screenshot was captured if only a JSON or Markdown receipt exists.
- [ ] The AI-assisted decision draft is a completed author reflection before the author reviews it.

## Questions for the mentor

- Does the hybrid local-Airflow/GCP-data-plane evidence satisfy the Week 7 checkpoint?
- Does the bounded local Spark result satisfy the Week 6 implementation outcome, or is a separate managed run required?
- Is a brief HR fact/dimension use-case mapping sufficient for the cross-cutting domain goal?
- What human review or course evidence is required for the remaining syllabus rows?