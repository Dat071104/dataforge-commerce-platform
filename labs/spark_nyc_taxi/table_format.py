"""Isolated, executable Delta Lake table-format demonstration."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeltaDemoReceipt:
    table_path: str
    format: str
    initial_row_count: int
    latest_row_count_after_append: int
    row_count_after_idempotent_replay: int
    time_travel_version: int
    time_travel_row_count: int
    latest_version: int
    history: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]
    schema: tuple[dict[str, str], ...]
    delta_log_files: tuple[str, ...]
    append_transaction_id: str
    append_transaction_version: int
    append_replay_verified: bool
    time_travel_verified: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_delta_table_demo(
    spark: Any,
    aggregate_df: Any,
    table_path: str | Path,
    *,
    initial_rows: int = 20,
) -> DeltaDemoReceipt:
    """Create a scratch Delta table, append once, replay safely, and time travel.

    `table_path` must be a new or empty scratch path owned by this lab. The
    function refuses to overwrite any pre-existing table or unrelated data.
    It uses a transactional application/version pair so a retry of the append
    is a no-op in Delta's log. No source or commerce table is touched.
    """
    if initial_rows < 1:
        raise ValueError("initial_rows must be positive")
    try:
        from delta.tables import DeltaTable
    except ImportError as exc:
        raise RuntimeError("Delta Lake is not installed in this Spark runtime") from exc

    path = Path(table_path)
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"refusing to replace non-empty Delta demo path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)

    key_columns = ["pickup_date", "pickup_hour", "pickup_zone"]
    missing = [column for column in key_columns if column not in aggregate_df.columns]
    if missing:
        raise ValueError(f"aggregate DataFrame is missing Delta demo keys: {missing}")

    initial = aggregate_df.orderBy(*key_columns).limit(initial_rows)
    initial_count = initial.count()
    if initial_count < 1:
        raise ValueError("cannot demonstrate a Delta table with an empty aggregate")
    initial.write.format("delta").mode("errorifexists").save(str(path))

    identity = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
    app_id = f"dataforge-p73-week6-{identity}"
    transaction_version = 1
    append_batch = initial.limit(1)

    def append_once() -> None:
        (
            append_batch.write.format("delta")
            .mode("append")
            .option("txnAppId", app_id)
            .option("txnVersion", transaction_version)
            .save(str(path))
        )

    append_once()
    after_append_count = DeltaTable.forPath(spark, str(path)).toDF().count()
    append_once()
    after_replay_count = DeltaTable.forPath(spark, str(path)).toDF().count()

    version_zero = (
        spark.read.format("delta").option("versionAsOf", 0).load(str(path)).count()
    )
    history_rows = (
        DeltaTable.forPath(spark, str(path))
        .history()
        .select("version", "operation", "operationParameters", "readVersion", "isolationLevel")
        .orderBy("version")
        .collect()
    )
    history = tuple(
        {
            "version": int(row["version"]),
            "operation": row["operation"],
            "operation_parameters": {
                str(key): str(value)
                for key, value in (row["operationParameters"] or {}).items()
            },
            "read_version": row["readVersion"],
            "isolation_level": row["isolationLevel"],
        }
        for row in history_rows
    )
    table = DeltaTable.forPath(spark, str(path))
    detail = table.detail().select(
        "format", "numFiles", "sizeInBytes", "partitionColumns", "minReaderVersion", "minWriterVersion"
    ).first()
    schema = tuple(
        {"name": field.name, "type": field.dataType.simpleString()}
        for field in table.toDF().schema.fields
    )
    log_dir = path / "_delta_log"
    log_files = tuple(sorted(item.name for item in log_dir.iterdir() if item.is_file()))
    latest_version = max(int(row["version"]) for row in history)
    metadata = {
        "format": detail["format"],
        "num_files": int(detail["numFiles"]),
        "size_bytes": int(detail["sizeInBytes"]),
        "partition_columns": list(detail["partitionColumns"] or []),
        "min_reader_version": int(detail["minReaderVersion"]),
        "min_writer_version": int(detail["minWriterVersion"]),
    }
    receipt = DeltaDemoReceipt(
        table_path=str(path.resolve()),
        format="delta",
        initial_row_count=initial_count,
        latest_row_count_after_append=after_append_count,
        row_count_after_idempotent_replay=after_replay_count,
        time_travel_version=0,
        time_travel_row_count=version_zero,
        latest_version=latest_version,
        history=history,
        metadata=metadata,
        schema=schema,
        delta_log_files=log_files,
        append_transaction_id=app_id,
        append_transaction_version=transaction_version,
        append_replay_verified=(
            after_append_count == initial_count + 1
            and after_replay_count == after_append_count
            and latest_version == 1
        ),
        time_travel_verified=(version_zero == initial_count),
    )
    if not receipt.append_replay_verified:
        raise AssertionError(f"Delta append replay was not idempotent: {receipt.to_dict()}")
    if not receipt.time_travel_verified:
        raise AssertionError(f"Delta version-0 read did not match initial write: {receipt.to_dict()}")
    if metadata["format"] != "delta":
        raise AssertionError(f"unexpected Delta table format metadata: {metadata}")
    return receipt
