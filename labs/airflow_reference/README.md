# Airflow reference and Mini3 integration

The lab keeps the offline Airflow reference DAG and adds a separate, opt-in Mini-project 3 cloud integration DAG. The fixture remains isolated. A historical one-shot integration ran Airflow locally in Docker while its data-plane tasks used the approved GCP resources. The P7.5 package-level Airflow 3.4.0 DAG tests pass in an isolated Python 3.11 environment; native Windows CLI migration remains unsupported because `fcntl` is unavailable. After Docker Desktop was started (H6), the pinned Linux no-egress scheduler harness ran locally. These scheduler checks fake only the authorized I/O seam and do not claim a new live GCP run.

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

The current P7.5 DAG accepts validated `mode=scheduled` or `mode=manual` Params and derives scheduled observation dates from the fixed DagRun interval. Cloud access has a separate `DATAFORGE_WEATHER_CLOUD_ENABLED` switch that defaults OFF; the DAG is paused on creation. The launcher passes `mode=manual` and sets the opt-in only inside its container. Invoking it starts real Cloud Run jobs and can write GCS and BigQuery, so it must not be run without the authorized scope and cost controls. The current code and launcher have not been exercised against GCP.

Cloud authentication has two explicit keyless modes. The default `impersonated_adc` mode requires the isolated ADC file and `DATAFORGE_AIRFLOW_IMPERSONATION_SERVICE_ACCOUNT`; it is used by the controlled local launcher. The hosted VM uses `DATAFORGE_AIRFLOW_IDENTITY_MODE=attached_service_account` and `DATAFORGE_AIRFLOW_ATTACHED_SERVICE_ACCOUNT`; the code requires no `GOOGLE_APPLICATION_CREDENTIALS`, loads ADC through `google.auth.default()`, refreshes from the VM metadata server, and verifies the resulting principal exactly matches the approved attached account. Neither mode accepts a static service-account key. The local tests mock the metadata credentials; no live GCP call was made. The earlier one-time impersonation grant was removed after the demonstration, so rerunning the local live integration requires a reviewed temporary grant and cleanup:

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

## Production-task scheduler retry harness

Run `.\labs\airflow_reference\ci.ps1 -Scenario scheduler_harness` to run the production Mini3 tasks under the pinned Airflow 3.4 scheduler. The harness DAG imports the real DAG factory and keeps the ingest submitter, reschedule sensor, and prerequisites; its backfill scenario also includes the production receipt reader and landing submitter. Airflow `standalone` starts the scheduler, Dag processor, and API server with a temporary SQLite metadata database and `LocalExecutor`. The Docker service uses `network_mode: none`.

Cloud Run submission tasks now return an Operation name immediately. `CloudRunExecutionReceiptSensor` uses `mode="reschedule"` to free the worker between checks, polls the operation and exact Execution state, fails fast on `EXECUTION_FAILED` or `EXECUTION_CANCELLED`, and waits for the immutable GCS invocation receipt on ingest. The downstream receipt reader validates the same generation the sensor observed. All Cloud Run submitters use the `cloud_run_submissions` pool; the VM bootstrap must create this pool before starting the scheduler. The DAG has a 90-minute experimental Deadline Alert measured from DagRun queue time. `PIPELINE_FAILED` is emitted only for terminal task failures; `PIPELINE_DEADLINE_MISSED` is emitted by the deadline callback. Both events are redacted local log lines, not external notifications.

The harness patches the production `_authorized_session` I/O seam and a test-only exact-receipt reader for backfill. The cloud authorization gate remains enabled in the positive/negative cloud scenarios; the mounted inert sentinel satisfies its file-mode check, but fakes never load credentials or open sockets. Manual test DAGs disable scheduling only in the derived harness DAG; the backfill test keeps the production daily timetable and disables scheduler auto-creation for that isolated run. Airflow 3.4 stores prior retry attempts in `task_instance` rows (`working_set`, `archived_reason`) and sensor reschedules in `task_reschedule`.

The real-scheduler scenarios cover: retry try 1 recorded as failed/retry then try 2 success with identical invocation arguments and no `PIPELINE_FAILED`; HTTP 403 fails on try 1 with one `PIPELINE_FAILED`; gate OFF skips with zero fake calls; failed Cloud Run Execution makes the sensor fail fast; and a short test Deadline Alert emits exactly one populated `PIPELINE_DEADLINE_MISSED` with no failure event. The backfill scenario uses `airflow backfill create` for five logical dates, then `airflow tasks clear` to replay one date in its existing DagRun. The fake landing ledger verifies five distinct invocation IDs, the replay uses the same invocation ID, and the 15 province/date grains remain unique with three duplicate inserts prevented. For the backfill CLI and task-clear steps, the harness stops the standalone scheduler while metadata is mutated, then restarts it for task execution; this avoids SQLite writer contention while preserving the real scheduler and metadata.

### Provider choice

The pinned image contains `apache-airflow-providers-google==22.8.0`, including `CloudRunExecuteJobOperator(deferrable=True)`, `GCSObjectExistenceSensor(deferrable=True)`, and `impersonation_chain`. The operator defers while waiting for the long-running operation and returns Job metadata after completion; it does not return the Execution identity to a separate sensor. The object sensor checks GCS presence but cannot inspect Cloud Run Execution state or fail fast on a failed/cancelled execution. The custom combined `BaseSensorOperator` therefore meets the receipt-plus-execution contract while preserving the fixed job allowlist and the keyless AuthorizedSession seam. Airflow API references: [Deadline Alerts](https://airflow.apache.org/docs/apache-airflow/3.4.0/howto/deadline-alerts.html), [Sensors](https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/sensors.html); Cloud Run references: [jobs.run](https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.jobs/run), [Executions](https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.jobs.executions).
