# Evidence index

This index separates repository artifacts, local verification, hosted CI, historical live observations, and human evidence. A link to code is not a run receipt; a historical live receipt is not a current resource inventory; and a prepared demo is not a mentor event.

## Evidence levels

| Label | What it proves | What it does not prove |
|---|---|---|
| **Source / local** | The implementation, fixture, local test, or offline harness recorded by the linked artifact. | A live GCP operation or a hosted service. |
| **CI** | A GitHub Actions job for the exact run/head linked below. | A successful later merge state unless the merge-SHA run is also linked. |
| **Historical live / observed** | A dated receipt from a real, bounded cloud operation or usage observation. | Current inventory, a recurring schedule, a settled invoice, or unrecorded work. |
| **Mentor / user-reported** | A direct user report or a recorded human event, if one exists. | A signed approval or presentation that has no retained record. |

## Current integration snapshot

This repository branch is based on main merge commit 95f89b4b8b9f6e8999d65d71edaa86ed8d423a0c. Lane C PR #11 is merged; the D-pack checklist records that its merge-SHA base and Week 7 main workflows passed.

At the last checklist update available while authoring these docs, Draft PR #9 for Lane B was at head 4f0c115. Base push/PR and Week 6 Spark checks passed. Week 7 push run 43570946116 failed the deadline scenario at job 132374987160 with a LocalExecutor task-state mismatch after seven reschedules; the PR Airflow job 132374995190 was still in progress. An RCA was recorded and no unchanged retry or fix was yet evidenced. Lane D head a7fe5b9 had passed base CI run 43569053596 (217 passed, 8 skipped) but still awaited rebase and integration after B. This is a point-in-time note; read the integrator's current checklist and remote CI before describing present status.

## By domain

