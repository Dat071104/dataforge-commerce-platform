"""Run production Mini3 task scenarios through Airflow's real scheduler."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

DAG_ID = "dataforge_week7_weather_cloud"
TASK_IDS = (
    "resolve_cloud_request",
    "authorize_cloud_execution",
    "verify_gcp_schedule_paused",
    "execute_api_ingest",
    "wait_for_api_ingest",
)
BACKFILL_TASK_IDS = TASK_IDS + (
    "read_execution_receipt",
    "load_bigquery_landing",
    "wait_for_bigquery_landing",
)
TERMINAL_DAG_STATES = {"success", "failed", "canceled"}


def _run_cli(args: list[str], env: dict[str, str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["airflow", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr + "\n" + result.stdout)[-5000:]
        raise RuntimeError(f"airflow {' '.join(args)} exited {result.returncode}:\n{detail}")
    return result


def _db_snapshot(database: Path, run_id: str) -> dict[str, object] | None:
    if not database.exists():
        return None
    with sqlite3.connect(database, timeout=5) as connection:
        dag_run = connection.execute(
            "SELECT state, run_type FROM dag_run WHERE dag_id=? AND run_id=?",
            (DAG_ID, run_id),
        ).fetchone()
        if not dag_run:
            return None
        dag_runs = connection.execute(
            "SELECT run_id, run_type, state FROM dag_run WHERE dag_id=? ORDER BY run_id",
            (DAG_ID,),
        ).fetchall()
        task_rows = connection.execute(
            "SELECT task_id, state, try_number, working_set, archived_reason FROM task_instance "
            "WHERE dag_id=? AND run_id=? ORDER BY task_id, try_number",
            (DAG_ID, run_id),
        ).fetchall()
        reschedule_rows = connection.execute(
            "SELECT ti.task_id, COUNT(tr.id) FROM task_reschedule tr "
            "JOIN task_instance ti ON ti.id=tr.ti_id "
            "WHERE ti.dag_id=? AND ti.run_id=? GROUP BY ti.task_id",
            (DAG_ID, run_id),
        ).fetchall()
        current_tasks: dict[str, dict[str, object]] = {}
        attempts: dict[str, list[dict[str, object]]] = {}
        for task_id, state, try_number, working_set, archived_reason in task_rows:
            row = {
                "state": state,
                "try_number": try_number,
                "working_set": working_set,
                "archived_reason": archived_reason,
            }
            if working_set == 1:
                current_tasks[task_id] = {"state": state, "try_number": try_number}
            else:
                attempts.setdefault(task_id, []).append(row)
        return {
            "dag_run_state": dag_run[0],
            "run_type": dag_run[1],
            "dag_runs": [
                {"run_id": found_run_id, "run_type": run_type, "state": state}
                for found_run_id, run_type, state in dag_runs
            ],
            "tasks": current_tasks,
            "attempts": attempts,
            "reschedules": {task_id: count for task_id, count in reschedule_rows},
        }


def _all_dag_runs(database: Path) -> list[dict[str, object]]:
    if not database.exists():
        return []
    with sqlite3.connect(database, timeout=5) as connection:
        rows = connection.execute(
            "SELECT run_id, run_type, state, logical_date FROM dag_run "
            "WHERE dag_id=? ORDER BY logical_date, run_id",
            (DAG_ID,),
        ).fetchall()
    return [
        {
            "run_id": run_id,
            "run_type": run_type,
            "state": state,
            "logical_date": str(logical_date),
        }
        for run_id, run_type, state, logical_date in rows
    ]


def _ledger(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _ingest_posts(calls: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        call
        for call in calls
        if call.get("method") == "POST"
        and call.get("target") == "cloud_run_ingest"
        and isinstance(call.get("args"), list)
        and call["args"]
        and call["args"][0] == "ingest"
    ]


def _failure_event_payload(line: str, marker: str) -> dict[str, object] | None:
    offset = line.find(marker)
    if offset < 0:
        return None
    payload_text = line[offset + len(marker) :].lstrip()
    candidates = [payload_text]
    unescaped = payload_text.replace(r'\"', '"')
    if unescaped != payload_text:
        candidates.append(unescaped)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            payload, _ = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("failure event marker does not contain a JSON object")


def _structured_events(home: Path, service_log: Path, marker: str) -> list[dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    paths = [service_log, *(home / "logs").rglob("*.log")]
    for path in paths:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            payload = _failure_event_payload(line, marker)
            if payload is None:
                continue
            found[json.dumps(payload, sort_keys=True)] = payload
    return list(found.values())


def _failure_events(home: Path, service_log: Path) -> list[dict[str, object]]:
    return _structured_events(home, service_log, "DATAFORGE_AIRFLOW_WEATHER_FAILURE ")


def _deadline_events(home: Path, service_log: Path) -> list[dict[str, object]]:
    return _structured_events(home, service_log, "DATAFORGE_AIRFLOW_WEATHER_DEADLINE ")


def _redacted_component_errors(path: Path) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(errors="replace").splitlines()[-500:]
    errors = [
        line
        for line in lines
        if any(marker in line.lower() for marker in ("error", "exception", "traceback", "failed"))
    ][-30:]
    return "\n".join(
        re.sub(r"(?i)(password|secret|token)(\s*[:=]\s*)\S+", r"\1\2<redacted>", line)
        for line in errors
    )


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=20)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def _start_standalone(
    env: dict[str, str], service_log: Path, *, append: bool
) -> subprocess.Popen[bytes]:
    with service_log.open("ab" if append else "wb") as component_output:
        return subprocess.Popen(
            ["airflow", "standalone"],
            env=env,
            stdout=component_output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _wait_for_dag_ready(process: subprocess.Popen[bytes], env: dict[str, str]) -> None:
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError(f"airflow standalone exited {process.returncode}")
        listing = _run_cli(["dags", "list", "--output", "json"], env, timeout=10)
        if DAG_ID in listing.stdout:
            return
        time.sleep(1)
    raise TimeoutError("production subset DAG did not appear in the Airflow DagBag")


def _run_scenario(scenario: str) -> dict[str, object]:
    home = Path(tempfile.mkdtemp(prefix=f"dataforge-airflow-{scenario}-", dir="/tmp/airflow"))
    if home.parent != Path("/tmp/airflow"):
        raise RuntimeError("test home escaped the expected temporary directory")
    database = home / "airflow.db"
    ledger_path = home / "test_session_ledger.jsonl"
    state_dir = home / "state"
    state_dir.mkdir()
    service_log = home / "standalone.log"
    env = os.environ.copy()
    env.update(
        {
            "AIRFLOW_HOME": str(home),
            "AIRFLOW__CORE__DAGS_FOLDER": "/workspace/labs/airflow_reference/harness/dags",
            "AIRFLOW__CORE__LOAD_EXAMPLES": "False",
            "AIRFLOW__CORE__EXECUTOR": "LocalExecutor",
            "AIRFLOW__CORE__PARALLELISM": "1",
            "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN": f"sqlite:///{database}",
            "AIRFLOW__DAG_PROCESSOR__MIN_FILE_PROCESS_INTERVAL": "1",
            "AIRFLOW__SCHEDULER__SCHEDULER_HEARTBEAT_SEC": "1",
            "AIRFLOW__SCHEDULER__SCHEDULER_IDLE_SLEEP_TIME": "1",
            "AIRFLOW__SCHEDULER__USE_JOB_SCHEDULE": (
                "False" if scenario == "backfill" else "True"
            ),
            "AIRFLOW__LOGGING__BASE_LOG_FOLDER": str(home / "logs"),
            "DATAFORGE_AIRFLOW_HARNESS_SCENARIO": scenario,
            "DATAFORGE_AIRFLOW_HARNESS_LEDGER": str(ledger_path),
            "DATAFORGE_AIRFLOW_HARNESS_STATE_DIR": str(state_dir),
            "DATAFORGE_WEATHER_CLOUD_ENABLED": "false" if scenario == "gate_off" else "true",
            "DATAFORGE_WEATHER_PROJECT_ID": "dataforge-p7-lab-d0f725",
            "DATAFORGE_WEATHER_REGION": "us-central1",
            "DATAFORGE_AIRFLOW_IMPERSONATION_SERVICE_ACCOUNT": (
                "dataforge-week7-airflow@dataforge-p7-lab-d0f725.iam.gserviceaccount.com"
            ),
            "GOOGLE_APPLICATION_CREDENTIALS": (
                "/run/dataforge/credentials/application_default_credentials.json"
            ),
        }
    )

    process: subprocess.Popen[bytes] | None = None
    try:
        version = _run_cli(["version"], env).stdout.strip()
        _run_cli(["db", "migrate"], env, timeout=120)
        _run_cli(
            ["pools", "set", "cloud_run_submissions", "1", "Cloud Run submissions"],
            env,
        )
        process = _start_standalone(env, service_log, append=False)
        _wait_for_dag_ready(process, env)

        _run_cli(["dags", "unpause", DAG_ID], env)
        backfill_info: dict[str, object] | None = None
        if scenario == "backfill":
            from_date = "2026-11-01T09:00:00+07:00"
            to_date = "2026-11-05T09:00:00+07:00"
            backfill_args = [
                "backfill",
                "create",
                "--dag-id",
                DAG_ID,
                "--from-date",
                from_date,
                "--to-date",
                to_date,
                "--max-active-runs",
                "1",
            ]
            _terminate(process)
            process = None
            dry_run = _run_cli([*backfill_args, "--dry-run"], env, timeout=60)
            _run_cli(backfill_args, env, timeout=600)
            process = _start_standalone(env, service_log, append=True)
            _wait_for_dag_ready(process, env)
            backfill_runs: list[dict[str, object]] = []
            for _ in range(600):
                backfill_runs = _all_dag_runs(database)
                if len(backfill_runs) == 5 and all(
                    row["run_type"] == "backfill" and row["state"] == "success"
                    for row in backfill_runs
                ):
                    break
                time.sleep(1)
            if len(backfill_runs) != 5 or any(
                row["run_type"] != "backfill" or row["state"] != "success"
                for row in backfill_runs
            ):
                raise TimeoutError(f"five successful backfill runs were not recorded: {backfill_runs}")

            target_run = backfill_runs[2]
            run_id = str(target_run["run_id"])
            run_date = str(target_run["logical_date"])
            initial_ingest_posts = [
                call
                for call in _ingest_posts(_ledger(ledger_path))
                if call.get("dag_run_id") == run_id
            ]
            if len(initial_ingest_posts) != 1:
                raise AssertionError(
                    f"target backfill run should have one ingest submission before rerun: {initial_ingest_posts}"
                )
            _terminate(process)
            process = None
            _run_cli(
                [
                    "tasks",
                    "clear",
                    DAG_ID,
                    "--start-date",
                    run_date,
                    "--end-date",
                    run_date,
                    "--yes",
                ],
                env,
                timeout=60,
            )
            process = _start_standalone(env, service_log, append=True)
            _wait_for_dag_ready(process, env)
            snapshot = None
            for _ in range(300):
                snapshot = _db_snapshot(database, run_id)
                repeated_posts = [
                    call
                    for call in _ingest_posts(_ledger(ledger_path))
                    if call.get("dag_run_id") == run_id
                ]
                if (
                    len(repeated_posts) >= 2
                    and snapshot
                    and snapshot["dag_run_state"] == "success"
                    and all(state["state"] == "success" for state in snapshot["tasks"].values())
                ):
                    break
                time.sleep(1)
            if (
                len(repeated_posts) != 2
                or not snapshot
                or snapshot["dag_run_state"] != "success"
                or not all(state["state"] == "success" for state in snapshot["tasks"].values())
            ):
                raise TimeoutError(
                    f"cleared backfill run did not rerun successfully: run_id={run_id}; "
                    f"posts={len(repeated_posts)}; metadata={snapshot}"
                )
            backfill_info = {
                "dry_run_excerpt": dry_run.stdout.splitlines()[:10],
                "runs_before_rerun": backfill_runs,
                "target_run_id": run_id,
                "target_logical_date": run_date,
                "ingest_posts_before_rerun": len(initial_ingest_posts),
                "ingest_posts_after_rerun": len(repeated_posts),
            }
        else:
            run_id = f"manual__scheduler_harness_{scenario}"
            conf = json.dumps(
                {"mode": "manual", "observation_date": "2026-11-06"},
                separators=(",", ":"),
            )
            _run_cli(
                [
                    "dags",
                    "trigger",
                    DAG_ID,
                    "--run-id",
                    run_id,
                    "--logical-date",
                    "2026-11-06T02:00:00+00:00",
                    "--conf",
                    conf,
                ],
                env,
            )

            snapshot = None
            for _ in range(180):
                snapshot = _db_snapshot(database, run_id)
                if snapshot and snapshot["dag_run_state"] in TERMINAL_DAG_STATES:
                    break
                time.sleep(1)
            if not snapshot or snapshot["dag_run_state"] not in TERMINAL_DAG_STATES:
                raise TimeoutError(f"DagRun did not finish; last metadata snapshot={snapshot}")
        if scenario in {"forbidden", "execution_failed"}:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if _failure_events(home, service_log):
                    break
                time.sleep(0.5)
        elif scenario == "deadline":
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if _deadline_events(home, service_log):
                    break
                time.sleep(0.5)

        _terminate(process)
        process = None
        calls = _ledger(ledger_path)
        task_states = snapshot["tasks"]
        ingest = task_states.get("execute_api_ingest")
        sensor = task_states.get("wait_for_api_ingest")
        sensor_reschedules = snapshot["reschedules"].get("wait_for_api_ingest", 0)
        expected_task_ids = set(BACKFILL_TASK_IDS if scenario == "backfill" else TASK_IDS)
        if set(task_states) != expected_task_ids:
            raise AssertionError(
                f"scheduler ran an unexpected task set: {sorted(task_states)}; "
                f"expected={sorted(expected_task_ids)}"
            )

        evidence: dict[str, object] = {
            "airflow_version": version,
            "executor": "LocalExecutor",
            "scheduler_process_started": True,
            "scheduler_invoked": "airflow standalone (scheduler + Dag processor + API server)",
            "dag_id": DAG_ID,
            "run_id": run_id,
            "dag_run_state": snapshot["dag_run_state"],
            "dag_runs": snapshot["dag_runs"],
            "task_states": task_states,
            "sensor_reschedules": sensor_reschedules,
            "network": "Docker network_mode=none; _authorized_session intercepted",
        }
        if scenario == "retry_once":
            history = snapshot["attempts"].get("execute_api_ingest", [])
            posts = [call for call in calls if call.get("method") == "POST"]
            args = [call["args"] for call in posts]
            failure_events = _failure_events(home, service_log)
            if (
                snapshot["dag_run_state"] != "success"
                or snapshot["run_type"] != "manual"
                or len(snapshot["dag_runs"]) != 1
                or ingest != {"state": "success", "try_number": 2}
                or sensor != {"state": "success", "try_number": 1}
                or sensor_reschedules < 1
                or not any(
                    row["state"] == "failed"
                    and row["try_number"] == 1
                    and row["working_set"] is None
                    and row["archived_reason"] == "retry"
                    for row in history
                )
                or len(posts) != 2
                or args[0] != args[1]
                or not posts[0]["injected_transport_failure"]
                or posts[1]["injected_transport_failure"]
                or failure_events
            ):
                raise AssertionError(
                    "native retry/sensor evidence mismatch: "
                    f"ingest={ingest}; sensor={sensor}; reschedules={sensor_reschedules}; "
                    f"history={history}; post_args={args}; failure_events={failure_events}"
                )
            evidence["execute_api_ingest"] = {
                "attempt_1_state": history,
                "current_state": ingest,
                "sensor_state": sensor,
                "sensor_reschedules": sensor_reschedules,
                "post_args_by_attempt": args,
                "fake_io_calls": calls,
            }
        elif scenario == "forbidden":
            posts = [call for call in calls if call.get("method") == "POST"]
            events = _failure_events(home, service_log)
            if (
                snapshot["dag_run_state"] != "failed"
                or snapshot["run_type"] != "manual"
                or len(snapshot["dag_runs"]) != 1
                or ingest != {"state": "failed", "try_number": 1}
                or sensor is None
                or sensor["state"] != "upstream_failed"
                or len(posts) != 1
                or len(events) != 1
                or events[0].get("event_type") != "PIPELINE_FAILED"
            ):
                raise AssertionError(
                    "403 no-retry evidence mismatch: "
                    f"ingest={ingest}; sensor={sensor}; posts={posts}; events={events}"
                )
            evidence["forbidden_control"] = {
                "task": ingest,
                "post_count": len(posts),
                "failure_events": events,
                "fake_io_calls": calls,
            }
        elif scenario == "execution_failed":
            posts = [call for call in calls if call.get("method") == "POST"]
            events = _failure_events(home, service_log)
            if (
                snapshot["dag_run_state"] != "failed"
                or snapshot["run_type"] != "manual"
                or ingest != {"state": "success", "try_number": 1}
                or sensor != {"state": "failed", "try_number": 1}
                or sensor_reschedules < 1
                or len(posts) != 1
                or len(events) != 1
                or events[0].get("event_type") != "PIPELINE_FAILED"
                or events[0].get("task_id") != "wait_for_api_ingest"
            ):
                raise AssertionError(
                    "execution fail-fast evidence mismatch: "
                    f"ingest={ingest}; sensor={sensor}; reschedules={sensor_reschedules}; "
                    f"posts={posts}; events={events}"
                )
            evidence["execution_failed_control"] = {
                "task": sensor,
                "sensor_reschedules": sensor_reschedules,
                "post_count": len(posts),
                "failure_events": events,
                "fake_io_calls": calls,
            }
        elif scenario == "deadline":
            deadline_events = _deadline_events(home, service_log)
            failure_events = _failure_events(home, service_log)
            if (
                snapshot["dag_run_state"] != "success"
                or sensor != {"state": "success", "try_number": 1}
                or sensor_reschedules < 1
                or len(deadline_events) != 1
                or deadline_events[0].get("event_type") != "PIPELINE_DEADLINE_MISSED"
                or failure_events
            ):
                raise AssertionError(
                    "deadline evidence mismatch: "
                    f"sensor={sensor}; reschedules={sensor_reschedules}; "
                    f"deadline_events={deadline_events}; failure_events={failure_events}"
                )
            evidence["deadline_control"] = {
                "deadline_events": deadline_events,
                "failure_events": failure_events,
                "sensor_reschedules": sensor_reschedules,
                "task": sensor,
            }
        elif scenario == "backfill":
            backfill_runs = _all_dag_runs(database)
            ingest_posts = _ingest_posts(calls)
            invocation_ids_by_run: dict[str, list[str]] = {}
            for post in ingest_posts:
                args = post["args"]
                if "--invocation-id" not in args or not post.get("dag_run_id"):
                    raise AssertionError(f"backfill ingest post lacks stable identifiers: {post}")
                invocation_id = args[args.index("--invocation-id") + 1]
                invocation_ids_by_run.setdefault(str(post["dag_run_id"]), []).append(invocation_id)
            target_run_id = str(backfill_info["target_run_id"]) if backfill_info else ""
            target_invocation_ids = invocation_ids_by_run.get(target_run_id, [])
            landing_rows_path = state_dir / "fake_landing_rows.jsonl"
            landing_rows = (
                [json.loads(line) for line in landing_rows_path.read_text().splitlines() if line.strip()]
                if landing_rows_path.exists()
                else []
            )
            landing_grains = [
                f"{row['observation_date']}|{row['province']}" for row in landing_rows
            ]
            landing_inserts = [
                call for call in calls if call.get("target") == "fake_landing_insert"
            ]
            inserted_rows = sum(int(call["new_rows"]) for call in landing_inserts)
            duplicate_attempts = sum(int(call["duplicate_rows"]) for call in landing_inserts)
            run_ids = [str(row["run_id"]) for row in backfill_runs]
            invocation_ids = [values[0] for values in invocation_ids_by_run.values() if values]
            backfill_failure_events = _failure_events(home, service_log)
            if (
                len(backfill_runs) != 5
                or any(row["run_type"] != "backfill" or row["state"] != "success" for row in backfill_runs)
                or len(set(run_ids)) != 5
                or len(invocation_ids_by_run) != 5
                or len(set(invocation_ids)) != 5
                or len(ingest_posts) != 6
                or len(target_invocation_ids) != 2
                or len(set(target_invocation_ids)) != 1
                or len(landing_rows) != 15
                or len(set(landing_grains)) != 15
                or inserted_rows != 15
                or duplicate_attempts != 3
                or len(landing_inserts) != 6
                or snapshot["run_type"] != "backfill"
                or snapshot["dag_run_state"] != "success"
                or sensor is None
                or sensor["state"] != "success"
                or sensor["try_number"] < 1
                or sensor_reschedules < 1
                or task_states.get("wait_for_bigquery_landing") is None
                or task_states["wait_for_bigquery_landing"]["state"] != "success"
                or task_states["wait_for_bigquery_landing"]["try_number"] < 1
                or snapshot["reschedules"].get("wait_for_bigquery_landing", 0) < 1
                or backfill_failure_events
            ):
                raise AssertionError(
                    "backfill/idempotency evidence mismatch: "
                    f"runs={backfill_runs}; invocations={invocation_ids_by_run}; "
                    f"ingest_posts={len(ingest_posts)}; target_ids={target_invocation_ids}; "
                    f"landing_rows={len(landing_rows)}; unique_grains={len(set(landing_grains))}; "
                    f"ingest_sensor={sensor}; inserted={inserted_rows}; duplicate_attempts={duplicate_attempts}; "
                    f"landing_sensor={task_states.get('wait_for_bigquery_landing')}"
                )
            evidence["backfill_idempotency"] = {
                "run_count": len(backfill_runs),
                "logical_dates": [row["logical_date"] for row in backfill_runs],
                "invocation_ids": sorted(set(invocation_ids)),
                "target_run_id_reprocessed": target_run_id,
                "target_invocation_id_by_attempt": target_invocation_ids,
                "landing_row_count": len(landing_rows),
                "distinct_grain_count": len(set(landing_grains)),
                "duplicate_insert_attempts_prevented": duplicate_attempts,
                "run_states": [row["state"] for row in backfill_runs],
            }
        else:
            if (
                snapshot["dag_run_state"] != "success"
                or snapshot["run_type"] != "manual"
                or len(snapshot["dag_runs"]) != 1
                or task_states["authorize_cloud_execution"]["state"] != "skipped"
                or task_states["verify_gcp_schedule_paused"]["state"] != "skipped"
                or ingest["state"] != "skipped"
                or sensor is None
                or sensor["state"] != "skipped"
                or calls
            ):
                raise AssertionError(f"cloud-off evidence mismatch: tasks={task_states}; calls={calls}")
            evidence["gate_off_control"] = {"fake_io_call_count": 0, "fake_io_calls": calls}

        return evidence
    except Exception as exc:
        details = _redacted_component_errors(service_log)
        if details:
            raise RuntimeError(f"{scenario} failed: {exc}\nAirflow component errors (redacted):\n{details}") from exc
        raise
    finally:
        if process is not None:
            _terminate(process)
        if home.parent == Path("/tmp/airflow"):
            shutil.rmtree(home, ignore_errors=True)


def main() -> int:
    for scenario in (
        "retry_once",
        "forbidden",
        "gate_off",
        "execution_failed",
        "deadline",
        "backfill",
    ):
        evidence = _run_scenario(scenario)
        print(
            "DATAFORGE_AIRFLOW_SCHEDULER_EVIDENCE "
            + json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
