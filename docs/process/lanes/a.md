# Lane A — Airflow ops

## Progress

**Status:** A1–A4 implemented and locally verified on `feat/w7-airflow-ops`; A5 runtime bundle is owned by the root agent in the separate `lane-a-runtime` worktree. No GCP calls/writes, VM deployment, CI run, push, or PR creation occurred in this lane.

### Changed files

- `labs/airflow_reference/dags/dataforge_week7_weather_cloud.py`: async Cloud Run submission, combined reschedule/receipt sensor, terminal execution fail-fast, Deadline Alert callback, task/pool/documentation semantics, and explicit attached VM identity authorization.
- `labs/airflow_reference/harness/dags/dataforge_week7_airflow_retry_harness.py`: derived harness DAG, controlled deadline/backfill subsets, short test poke interval, fake I/O wrapper.
- `labs/airflow_reference/harness/dataforge_week7_airflow_test_session.py`: deterministic no-network operation, execution, receipt, transient failure, and idempotent fake landing behavior.
- `labs/airflow_reference/harness/run_scheduler_harness.py`: six real-scheduler scenarios, metadata/reschedule assertions, five-date backfill and cleared-run replay proof.
- `labs/airflow_reference/tests/test_week7_weather_dag_contract.py`: DAG, deadline, sensor, fail-fast, and attached-identity contract tests.
- `labs/airflow_reference/README.md`: A1–A4 harness and provider decision documentation; removed an unsupported claim that this uncommitted lane had exact-head GitHub Actions evidence.
- `docs/process/lanes/a.md`: this RCA and verification report.

### Verification evidence

Commands were run from `D:\DATA_ENGINEER\DataForge_worktrees\lane-a` against the digest-pinned `apache/airflow:3.4.0-python3.11` image:

1. `.\labs\airflow_reference\ci.ps1 -Scenario no_new_batch`: exit 0. Captured summary: `Ran 39 tests in 0.384s`, `OK`, and the local fixture DagRun ended with `state=success`.
2. `.\labs\airflow_reference\ci.ps1 -Scenario scheduler_harness`: exit 0. The `DATAFORGE_AIRFLOW_SCHEDULER_EVIDENCE` output recorded six scenario records:
   - `retry_once`: DagRun success; ingest attempt 1 archived `failed` with retry reason, attempt 2 success; stable invocation arguments; 2 sensor reschedules; no `PIPELINE_FAILED`.
   - `forbidden`: DagRun failed on HTTP 403 after one POST; one redacted `PIPELINE_FAILED`; sensor `upstream_failed` with zero sensor reschedules.
   - `gate_off`: DagRun success; all cloud work skipped; zero fake I/O calls.
   - `execution_failed`: DagRun failed; one sensor reschedule, then terminal Execution failure; one `PIPELINE_FAILED`.
   - `deadline`: DagRun success; one populated `PIPELINE_DEADLINE_MISSED`; no failure event; 9 sensor reschedules.
   - `backfill`: five successful 2026-11-01 through 2026-11-05 logical dates; 5 invocation IDs; clearing and replaying the existing Nov 3 run preserved its run ID and invocation ID; 15 distinct province/date grains and 3 duplicate writes prevented.
3. `python -m compileall -q labs/airflow_reference` and `git diff --check`: exit 0.
4. `python scripts/week7_secret_scan.py`: `SECRET_SCAN_STATUS=PASS findings=0 files_scanned=497`.
5. Pinned image auth inspection: `docker run --rm --network none --entrypoint airflow apache/airflow:3.4.0-python3.11@sha256:be92e15d57c5be726fc39a91cd09cce8f7488483b67979e0fb74c1a2c7cfb4e2 config get-value core auth_manager` printed `airflow.api_fastapi.auth.managers.simple.simple_auth_manager.SimpleAuthManager`. Inspection of the same image confirmed `apache-airflow-providers-fab==3.10.2`; its `FabAirflowSecurityManagerOverride.add_user()` hashes the supplied password and commits the user row. This was source inspection only; no user/password was created.
6. CI status: none for this lane; exact-head Actions evidence was not claimed.

The production task network path was not exercised. The scheduler scenarios ran with Docker `network_mode: none`; only the fake authorized-session seam was enabled. The attached identity tests mocked Compute Engine credentials and did not request a token or contact GCP.

### Provider ADR

