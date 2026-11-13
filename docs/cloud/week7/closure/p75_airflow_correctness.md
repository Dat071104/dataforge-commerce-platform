# P7.5 Airflow Correctness Closure

**Implementation state:** Airflow 3.4.0 package-level DAG contract tests pass in an isolated Python 3.11 virtual environment. Airflow warns that native Windows is unsupported; the pinned Linux Docker image/CLI run remains `NOT_RUN` because the Docker daemon is unavailable. This note does not claim a hosted scheduler run, a native retry transition for the revised Cloud Run task, or external notification.

## Before and after

| Area | Before | After |
|---|---|---|
| Scheduled request | `resolve_request()` required `dag_run.conf.mode=cloud_integration`; an empty scheduled conf failed before ingest. | DAG-level Airflow 3.4 Params default to `mode=scheduled` and no date override. The request uses the fixed DagRun interval end in `Asia/Ho_Chi_Minh`, minus the seven-day settling lag. A manual run can explicitly select `mode=manual` and an allowed date. |
| Cloud authorization | The run mode in user-controlled conf was the only cloud opt-in. | `DATAFORGE_WEATHER_CLOUD_ENABLED` is independently required and defaults to OFF. A disabled run emits a redacted `DISABLED` no-op log and skips cloud tasks. The enabled path is fixed to the approved project/region, exact Airflow service account, and explicit keyless ADC mount. The DAG remains paused on creation. |
| Invocation identity | The run ID hash was stable but hidden behind the required cloud-mode conf. | SHA-256 of `dag_id + run_id` remains the immutable invocation identity. It does not depend on wall-clock retry time. Replaying the same DagRun reuses the same identity; a separate DagRun gets a separate identity. |
| Cloud Run lifecycle | The task synchronously polled the Cloud Run operation to completion, then a GCS sensor waited for a receipt that would usually already exist. | The task still owns the bounded operation poll. The redundant sensor was removed. A separate receipt read waits at most 120 seconds for the exact immutable receipt and fails closed on invalid schema, identity, digest, generation, or JSON. No asynchronous Airflow sensor is claimed by the updated DAG. |
| Failures and recovery | Most Cloud Run response statuses raised the same retryable Airflow exception. | HTTP 408/429/5xx are retryable; other 4xx, identity, date, receipt, and contract errors fail without retries. Polling transient read failures retry twice against the same operation; an exhausted poll or ambiguous operation timeout fails closed for manual inspection. Airflow task retries are bounded to one. |
| Failure notification | The callback logged a local record, but there was no structured failure event contract. | The callback logs one redacted `PIPELINE_FAILED` event for the failed task instance, including run/task identifiers and error class only. It states `local_airflow_log_only` and `external_notification_sent=false`; it does not send email or create a Monitoring policy. |
| dbt weather tests | Airflow and Workflows ran `dbt build --select tag:weather_mini3` and then `dbt test` with the identical selector. | The second identical `dbt test` invocation was removed from both orchestration paths. The selected weather build runs its associated model tests before publication; the accepted historical receipt is retained unchanged. The Workflows source change is code-only and has not been applied to GCP. |

## Retry, idempotency, and failure boundary

The request identity remains stable across an Airflow retry. The existing weather job first checks for a completed invocation receipt, writes immutable GCS objects with create-if-absent preconditions, and uses deterministic request/manifest identities. BigQuery landing uses a merge, and the publication macro recognizes the same `workflow_run_id` and candidate hash as a no-op. These controls make repeated executions safe for published data state; they do not guarantee exactly-once Cloud Run submission or exactly-once provider API calls.

Cloud Run's `:run` request does not receive a caller-supplied idempotency token. A transport timeout after submission can therefore leave the operation outcome ambiguous; the one bounded Airflow retry uses the same run identity, but duplicate execution is possible before a completion receipt exists. A poll timeout after an operation name is known is terminal and asks an operator to inspect Cloud Run before replay. No automatic schedule or cloud resource was enabled by this code change.

The receipt read is a normal bounded task after the synchronous Cloud Run operation completes. Its timeout retry does not resubmit that job. This design avoids presenting a post-completion GCS check as an asynchronous Airflow sensor.

## dbt build/test review

The repository applies `weather_mini3` tags to each weather model and weather SQL test. Offline dbt 1.11.17 parse and selector resolution identified the tagged tests. The official dbt `build` command runs selected resources and their associated tests, so a subsequent identical `dbt test --select tag:weather_mini3` repeats checks and adds warehouse queries. Both orchestration paths now rely on the build's test phase. No cloud job ran and the Workflows source change has not been applied to GCP.

The prior accepted `airflow_integration_receipt.md` is retained as historical evidence for the earlier implementation and successful run; it is not rewritten to describe this updated DAG.

## Validation performed

