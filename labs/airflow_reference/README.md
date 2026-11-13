# Airflow reference and Mini3 integration

The lab keeps the offline Airflow reference DAG and adds a separate, opt-in Mini-project 3 cloud integration DAG. The fixture remains isolated. A historical one-shot integration ran Airflow locally in Docker while its data-plane tasks used the approved GCP resources. P7.5's DAG contract tests passed with the Airflow 3.4.0 Python 3.11 package in an isolated Windows virtual environment; the pinned Linux container and CLI DagRun were not run because Docker was unavailable, and Airflow warns that native Windows is unsupported.

## Offline fixture DAG

The fixture DAG models stages and failure rules using Apache Airflow 3.4.0 and a checked-in synthetic Silver fixture:

```text
resolve manifest / NO_NEW_BATCH
  → consume Silver fixture
  → local dbt-stage contract calculation
  → quality gate
  → publication fence
  → run metadata receipt
```

The default path is `NO_NEW_BATCH` and succeeds while preserving the previous publication. The `local_fixture` path validates one synthetic order with two separate payment rows. The transform is a small Python reference calculation; `dbt_execution` remains `NOT_RUN`. The publication fence never writes a table or pointer. Neither path accesses GCP, uses credentials, downloads data, sends notifications, or writes to the repository. Docker receives only this Airflow-reference directory as a read-only mount; it cannot read the repository's `.env` or Terraform state.

The failure hook writes only a redacted JSON log line (`dag_id`, `run_id`, `task_id`, `try_number`, and exception type). It has no email, webhook, or other external sink. A single retry is allowed for ordinary task errors; malformed run configuration raises Airflow's non-retryable `AirflowFailException`. The `retry_once` scenario injects one transient failure before any side effect and records `RECOVERED_AFTER_BOUNDED_RETRY`. The `invalid_mode` scenario checks that malformed input fails without retry and records the local-only alert hook.

## Run locally on Windows

Run from the DataForge repository root. Docker runs an isolated one-shot Airflow container with a temporary SQLite metadata database, a read-only workspace mount, and no container network:

```powershell
.\labs\airflow_reference\ci.ps1
.\labs\airflow_reference\ci.ps1 -Scenario local_fixture
.\labs\airflow_reference\ci.ps1 -Scenario retry_once
.\labs\airflow_reference\ci.ps1 -Scenario invalid_mode
```

The first run downloads the pinned official Airflow image if it is not already present. It runs the Airflow DAG contract tests, initializes the temporary metadata database, and executes one DagRun. The scenario commands use local-only run configuration; `invalid_mode` expects a task failure but the script passes only when the failure is non-retryable and the local alert hook ran. The Airflow CLI `dags test` command executes a single DagRun; it does not start a scheduler.

To inspect or change the DAG, edit `dags/dataforge_week7_reference.py`. Pure transformations and fixture checks are in `dags/dataforge_week7_logic.py`; the checked-in rows are in `fixtures/silver_snapshot.json`.

## Opt-in Mini-project 3 cloud integration

`dags/dataforge_week7_weather_cloud.py` is a distinct integration DAG. The historical one-shot Airflow 3.4.0 DagRun is recorded in `../cloud/week7/closure/airflow_integration_receipt.md`. That earlier implementation invoked the weather Cloud Run jobs, then checked the immutable GCS receipt with a sensor after the blocking Cloud Run operation had completed. It did not demonstrate asynchronous sensor waiting. The run loaded and reconciled BigQuery landing, ran weather dbt build/tests/publication, and verified the three-row Gold result using read-only mounted keyless ADC and a scoped Airflow service account. It did not use a static service-account key or start a persistent Airflow scheduler.

The current P7.5 DAG accepts validated `mode=scheduled` or `mode=manual` Params and derives scheduled observation dates from the fixed DagRun interval. Cloud access has a separate `DATAFORGE_WEATHER_CLOUD_ENABLED` switch that defaults OFF; the DAG is paused on creation. The launcher passes `mode=manual` and sets the opt-in only inside its container. Invoking it starts real Cloud Run jobs and can write GCS and BigQuery, so it must not be run without fresh, explicit authorization. The earlier impersonation grant was removed. The current DAG and launcher changes have not been exercised against GCP.

The runner requires an explicitly selected isolated ADC file and the approved Airflow caller identity. The one-time impersonation grant was removed after the demonstration, so rerunning the live integration requires a reviewed temporary grant and cleanup:

```powershell
. .\scripts\enter_dataforge_cloud.ps1
$env:DATAFORGE_AIRFLOW_ADC_FILE = Join-Path $env:CLOUDSDK_CONFIG 'application_default_credentials.json'
$env:DATAFORGE_AIRFLOW_IMPERSONATION_SERVICE_ACCOUNT = 'dataforge-week7-airflow@dataforge-p7-lab-d0f725.iam.gserviceaccount.com'
.\labs\airflow_reference\run_cloud_integration.ps1 -ObservationDate 2026-11-05
```

The runner uses `airflow dags test` for one DagRun; the integration DAG also checks that the GCP Scheduler job is paused or absent before starting. The current Airflow failure callback writes a redacted local log event only. It does not send email or create a Monitoring policy. The separate Cloud Monitoring receipt is historical evidence of one earlier controlled notification, not a current delivery path.

## Runtime and compatibility

- Pinned runtime: `apache/airflow:3.4.0-python3.11@sha256:be92e15d57c5be726fc39a91cd09cce8f7488483b67979e0fb74c1a2c7cfb4e2`.
- DAG authoring uses Airflow 3's public `airflow.sdk` TaskFlow interface and SDK exceptions.
- Airflow 3.4 documents Python 3.11 support and `airflow dags test`; see [Airflow prerequisites](https://airflow.apache.org/docs/apache-airflow/3.4.0/installation/prerequisites.html), [TaskFlow](https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/taskflow.html), and [DAG testing](https://airflow.apache.org/docs/apache-airflow/3.4.0/cli-and-env-variables-ref.html).
- The fixture task graph demonstrates dependencies and XCom metadata with small JSON objects. It intentionally does not invoke `dbt`, Cloud Run, BigQuery, Workflows, Cloud Scheduler, or Airflow's production notification integrations. Those calls exist only in the separate opt-in cloud integration DAG.

The offline fixture commands prove only local DAG import, contract behavior, and local-only retries. The separate integration run proves one real Airflow-to-GCP API-to-Gold execution; it does not prove a hosted Airflow service, recurring Airflow schedule, or Airflow notification channel.
