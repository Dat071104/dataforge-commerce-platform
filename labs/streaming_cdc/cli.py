"""Cross-platform entry point for the isolated Week 8 Compose lab."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

import requests

from labs.streaming_cdc.connectors import register_or_update_connector
from labs.streaming_cdc.preflight import assert_stack_memory_budget
from labs.streaming_cdc.registry import set_global_compatibility

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "labs" / "streaming_cdc" / "compose.yaml"
STATE_DIR = REPO_ROOT / "labs" / "streaming_cdc" / "_state"
EVIDENCE_DIR = REPO_ROOT / "docs" / "week8" / "evidence"
LOCAL_ENV_FILE = REPO_ROOT / "labs" / "streaming_cdc" / "w8.env"
PROJECT_NAME = "dataforge-w8"
CONNECTOR_NAME = "dataforge-w8-postgres"
DOCKER_LOCK = Path(r"D:\DATA_ENGINEER\DataForge_D_Week7_Final\DOCKER_LOCK")
REGISTRY_URL = "http://127.0.0.1:18081"
CONNECT_URL = "http://127.0.0.1:18083"
TOPICS = (
    "dataforge.dataforge_operational.orders",
    "dataforge.dataforge_operational.payment_events",
    "dataforge.dataforge_operational.change_journal",
)
ORDERS_TOPIC = TOPICS[0]
TRANSACTION_TOPIC = "dataforge.transaction"
OFFSET_AUDIT_GROUP = "dataforge-w8-offset-probe"


def _compose_command(*args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        PROJECT_NAME,
        "--file",
        str(COMPOSE_FILE),
        *args,
    ]


def _run_compose(*args: str, timeout_seconds: int | None = None) -> None:
    try:
        subprocess.run(
            _compose_command(*args),
            cwd=REPO_ROOT,
            check=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"docker compose exceeded {timeout_seconds} seconds") from exc


def _check_shared_docker_lock() -> None:
    if os.name == "nt" and DOCKER_LOCK.exists():
        owner = DOCKER_LOCK.read_text(encoding="utf-8", errors="replace").strip()
        raise RuntimeError(
            "Docker lock is present; Week 8 will not start or build containers. "
            f"Lock: {owner}"
        )


def _ensure_local_env() -> None:
    if LOCAL_ENV_FILE.is_symlink():
        raise RuntimeError(f"refusing symlinked Week 8 environment file: {LOCAL_ENV_FILE}")
    if LOCAL_ENV_FILE.exists():
        values = {}
        for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    else:
        password = secrets.token_urlsafe(32)
        values = {
            "POSTGRES_USER": "dataforge_w8",
            "POSTGRES_PASSWORD": password,
            "POSTGRES_DB": "dataforge_operational",
            "DATAFORGE_W8_DB_PASSWORD": password,
        }
        LOCAL_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_ENV_FILE.write_text(
            "".join(f"{key}={value}\n" for key, value in values.items()),
            encoding="utf-8",
        )
        if os.name != "nt":
            os.chmod(LOCAL_ENV_FILE, 0o600)

    password = values.get("DATAFORGE_W8_DB_PASSWORD") or values.get("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError(f"Week 8 env file is missing a local database password: {LOCAL_ENV_FILE}")
    values.setdefault("POSTGRES_USER", "dataforge_w8")
    values.setdefault("POSTGRES_DB", "dataforge_operational")
    values["POSTGRES_PASSWORD"] = password
    values["DATAFORGE_W8_DB_PASSWORD"] = password
    os.environ.update(values)


def _create_topics(*, timeout_seconds: int = 30) -> None:
    topics = [(topic, 3, False) for topic in TOPICS] + [
        (TRANSACTION_TOPIC, 1, False),
        ("_schemas", 1, True),
        ("dataforge-w8-connect-configs", 1, True),
        ("dataforge-w8-connect-offsets", 25, True),
        ("dataforge-w8-connect-status", 5, True),
    ]
    for topic, partitions, compact in topics:
        arguments = [
            "exec",
            "--no-TTY",
            "kafka",
            "kafka-topics",
            "--bootstrap-server",
            "kafka:9092",
            "--create",
            "--if-not-exists",
            "--topic",
            topic,
            "--partitions",
            str(partitions),
            "--replication-factor",
            "1",
        ]
        if compact:
            arguments.extend(["--config", "cleanup.policy=compact"])
        subprocess.run(
            _compose_command(*arguments),
            cwd=REPO_ROOT,
            check=True,
            timeout=timeout_seconds,
        )
    for topic in TOPICS:
        described = subprocess.run(
            _compose_command(
                "exec",
                "--no-TTY",
                "kafka",
                "kafka-topics",
                "--bootstrap-server",
                "kafka:9092",
                "--describe",
                "--topic",
                topic,
            ),
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if "PartitionCount: 3" not in described.stdout:
            raise RuntimeError(f"CDC topic {topic} does not have exactly three partitions")


def _wait_for_topic_schemas(timeout_seconds: int = 90) -> list[str]:
    missing = {f"{topic}-value" for topic in TOPICS}
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    while time.monotonic() < deadline and missing:
        for subject in tuple(missing):
            try:
                response = requests.get(
                    f"{REGISTRY_URL}/subjects/{subject}/versions", timeout=5
                )
                if response.status_code == 200 and response.json():
                    missing.remove(subject)
                else:
                    last_error = f"Schema Registry returned HTTP {response.status_code} for {subject}"
            except requests.RequestException as exc:
                last_error = str(exc)
        if not missing:
            return sorted({f"{topic}-value" for topic in TOPICS})
        time.sleep(2)
    raise TimeoutError(f"Avro subjects were not registered: {sorted(missing)}; last error={last_error}")


def _wait_for_publication_and_slot(timeout_seconds: int = 90) -> None:
    sql = """
    SELECT
      EXISTS (SELECT 1 FROM pg_publication WHERE pubname='dataforge_w8_publication'),
      EXISTS (SELECT 1 FROM pg_replication_slots
               WHERE slot_name='dataforge_w8_slot' AND plugin='pgoutput');
    """
    deadline = time.monotonic() + timeout_seconds
    last_result = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            _compose_command(
                "exec",
                "--no-TTY",
                "postgres",
                "psql",
                "--no-align",
                "--tuples-only",
                "--field-separator=|",
                "--username",
                "dataforge_w8",
                "--dbname",
                "dataforge_operational",
                "--command",
                sql,
            ),
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        last_result = result.stdout.strip()
        if last_result == "t|t":
            return
        time.sleep(2)
    raise TimeoutError(f"publication or replication slot is missing; last query result={last_result!r}")


def register_connector(
    *, wait_seconds: int = 180, deadline: float | None = None
) -> dict:
    def remaining() -> int:
        if deadline is None:
            return wait_seconds
        seconds = int(deadline - time.monotonic())
        if seconds <= 0:
            raise TimeoutError("Week 8 startup budget expired during connector registration")
        return seconds

    _check_shared_docker_lock()
    _ensure_local_env()
    _create_topics(timeout_seconds=min(30, remaining()))
    set_global_compatibility(REGISTRY_URL, "BACKWARD")
    status = register_or_update_connector(CONNECT_URL, wait_seconds=remaining())
    print(f"Debezium connector is {status['connector']['state']}")
    _wait_for_publication_and_slot(timeout_seconds=min(90, remaining()))
    subjects = _wait_for_topic_schemas(timeout_seconds=remaining())
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "connector_setup.json").write_text(
        json.dumps(
            {
                "connector": CONNECTOR_NAME,
                "connector_state": status["connector"]["state"],
                "publication": "dataforge_w8_publication",
                "slot": "dataforge_w8_slot",
                "plugin": "pgoutput",
                "replication_objects_verified": True,
                "topic_partition_count": 3,
                "registered_value_subjects": subjects,
            },
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    return status


def start_stack() -> None:
    _check_shared_docker_lock()
    available_mib, docker_mib = assert_stack_memory_budget()
    _ensure_local_env()
    print(
        f"Week 8 RAM preflight passed: host available={available_mib} MiB, "
        f"Docker total={docker_mib} MiB, Compose cap=5376 MiB"
    )
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "control").mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    budget = int(os.environ.get("DATAFORGE_W8_STARTUP_BUDGET_SEC", "180"))
    deadline = time.monotonic() + budget

    def remaining() -> int:
        seconds = int(deadline - time.monotonic())
        if seconds <= 0:
            raise TimeoutError(f"Week 8 stack did not become healthy within {budget} seconds")
        return seconds

    try:
        core_timeout = remaining()
        _run_compose(
            "up",
            "--detach",
            "--build",
            "--wait",
            "--wait-timeout",
            str(min(180, core_timeout)),
            "postgres",
            "kafka",
            timeout_seconds=core_timeout,
        )
        _create_topics(timeout_seconds=min(30, remaining()))
        services_timeout = remaining()
        _run_compose(
            "up",
            "--detach",
            "--build",
            "--wait",
            "--wait-timeout",
            str(min(180, services_timeout)),
            "schema-registry",
            "connect",
            timeout_seconds=services_timeout,
        )
        register_connector(deadline=deadline)
        _check_shared_docker_lock()
        spark_timeout = remaining()
        _run_compose(
            "up",
            "--detach",
            "--build",
            "--wait",
            "--wait-timeout",
            str(min(180, spark_timeout)),
            "spark",
            timeout_seconds=spark_timeout,
        )
    except Exception:
        try:
            _run_compose("down", "--remove-orphans", timeout_seconds=30)
        except Exception as cleanup_error:  # keep the original startup failure
            print(f"Week 8 cleanup after failed startup also failed: {cleanup_error}", file=sys.stderr)
        raise

    elapsed = round(budget - max(0, deadline - time.monotonic()), 2)
    _write_stack_evidence(elapsed, available_mib, docker_mib)
    print("Week 8 stack is healthy.")


def _write_stack_evidence(elapsed_seconds: float, host_available_mib: int, docker_mib: int) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "project": PROJECT_NAME,
        "healthy": True,
        "startup_seconds": elapsed_seconds,
        "host_available_ram_mib_before_start": host_available_mib,
        "docker_memory_mib": docker_mib,
        "compose_memory_cap_mib": 5_376,
        "captured_at": datetime.now(UTC).isoformat(),
    }
    (EVIDENCE_DIR / "stack_startup.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
    )


def stop_stack(*, remove_volumes: bool = False) -> None:
    args = ["down", "--remove-orphans"]
    if remove_volumes:
        args.append("--volumes")
    _run_compose(*args)


def reset_stack() -> None:
    """Remove only the named Week 8 volumes and ignored checkpoint directory."""
    stop_stack(remove_volumes=True)
    repo_root = REPO_ROOT.resolve()
    expected = (repo_root / "labs" / "streaming_cdc" / "_state").resolve()
    state = STATE_DIR.resolve()
    if state != expected or state == repo_root or not state.is_relative_to(repo_root):
        raise RuntimeError(f"refusing to clear unexpected Week 8 state path: {state}")
    if STATE_DIR.is_symlink():
        raise RuntimeError(f"refusing to clear symlinked Week 8 state path: {STATE_DIR}")
    if state.exists():
        shutil.rmtree(state)


def seed_source() -> None:
    _check_shared_docker_lock()
    sql = """
    INSERT INTO dataforge_operational.orders
      (order_id, customer_id, order_date, province_id, status, order_net_amount, event_time)
    VALUES
      ('w8-demo-001', 'customer-demo-001', CURRENT_DATE, 'province-demo', 'created', 42.50, clock_timestamp())
    ON CONFLICT (order_id) DO NOTHING;
    """
    subprocess.run(
        _compose_command(
            "exec",
            "--no-TTY",
            "postgres",
            "psql",
            "--set",
            "ON_ERROR_STOP=1",
            "--username",
            "dataforge_w8",
            "--dbname",
            "dataforge_operational",
            "--command",
            sql,
        ),
        cwd=REPO_ROOT,
        check=True,
    )


def mutate_source() -> None:
    _check_shared_docker_lock()
    sql = """
    BEGIN;
    INSERT INTO dataforge_operational.orders
      (order_id, customer_id, order_date, province_id, status, order_net_amount, event_time)
    VALUES
      ('w8-demo-002', 'customer-demo-002', CURRENT_DATE, 'province-demo', 'created', 85.00, clock_timestamp())
    ON CONFLICT (order_id) DO UPDATE SET
      status = EXCLUDED.status,
      order_net_amount = EXCLUDED.order_net_amount,
      event_time = EXCLUDED.event_time;
    UPDATE dataforge_operational.orders
       SET status = 'paid',
           order_net_amount = 47.50,
           event_time = clock_timestamp()
     WHERE order_id = 'w8-demo-001';
    DELETE FROM dataforge_operational.orders WHERE order_id = 'w8-seed-002';
    COMMIT;
    """
    subprocess.run(
        _compose_command(
            "exec",
            "--no-TTY",
            "postgres",
            "psql",
            "--set",
            "ON_ERROR_STOP=1",
            "--username",
            "dataforge_w8",
            "--dbname",
            "dataforge_operational",
            "--command",
            sql,
        ),
        cwd=REPO_ROOT,
        check=True,
    )


def collect_consumer_offsets() -> tuple[str, str, str]:
    """Commit a bounded audit consumer group and capture its lag report."""
    _check_shared_docker_lock()
    consume = subprocess.run(
        _compose_command(
            "exec",
            "--no-TTY",
            "kafka",
            "kafka-console-consumer",
            "--bootstrap-server",
            "kafka:9092",
            "--topic",
            ORDERS_TOPIC,
            "--group",
            OFFSET_AUDIT_GROUP,
            "--from-beginning",
            "--timeout-ms",
            "10000",
            "--consumer-property",
            "enable.auto.commit=true",
            "--consumer-property",
            "auto.commit.interval.ms=1000",
            "--property",
            "print.partition=true",
            "--property",
            "print.offset=true",
            "--property",
            "print.value=false",
        ),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    time.sleep(2)
    topic_description = subprocess.run(
        _compose_command(
            "exec",
            "--no-TTY",
            "kafka",
            "kafka-topics",
            "--bootstrap-server",
            "kafka:9092",
            "--describe",
            "--topic",
            ORDERS_TOPIC,
        ),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    describe = subprocess.run(
        _compose_command(
            "exec",
            "--no-TTY",
            "kafka",
            "kafka-consumer-groups",
            "--bootstrap-server",
            "kafka:9092",
            "--describe",
            "--group",
            OFFSET_AUDIT_GROUP,
        ),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "consumer_group_probe.txt").write_text(
        "Consumer probe output:\n"
        + consume.stdout
        + "\nTopic partition description:\n"
        + topic_description.stdout
        + "\nConsumer group describe:\n"
        + describe.stdout,
        encoding="utf-8",
    )
    return consume.stdout, topic_description.stdout, describe.stdout


def health_check() -> int:
    health_path = STATE_DIR / "health.json"
    if not health_path.exists():
        print(f"Spark health file not found: {health_path}", file=sys.stderr)
        return 1
    try:
        health = json.loads(health_path.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(health["updated_at"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"Spark health file is invalid: {exc}", file=sys.stderr)
        return 1
    age_seconds = (datetime.now(UTC) - updated.astimezone(UTC)).total_seconds()
    if health.get("status") != "ready" or age_seconds > 30:
        print(f"Spark is not healthy: status={health.get('status')}, age={age_seconds:.1f}s")
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("up", help="start the pinned Week 8 stack")
    down_parser = subparsers.add_parser("down", help="stop the Week 8 stack")
    down_parser.add_argument("--volumes", action="store_true", help="also remove Kafka/Postgres volumes")
    subparsers.add_parser("seed", help="insert one deterministic demonstration order")
    subparsers.add_parser("mutate", help="insert/update/delete demonstration orders")
    subparsers.add_parser("register-connector", help="register or update the Debezium source connector")
    subparsers.add_parser("offsets", help="capture a Kafka consumer-group offset/lag report")
    subparsers.add_parser("reset", help="stop Week 8 and clear its volumes and ignored state")
    subparsers.add_parser("health", help="check the local Spark application health file")

    args = parser.parse_args(argv)
    try:
        if args.command == "up":
            start_stack()
        elif args.command == "down":
            stop_stack(remove_volumes=args.volumes)
        elif args.command == "seed":
            seed_source()
        elif args.command == "mutate":
            mutate_source()
        elif args.command == "register-connector":
            register_connector()
        elif args.command == "offsets":
            consumed, topic_description, described = collect_consumer_offsets()
            print(consumed)
            print(topic_description)
            print(described)
        elif args.command == "reset":
            reset_stack()
        elif args.command == "health":
            return health_check()
        else:  # pragma: no cover - argparse enforces the command set
            parser.error(f"unsupported command: {args.command}")
    except (OSError, RuntimeError, requests.RequestException, subprocess.CalledProcessError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through CLI
    raise SystemExit(main())
