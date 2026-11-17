from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest

if os.environ.get("RUN_DATAFORGE_W8_INTEGRATION") != "1":
    pytest.skip("Week 8 Compose integration suite is opt-in", allow_module_level=True)

psycopg = pytest.importorskip("psycopg", reason="Week 8 integration dependencies are required")
requests = pytest.importorskip("requests", reason="Week 8 integration dependencies are required")
pytest.importorskip("kafka", reason="Week 8 Kafka probe dependency is required")
fastavro = pytest.importorskip("fastavro", reason="Week 8 Avro probe dependency is required")

KafkaConsumer = importlib.import_module("kafka").KafkaConsumer
decode_confluent_avro = importlib.import_module(
    "labs.streaming_cdc.envelopes"
).decode_confluent_avro
unpack_confluent_frame = importlib.import_module(
    "labs.streaming_cdc.envelopes"
).unpack_confluent_frame
subject_schemas = importlib.import_module("labs.streaming_cdc.registry").subject_schemas
schemaless_reader = fastavro.schemaless_reader
parse_schema = fastavro.parse_schema

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_ID = uuid.uuid4().hex[:8]
STATE_DIR = REPO_ROOT / "labs" / "streaming_cdc" / "_state"
LOCAL_ENV_FILE = REPO_ROOT / "labs" / "streaming_cdc" / "w8.env"
EVIDENCE_DIR = REPO_ROOT / "docs" / "week8" / "evidence"
GOLD_TEST_EVENTS_DIR = STATE_DIR / "test_events"
COMPOSE_FILE = REPO_ROOT / "labs" / "streaming_cdc" / "compose.yaml"
PROJECT = "dataforge-w8"
SPARK_URL = "http://127.0.0.1:17079"
REGISTRY_URL = "http://127.0.0.1:18081"
ORDERS_TOPIC = "dataforge.dataforge_operational.orders"
VALUE_SUBJECT = f"{ORDERS_TOPIC}-value"
KEY_SUBJECT = f"{ORDERS_TOPIC}-key"
T4_ORDER_ID = f"w8-{RUN_ID}-t4-sequence"
BASE_FIELDS = (
    "order_id",
    "customer_id",
    "order_date",
    "province_id",
    "status",
    "order_net_amount",
    "event_time",
)


