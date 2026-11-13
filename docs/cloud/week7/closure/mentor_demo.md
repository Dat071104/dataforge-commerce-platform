# Mentor walkthrough — 5 to 7 minutes

This is a live walkthrough script. Use the saved receipts for exact IDs and hashes; redact the notification destination and any browser account details.

| Time | Show | Explain |
|---|---|---|
| 0:00–0:45 | architecture_and_adr.md and the separate weather datasets | Mini3 is an independent observation domain. Week 5 order/payment controls and the accepted commerce Workflow were not changed. Workflows was used for the one timed GCP run; Airflow was a separate one-shot controller. |
| 0:45–1:30 | api_to_gold_e2e_receipt.json; GCS manifest and typed Parquet metadata | Open-Meteo ERA5 data for HCM, HN, and DN on 2026-11-05 used a seven-day settling delay. Show request ID, raw/typed hashes, exact manifest generation, source attribution, and immutable object path. |
| 1:30–2:15 | BigQuery weather_landing and exact replay section | Airflow loaded and reconciled 3 rows. Replaying the same manifest generation left 3 province/date grains and zero duplicates. The source is not joined to commerce financial metrics. |
| 2:15–3:00 | dbt weather model folder, schema tests, and published Gold view | Show staging, latest-generation Silver, weather Gold, source lineage, millimetres and degrees Celsius. The live dbt build and tests passed; incremental and full-refresh targets had three identical rows and zero differences. |
| 3:00–3:45 | scheduler_execution_receipt.json and Workflow execution receipt | Show the automatic 15:55 HCM trigger and successful execution 5028cbfb-e5a2-4596-b663-6d0d964a8c56. State clearly that the job was deleted after one firing and no schedule is active now. |
| 3:45–4:45 | Airflow integration DAG and airflow_integration_receipt.md | Walk through the real receipt sensor, GCS exact-generation validation, landing, post-load reconciliation, dbt build/test/publish, and Gold check. Airflow 3.4.0 ran in local one-shot Docker; the GCP data plane was live. The scheduler/UI were not hosted. |
| 4:45–5:30 | notification_delivery_receipt.md and controlled-failure ledger entry | Show the one controlled failure after dbt tests and before publish, the Monitoring incident, and the redacted user-confirmed email receipt. Point out that Gold stayed at version 4 and both the temporary channel and alert policy were deleted. |
| 5:30–6:15 | dbt_scd2_history_receipt.json | Show the synthetic CREATED, PROCESSING, and CANCELLED/tombstone versions, adjacent valid windows, one current row, no overlaps, and unchanged replay. State that it proves snapshot observation history, not all unseen business-effective changes. |
| 6:15–7:00 | iam_cost_cleanup.md and acceptance_matrix.md | Review bounded Cloud Run/BigQuery usage, small retained storage, no active Scheduler or alert channel, temporary IAM cleanup, and the remaining partial live fault probes. The independent controller and release decision are separate. |

## Evidence files

- Full API-to-Gold, full-refresh parity, exact replay, and negative probes: api_to_gold_e2e_receipt.json
- Automatic time-based Scheduler trigger: scheduler_execution_receipt.json
- Real Airflow integration: airflow_integration_receipt.md
- One delivered failure email: notification_delivery_receipt.md
- Isolated SCD2 history: dbt_scd2_history_receipt.json
- Cost, IAM, and cleanup: iam_cost_cleanup.md
- Requirement status and limitations: acceptance_matrix.md

Do not describe the slice as real-time or production-scale. It is a bounded learning workload with three locations and one historical observation date.