| Domain | Source / local evidence | CI or hosted evidence | Historical live / observed evidence | Current limit |
|---|---|---|---|---|
| Local commerce ingestion and metrics | [Architecture](architecture.md), [metric contract](metric_contract.md), [SQL schema and analyses](../sql/), [ingestion tests](../tests/) | Base regression and project checks are defined in [CI workflow](../.github/workflows/ci.yml); post-C merge-SHA base run [43569675543](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43569675543) passed. | [P6.2 release record](releases/v1.0-local.md) and its retained local screenshots. | All business data is synthetic; fulfilled sales is a proxy, not accounting revenue. |
| Week 1 CSV and Linux labs | [CSV fetch script](../scripts/week1_fetch_csv.sh), [fixture tests](../tests/week1/test_week1_fetch_csv.py), [Lane D Linux lab at exact commit](https://github.com/Dat071104/dataforge-commerce-platform/blob/a7fe5b93f1b4cec2f1e70e7b39551a97f87b5b8f/labs/learning/linux_cli_lab.sh). | PR #8 is merged. D head base CI [43569053596](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43569053596) passed its Linux D4 test. | Test fixtures run locally/CI; no SSH host or recurring cron was used. | D learning work is not integrated at the snapshot above. |
| Week 4 GCP setup and transfer | [Week 4 acceptance](cloud/week4_acceptance.md), [IAM matrix](cloud/iam_matrix.md), [Terraform](../cloud/terraform/), [syllabus mapping](cloud/syllabus_mapping.md). | Static Terraform validation appears in Week 7 CI roots; see current PR run rather than treating it as a live plan. | Historical GCS/BigQuery receipts under [cloud evidence](cloud/evidence/), plus the later [Mini3 API-to-Gold receipt](cloud/week7/closure/api_to_gold_e2e_receipt.json). | Current inventory was not reverified in Lane E; checklist says cached gcloud credentials require refresh. |
| Week 5 change journal and recovery | [Source journal](../src/dataforge/incremental/source.py), [batch runtime](../src/dataforge/incremental/batch.py), [acceptance matrix](cloud/week5/acceptance_matrix.md), [recovery reports](cloud/week5/failure_recovery.md). | Main CI is evidence for code checks only. | Retained batch, incident, manifest, and BigQuery job receipts under [Week 5 evidence](cloud/week5/). | The simulator is a bounded synthetic change journal, not generic CDC or streaming. |
| Week 6 local Spark | [Spark lab](../labs/spark_nyc_taxi/), [benchmark](cloud/week6/benchmark.md), [runtime](cloud/week6/runtime_and_environment.md). | Week 6 Spark CI is part of Lane B PR #9 and passed at the last checklist snapshot. | Local Docker run processed 13,069,067 input rows; retained [final report](cloud/week6/final_report.md) records reconciliation and the measured negative broadcast result. | No managed Spark batch; no Spark UI screenshot is claimed. |
| Week 7 dbt and publication | [dbt project](../dbt/dataforge/), [model contract](cloud/week7/dbt_model_contract.md), [acceptance matrix](cloud/week7/acceptance_matrix.md), [recovery report](cloud/week7/failure_recovery.md). | PR #11 checks and its merge-SHA CI are linked in the integration snapshot. Lane B's exact combined-head run is still subject to the deadline failure recorded there. | Historical BigQuery/dbt run artifacts are linked from [Week 7 receipts](cloud/week7/). | The simulator contains five orders and six payment events; it is not a full Week 4 commerce feed. |
| Week 7 Airflow / P7.5 | [Airflow DAG](../labs/airflow_reference/dags/dataforge_week7_weather_cloud.py), [harness](../labs/airflow_reference/harness/), [P7.5 closure](cloud/week7/closure/p75_airflow_correctness.md). | PR #11 Week 7 run [43567547422](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43567547422), job [132364562675](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43567547422/job/132364562675), passed its six no-egress scheduler scenarios. The later Lane B combined-head run exposed the separate unresolved deadline mismatch noted above. | [Historical Airflow integration receipt](cloud/week7/closure/airflow_integration_receipt.md) records one local-Docker Airflow integration against GCP. | Airflow is not hosted; the revised DAG does not claim an asynchronous sensor wait; no recurring schedule is active. |
| Mini3 weather | [API contract](cloud/week7/closure/mini3_api_contract.md), [weather dbt lineage](cloud/week7/model_lineage.md), [reconciliation](cloud/week7/closure/reconciliation_and_recovery.md). | Code and test CI do not substitute for the retained cloud receipt. | [API-to-Gold receipt](cloud/week7/closure/api_to_gold_e2e_receipt.json): one settled date, HCM/HN/DN, three rows. [Scheduler receipt](cloud/week7/closure/scheduler_execution_receipt.json) records one historical firing. | The temporary scheduler job, alert policy, and notification channel were removed. No daily hosted Airflow or current external alert. |
| Week 7 SCD2 and notification | [dbt model contract](cloud/week7/dbt_model_contract.md), [Airflow failure contract](cloud/week7/closure/p75_airflow_correctness.md). | PR #11 harness verifies local failure/deadline event behavior only. | [SCD2 receipt](cloud/week7/closure/dbt_scd2_history_receipt.json) and [redacted delivery receipt](cloud/week7/closure/notification_delivery_receipt.md). | The snapshot is synthetic order-state history, not a customer dimension. The historical email was one controlled delivery; no current alert channel remains. |
| Week 1–7 portfolio and demo | [Canonical syllabus coverage](SYLLABUS_COVERAGE.md), [engineering decisions](ENGINEERING_DECISIONS.md), [course tracker](course_tracker.md), [demo walkthrough](demo/week7_checkpoint/walkthrough.md), [20-question defense](demo/week7_checkpoint/technical_defense.md). | The independent reviewer is not Lane E's author. The Lane E docs themselves are not hosted CI evidence. | No mentor presentation, final checkpoint, or course completion is recorded. | The decision log is first-person AI-assisted draft and requires AUTHOR REVIEW. |

## Costs and live-resource boundary

See the [demo cost table](demo/week7_checkpoint/cost_table.md) and [Week 7 cost/cleanup report](cloud/week7/closure/iam_cost_cleanup.md). The approximately USD 0.095 Mini3 Cloud Run/BigQuery figure is a historical gross list-rate estimate before free usage and unpriced services. The C4 and C7 numbers are planned estimates. The total settled project bill is unknown. No Lane D/E GCP activity occurred. Live VM/resource inventory is unknown at this snapshot; do not report a running-resource hourly rate without a current authorized receipt.

The accepted Week 7 cloud receipts describe a temporary Scheduler job, alert channel, and alert policy that were deleted after their demonstrations. Those historical cleanup records do not establish the state of unrelated project resources today.

## Safe local regression reference

From the repository root, with the project's configured environment, the baseline offline regression command is:

~~~powershell
$env:RUN_POSTGRES_TESTS = '0'
.\.venv\Scripts\python.exe -m pytest -q tests dashboards/P5/tests
.\.venv\Scripts\ruff.exe check src tests scripts dashboards/P5
.\.venv\Scripts\python.exe -m compileall -q src tests scripts dashboards/P5
~~~

This is a command reference, not evidence that Lane E ran the full suite. Cloud writes, paid queries, Terraform apply, live scheduler starts, and notification sends are not part of this index.