| Check | Result | Command / evidence |
|---|---|---|
| Pure request, authorization, status-classifier, receipt-wait, and receipt-validation tests | PASS: 13 tests, 49 subtests | `.venv/Scripts/python.exe -m pytest labs/airflow_reference/tests/test_week7_weather_logic.py -q` |
| Python syntax compilation | PASS | `.venv/Scripts/python.exe -m compileall -q` on the two DAG modules and both focused test modules |
| Ruff | PASS | `.venv/Scripts/ruff.exe check` on the changed Airflow modules/tests |
| Whitespace check | PASS | `git diff --check` on changed Airflow files and the launcher |
| Launcher syntax | PASS | `System.Management.Automation.Language.Parser.ParseFile` returned zero errors for `run_cloud_integration.ps1`. |
| dbt parse and weather-test selector | PASS | dbt Core 1.11.17 / BigQuery adapter 1.11.3 parsed offline; `dbt ls --select tag:weather_mini3 --resource-type test` resolved 36 test nodes. No warehouse query was run. |
| Full offline repository regression | PASS: 194 passed, 7 skipped | `.venv/Scripts/python.exe -m pytest -q tests dashboards/P5/tests` with `RUN_POSTGRES_TESTS=0`; skips are gated PostgreSQL/operational-source tests. |
| Unified post-B offline repository regression | PASS: 210 passed, 7 skipped | `.venv/Scripts/python.exe -m pytest -q tests dashboards/P5/tests` with `RUN_POSTGRES_TESTS=0`, rerun after Prompt B integration. |
| Offline transient-retry example | PASS for the bounded Airflow reference; PARTIAL for the new Cloud Run task transition | The retained pinned Airflow 3.4 receipt at `docs/cloud/week7/airflow_test_receipt.json` records `retry_once`: one local transient task error, one retry, and a successful DagRun. Current tests map HTTP 503 to retryable `AirflowException` and verify that a retry submits the same invocation arguments. The receipt does not preserve the literal `UP_FOR_RETRY` state label, and the updated Cloud Run task was not run through a native Airflow retry because Docker was unavailable. |
| Airflow DAG import/contract/fault tests | PASS WITH PLATFORM LIMIT | An isolated Windows virtual environment installed `apache-airflow==3.4.0` and the pinned Google client versions. `python -m unittest discover -s labs/airflow_reference/tests -p 'test_*.py' -v` ran 32 tests successfully, including the actual DAG import and Params schema assertions. Airflow emitted its unsupported-Windows warning. The pinned Linux Docker image was unavailable because Docker Desktop's engine was unavailable. A native CLI migration/DagRun attempt stopped at Airflow's `fcntl` import, which Windows does not provide. |
| Live GCP schedule, transient retry, receipt, or publication | NOT_RUN | No GCP operation was started. The previously accepted one-time schedule and alert were removed; no recurring schedule or notification is active based on the retained P7.4.1 receipts. |
| External notification delivery | NOT_AUTHORIZED | The prior one-time notification approval was consumed. This callback is local logging only. |

## Prompt A transition

`A_CODE_READY` is reached for the local/code scope: focused Airflow contract helpers, Airflow 3.4.0 package-level DAG contract tests, Mini3 weather tests, Workflows contract tests, offline dbt parse/selector, full offline regression, Ruff, compilation, pip consistency, PowerShell parsing, and diff checks pass. The pinned Linux Airflow 3.4 Docker/CLI suite remains an explicit environment skip because the local Docker daemon is unavailable. Native scheduler retry state for the revised Cloud Run task and all live cloud execution remain unverified; neither is represented as a cloud pass.

## Remaining live gates

- `LIVE_SCHEDULE_NOT_AUTHORIZED`: no hosted/unattended Airflow schedule was enabled or observed.
- `LIVE_RETRY_NOT_AUTHORIZED`: no live Cloud Run fault/retry was injected.
- `NOTIFICATION_DELIVERY_NOT_AUTHORIZED`: no new email, Monitoring policy, or destination was configured.
- `DELIVERY_UNVERIFIED_PENDING_NEW_APPROVAL`: an Airflow log event is not proof of external delivery.
- The updated DAG has no actual asynchronous sensor. Its Week 7 sensor competency is not demonstrated by this synchronous Cloud Run operation + bounded receipt-read design.

## Primary references

- [Airflow 3.4 Params](https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/params.html) — scheduled DagRuns use default Param values; Param values are JSON-Schema validated.
- [Airflow 3.4 Timetables](https://airflow.apache.org/docs/apache-airflow/3.4.0/authoring-and-scheduling/timetable.html) — a bare cron schedule defaults to a trigger timetable in Airflow 3.4 unless configured otherwise; its interval is point-in-time by default.
- [Airflow 3.4 Tasks](https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/tasks.html) — `AirflowSkipException` skips, while `AirflowFailException` fails without remaining retries.
- [dbt build](https://docs.getdbt.com/reference/commands/build) — builds and tests selected resources, including tests selected indirectly through their model dependencies.
