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
        }


def _ledger(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


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


def _failure_events(home: Path, service_log: Path) -> list[dict[str, object]]:
    marker = "DATAFORGE_AIRFLOW_WEATHER_FAILURE "
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
        with service_log.open("wb") as component_output:
            process = subprocess.Popen(
                ["airflow", "standalone"],
                env=env,
                stdout=component_output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            dag_ready = False
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError(f"airflow standalone exited {process.returncode}")
                listing = _run_cli(["dags", "list", "--output", "json"], env, timeout=10)
                if DAG_ID in listing.stdout:
                    dag_ready = True
                    break
                time.sleep(1)
            if not dag_ready:
                raise TimeoutError("production subset DAG did not appear in the Airflow DagBag")

            _run_cli(["dags", "unpause", DAG_ID], env)
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
            if scenario == "forbidden":
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if _failure_events(home, service_log):
                        break
                    time.sleep(0.5)

        _terminate(process)
        process = None
        calls = _ledger(ledger_path)
        task_states = snapshot["tasks"]
        ingest = task_states.get("execute_api_ingest")
        if set(task_states) != set(TASK_IDS):
            raise AssertionError(f"scheduler ran an unexpected task set: {sorted(task_states)}")

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
            "network": "Docker network_mode=none; _authorized_session intercepted",
        }
        if scenario == "retry_once":
            history = snapshot["attempts"].get("execute_api_ingest", [])
            posts = [call for call in calls if call["method"] == "POST"]
            args = [call["args"] for call in posts]
            if (
                snapshot["dag_run_state"] != "success"
                or snapshot["run_type"] != "manual"
                or len(snapshot["dag_runs"]) != 1
                or ingest != {"state": "success", "try_number": 2}
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
            ):
                raise AssertionError(
                    f"native retry evidence mismatch: ingest={ingest}; history={history}; post_args={args}"
                )
            evidence["execute_api_ingest"] = {
                "attempt_1_state": history,
                "current_state": ingest,
                "post_args_by_attempt": args,
                "fake_io_calls": calls,
            }
        elif scenario == "forbidden":
            posts = [call for call in calls if call["method"] == "POST"]
            events = _failure_events(home, service_log)
            if (
                snapshot["dag_run_state"] != "failed"
                or snapshot["run_type"] != "manual"
                or len(snapshot["dag_runs"]) != 1
                or ingest != {"state": "failed", "try_number": 1}
                or len(posts) != 1
                or len(events) != 1
                or events[0].get("event_type") != "PIPELINE_FAILED"
            ):
                raise AssertionError(
                    f"403 no-retry evidence mismatch: ingest={ingest}; posts={posts}; events={events}"
                )
            evidence["forbidden_control"] = {
                "task": ingest,
                "post_count": len(posts),
                "failure_events": events,
                "fake_io_calls": calls,
            }
        else:
            if (
                snapshot["dag_run_state"] != "success"
                or snapshot["run_type"] != "manual"
                or len(snapshot["dag_runs"]) != 1
                or task_states["authorize_cloud_execution"]["state"] != "skipped"
                or task_states["verify_gcp_schedule_paused"]["state"] != "skipped"
                or ingest["state"] != "skipped"
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
    for scenario in ("retry_once", "forbidden", "gate_off"):
        evidence = _run_scenario(scenario)
        print(
            "DATAFORGE_AIRFLOW_SCHEDULER_EVIDENCE "
            + json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
