# Evidence Index

This index points from each syllabus item to the code, a safe validation command, the retained evidence, and the boundary of what that evidence proves. Live receipts are historical; they do not mean a scheduler, alert, or cloud job is still active.

**Status vocabulary:** `MET` = the named bounded requirement has evidence; `PARTIAL` = a stated portion remains unverified; `NOT_RUN` = no evidence is claimed; `MENTOR_CONFIRMATION_PENDING` = the mentor checkpoint has not been independently documented.

## Weeks 1–3 · foundations and Mini-projects 1–2

| Requirement | Code / runnable validation | Recorded evidence | Status and explanation |
|---|---|---|---|
| Week 1 shell, Git, and public-CSV exercise | [Fetch/validate/gzip script](../scripts/week1_fetch_csv.sh), [usage guide](../scripts/week1/README.md), and [loopback fixture tests](../tests/week1/test_week1_fetch_csv.py); .venv/Scripts/python.exe -m pytest -q tests/week1 (16 passed). | [Syllabus coverage](SYLLABUS_COVERAGE.md); draft P7.5 [PR #8](https://github.com/Dat071104/dataforge-commerce-platform/pull/8). | **PARTIAL:** code, fixture tests, and hosted PR CI pass. The work is in draft PR #8 and is not merged; no historical Week 1 PR is claimed. |
| Week 2 Python and Mini-project 1 API-to-Parquet | [Weather adapter](../src/dataforge/weather.py), [unit tests](../tests/test_weather.py); `.\.venv\Scripts\python.exe -m pytest -q tests/test_weather.py`. | [Source provenance](source_provenance.md); [Mini3 API contract](cloud/week7/closure/mini3_api_contract.md) reuses the adapter. | **MET for the bounded adapter.** Provider use remains subject to Open-Meteo attribution and non-commercial terms; no recurring service is claimed. |
| Week 3 SQL, dimensional modeling, and Mini-project 2 | [SQL schema](../sql/schema/001_init.sql), [mart build](../sql/build/010_marts.sql), [10 analyses](../sql/analysis/), [Power BI PBIP](../dashboards/P5/DataForge/DataForge.pbip). | [Metric contract](metric_contract.md); [P6.2 release](releases/v1.0-local.md); screenshots are existing files under [v1.0-local screenshots](screenshots/v1.0-local/). | **MET for the bounded synthetic portfolio.** Separate item/payment/return/shipment grains; no accounting claim. |
| Week 3 SQL test and mentor code review | Same Mini1/Mini2 sources; safe local regression command below. | [P6.2 release record](releases/v1.0-local.md). | **MENTOR_CONFIRMATION_PENDING.** The repo does not claim that a timed mentor checkpoint occurred. |

## Weeks 4–7 · cloud, batch, Spark, and orchestration

| Requirement | Code / runnable validation | Recorded evidence | Status and explanation |
|---|---|---|---|
| Week 4 cloud platform, IaC, Medallion concepts, IAM and FinOps | [Cloud adapters/contracts](../src/dataforge/cloud/); offline full tests. Do not use a local unit test as proof of a live transfer. | [Week 4 acceptance](cloud/week4_acceptance.md); [release report](cloud/release_report.md); [transfer receipts](cloud/evidence/transfers/); [reruns](cloud/evidence/reruns/). | **MET for the user-reported GCP substitution.** The original syllabus names Azure/Fabric. No Azure service-equivalence claim; no budget alert or settled bill is claimed. |
| Week 5 incremental ETL, replay, backfill and recovery | [Journal/source](../src/dataforge/incremental/source.py), [batch runtime](../src/dataforge/incremental/batch.py), [Cloud Run consumer](../cloud/jobs/week5/consumer.py); `.\.venv\Scripts\python.exe -m pytest -q tests/incremental`. | [Week 5 acceptance](cloud/week5/acceptance_matrix.md); [final report](cloud/week5/final_report.md); scenario ledger/receipts under [Week 5 evidence](cloud/week5/). | **MET for the synthetic change-journal batch.** Uses sequence IDs, not a claim of CDC/streaming. The 100K snapshot/MERGE test showed equal billed bytes. |
| Week 6 local Spark | [Spark lab](../labs/spark_nyc_taxi/); `.\labs\spark_nyc_taxi\ci.ps1` runs the fixture CI when Docker is available. | [Final report](cloud/week6/final_report.md); [benchmark](cloud/week6/benchmark.md); [validation receipt](cloud/week6/validation_receipt.md). | **MET for local Spark.** 13.07M input rows and the measured broadcast join was slower. |
| Week 6 managed Spark | Same lab and local oracle can serve as a future comparison; no managed job command is provided. | [Acceptance matrix](cloud/week6/acceptance_matrix.md). | **NOT_RUN.** No managed batch was authorized or executed. |
| Week 7 commerce dbt, tests, orchestration and failure recovery | [dbt project](../dbt/dataforge/), [Week 7 Workflows](../cloud/workflows/week7_workflow.yaml), [publication macro](../dbt/dataforge/macros/week7_publication.sql), [runner](../scripts/week7_run_workflow.py). Offline dbt parse uses `.\dbt\dataforge\.venv\Scripts\dbt.exe parse --project-dir .\dbt\dataforge --profiles-dir .\dbt\dataforge --target offline`. | [Week 7 acceptance](cloud/week7/acceptance_matrix.md); [final report](cloud/week7/final_report.md); [recovery evidence](cloud/week7/failure_recovery.md). | **MET for the bounded Week 5 orders/payment simulator.** Ten live failure drills and 51 dbt tests were recorded; not all Week 4 streams feed this path. |
| Week 7 Airflow / Mini-project 3 | [Airflow reference](../labs/airflow_reference/); [Mini3 source job](../cloud/jobs/week7_weather/weather_job.py); [weather models](../dbt/dataforge/models/weather/); [Mini3 tests](../tests/mini3_api/). Pure contract checks: `.\.venv\Scripts\python.exe -m pytest -q labs/airflow_reference/tests/test_week7_weather_logic.py`. Pinned Airflow suite: `docker compose --file labs/airflow_reference/compose.yaml run --rm airflow-reference-test`. | [API-to-Gold receipt](cloud/week7/closure/api_to_gold_e2e_receipt.json); [Airflow integration record](cloud/week7/closure/airflow_integration_receipt.md); [P7.5 Airflow closure](cloud/week7/closure/p75_airflow_correctness.md). | **PARTIAL overall.** The historical one-off Airflow run and Workflows firing are real. Airflow was local Docker, not hosted; the prior sensor followed a blocking Cloud Run wait and did not demonstrate asynchronous waiting. The earlier package-level Docker command was not run while Docker was unavailable; later the no-egress scheduler harness passed locally and on exact-head Linux CI, proving the revised task's native retry transition. |
| Week 7 SCD2, publication safety, and alerts | [SCD2 proof](cloud/week7/closure/dbt_scd2_history_receipt.json); [weather publication macro](../dbt/dataforge/macros/weather_mini3_publication.sql); [one-time delivery receipt](cloud/week7/closure/notification_delivery_receipt.md). | [P7.4.1 matrix](cloud/week7/closure/acceptance_matrix.md); [P7.5 failure contract](cloud/week7/closure/p75_airflow_correctness.md). | **PARTIAL overall.** The synthetic snapshot had three versions; one controlled email was confirmed and its temporary policy removed. No recurring alert or current external Airflow notifier is active. |

## P7.5 closure and current validation

| Gate | Command / evidence | Status and limitation |
|---|---|---|
| Airflow request, authorization, retry classifier, receipt validation | `.\.venv\Scripts\python.exe -m pytest -q labs/airflow_reference/tests/test_week7_weather_logic.py` | **PASS**: 13 tests / 49 subtests, per [closure report](cloud/week7/closure/p75_airflow_correctness.md). |
| Full offline Python regression | `$env:RUN_POSTGRES_TESTS='0'; .\.venv\Scripts\python.exe -m pytest -q tests dashboards/P5/tests` | **PASS**: 210 passed, 7 expected gated skips after adding Week 1 fixture tests. This is not a live cloud test. |
| Ruff, compile, pip, dbt parse/selector, PowerShell parser | See the exact commands in [P7.5 Airflow closure](cloud/week7/closure/p75_airflow_correctness.md). | **PASS** for recorded local checks. |
| Airflow 3.4 package-level DAG import and contract suite | In an isolated Python 3.11 venv with `apache-airflow==3.4.0`, set `PYTHONPATH` to `labs/airflow_reference/dags`, then run `python -m unittest discover -s labs/airflow_reference/tests -p 'test_*.py' -v`. | **PASS WITH PLATFORM LIMIT**: 32 tests passed. Airflow warns that native Windows is unsupported. At that earlier snapshot the pinned Linux Docker image was unavailable; CLI DB migration/DagRun cannot run on native Windows (`fcntl` is missing). Later no-egress Linux scheduler evidence is recorded in the P7.5 Airflow closure. |
| Unified P7.5 Prompt B, final independent review, exact-head hosted CI, merge | [Persistent execution checklist](cloud/week7/closure/p75_execution_checklist.md); [PR #8](https://github.com/Dat071104/dataforge-commerce-platform/pull/8). | **PARTIAL — merge pending:** the one independent controller returned `P75_CONDITIONAL_GO`; its Linux Airflow retry condition is satisfied by the real scheduler harness on code head `4562d3f` (Week 7 PR run `43424336220`, job `131881909659`, artifact `14035891377`). Exact-head base PR run `43424335661`, Week 7 push run `43424323389`, and base push run `43424323374` also succeeded. PR #8 remains draft; merge, main CI, and local sync are not yet complete. |

## Safe local regression command

From the repository root, with the project virtual environment configured:

```powershell
$env:RUN_POSTGRES_TESTS = '0'
.\.venv\Scripts\python.exe -m pytest -q tests dashboards/P5/tests
.\.venv\Scripts\ruff.exe check src tests scripts dashboards/P5
.\.venv\Scripts\python.exe -m compileall -q src tests scripts dashboards/P5
.\.venv\Scripts\python.exe -m pip check
```

Integration tests requiring PostgreSQL use the separate opt-in flag and disposable databases. Cloud commands that write to GCP are intentionally excluded from this index.
