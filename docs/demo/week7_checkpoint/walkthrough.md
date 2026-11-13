# Mentor walkthrough · 5–7 minutes

This is a prepared walkthrough, not a record that a presentation or mentor sign-off occurred. Use the repository receipts as the source of truth. Do not deploy, execute cloud jobs, send alerts, or run billed BigQuery queries during the demo.

| Time | Screen / file | Script |
|---|---|---|
| 0:00–0:45 | [README](../../../README.md) and [editable architecture](../../architecture/dataforge_overview.drawio) | “DataForge is a set of small, independently verified data workloads. The local commerce facts, Week 4/5/7 GCP path, local Spark lab, and weather Mini3 have separate grains and boundaries. This is an educational portfolio, not a production service.” |
| 0:45–1:35 | Existing [Power BI screenshots](../../screenshots/v1.0-local/) and [metric contract](../../metric_contract.md) | “The local baseline has 3,000 synthetic orders. Items, payments, returns, and shipments remain separate facts. The report has 10 tables, 15 relationships, 3 pages, and 33 visuals. Fulfilled sales is a proxy, not recognized revenue.” |
| 1:35–2:25 | [Week 4 acceptance](../../cloud/week4_acceptance.md) and [Week 5 acceptance](../../cloud/week5/acceptance_matrix.md) | “Week 4 moved 11 synthetic sources through private GCS to typed BigQuery staging and verified safe replays. Week 5 is a distinct change-journal path: sequence-based events, immutable manifests, a bounded Cloud Run consumer, and a transactional checkpoint. The 100K-row comparison billed equal bytes for snapshot and incremental MERGE.” |
| 2:25–3:15 | [Week 7 recovery matrix](../../cloud/week7/acceptance_matrix.md) and [failure recovery](../../cloud/week7/failure_recovery.md) | “Week 7 adds dbt candidate checks and a guarded publication pointer. Ten live failure drills are recorded. A failed candidate does not replace published Gold; exact-manifest replay is the recovery path. These five orders are a bounded synthetic simulator.” |
| 3:15–4:00 | [Spark benchmark](../../cloud/week6/benchmark.md) | “The separate local Spark lab reconciled 13.07 million taxi rows. Broadcast cut shuffle bytes but ran 19.8% slower by median. The result shows why I measure the plan and runtime rather than assume an optimization helped.” |
| 4:00–5:00 | [Mini3 API-to-Gold receipt](../../cloud/week7/closure/api_to_gold_e2e_receipt.json), [SCD2 receipt](../../cloud/week7/closure/dbt_scd2_history_receipt.json), and [one-time notification receipt](../../cloud/week7/closure/notification_delivery_receipt.md) | “Mini3 is a separate Open-Meteo weather domain. The observed example is one settled date for HCM, HN, and DN: three rows with manifest identity, exact generation, and a weather-only Gold pointer. A synthetic dbt snapshot recorded three versions. One controlled failure notification was confirmed; the temporary policy was removed.” |
| 5:00–6:00 | [Airflow integration receipt](../../cloud/week7/closure/airflow_integration_receipt.md) and [P7.5 Airflow closure](../../cloud/week7/closure/p75_airflow_correctness.md) | “Airflow 3.4 ran once in local Docker against the real GCP data plane; Airflow itself was not hosted. The older receipt says it used a reschedule sensor, but the task waited synchronously for Cloud Run before that sensor ran. P7.5 removes the redundant sensor, fixes the empty-conf scheduled contract, separates cloud authorization, and makes failure handling explicit. A real async sensor wait and an unattended Airflow schedule are still not demonstrated.” |
| 6:00–6:45 | [Syllabus coverage](../../SYLLABUS_COVERAGE.md) and [execution checklist](../../cloud/week7/closure/p75_execution_checklist.md) | “Managed Spark, hosted Airflow, recurring alerts, settled billing, Week 8+, and course certificates remain unclaimed. Check the P7.5 execution checklist and GitHub PR/main history for the exact controller, hosted CI, and merge state. This code closure does not demonstrate a live scheduler.” |

## Evidence to open if asked

- Local baseline: [P6.2 release record](../../releases/v1.0-local.md).
- Cloud setup and project boundary: [target metadata](../../cloud/target.json) and [Week 4 matrix](../../cloud/week4_acceptance.md).
- Incremental recovery: [Week 5 matrix](../../cloud/week5/acceptance_matrix.md).
- Week 7 publication and cost: [report](../../cloud/week7/final_report.md), [cost and performance](../../cloud/week7/performance_and_cost.md).
- Mini3 exact manifest, scheduler, and alert receipts: [closure directory](../../cloud/week7/closure/).

If a screen is unavailable, show the static repository evidence above. Do not recreate or edit a receipt for presentation. Authentic screenshot opportunities and redactions are listed in [screenshot plan](screenshot_plan.md).
