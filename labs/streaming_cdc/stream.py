"""Spark Structured Streaming jobs for the Week 8 CDC lab."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from labs.streaming_cdc.merge import merge_order_changes
from labs.streaming_cdc.registry import latest_subject_schema, subject_schemas
from labs.streaming_cdc.windows import build_windowed_revenue

LOGGER = logging.getLogger("dataforge.week8.streaming")
TOPIC = "dataforge.dataforge_operational.orders"
VALUE_SUBJECT = f"{TOPIC}-value"
SILVER_APP_ID = "dataforge-w8-silver-orders"
WINDOW_DURATION = "5 minutes"
WATERMARK_DURATION = "10 minutes"
HTTP_PORT = 7079


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2), encoding="utf-8")
    temporary.replace(path)


def _schema_decoder(spark: Any, kafka_df: Any, registry_url: str) -> Any:
    """Decode Confluent's 5-byte framing, selecting writer schema by ID.

    Every writer schema is decoded with its own registry schema and the latest
    BACKWARD-compatible reader schema. That lets an added nullable field flow
    into the Spark struct after the query restarts and refreshes its schema map.
    """
    from pyspark.sql import functions as F
    from pyspark.sql.avro.functions import from_avro

    writer_schemas = subject_schemas(registry_url, VALUE_SUBJECT)
    if not writer_schemas:
        raise RuntimeError(f"Schema Registry has no writer schemas for {VALUE_SUBJECT}")
    reader_schema = json.dumps(latest_subject_schema(registry_url, VALUE_SUBJECT))
    schema_id = F.conv(F.hex(F.substring(F.col("value"), 2, 4)), 16, 10).cast("long")
    payload = F.substring(F.col("value"), 6, F.length(F.col("value")) - 5)

    event = None
    for schema_id_value, writer_schema in sorted(writer_schemas.items()):
        decoded = from_avro(
            payload,
            json.dumps(writer_schema),
            {"avroSchema": reader_schema, "mode": "PERMISSIVE"},
        )
        branch = F.when(schema_id == F.lit(schema_id_value), decoded)
        event = branch if event is None else branch.otherwise(event)
    return kafka_df.withColumn("event", event)


def _normalized_order_changes(event_df: Any) -> Any:
    from pyspark.sql import functions as F

    op = F.coalesce(F.col("event.op"), F.lit("tombstone"))
    row = F.when(op == F.lit("d"), F.col("event.before")).otherwise(F.col("event.after"))
    return event_df.select(
        row["order_id"].cast("string").alias("order_id"),
        row["customer_id"].cast("string").alias("customer_id"),
        row["order_date"].alias("order_date"),
        row["province_id"].cast("string").alias("province_id"),
        row["status"].cast("string").alias("status"),
        row["order_net_amount"].alias("order_net_amount"),
        F.to_timestamp(row["event_time"]).alias("event_time"),
        F.col("event.source.lsn").cast("long").alias("source_lsn"),
        F.col("event.transaction.total_order").cast("long").alias("transaction_order"),
        F.col("event.ts_ms").cast("long").alias("source_ts_ms"),
        op.alias("op"),
    )


def _signed_revenue_changes(event_df: Any) -> Any:
    from pyspark.sql import functions as F

    op = F.coalesce(F.col("event.op"), F.lit("tombstone"))
    before = event_df.filter(op.isin("u", "d")).select(
        F.to_timestamp(F.col("event.before.event_time")).alias("event_time"),
        F.col("event.before.province_id").cast("string").alias("province_id"),
        (-F.col("event.before.order_net_amount")).alias("revenue_delta"),
    )
    after = event_df.filter(op.isin("c", "u", "r")).select(
        F.to_timestamp(F.col("event.after.event_time")).alias("event_time"),
        F.col("event.after.province_id").cast("string").alias("province_id"),
        F.col("event.after.order_net_amount").alias("revenue_delta"),
    )
    return before.unionByName(after)


def _wait_if_paused(state_dir: Path, batch_id: int) -> None:
    pause = state_dir / "control" / "pause_after_sink"
    if not pause.exists():
        return
    _write_json(
        state_dir / "control" / "sink_applied.json",
        {"batch_id": int(batch_id), "applied_at": datetime.now(UTC).isoformat()},
    )
    LOGGER.warning("Test pause after sink commit for Spark batch %s", batch_id)
    while pause.exists():
        time.sleep(0.1)


def _make_http_handler(
    *,
    spark: Any,
    state_dir: Path,
    evidence_dir: Path,
    silver_path: Path,
    gold_path: Path,
    queries: dict[str, Any],
):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _table_rows(self, path: Path) -> list[dict[str, Any]]:
            from delta.tables import DeltaTable

            if not DeltaTable.isDeltaTable(spark, str(path)):
                return []
            rows = spark.read.format("delta").load(str(path)).orderBy("order_id").toJSON().collect()
            return [json.loads(row) for row in rows]

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            route = urlparse(self.path).path
            if route == "/health":
                self._send(
                    200,
                    {
                        "status": "ready" if all(query.isActive for query in queries.values()) else "starting",
                        "updated_at": datetime.now(UTC).isoformat(),
                        "queries": {name: query.status for name, query in queries.items()},
                    },
                )
                return
            if route == "/tables/silver":
                self._send(200, self._table_rows(silver_path))
                return
            if route == "/history/silver":
                from delta.tables import DeltaTable

                if not DeltaTable.isDeltaTable(spark, str(silver_path)):
                    self._send(200, [])
                    return
                history = (
                    spark.sql(f"DESCRIBE HISTORY delta.`{silver_path}`")
                    .limit(20)
                    .orderBy("version")
                    .toJSON()
                    .collect()
                )
                self._send(200, [json.loads(row) for row in history])
                return
            if route == "/tables/gold":
                from delta.tables import DeltaTable

                if not DeltaTable.isDeltaTable(spark, str(gold_path)):
                    self._send(200, [])
                    return
                rows = (
                    spark.read.format("delta")
                    .load(str(gold_path))
                    .orderBy("window.start", "province_id")
                    .toJSON()
                    .collect()
                )
                self._send(200, [json.loads(row) for row in rows])
                return
            if route in {"/progress/silver", "/progress/gold"}:
                name = route.rsplit("/", 1)[1]
                path = evidence_dir / f"{name}_progress.json"
                self._send(200, json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})
                return
            if route == "/batch/latest":
                path = state_dir / "replay" / "latest.json"
                self._send(200, json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})
                return
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if urlparse(self.path).path != "/admin/replay":
                self._send(404, {"error": "not found"})
                return
            size = int(self.headers.get("Content-Length", "0"))
            request_body = json.loads(self.rfile.read(size) or b"{}")
            metadata_path = state_dir / "replay" / "latest.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            batch_id = int(request_body.get("batch_id", metadata["batch_id"]))
            if batch_id != int(metadata["batch_id"]):
                self._send(400, {"error": "only the most recent batch is retained for replay"})
                return
            batch = spark.read.parquet(metadata["path"])
            applied = merge_order_changes(
                batch,
                silver_path,
                batch_id=batch_id,
                transaction_app_id=SILVER_APP_ID,
            )
            self._send(200, {"batch_id": batch_id, "applied": applied})

        def log_message(self, format: str, *args: Any) -> None:
            LOGGER.info("stream status API: " + format, *args)

    return Handler


def _start_status_server(
    *,
    spark: Any,
    state_dir: Path,
    evidence_dir: Path,
    silver_path: Path,
    gold_path: Path,
    queries: dict[str, Any],
) -> ThreadingHTTPServer:
    handler = _make_http_handler(
        spark=spark,
        state_dir=state_dir,
        evidence_dir=evidence_dir,
        silver_path=silver_path,
        gold_path=gold_path,
        queries=queries,
    )
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="w8-status-api")
    thread.start()
    return server


def _start_progress_listener(spark: Any, evidence_dir: Path):
    from pyspark.sql.streaming import StreamingQueryListener

    class Listener(StreamingQueryListener):
        def onQueryStarted(self, event: Any) -> None:  # noqa: N802 - Spark API
            LOGGER.info("Started query %s (%s)", event.name, event.id)

        def onQueryProgress(self, event: Any) -> None:  # noqa: N802 - Spark API
            progress = json.loads(event.progress.json)
            name = progress.get("name") or "unknown"
            output = "silver_progress.json" if name == "silver_orders_cdc" else "gold_progress.json"
            _write_json(evidence_dir / output, progress)
            history_path = evidence_dir / "streaming_progress.jsonl"
            history_path.parent.mkdir(parents=True, exist_ok=True)
            with history_path.open("a", encoding="utf-8") as history:
                history.write(json.dumps(progress, sort_keys=True) + "\n")

        def onQueryTerminated(self, event: Any) -> None:  # noqa: N802 - Spark API
            LOGGER.error("Query %s terminated: %s", event.id, event.exception)

    listener = Listener()
    spark.streams.addListener(listener)
    return listener


def _health_heartbeat(state_dir: Path, queries: dict[str, Any], stop: threading.Event) -> None:
    path = state_dir / "health.json"
    while not stop.is_set():
        active = bool(queries) and all(query.isActive for query in queries.values())
        _write_json(
            path,
            {
                "status": "ready" if active else "starting",
                "updated_at": datetime.now(UTC).isoformat(),
                "queries": {name: query.status for name, query in queries.items()},
            },
        )
        stop.wait(5)


def run_streaming_app() -> None:
    from delta import configure_spark_with_delta_pip
    from pyspark.sql import SparkSession

    logging.basicConfig(level=os.environ.get("DATAFORGE_W8_LOG_LEVEL", "INFO"))
    state_dir = Path(os.environ.get("DATAFORGE_W8_STATE_DIR", "labs/streaming_cdc/_state"))
    evidence_dir = Path(os.environ.get("DATAFORGE_W8_EVIDENCE_DIR", "docs/week8/evidence"))
    state_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    package_list = ",".join(
        [
            "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.9",
            "org.apache.spark:spark-avro_2.12:3.5.9",
        ]
    )
    builder = (
        SparkSession.builder.appName("dataforge-week8-cdc")
        .master("local[2]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.ui.enabled", "true")
        .config("spark.ui.port", "4040")
        .config("spark.ui.bindAddress", "0.0.0.0")
        .config("spark.driver.bindAddress", "0.0.0.0")
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.memory", "1g")
        .config("spark.driver.maxResultSize", "256m")
        .config("spark.jars.packages", package_list)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
    )
    spark = configure_spark_with_delta_pip(builder, extra_packages=[]).getOrCreate()
    spark.sparkContext.setLogLevel(os.environ.get("DATAFORGE_W8_SPARK_LOG_LEVEL", "WARN"))

    brokers = os.environ.get("DATAFORGE_W8_BROKERS", "kafka:9092")
    registry_url = os.environ.get(
        "DATAFORGE_W8_SCHEMA_REGISTRY", "http://schema-registry:8081"
    )
    silver_path = state_dir / "delta" / "silver_orders_cdc"
    gold_path = state_dir / "delta" / "gold_revenue_5m"
    checkpoint_root = state_dir / "checkpoints"

    topic = os.environ.get("DATAFORGE_W8_TOPIC", TOPIC)
    raw = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", brokers)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("maxOffsetsPerTrigger", "1000")
        .option("failOnDataLoss", "false")
        .load()
    )
    decoded = _schema_decoder(spark, raw, registry_url)
    order_changes = _normalized_order_changes(decoded)
    revenue_changes = _signed_revenue_changes(decoded)
    windowed = build_windowed_revenue(
        revenue_changes,
        event_time_column="event_time",
        revenue_delta_column="revenue_delta",
        window_duration=WINDOW_DURATION,
        watermark_duration=WATERMARK_DURATION,
    )

    def apply_silver_batch(batch_df: Any, batch_id: int) -> None:
        if batch_df.rdd.isEmpty():
            return
        replay_path = state_dir / "replay" / "silver_latest"
        batch_df.write.mode("overwrite").parquet(str(replay_path))
        _write_json(
            state_dir / "replay" / "latest.json",
            {"batch_id": int(batch_id), "path": str(replay_path)},
        )
        merge_order_changes(
            batch_df,
            silver_path,
            batch_id=int(batch_id),
            transaction_app_id=SILVER_APP_ID,
        )
        _wait_if_paused(state_dir, int(batch_id))

    _start_progress_listener(spark, evidence_dir)
    queries: dict[str, Any] = {}
    silver_query = (
        order_changes.writeStream.queryName("silver_orders_cdc")
        .outputMode("append")
        .option("checkpointLocation", str(checkpoint_root / "silver"))
        .foreachBatch(apply_silver_batch)
        .trigger(processingTime="1 second")
        .start()
    )
    queries["silver_orders_cdc"] = silver_query
    gold_query = (
        windowed.writeStream.queryName("gold_revenue_5m")
        .outputMode("append")
        .format("delta")
        .option("checkpointLocation", str(checkpoint_root / "gold"))
        .trigger(processingTime="1 second")
        .start(str(gold_path))
    )
    queries["gold_revenue_5m"] = gold_query

    server = _start_status_server(
        spark=spark,
        state_dir=state_dir,
        evidence_dir=evidence_dir,
        silver_path=silver_path,
        gold_path=gold_path,
        queries=queries,
    )
    heartbeat_stop = threading.Event()
    heartbeat = threading.Thread(
        target=_health_heartbeat,
        args=(state_dir, queries, heartbeat_stop),
        daemon=True,
        name="w8-health-heartbeat",
    )
    heartbeat.start()
    LOGGER.info(
        "Week 8 streams started: silver checkpoint=%s, gold checkpoint=%s",
        checkpoint_root / "silver",
        checkpoint_root / "gold",
    )
    try:
        spark.streams.awaitAnyTermination()
        failures = [query.exception() for query in queries.values() if query.exception()]
        if failures:
            raise RuntimeError(f"Week 8 streaming query failed: {failures}")
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=5)
        server.shutdown()
        for query in queries.values():
            if query.isActive:
                query.stop()
        spark.stop()


if __name__ == "__main__":  # pragma: no cover - launched by Docker Compose
    run_streaming_app()
