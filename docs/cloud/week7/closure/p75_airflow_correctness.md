# P7.5 Airflow Correctness Closure

**Implementation state:** Airflow 3.4.0 package-level DAG contract tests pass in an isolated Python 3.11 virtual environment. The initial code-closure snapshot could not run the pinned Linux image because Docker Desktop was unavailable then. After the user started Docker Desktop (H6), the local no-egress scheduler harness passed all three scenarios; the same required harness job passed on the exact PR code head in GitHub Actions. This proves a native Airflow retry transition for the revised task under the harness's fake I/O seam. It does not claim live GCP execution or external notification.

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
| Native Airflow retry transition for the revised Cloud Run task | PASS in the no-egress scheduler harness; live GCP retry NOT_RUN | The Airflow 3.4 harness below runs the production `execute_api_ingest` callable. Metadata records try 1 as failed/retry and try 2 as success; the two intercepted fake `:run` POST argument lists are identical. The historical fixture-DAG receipt at `docs/cloud/week7/airflow_test_receipt.json` remains unchanged and is not used as evidence for this revised task. |
| Airflow DAG import/contract/fault tests | PASS WITH PLATFORM LIMIT | An isolated Windows virtual environment installed `apache-airflow==3.4.0` and the pinned Google client versions. `python -m unittest discover -s labs/airflow_reference/tests -p 'test_*.py' -v` ran 32 tests successfully, including the actual DAG import and Params schema assertions. Airflow emitted its unsupported-Windows warning. At that earlier snapshot Docker Desktop was unavailable. A native CLI migration/DagRun attempt stopped at Airflow's `fcntl` import, which Windows does not provide. Subsequent Linux scheduler evidence is recorded below. |
| No-egress Airflow 3.4 scheduler harness | PASS | Local `.\labs\airflow_reference\ci.ps1 -Scenario scheduler_harness` exited 0 after H6. The Linux `LocalExecutor` scheduler ran the production Mini3 task subset: retry try 1 archived as failed/retry, try 2 success with identical intercepted fake POST args; 403 failed on try 1 with one POST and one `PIPELINE_FAILED`; gate OFF skipped with zero fake API calls. The command was run with Docker `network_mode=none`; only `_authorized_session` was intercepted. Local evidence: `D:\DATA_ENGINEER\DataForge_D_Week7_Final\evidence\airflow-scheduler-harness-local-2026-11-13.log`. |
| Live GCP schedule, transient retry, receipt, or publication | NOT_RUN | No GCP operation was started. The previously accepted one-time schedule and alert were removed; no recurring schedule or notification is active based on the retained P7.4.1 receipts. |
| External notification delivery | NOT_RUN | This callback is local logging only; this PR harness made no external notification call. |

## Prompt A transition

`A_CODE_READY` is reached for the local/code scope: focused Airflow contract helpers, Airflow 3.4.0 package-level DAG contract tests, Mini3 weather tests, Workflows contract tests, offline dbt parse/selector, full offline regression, Ruff, compilation, pip consistency, PowerShell parsing, diff checks, and the no-egress Linux scheduler harness pass. The scheduler harness proves Airflow's native retry transition for the revised Cloud Run task while faking only its authorized I/O seam. It is not a live Cloud Run retry or a live cloud execution.

## Remaining live gates

- No hosted/unattended Airflow schedule or live Cloud Run fault/retry was run as part of this PR release harness; those remain separate Phase 4/5 operations.
- No new email, Monitoring policy, or destination was configured in this PR. An Airflow log event is not proof of external delivery.
- The updated DAG has no actual asynchronous sensor. Its Week 7 sensor competency is not demonstrated by this synchronous Cloud Run operation + bounded receipt-read design.

## Phase 1 release follow-up — 2026-11-13

The local command `.\labs\airflow_reference\ci.ps1 -Scenario scheduler_harness` passed after Docker Desktop reported server version `29.9.3`. Its real Airflow 3.4 `LocalExecutor` scheduler produced three manual DagRuns with the expected positive and negative outcomes summarized in the validation table. Afterward, `docker ps` showed only the pre-existing healthy `dataforge-postgres` container; the temporary harness container had been removed. The saved local log records the earlier same-code run; the post-H6 rerun also exited 0.

The same harness passed in the exact-head PR run [43424336220](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43424336220), job `131881909659`, for code head `4562d3f425b23d80312543cb566970e532037b64`. The run uploaded `airflow-scheduler-harness` (artifact `14035891377`, 1,167 bytes, SHA-256 `3dea5e088cfc7bea30e3e93d71846a3a83672d27e267eea10387d13fd99490b1`). The Week 7 push run `43424323389` also succeeded, including its push-only read-only dbt compile. No cloud write or live GCP call was made by the harness.

## Primary references

- [Airflow 3.4 Params](https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/params.html) — scheduled DagRuns use default Param values; Param values are JSON-Schema validated.
- [Airflow 3.4 Timetables](https://airflow.apache.org/docs/apache-airflow/3.4.0/authoring-and-scheduling/timetable.html) — a bare cron schedule defaults to a trigger timetable in Airflow 3.4 unless configured otherwise; its interval is point-in-time by default.
- [Airflow 3.4 Tasks](https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/tasks.html) — `AirflowSkipException` skips, while `AirflowFailException` fails without remaining retries.
- [dbt build](https://docs.getdbt.com/reference/commands/build) — builds and tests selected resources, including tests selected indirectly through their model dependencies.