Use the custom `CloudRunExecutionReceiptSensor` instead of stacking `CloudRunExecuteJobOperator(deferrable=True)` and `GCSObjectExistenceSensor(deferrable=True)`. The latter checks object presence but does not inspect the exact Cloud Run Execution state or fail fast for `EXECUTION_FAILED` / `EXECUTION_CANCELLED`; the former operator owns the full long-running wait and does not expose an Execution identifier for the required downstream combined sensor. The custom operator returns the operation and execution identity, polls in Airflow `reschedule` mode, checks terminal execution state, and validates the exact immutable receipt generation. API choices follow Airflow 3.4 [Deadline Alert](https://airflow.apache.org/docs/apache-airflow/3.4.0/howto/deadline-alerts.html) and [sensor](https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/sensors.html) docs and the Cloud Run v2 [jobs.run](https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.jobs/run) and [Execution](https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.jobs.executions) APIs.

### Open items and risks

- A5 is not part of this lane commit. Root owns the VM runtime bundle and Secret Manager bootstrap in `lane-a-runtime`; C4 expects a digest-pinned image input, startup/runtime bundle inputs, and `container_name=airflow-scheduler` for gcplogs.
- The pinned Airflow image defaults to SimpleAuthManager, which writes a generated admin password file and logs the initial password. Root was given the verified installed `apache-airflow-providers-fab==3.10.2` option; using FAB with a Secret Manager sourced password and a metadata-DB hash needs to be implemented/verified in A5 before a VM can start.
- Cloud Run submission has no caller-supplied idempotency token. A transport timeout can leave execution creation ambiguous; the task keeps invocation arguments stable and surfaces an explicit replay warning, but runtime reconciliation against a receipt is still needed before a manual replay.
- Deadline Alert is experimental in Airflow 3.4. The new callback is local-log-only; no external notification path was added here.
- No live Cloud Run, GCS, BigQuery, or VM verification was performed. CI is not available for this branch work.

### Commit

The A1–A4 implementation commit is `d96a790cf7602402d8ec9e6a0b9689972fe5f329`. This report is committed separately so it can name that immutable implementation SHA without a self-referential hash.

## RCA log

### 2026-11-13 — pinned provider source probe

- **Symptom:** the Docker Python probe exited 1 with `ImportError: cannot import name 'operation' from 'google.cloud.run_v2.types'`.
- **Expected vs actual:** expected to inspect Cloud Run OperationMetadata fields; the assumed module name is not exported by the pinned package. No DAG run or network call occurred.
- **Reproduction:** `docker compose --file labs/airflow_reference/compose.yaml run --rm --entrypoint python airflow-scheduler-harness -c "from google.cloud.run_v2.types import operation"`.
- **Hypotheses:** (1) OperationMetadata is in another generated module; (2) the pinned Google Cloud Run library omits that generated type. Package path confirms only the import path is unverified; no evidence yet that the library lacks the type.
- **Root cause:** the probe guessed a module export that does not exist in `google.cloud.run_v2.types`.
- **Fix:** enumerate the installed package modules and inspect the official generated REST/Proto definitions before selecting an import.
- **Guard:** next probe lists modules before import; preserve a no-network container and do not retry the same import.
### 2026-11-13 — metadata schema inspection quoting

- **Symptom:** the host PowerShell probe exited 1 with `task_instance: The term 'task_instance' is not recognized`; the SQLite table-column output was incomplete.
- **Expected vs actual:** expected to inspect the Airflow metadata table columns inside the no-egress container; nested quoting caused part of the SQL command to be interpreted by the host shell.
- **Reproduction:** the failed `docker compose ... -lc "airflow db migrate ... python -c ..."` probe.
- **Hypotheses:** (1) PowerShell parsed nested quotes before Docker; (2) the table name needed escaping. The PowerShell error text confirms (1); no evidence indicates a database/schema issue.
- **Root cause:** backslash escaping does not protect nested quotes in a PowerShell native command argument.
- **Fix:** use a PowerShell single-quoted command string for the bash `-lc` argument, then use double quotes inside the Python `-c` code.
- **Guard:** inspect the exact container command string before retry and require a complete table-column list plus exit 0.
### 2026-11-13 — metadata schema inspection quoting, second attempt

- **Symptom:** the second container probe exited 1 with Python `SyntaxError`; the shell removed quotes around `/tmp/airflow/airflow.db` and the `pragma` strings.
- **Expected vs actual:** expected complete `task_instance` and `task_reschedule` column lists; container Python received unquoted identifiers instead.
- **Reproduction:** the failed nested `docker compose run ... /bin/bash -lc '... python -c "..."'` command.
- **Hypotheses:** PowerShell native argument quoting versus bash parsing. The traceback shows Python got `/tmp/airflow/airflow.db` without string quotes, identifying native argument transformation before execution.
- **Root cause:** nested PowerShell → Docker → bash → Python quoting was brittle; command strings were transformed before Python parsing.
- **Fix:** bypass bash and set the container entrypoint directly to `python`, passing one PowerShell single-quoted `-c` argument.
- **Guard:** keep the query read-only, inspect both table outputs, and require exit 0 before using the schema in the runner.
### 2026-11-13 — runner patch context mismatch

- **Symptom:** `apply_patch` rejected the `run_scheduler_harness.py` context; no source file changed.
- **Expected vs actual:** expected to add task-reschedule assertions; the patch included a retry assertion line that is not present in the current runner.
- **Reproduction:** the failed context patch in this Lane A turn.
- **Hypotheses:** stale source context versus concurrent edit. A fresh read of the runner is required to distinguish them; no concurrent edit is visible in the worktree.
- **Root cause:** the patch copied an incorrect line from the expected test shape rather than the actual source.
- **Fix:** re-read the exact runner block and apply smaller hunks against literal current context.
- **Guard:** verify `git diff --check` and the changed function after each hunk before running the harness.
### 2026-11-13 — contract test patch context mismatch

- **Symptom:** `apply_patch` rejected the `test_week7_weather_dag_contract.py` import context; no test file changed.
- **Expected vs actual:** expected to add sensor/Deadline test imports; the patch named `dataforge_week7_airflow_cloud`, while the actual module is `dataforge_week7_weather_cloud`.
- **Reproduction:** the failed context patch in the current Lane A worktree.
- **Hypotheses:** transcription error versus concurrent change. The earlier exact file read shows the module name is `dataforge_week7_weather_cloud`; no concurrent edit is present.
- **Root cause:** the patch copied the wrong module name from memory instead of the current source.
- **Fix:** re-read the import block and patch with the exact module name.
- **Guard:** inspect the diff and rerun the focused test module after applying.
### 2026-11-13 — harness DAG patch context mismatch

- **Symptom:** `apply_patch` rejected a repeated harness DAG patch; no new file change occurred.
- **Expected vs actual:** the patch expected the old `execute_api_ingest` subset, but readback showed the previously applied `wait_for_api_ingest` subset and sensor wrapper already present.
- **Reproduction:** the failed patch in this Lane A turn, followed by reading `dataforge_week7_airflow_retry_harness.py`.
- **Hypotheses:** stale context or concurrent edit. The file readback matched the earlier successful Lane A patch, and this worktree has a single owner.
- **Root cause:** the patch repeated a change that had already succeeded; its old context no longer existed.
- **Fix:** no code fix; keep the existing sensor subset/wrapper and validate the diff.
- **Guard:** re-read the staged/current block before applying a patch; verify with `git diff --check`.

### 2026-11-13 — Airflow contract assertion mismatch

- **Symptom:** `ci.ps1 -Scenario no_new_batch` exited 1; 37 tests ran and two new DAG structure assertions failed.
- **Expected vs actual:** expected `dag.deadline` to be a single `DeadlineAlert`, but Airflow 3.4 normalizes it to a one-item list; expected the sensor to depend only on submit, but its `request` XCom also creates a direct dependency on `resolve_cloud_request`.
- **Reproduction:** `.\labs\airflow_reference\ci.ps1 -Scenario no_new_batch` in `D:\DATA_ENGINEER\DataForge_worktrees\lane-a`.
- **Hypotheses:** code serialization defect versus assertions not matching Airflow's normalized DAG graph. The failure values show valid normalization and the expected XCom dependency; other 35 tests passed.
- **Root cause:** the tests asserted a scalar deadline and incomplete upstream set, despite Airflow 3.4 storing the deadline as a list and the sensor needing the resolved request.
- **Fix:** update only the structure assertions to accept the one-item deadline list and the two upstream task IDs.
- **Guard:** rerun the focused contract suite, then the real scheduler harness and verify its metadata reschedule count.
### 2026-11-13 — receipt ancestry assertion mismatch

- **Symptom:** the second `ci.ps1 -Scenario no_new_batch` run had 36/37 passing tests; the structure test failed only for `receipt_upstream='execute_api_ingest'`.
- **Expected vs actual:** expected the submit task to be a direct upstream of the final receipt task; actual graph correctly routes the result through `wait_for_api_ingest`, whose output carries the execution name and receipt generation.
- **Reproduction:** `.labs\airflow_reference\ci.ps1 -Scenario no_new_batch`; assertion at `test_week7_weather_dag_contract.py` receipt upstream loop.
- **Hypotheses:** missing dependency versus test checking direct rather than transitive ancestry. The graph output shows `wait_for_api_ingest` is direct; its own upstream set contains submit.
- **Root cause:** the existing structure test expected the old synchronous ingest task to feed the final receipt directly.
- **Fix:** assert the sensor as the direct receipt input and retain the separate sensor-upstream assertion for the submit task.
- **Guard:** rerun the focused package tests and the real scheduler harness; sensor metadata must show reschedules and terminal state.
### 2026-11-13 — receipt assertion patch context mismatch

- **Symptom:** the test patch to remove the stale direct-submit upstream expectation was rejected; no test file changed.
- **Expected vs actual:** the patch expected `execute_api_ingest` immediately before `read_execution_receipt`, but readback shows both `execute_api_ingest` and the new `wait_for_api_ingest` entries.
- **Reproduction:** the failed narrow `apply_patch` in this Lane A turn.
- **Hypotheses:** stale context or unreported concurrent edit. Readback shows the sensor entry came from the earlier successful structure patch; no other worktree edits are present.
- **Root cause:** the patch context omitted the already-added sensor line.
- **Fix:** remove only the stale `execute_api_ingest` line from the final-receipt upstream assertion list.
- **Guard:** inspect that list and rerun the focused structure test.
### 2026-11-13 — 403 sensor downstream state assertion

- **Symptom:** the real scheduler harness retry scenario passed, but `forbidden` exited 1 at the assertion that the downstream sensor must be `skipped`; the emitted evidence did not include the sensor state.
- **Expected vs actual:** the 403 task was `failed` at try 1, one POST and one `PIPELINE_FAILED` were observed; the runner rejected the downstream sensor-state classification before printing it.
- **Reproduction:** `.labs\airflow_reference\ci.ps1 -Scenario scheduler_harness`; `run_scheduler_harness.py` `forbidden` control.
- **Hypotheses:** (1) default `all_success` marks a direct downstream task `upstream_failed`; (2) scheduler leaves it `skipped`/unmaterialized. Airflow 3.4 docs define `upstream_failed` for an upstream failure when the trigger rule requires success, and `execute_api_ingest` is the sensor's upstream parent.
- **Root cause:** the control asserted `skipped`, which is the gate-off behavior, instead of the default `upstream_failed` behavior expected after a terminal parent failure.
- **Fix:** assert the Airflow 3.4 downstream failure state `upstream_failed` and include the observed sensor state in the failure message; still require one POST, one event, and no sensor I/O.
- **Guard:** rerun all real-scheduler scenarios; 403 must fail try 1, the sensor must not run, and only one redacted PIPELINE_FAILED must be logged. Reference: https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/tasks.html and https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/dags.html.
### 2026-11-13 — Cloud Run chain patch context mismatch

- **Symptom:** the patch intended to replace synchronous downstream job calls was rejected; no DAG file change occurred.
- **Expected vs actual:** the patch expected the old direct `load_bigquery_landing`/`verify_landing_reconciliation`/dbt/publish chain; readback showed operation submissions and combined reschedule sensors already present.
- **Reproduction:** the failed context patch in this Lane A turn, followed by reading the exact bottom of the DAG factory.
- **Hypotheses:** stale patch context versus concurrent code edit. The DAG readback matches the earlier successful Lane A multi-sensor patch; only this worktree owns these files.
- **Root cause:** the patch repeated a previously applied downstream sensor-chain change.
- **Fix:** no code fix; keep the verified async chain and review the current diff rather than reapplying.
- **Guard:** run DAG structure tests and the real scheduler harness after the chain's final edits.
### 2026-11-13 — Deadline callback context fields were null

- **Symptom:** the real scheduler `deadline` scenario fired exactly one `PIPELINE_DEADLINE_MISSED`, but its `dag_id`, `workflow_run_id`, and `deadline_time` values were null.
- **Expected vs actual:** expected redacted identifiers/time from the DagRun; actual event type and callback count were correct, but fields were empty.
- **Reproduction:** `.\labs\airflow_reference\ci.ps1 -Scenario scheduler_harness`; inspect the `deadline_control` output.
- **Hypotheses:** Airflow passed context in a different shape, or callback event context is absent. Pinned Airflow 3.4 `airflow.models.deadline.Deadline.handle_miss` source builds `context` with nested JSON mappings: `dag_run` and `deadline` are dictionaries.
- **Root cause:** `local_deadline_log` used `getattr()` on nested dictionary values, so it discarded the identifiers/time.
- **Fix:** read nested fields from `Mapping` values (with attribute fallback for direct unit callers) and keep the event redacted.
- **Guard:** unit test with mapping context and real scheduler deadline scenario must assert non-null `dag_id`, `workflow_run_id`, `deadline_time`, exactly one deadline event, and zero failure events.
### 2026-11-13 — harness scenario patch syntax

- **Symptom:** `apply_patch` rejected a multi-hunk edit with `invalid hunk ... Expected update hunk to start with @@`; no harness file changed.
- **Expected vs actual:** expected to switch the harness target DAG by scenario; patch text omitted the hunk header before the second block.
- **Reproduction:** the failed multi-hunk patch in this Lane A turn.
- **Hypotheses:** patch parser syntax versus source mismatch. The diagnostic names an invalid hunk header, so the source was not inspected or changed by this attempt.
- **Root cause:** malformed patch formatting between hunks.
- **Fix:** apply the scenario-specific changes as separate, well-formed hunks against freshly read source.
- **Guard:** verify `git diff --check` and re-read the harness DAG target selection before running.
### 2026-11-13 — backfill runner evidence patch context mismatch

- **Symptom:** `apply_patch` rejected a hunk intended to add post-rerun evidence; no runner file changed.
- **Expected vs actual:** the patch context expected to add a `scenario == "backfill"` branch; the current runner already had the backfill creation, clear, and replay flow.
- **Reproduction:** the failed backfill evidence hunk in this Lane A turn, followed by reading the current runner branches.
- **Hypotheses:** missing branch versus stale patch context. Readback confirms the branch is already present; only final evidence assertions are still missing.
- **Root cause:** the patch tried to re-create a branch that had already been applied in an earlier hunk.
- **Fix:** no code fix; add only the missing outcome assertion in the current result-selection block.
- **Guard:** verify five successful backfill runs, same target run ID after clear, same invocation ID on both ingest calls, and 15 distinct landing grains.

### 2026-11-13 — direct backfill harness invocation lacked its temp parent

- **Symptom:** the direct Docker call for `_run_scenario("backfill")` exited 1 with `FileNotFoundError` creating `/tmp/airflow/dataforge-airflow-backfill-*`.
- **Expected vs actual:** expected the runner to create its temporary home; the runner requires parent `/tmp/airflow`, which the normal Compose command creates before invocation.
- **Reproduction:** direct `docker compose ... --entrypoint python ... -c '..._run_scenario("backfill")'` call.
- **Hypotheses:** missing mount or wrong path versus bypassed entrypoint setup. Container was otherwise available; the call overrode Compose's bash entrypoint, so its `mkdir -p /tmp/airflow` step did not run.
- **Root cause:** the direct diagnostic invocation skipped the harness wrapper initialization.
- **Fix:** retry the one-scenario invocation with `mkdir -p /tmp/airflow` before importing the runner.
- **Guard:** verify the container remains `network_mode=none` and require run exit status/output; use the standard CI wrapper for the full suite.
### 2026-11-13 — backfill harness omitted the downstream landing sensor

- **Symptom:** the one-scenario backfill harness did not load its DAG; `airflow dags list-import-errors` reported `RuntimeError: unexpected production Mini3 subset`, with `load_bigquery_landing` present but `wait_for_bigquery_landing` absent. The runner remained in its bounded DagBag readiness poll.
- **Expected vs actual:** expected the backfill subset to include the real landing task and its Cloud Run execution sensor; the current partial subset targeted the landing task only and included upstream tasks, not downstream sensors.
- **Reproduction:** `docker compose ... _run_scenario("backfill")`, then inside the running no-egress container `airflow dags list-import-errors`; actual task set is in the error text.
- **Hypotheses:** a production task graph defect versus the harness subset target. The error shows the production DAG has the landing task; the test subset selection omitted the downstream sensor.
- **Root cause:** backfill harness selected `load_bigquery_landing` with `include_downstream=False`, so the expected `wait_for_bigquery_landing` sensor was excluded.
- **Fix:** select `wait_for_bigquery_landing` as the backfill subset target so its upstream closure includes load, receipt, and ingest.
- **Guard:** require the DagBag task set to include both load and sensor, then run real `airflow backfill create` and assert metadata, invocation IDs, and fake landing grain counts.
### 2026-11-13 — backfill CLI contended with SQLite metadata writes

- **Symptom:** the real Airflow backfill command exited 1 after creating the first two DagRuns; the third `INSERT INTO dag_run` failed with `sqlite3.OperationalError: database is locked`.
- **Expected vs actual:** expected five sequential backfill runs in the fake data plane; actual backfill creation stopped while the standalone scheduler and backfill CLI shared the SQLite metadata DB.
- **Reproduction:** direct no-egress `_run_scenario("backfill")` call; Airflow 3.4 stack trace shows failure during `airflow backfill create` DagRun insert, not a Cloud API call.
- **Hypotheses:** (1) SQLite multi-process write contention; (2) lock caused by test pool setup or DagBag serialization. The exact SQLite lock plus concurrent standalone scheduler/backfill command supports (1). Pinned Airflow source inspection confirms `_create_backfill` inserts the DagRun rows in its own transaction.
- **Root cause:** SQLite is used by both the running scheduler and the separate backfill CLI while the CLI inserts the five DagRun rows concurrently.
- **Fix:** serialize metadata writes: stop the test standalone scheduler while `backfill create` and `tasks clear` mutate metadata, then restart it to execute the real backfill tasks. If serial execution still locks, use a test-only Postgres service on an internal no-egress network; never touch the host `dataforge-postgres`.
- **Guard:** confirm scheduler is stopped during each CLI metadata mutation, restart it before task execution, then assert five backfill rows, same run ID/invocation on clear-and-rerun, and 15 unique fake landing grains.

### 2026-11-13 — runner indentation after scheduler helper extraction

- **Symptom:** direct backfill harness invocation exited 1 with `IndentationError: unexpected indent` at `run_scheduler_harness.py:291`.
- **Expected vs actual:** expected the backfill/manual trigger branch inside `_run_scenario`'s `try`; the branch retained one indentation level from the removed log-file context manager.
- **Reproduction:** the isolated `_run_scenario("backfill")` container command after extracting `_start_standalone()`.
- **Hypotheses:** malformed Python block versus runtime import problem. The Python parser reported the first `airflow dags unpause` line before any Airflow process started, confirming source indentation.
- **Root cause:** the scheduler start helper extraction removed a `with` block but did not dedent its former body.
- **Fix:** dedent the trigger/backfill branch to the `try` body.
- **Guard:** `python -m compileall -q labs/airflow_reference` and rerun the isolated backfill scheduler scenario.
### 2026-11-13 — backfill runner indentation after branch serialization

- **Symptom:** `python -m compileall -q labs/airflow_reference` exited 1 with `IndentationError: unexpected indent` at `run_scheduler_harness.py:309`.
- **Expected vs actual:** expected backfill setup statements at the `if scenario == "backfill"` body level; readback shows `process = None` and subsequent statements one indentation level deeper than `_terminate(process)`.
- **Reproduction:** compileall immediately after the first dedent of the old context-manager block.
- **Hypotheses:** an incomplete dedent versus tabs mixed with spaces. Exact file lines show spaces only and a single line group retained four extra spaces.
- **Root cause:** the automated dedent removed indentation from the outer block but left a nested subsection at its old level.
- **Fix:** normalize the backfill branch indentation against the current `if`/`for` structure instead of applying a blanket text dedent.
- **Guard:** compileall and `git diff --check` must pass before another Docker run.
### 2026-11-13 — runner else branch remained nested

- **Symptom:** `python -m compileall -q labs/airflow_reference` still exited 1 with `SyntaxError` at `run_scheduler_harness.py:393` on `else:`.
- **Expected vs actual:** the backfill `if` is at the `try` body level, but its sibling `else` and manual-scenario body retained one indentation level from the removed context manager.
- **Reproduction:** compileall after dedenting only the backfill branch body.
- **Hypotheses:** unmatched `if` versus sibling indentation. The line-count readback confirms `if` at 8 spaces and `else` at 12.
- **Root cause:** the earlier indentation fix did not dedent the sibling manual branch/event-wait block after removing the outer `with`.
- **Fix:** dedent the `else` plus subsequent manual scenario/event-wait block one level, leaving `_terminate(process)` at the try-body level.
- **Guard:** compileall, `git diff --check`, then the targeted backfill scenario.
### 2026-11-13 — backfill landing task escaped the fake I/O seam

- **Symptom:** the backfill scenario produced `AirflowFailException: keyless GCP credential setup failed` in `load_bigquery_landing`; the sentinel ADC file was not valid JSON.
- **Expected vs actual:** expected the no-egress fake session to intercept the landing submission; actual `execute_api_ingest` and sensor were patched, but the backfill subset also ran the unwrapped production `load_bigquery_landing` callable.
- **Reproduction:** direct no-egress `_run_scenario("backfill")`; Airflow task log shows `load_bigquery_landing` → `_submit_cloud_run_job` → `_authorized_session` → `google.auth.default` failure on the test sentinel.
- **Hypotheses:** invalid fake receipt/manifest versus missing fake-session patch. The stack trace never reached response parsing; it failed while constructing AuthorizedSession in the landing task.
- **Root cause:** the harness patched only the preflight/ingest callables and sensor poke; the newly included landing submit task did not use the fake I/O seam.
- **Fix:** in the backfill harness DAG, wrap the production `load_bigquery_landing` callable with `_run_with_fake_session`, preserving all production args and task logic.
- **Guard:** the same network-none backfill run must show fake `land` POSTs, no credential load, five successful runs, same-run retry identity, and no duplicate fake landing grains.
### 2026-11-13 — backfill rerun task attempt number assertion

- **Symptom:** the backfill CLI created five successful runs, clear-and-rerun produced a second ingest POST with the same invocation ID, and the fake landing table stayed at 15 distinct rows, but the runner rejected the target landing sensor because it expected try 1.
- **Expected vs actual:** target sensor succeeded after `airflow tasks clear`; its recorded current try number was 2 because the task had already run once before clearing.
- **Reproduction:** isolated `backfill` scheduler scenario; assertion output includes `landing_sensor={'state': 'success', 'try_number': 2}` and 5 successful backfills.
- **Hypotheses:** sensor retry versus deliberate task clearing. The CLI `tasks clear` reprocessed the same DagRun; metadata state and identical invocation ID confirm this is the intended second task attempt.
- **Root cause:** the final backfill assertion hard-coded try number 1 even though the scenario intentionally clears and reruns that same logical date.
- **Fix:** require the landing sensor state to be success with a positive try number, while separately asserting the same DagRun ID/invocation ID and no duplicate grains.
- **Guard:** rerun backfill; target run must remain one backfill DagRun, ingest POSTs must reuse one invocation ID, and landing rows must remain 15 unique province/date grains.
### 2026-11-13 — ingest sensor attempt number after backfill clear

- **Symptom:** the rerun harness still returned exit 1 after creating five successful backfills, six ingest POSTs, 15 unique landing rows, and three duplicate inserts prevented; the backfill assertion failed.
- **Expected vs actual:** the previous output showed the cleared target's landing sensor succeeded at try 2. The runner still required the ingest sensor to be exactly try 1; clearing the whole target DagRun reruns both sensors.
- **Reproduction:** isolated `_run_scenario("backfill")`; the failure predicate compares `sensor` to `{state: success, try_number: 1}` after task clearing.
- **Hypotheses:** invocation-ID/data mismatch versus attempt-number assertion. The failure report confirms five runs, same target invocation ID on both ingest POSTs, and 15 unique landing grains; source shows the remaining strict condition is the ingest sensor try count.
- **Root cause:** the target DagRun's successful sensor tasks are cleared and rerun, so Airflow records their current attempt number as 2 rather than 1.
- **Fix:** require the target ingest sensor to be `success` with a positive try number, just like the landing sensor; keep the same-run/same-invocation and grain-count assertions.
- **Guard:** rerun backfill and verify both sensor states, target DagRun ID, same invocation ID across its two ingest submissions, and no duplicate grains.
### 2026-11-13 — attached Airflow VM identity cannot use the ADC-file gate

- **Symptom:** code review found the current production gate requires `GOOGLE_APPLICATION_CREDENTIALS` to equal a mounted ADC JSON path and requires that file to exist; C4/A5 explicitly prohibit an ADC file on the VM.
- **Expected vs actual:** the VM should use the attached `dataforge-week7-airflow` service account through the metadata server. Current code always loads file-based ADC and impersonates a target principal; that path cannot run on the approved attached-identity VM without a file.
- **Reproduction:** inspect `_require_cloud_authorization()` and `_impersonated_credentials()` in `labs/airflow_reference/dags/dataforge_week7_weather_cloud.py`; no live GCP call was made.
- **Hypotheses:** default ADC may resolve attached compute credentials, but the current code rejects the VM identity path; static service-account JSON must still be rejected.
- **Root cause:** cloud authorization conflates the existing local impersonated-ADC mode with the hosted VM attached-service-account mode.
- **Fix:** add a distinct explicit `DATAFORGE_AIRFLOW_IDENTITY_MODE=attached_service_account` branch that requires no `GOOGLE_APPLICATION_CREDENTIALS`, obtains ADC through `google.auth.default()`, requires Compute Engine metadata credentials, refreshes only to discover the attached principal, and compares it exactly to the approved service account; preserve the current explicit-file impersonation branch for CI/harness/live local runs.
- **Guard:** tests prove attached mode needs no file, accepts only the expected metadata principal, rejects a wrong principal and any ADC file, while cloud opt-in/project/region/job-allowlist gates remain unchanged. No live token or GCP request in the tests.
### 2026-11-13 — Lane README patch context mismatch

- **Symptom:** `apply_patch` rejected the Airflow README replacement; no README content changed.
- **Expected vs actual:** the patch expected an extra space after the opening backtick in the local command; the actual README line has no space.
- **Reproduction:** the failed multi-section README patch in this Lane A turn.
- **Hypotheses:** stale whole-section context versus concurrent README edit. A fresh read is required; only the root feature worktree exists for `labs/airflow_reference/**`.
- **Root cause:** the patch text did not match the exact current README command string.
- **Fix:** re-read the exact section and patch only the stale top paragraph and harness section.
- **Guard:** `git diff --check` and read back the entire updated sections.
### 2026-11-13 — scheduler README section patch context mismatch

- **Symptom:** `apply_patch` rejected the README scheduler section; no README file change occurred in that attempt.
- **Expected vs actual:** patch context contained `Run ` .\...`, but the source line has `Run `.\...` with no intervening space.
- **Reproduction:** the failed whole-section patch in this Lane A turn.
- **Hypotheses:** spurious command whitespace versus unrelated section edits. Exact `rg` readback confirms the spurious whitespace is the mismatch.
- **Root cause:** copied the local PowerShell command into the patch with a leading space inside its code span.
- **Fix:** replace only the section between the exact heading and the next known heading using a match-count-checked rewrite.
- **Guard:** read back the new section and run `git diff --check`.

### 2026-11-13 — combined harness indexed non-HTTP ledger rows as requests

- **Symptom:** `ci.ps1 -Scenario scheduler_harness` exited 1 in `retry_once` with `KeyError: 'method'` while collecting POST calls.
- **Expected vs actual:** expected to filter only fake HTTP POST records; the ledger also contains `cloud_run_operation_submitted` and receipt/landing records without a `method` key.
- **Reproduction:** `.\labs\airflow_reference\ci.ps1 -Scenario scheduler_harness`; the exception occurs at `run_scheduler_harness.py:464` after the real scheduler completes the injected retry task.
- **Hypotheses:** malformed HTTP request records versus strict indexing of mixed ledger records. The traceback points directly to `call["method"]` and source shows operation records intentionally omit `method`.
- **Root cause:** scenario assertions index `method` on all ledger rows rather than filtering mixed ledger rows with a safe lookup.
- **Fix:** use `call.get("method") == "POST"` for every scenario POST filter; preserve the ledger's non-HTTP evidence rows.
- **Guard:** rerun the combined real-scheduler suite and require all six scenarios, including retry, forbidden response, opt-out, fail-fast execution, deadline, and five-date backfill, to exit 0.
