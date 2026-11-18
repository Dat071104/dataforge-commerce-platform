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

The prior integration baseline remains PR #9 at 9bca18c and PR #13 at f4d340f; their historical merge-SHA CI receipts are listed below.

As of 2026-11-18 14:06 +07, the Week 7 execution checklist is complete through S11 on main baseline 6b256f2. S10 Airflow 3 screenshots are retained under cloud/week7/evidence/. S11 paused the DAG, destroyed the temporary Airflow VM lane, removed its C8 secrets/A2/A5 grants and the C14/D1 execution-reader role/bindings, and verified 0 Week 7 VM, disk, static IP, and IAP firewall. C2/C3/C10/C11 and shared weather job/operation roles remain. S12 evidence PR, S13 release, and S14 final report are pending.

These are dated live observations, not a settled billing export or a claim that every project resource is gone.

## By domain

| Domain | Source / local evidence | CI or hosted evidence | Historical live / observed evidence | Current limit |
|---|---|---|---|---|
| Local commerce ingestion and metrics | [Architecture](architecture.md), [metric contract](metric_contract.md), [SQL schema and analyses](../sql/), [ingestion tests](../tests/) | Base regression and project checks are defined in [CI workflow](../.github/workflows/ci.yml); post-C merge-SHA base run [43569675543](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43569675543) passed. | [P6.2 release record](releases/v1.0-local.md) and its retained local screenshots. | All business data is synthetic; fulfilled sales is a proxy, not accounting revenue. |
| Week 1 CSV and Linux labs | [CSV fetch script](../scripts/week1_fetch_csv.sh), [fixture tests](../tests/week1/test_week1_fetch_csv.py), [Lane D Linux lab at merged PR head](https://github.com/Dat071104/dataforge-commerce-platform/blob/3d3b4e47c015fe20b8f1e1e987bdca7388c48fc0/labs/learning/linux_cli_lab.sh). | PR #8 and PR #13 are merged. The earlier D base CI [43569053596](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43569053596) passed D4; the merged D exact-head checks also passed in run [43584910006](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43584910006). | Test fixtures run locally/CI; no SSH host or recurring cron was used. | D4 is a safe fixture lab, not a live cron/SSH operation. |
| Week 4 GCP setup and transfer | [Week 4 acceptance](cloud/week4_acceptance.md), [IAM matrix](cloud/iam_matrix.md), [Terraform](../cloud/terraform/), and [syllabus mapping](cloud/syllabus_mapping.md). | Historical static validation and earlier CI remain separate from live inventory. | S11 R1 reverified the Week 7 VM lane after teardown and retained C2/C3/C10/C11; see [S11 inventory summary](cloud/week7/evidence/s11-teardown-summary.md). | This was a bounded Week 7 lane inventory, not a full audit of all historical Week 4 resources. |
| Week 5 change journal and recovery | [Source journal](../src/dataforge/incremental/source.py), [batch runtime](../src/dataforge/incremental/batch.py), [acceptance matrix](cloud/week5/acceptance_matrix.md), [recovery reports](cloud/week5/failure_recovery.md). | Main CI is evidence for code checks only. | Retained batch, incident, manifest, and BigQuery job receipts under [Week 5 evidence](cloud/week5/). | The simulator is a bounded synthetic change journal, not generic CDC or streaming. |
| Week 6 Spark | [Local lab](../labs/spark_nyc_taxi/), [benchmark](cloud/week6/benchmark.md), [runtime](cloud/week6/runtime_and_environment.md), and [S7-R result](cloud/week6/evidence/c7-s7-a4-result-20261118.md). | Local CI and the merged Lane B checks validate the fixture-based code path. | The local workload processed 13,069,067 rows; the separately authorized S7-R Dataproc a4 batch succeeded with exact Oracle match. Sanitized driver/history and cost receipts are in [S7-R evidence](cloud/week6/evidence/c7-s7-a4-result-20261118.md), [cost](cloud/week6/evidence/c7-s7-a4-cost-20261118.log), and [driver/history summary](cloud/week6/evidence/c7-s7-a4-driver-history-summary.md). | S7-R compute+shuffle estimate USD0.095; GCS/network invoice unavailable; no persistent cluster or Spark UI screenshot is claimed. |
| Week 7 dbt and publication | [dbt project](../dbt/dataforge/), [model contract](cloud/week7/dbt_model_contract.md), [acceptance matrix](cloud/week7/acceptance_matrix.md), [S4 NO_OP RCA](cloud/week7/evidence/s4-noop-oct30-rca-20261118.md). | Historical merge-SHA base/Week-7 CI receipts remain linked from the earlier baseline. | E2 deployed weather-dbt digest 3719ed35; live dbt build/tests PASS=49/49. S4 published 21 rows for Oct25–31; replay of the latest S6 publication returned NO_OP without Gold/version-row change. | The publication guard intentionally rejects reusing an older run ID against a changed cumulative snapshot; see the RCA. Invoice unavailable. |
| Week 7 Airflow / P7.5 | [Airflow DAG](../labs/airflow_reference/dags/dataforge_week7_weather_cloud.py), [harness](../labs/airflow_reference/harness/), [P7.5 closure](cloud/week7/closure/p75_airflow_correctness.md), [S10 UI manifest](cloud/week7/evidence/s10-airflow-ui-capture-20261118.md). | PR #11/#13 no-egress scheduler scenarios and their prior merge-SHA receipts are historical CI evidence. | Natural scheduled__2026-11-18T02:00:00+00:00 succeeded 16/16; S6 retry try1 made no Cloud Run POST and try2 succeeded with the same invocation ID. Five UI screenshots show Grid, Graph, task log, and both retry tries. | The temporary Airflow VM is now destroyed and DAG paused; no current hosted or recurring Airflow is claimed. |
| Mini3 weather | [API contract](cloud/week7/closure/mini3_api_contract.md), [weather dbt lineage](cloud/week7/model_lineage.md), [reconciliation](cloud/week7/closure/reconciliation_and_recovery.md), [S10 captures](cloud/week7/evidence/s10-airflow-ui-capture-20261118.md). | CI validates source/contracts; it does not replace live receipts. | S3 canary, S4 Oct25–31 backfill (21 Gold rows, 0 duplicate grains), S6 retry on Nov1 (+3 rows), and S9 natural scheduled run are recorded; final Gold was 30 rows/10 dates/0 duplicates. | Only one natural scheduled run was observed; the VM is torn down, so daily hosted service is not claimed. |
| Week 7 SCD2 and notification | [dbt model contract](cloud/week7/dbt_model_contract.md), [Airflow failure contract](cloud/week7/closure/p75_airflow_correctness.md). | No-egress CI covers failure/deadline behavior; it is separate from Monitoring. | Three historical synthetic SCD2 versions are retained. Monitoring recorded 8 PIPELINE_FAILED and 5 PIPELINE_DEADLINE_MISSED incidents; 2 receipts are confirmed, 11 unconfirmed; deliberate drills remain 0/2. | C3 alert policies remain; no claim that every incident email was received. |
| Week 1–7 portfolio and demo | [Canonical syllabus coverage](SYLLABUS_COVERAGE.md), [engineering decisions](ENGINEERING_DECISIONS.md), [demo walkthrough](demo/week7_checkpoint/walkthrough.md), [cost table](demo/week7_checkpoint/cost_table.md). | This S12 branch updates evidence and narrow Terraform desired-state reconciliation; CI is pending. | S10 screenshots and S11 R1 summary are retained under cloud/week7/evidence/. | No mentor/team presentation or feedback is recorded; W7-08 remains pending. |

## Costs and live-resource boundary

The S11 R1 inventory verifies 0 Week 7 VM, disk, static IP, or IAP firewall. The Airflow DAG is paused; the VM lane and three C8 secrets are removed. C14/D1 execution-reader role/bindings are absent. C2 budget, C3 alert policies, C10 Terraform-state bucket, C11 Artifact Registry cleanup policy, weather Cloud Run jobs, BigQuery/GCS data, and shared job-runner/operation-reader roles remain.

The conservative gross phase estimate remains approximately USD 12.893, below the USD 16 stop line and USD 20 cap. It includes the C4 120-hour envelope of USD 6.166 and the C7 three-attempt bound; the VM actually ran about 42h55m before teardown. The completed S7-R a4 batch measured USD 0.095 compute plus shuffle; the measured S4/B2 window was about USD 0.101 Cloud Run plus BigQuery. The total settled project bill, free-tier use, and GCS/network charges are unknown; this is not an invoice.

The older [P7.4.1 IAM/cost/cleanup report](cloud/week7/closure/iam_cost_cleanup.md) is a historical snapshot. For the current post-S11 inventory use [S11 teardown summary](cloud/week7/evidence/s11-teardown-summary.md) and the [final cost table](demo/week7_checkpoint/cost_table.md).

## Safe local regression reference

From the repository root, with the project's configured environment, the baseline offline regression command is:

~~~powershell
$env:RUN_POSTGRES_TESTS = '0'
.\.venv\Scripts\python.exe -m pytest -q tests dashboards/P5/tests
.\.venv\Scripts\ruff.exe check src tests scripts dashboards/P5
.\.venv\Scripts\python.exe -m compileall -q src tests scripts dashboards/P5
~~~

This is a command reference, not evidence that Lane E ran the full suite. Cloud writes, paid queries, Terraform apply, live scheduler starts, and notification sends are not part of this index.
