# Week 7 Airflow reference DAG

This is a **local orchestration reference**, not a deployed Week-7 pipeline. It models the intended stages and failure rules using Apache Airflow 3.4.0 and a checked-in synthetic Silver fixture:

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

## Runtime and compatibility

- Pinned runtime: `apache/airflow:3.4.0-python3.11@sha256:be92e15d57c5be726fc39a91cd09cce8f7488483b67979e0fb74c1a2c7cfb4e2`.
- DAG authoring uses Airflow 3's public `airflow.sdk` TaskFlow interface and SDK exceptions.
- Airflow 3.4 documents Python 3.11 support and `airflow dags test`; see [Airflow prerequisites](https://airflow.apache.org/docs/apache-airflow/3.4.0/installation/prerequisites.html), [TaskFlow](https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/taskflow.html), and [DAG testing](https://airflow.apache.org/docs/apache-airflow/3.4.0/cli-and-env-variables-ref.html).
- The task graph demonstrates dependencies and XCom metadata with small JSON objects. It intentionally does not invoke `dbt`, Cloud Run, BigQuery, Workflows, Cloud Scheduler, or Airflow's production notification integrations.

This artifact only proves the DAG imports and its local contract test can execute in the pinned runtime. It is not evidence of a cloud workflow, a dbt build, a scheduled production run, or a deployed alert channel.