def _local_db_password() -> str:
    values = {}
    for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    password = values.get("DATAFORGE_W8_DB_PASSWORD") or values.get("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("Week 8 local env file has no database password")
    return password


DB_DSN = (
    "host=127.0.0.1 port=55433 dbname=dataforge_operational "
    f"user=dataforge_w8 password={_local_db_password()}"
)


def _compose(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            PROJECT,
            "--file",
            str(COMPOSE_FILE),
            *args,
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _db_execute(statement: str, params: tuple | None = None) -> None:
    with psycopg.connect(DB_DSN, autocommit=True) as connection:
        connection.execute(statement, params or ())


def _replica_identity() -> dict[str, str]:
    with psycopg.connect(DB_DSN) as connection:
        rows = connection.execute(
            """
            SELECT c.relname, c.relreplident
              FROM pg_class AS c
              JOIN pg_namespace AS n ON n.oid = c.relnamespace
             WHERE n.nspname = 'dataforge_operational'
               AND c.relname = ANY(%s)
            """,
            (["orders", "payment_events", "change_journal"],),
        ).fetchall()
    return {str(name): str(identity) for name, identity in rows}


def _write_gold_test_event(filename: str, payload: dict) -> None:
    GOLD_TEST_EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    (GOLD_TEST_EVENTS_DIR / filename).write_text(
        json.dumps(payload, sort_keys=True, default=str), encoding="utf-8"
    )


def _insert_order(
    order_id: str,
    *,
    amount: str = "10.00",
    status: str = "created",
    province_id: str = "province-test",
    event_time: datetime | None = None,
) -> None:
    _db_execute(
        """
        INSERT INTO dataforge_operational.orders
          (order_id, customer_id, order_date, province_id, status, order_net_amount, event_time)
        VALUES (%s, %s, CURRENT_DATE, %s, %s, %s, %s)
        ON CONFLICT (order_id) DO UPDATE SET
          province_id = EXCLUDED.province_id,
          status = EXCLUDED.status,
          order_net_amount = EXCLUDED.order_net_amount,
          event_time = EXCLUDED.event_time
        """,
        (
            order_id,
            f"customer-{order_id}",
            province_id,
            status,
            Decimal(amount),
            event_time or datetime.now(UTC),
        ),
    )


def _update_order(order_id: str, *, status: str, amount: str, event_time=None) -> None:
    _db_execute(
        """
        UPDATE dataforge_operational.orders
           SET status = %s, order_net_amount = %s, event_time = %s
         WHERE order_id = %s
        """,
        (status, Decimal(amount), event_time or datetime.now(UTC), order_id),
    )


def _source_rows() -> list[dict]:
    with psycopg.connect(DB_DSN) as connection:
        cursor = connection.execute(
            """
            SELECT order_id, customer_id, order_date, province_id, status,
                   order_net_amount, event_time
              FROM dataforge_operational.orders
             ORDER BY order_id
            """
        )
        return [dict(zip(BASE_FIELDS, row, strict=True)) for row in cursor.fetchall()]


def _get_json(route: str, *, timeout: int = 10):
    response = requests.get(f"{SPARK_URL}{route}", timeout=timeout)
    response.raise_for_status()
    return response.json()


def _canonical_timestamp(value) -> str:
    if isinstance(value, datetime):
        timestamp = value
    else:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC).isoformat(timespec="microseconds")


def _canonical_row(row: dict) -> dict[str, str]:
    return {
        "order_id": str(row["order_id"]),
        "customer_id": str(row["customer_id"]),
        "order_date": str(row["order_date"]),
        "province_id": str(row["province_id"]),
        "status": str(row["status"]),
        "order_net_amount": format(
            Decimal(str(row["order_net_amount"])).quantize(Decimal("0.01")), "f"
        ),
        "event_time": _canonical_timestamp(row["event_time"]),
    }


def _row_hashes(rows: list[dict]) -> list[tuple[str, str]]:
    result = []
    for row in rows:
        normalized = _canonical_row(row)
        digest = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        result.append((normalized["order_id"], digest))
    return sorted(result)


def _wait_until(predicate, label: str, *, timeout: int = 60, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (requests.RequestException, FileNotFoundError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {label}; last error={last_error}")


def _wait_for_silver_row(order_id: str, *, timeout: int = 60) -> dict:
    def find_row():
        rows = _get_json("/tables/silver")
        return next((row for row in rows if row.get("order_id") == order_id), None)

    return _wait_until(find_row, f"silver order {order_id}", timeout=timeout)


def _current_silver_hashes() -> dict[str, str]:
    return _row_hashes(_get_json("/tables/silver"))


def _wait_for_source_parity(timeout: int = 60) -> tuple[dict[str, str], dict[str, str]]:
    last_state: dict[str, object] = {}

    def matches():
        source_rows = _source_rows()
        silver_rows = _get_json("/tables/silver")
        source_hashes = _row_hashes(source_rows)
        silver_hashes = _row_hashes(silver_rows)
        source_by_id = {row["order_id"]: row for row in source_rows}
        silver_by_id = {row["order_id"]: row for row in silver_rows}
        last_state.update(
            {
                "source_rows": source_rows,
                "silver_rows": silver_rows,
                "source_hashes": source_hashes,
                "silver_hashes": silver_hashes,
                "source_only_ids": sorted(set(source_by_id) - set(silver_by_id)),
                "silver_only_ids": sorted(set(silver_by_id) - set(source_by_id)),
                "mismatched_rows": {
                    order_id: {"source": source_by_id[order_id], "silver": silver_by_id[order_id]}
                    for order_id in sorted(set(source_by_id) & set(silver_by_id))
                    if _row_hashes([source_by_id[order_id]])
                    != _row_hashes([silver_by_id[order_id]])
                },
            }
        )
        return (source_hashes, silver_hashes) if source_hashes == silver_hashes else None

    try:
        return _wait_until(matches, "silver row hashes to equal the Postgres source", timeout=timeout)
    except AssertionError:
        _write_evidence("t1_parity_failure.json", last_state)
        raise


def _latest_progress(name: str) -> dict:
    return _get_json(f"/progress/{name}")


def _progress_offsets(progress: dict) -> tuple[str, ...]:
    return tuple(str(source.get("endOffset")) for source in progress.get("sources", []))


def _test_event_offset(progress: dict) -> str | None:
    return next(
        (
            str(source.get("endOffset"))
            for source in progress.get("sources", [])
            if "test_events" in str(source.get("description", ""))
        ),
        None,
    )


def _wait_for_test_event_file(previous: dict, label: str) -> dict:
    previous_offset = _test_event_offset(previous)
    assert previous_offset is not None, "gold query has no CDC test-file source"

    def advanced():
        current = _latest_progress("gold")
        offset = _test_event_offset(current)
        return current if offset is not None and offset != previous_offset else None

    return _wait_until(advanced, label, timeout=60)


def _wait_for_gold_progress_after(previous: dict, minimum_event_time: datetime, label: str) -> dict:
    previous_offsets = _progress_offsets(previous)

    def advanced():
        current = _latest_progress("gold")
        event_time = current.get("eventTime", {}).get("max")
        offsets = _progress_offsets(current)
        if event_time is None or offsets == previous_offsets:
            return None
        observed = datetime.fromisoformat(str(event_time).replace("Z", "+00:00"))
        if observed.astimezone(UTC) < minimum_event_time.astimezone(UTC):
            return None
        return current

    return _wait_until(advanced, label, timeout=60)


def _write_evidence(filename: str, payload: dict | str) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / filename
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, sort_keys=True, indent=2, default=str), encoding="utf-8")


def test_t1_snapshot_insert_update_delete_matches_postgres_by_row_hash():
    connector_setup = json.loads(
        (EVIDENCE_DIR / "connector_setup.json").read_text(encoding="utf-8")
    )
    assert connector_setup["connector_state"] == "RUNNING"
    assert connector_setup["replication_objects_verified"] is True
    assert connector_setup["heartbeat_topic"] == "__debezium-heartbeat.dataforge"
    replica_identity = _replica_identity()
    assert replica_identity == {
        "orders": "f",
        "payment_events": "f",
        "change_journal": "f",
    }
    assert set(connector_setup["registered_value_subjects"]) == {
        f"{topic}-value" for topic in (
            ORDERS_TOPIC,
            "dataforge.dataforge_operational.payment_events",
            "dataforge.dataforge_operational.change_journal",
        )
    }
    _wait_for_silver_row("w8-seed-001")
    _wait_for_silver_row("w8-seed-002")
    _insert_order(f"w8-{RUN_ID}-t1-001", amount="10.00")
    _insert_order(f"w8-{RUN_ID}-t1-002", amount="20.00")
    _insert_order(f"w8-{RUN_ID}-t1-003", amount="30.00")
    _update_order(f"w8-{RUN_ID}-t1-001", status="paid", amount="12.50")
    _update_order("w8-seed-001", status="settled", amount="121.00")
    _db_execute(
        "DELETE FROM dataforge_operational.orders WHERE order_id = %s",
        (f"w8-{RUN_ID}-t1-002",),
    )

    source_hashes, silver_hashes = _wait_for_source_parity(timeout=60)
    assert silver_hashes == source_hashes
    silver_ids = [order_id for order_id, _ in silver_hashes]
    assert len(silver_ids) == len(set(silver_ids))
    assert f"w8-{RUN_ID}-t1-001" in silver_ids
    assert f"w8-{RUN_ID}-t1-002" not in silver_ids
    assert f"w8-{RUN_ID}-t1-003" in silver_ids
    _write_evidence(
        "t1_row_hashes.json",
        {
            "source_rows": len(source_hashes),
            "silver_rows": len(silver_hashes),
            "replica_identity_full": replica_identity,
            "hashes": [{"order_id": order_id, "sha256": digest} for order_id, digest in silver_hashes],
        },
    )


def test_t2_restart_replays_uncheckpointed_sink_batch_without_duplicates():
    control = STATE_DIR / "control"
    pause_path = control / "pause_after_sink"
    applied_path = control / "sink_applied.json"
    pause_path.parent.mkdir(parents=True, exist_ok=True)
    pause_path.write_text("pause", encoding="utf-8")
    applied_path.unlink(missing_ok=True)

    order_id = f"w8-{RUN_ID}-t2-restart"
    _insert_order(order_id, amount="51.00")
    _wait_until(
        lambda: applied_path.exists() and any(
            row.get("order_id") == order_id for row in _get_json("/tables/silver")
        ),
        "silver commit before the Spark checkpoint",
        timeout=60,
    )

    _compose("kill", "--signal", "SIGKILL", "spark")
    pause_path.unlink(missing_ok=True)
    applied_path.unlink(missing_ok=True)
    _compose("up", "--detach", "--wait", "--wait-timeout", "180", "spark")
    _wait_for_silver_row(order_id, timeout=120)
    parity = _wait_for_source_parity(timeout=60)
    rows = [row for row in _get_json("/tables/silver") if row.get("order_id") == order_id]
    assert len(rows) == 1
    assert parity[0] == parity[1]
    _write_evidence("t2_restart.json", {"order_id": order_id, "duplicates": 0, "parity": True})


def test_t3_replaying_the_same_microbatch_leaves_delta_unchanged():
    order_id = f"w8-{RUN_ID}-t3-replay"
    _insert_order(order_id, amount="33.00")
    _wait_for_silver_row(order_id)

    def latest_batch():
        metadata = _get_json("/batch/latest")
        return metadata if metadata.get("batch_id") is not None else None

    before = _row_hashes(_get_json("/tables/silver"))
    metadata = _wait_until(latest_batch, "latest persisted Silver microbatch", timeout=30)
    response = requests.post(
        f"{SPARK_URL}/admin/replay",
        json={"batch_id": int(metadata["batch_id"])},
        timeout=30,
    )
    response.raise_for_status()
    replay = response.json()
    after = _row_hashes(_get_json("/tables/silver"))
    assert replay["applied"] is False
    assert after == before
    _write_evidence("t3_replay.json", {"batch_id": replay["batch_id"], "unchanged": True})


def test_t4_rapid_per_key_updates_end_at_last_lsn_and_partition():
    order_id = T4_ORDER_ID
    _insert_order(order_id, status="seq-00", amount="100.00")
    for index in range(1, 16):
        _update_order(order_id, status=f"seq-{index:02d}", amount=f"{100 + index:.2f}")
    row = _wait_until(
        lambda: next(
            (
                item
                for item in _get_json("/tables/silver")
                if item.get("order_id") == order_id and item.get("status") == "seq-15"
            ),
            None,
        ),
        "last per-key update in Silver",
        timeout=60,
    )
    assert Decimal(str(row["order_net_amount"])) == Decimal("115.00")

    key_schemas = subject_schemas(REGISTRY_URL, KEY_SUBJECT)
    value_schemas = subject_schemas(REGISTRY_URL, VALUE_SUBJECT)
    consumer = KafkaConsumer(
        ORDERS_TOPIC,
        bootstrap_servers=["127.0.0.1:19093"],
        group_id=f"w8-key-order-{uuid.uuid4().hex}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        consumer_timeout_ms=10000,
    )
    partitions: set[int] = set()
    lsns: list[int] = []
    for record in consumer:
        key_frame = unpack_confluent_frame(record.key)
        if key_frame is None:
            continue
        key_schema_id, key_payload = key_frame
        key = schemaless_reader(BytesIO(key_payload), parse_schema(key_schemas[key_schema_id]))
        if key.get("order_id") != order_id:
            continue
        partitions.add(int(record.partition))
        decoded = decode_confluent_avro(record.value, schemas_by_id=value_schemas, key=key)
        if decoded.source_lsn is not None:
            lsns.append(decoded.source_lsn)
    consumer.close(autocommit=False)

    assert len(partitions) == 1
    assert lsns
    assert lsns == sorted(lsns)
    _write_evidence(
        "t4_per_key_order.json",
        {"order_id": order_id, "partition": next(iter(partitions)), "lsns": lsns},
    )


def test_t5_watermark_accepts_recent_late_event_drops_old_event_and_reports_metrics():
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    window_floor = now.replace(minute=(now.minute // 5) * 5)
    anchor = window_floor + timedelta(minutes=2)
    progress_history = EVIDENCE_DIR / "streaming_progress.jsonl"
    initial_size = progress_history.stat().st_size if progress_history.exists() else 0
    province_id = f"province-t5-late-{RUN_ID}"
    anchor_order = f"w8-{RUN_ID}-t5-anchor"
    within_order = f"w8-{RUN_ID}-t5-within"
    beyond_order = f"w8-{RUN_ID}-t5-beyond"

    def event(order_id: str, lsn: int, event_time: datetime, province: str, amount: str):
        return {
            "order_id": order_id,
            "source_lsn": lsn,
            "transaction_order": 1,
            "event_time": event_time.isoformat(),
            "op": "upsert",
            "before_province_id": None,
            "before_order_net_amount": None,
            "after_province_id": province,
            "after_order_net_amount": amount,
        }

    previous = _latest_progress("gold")
    anchor_file_event = event(anchor_order, 880_001, anchor, province_id, "1.00")
    _write_gold_test_event(f"{RUN_ID}-t5-01-anchor.json", anchor_file_event)
    progress = _wait_for_test_event_file(previous, "gold query to consume the watermark anchor")
    event_max = datetime.fromisoformat(
        str(progress.get("eventTime", {}).get("max")).replace("Z", "+00:00")
    )
    assert event_max.astimezone(UTC) >= anchor.astimezone(UTC)

    duplicate = event(anchor_order, 880_001, anchor, province_id, "999.00")
    duplicate["transaction_order"] = 1
    previous = progress
    _write_gold_test_event(f"{RUN_ID}-t5-02-duplicate.json", duplicate)
    progress = _wait_for_test_event_file(previous, "gold query to consume the duplicate CDC event")

    within_time = anchor - timedelta(minutes=1)
    previous = progress
    _write_gold_test_event(
        f"{RUN_ID}-t5-03-within.json",
        event(within_order, 880_002, within_time, province_id, "22.00"),
    )
    progress = _wait_for_test_event_file(previous, "gold query to consume an in-watermark event")
    beyond_time = anchor - timedelta(minutes=20)
    previous = progress
    _write_gold_test_event(
        f"{RUN_ID}-t5-04-beyond.json",
        event(beyond_order, 880_003, beyond_time, f"province-t5-dropped-{RUN_ID}", "33.00"),
    )
    progress = _wait_for_test_event_file(previous, "gold query to consume an out-of-watermark event")

    def window_total():
        return next(
            (
                row
                for row in _get_json("/tables/gold")
                if row.get("province_id") == province_id
                and Decimal(str(row.get("revenue_delta"))) == Decimal("23.00")
            ),
            None,
        )

    within_row = _wait_until(window_total, "merged in-watermark revenue window", timeout=90)
    gold_rows = _get_json("/tables/gold")
    assert not any(row.get("province_id") == f"province-t5-dropped-{RUN_ID}" for row in gold_rows)

    history_lines = []
    if progress_history.exists():
        with progress_history.open("r", encoding="utf-8") as history:
            history.seek(initial_size)
            history_lines = [json.loads(line) for line in history if line.strip()]
    dropped = [
        int(operator.get("numRowsDroppedByWatermark", 0))
        for progress_item in history_lines
        if progress_item.get("name") == "gold_revenue_5m"
        for operator in progress_item.get("stateOperators", [])
    ]
    assert any(value > 0 for value in dropped)
    latest = _latest_progress("gold")
    assert latest.get("stateOperators")
    _write_evidence(
        "t5_watermark.json",
        {"within_window": within_row, "dropped_by_watermark": max(dropped), "latest_progress": latest},
    )


def test_t6_nullable_schema_addition_flows_and_breaking_schema_is_rejected():
    nullable_field = f"nullable_note_{RUN_ID}"
    topic_versions_url = f"{REGISTRY_URL}/subjects/{VALUE_SUBJECT}/versions"
    prior_versions = requests.get(topic_versions_url, timeout=10)
    prior_versions.raise_for_status()
    prior_count = len(prior_versions.json())

    _compose("stop", "spark")
    _db_execute(
        f"ALTER TABLE dataforge_operational.orders ADD COLUMN IF NOT EXISTS {nullable_field} TEXT"
    )
    _db_execute(
        f"UPDATE dataforge_operational.orders SET {nullable_field}=%s, event_time=clock_timestamp() WHERE order_id=%s",
        ("backward-compatible", T4_ORDER_ID),
    )
    def new_schema_versions():
        result = requests.get(topic_versions_url, timeout=5)
        result.raise_for_status()
        versions = result.json()
        return versions if len(versions) > prior_count else None

    versions = _wait_until(
        new_schema_versions,
        "nullable Avro schema version registration",
        timeout=60,
    )
    assert len(versions) > prior_count
    _compose("up", "--detach", "--wait", "--wait-timeout", "180", "spark")
    row = _wait_until(
        lambda: next(
            (
                item
                for item in _get_json("/tables/silver")
                if item.get("order_id") == T4_ORDER_ID
                and item.get(nullable_field) == "backward-compatible"
            ),
            None,
        ),
        "nullable field through the Avro reader and Delta merge",
        timeout=90,
    )

    latest = requests.get(
        f"{REGISTRY_URL}/subjects/{VALUE_SUBJECT}/versions/latest", timeout=10
    )
    latest.raise_for_status()
    schema = json.loads(latest.json()["schema"])

    def make_breaking(node) -> bool:
        if isinstance(node, dict):
            if node.get("name") == "order_net_amount" and "type" in node:
                node["type"] = ["null", "string"]
                node["default"] = None
                return True
            for value in node.values():
                if make_breaking(value):
                    return True
        elif isinstance(node, list):
            for value in node:
                if make_breaking(value):
                    return True
        return False

    assert make_breaking(schema)
    registration = requests.post(
        f"{REGISTRY_URL}/subjects/{VALUE_SUBJECT}/versions",
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
        json={"schema": json.dumps(schema)},
        timeout=10,
    )
    assert registration.status_code in {409, 422}
    _write_evidence(
        "t6_schema_evolution.json",
        {
            "nullable_versions": len(versions),
            "nullable_field": nullable_field,
            "flowed_value": row.get(nullable_field),
            "breaking_status": registration.status_code,
        },
    )


def test_t7_consumer_group_offsets_show_zero_lag_after_catchup():
    cli = importlib.import_module("labs.streaming_cdc.cli")
    consumed, topic_description, described = cli.collect_consumer_offsets()
    assert all(
        re.search(rf"Partition:\s*{partition}\b", topic_description) for partition in range(3)
    )
    assert "LAG" in described
    assert ORDERS_TOPIC in described
    partition_lines = [line for line in described.splitlines() if ORDERS_TOPIC in line]
    assert partition_lines
    for line in partition_lines:
        fields = re.split(r"\s+", line.strip())
        assert len(fields) >= 6
        assert fields[3] not in {"-", "-1"}
        assert fields[5] == "0"
    history = _get_json("/history/silver")
    assert history
    assert any(row.get("operation") == "MERGE" for row in history)
    _write_evidence(
        "t7_consumer_groups.txt",
        f"Consumed records:\n{consumed}\nTopic partitions:\n{topic_description}\n{described}",
    )
    _write_evidence("delta_silver_history.json", history)
