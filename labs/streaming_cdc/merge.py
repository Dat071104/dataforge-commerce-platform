"""Idempotent Delta MERGE helpers for the Week 8 order CDC sink."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REQUIRED_MERGE_COLUMNS = {
    "order_id",
    "op",
    "source_lsn",
    "transaction_order",
}


def _identifier(value: str) -> str:
    if not _SQL_IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid SQL identifier: {value!r}")
    return value


def build_merge_condition(
    *, key_column: str = "order_id", target_alias: str = "t", source_alias: str = "s"
) -> str:
    """Build the primary-key equality used by Delta MERGE."""
    key = _identifier(key_column)
    target = _identifier(target_alias)
    source = _identifier(source_alias)
    return f"{target}.{key} = {source}.{key}"


def build_newer_version_condition(
    *,
    target_alias: str = "t",
    source_alias: str = "s",
    lsn_column: str = "source_lsn",
    order_column: str = "transaction_order",
) -> str:
    """Reject stale changes and break same-LSN ties with transaction order."""
    target = _identifier(target_alias)
    source = _identifier(source_alias)
    lsn = _identifier(lsn_column)
    order = _identifier(order_column)
    return (
        f"coalesce({source}.{lsn}, -1) > coalesce({target}.{lsn}, -1) OR "
        f"(coalesce({source}.{lsn}, -1) = coalesce({target}.{lsn}, -1) AND "
        f"coalesce({source}.{order}, -1) > coalesce({target}.{order}, -1))"
    )


def prepare_merge_batch(batch_df: Any, *, key_column: str = "order_id") -> Any:
    """Keep the newest non-tombstone event per key in a micro-batch."""
    missing = sorted(_REQUIRED_MERGE_COLUMNS - set(batch_df.columns))
    if missing:
        raise ValueError(f"CDC batch is missing merge columns: {missing}")
    if key_column not in batch_df.columns:
        raise ValueError(f"CDC batch is missing key column: {key_column}")

    from pyspark.sql import Window
    from pyspark.sql import functions as F

    ranked = batch_df.filter(F.col("op") != F.lit("tombstone"))
    order = [F.col("source_lsn").desc_nulls_last()]
    if "transaction_order" in ranked.columns:
        order.append(F.col("transaction_order").desc_nulls_last())
    if "source_ts_ms" in ranked.columns:
        order.append(F.col("source_ts_ms").desc_nulls_last())
    latest = Window.partitionBy(F.col(key_column)).orderBy(*order)
    return (
        ranked.withColumn("__w8_rank", F.row_number().over(latest))
        .filter(F.col("__w8_rank") == 1)
        .drop("__w8_rank")
    )


def _has_delta_table(spark: Any, path: str) -> bool:
    from delta.tables import DeltaTable

    return DeltaTable.isDeltaTable(spark, path)


def _latest_recorded_batch(spark: Any, marker_path: str, app_id: str) -> int | None:
    if not _has_delta_table(spark, marker_path):
        return None
    from pyspark.sql import functions as F

    row = (
        spark.read.format("delta")
        .load(marker_path)
        .filter(F.col("app_id") == app_id)
        .agg(F.max("batch_id").alias("last_batch_id"))
        .first()
    )
    return None if row is None or row["last_batch_id"] is None else int(row["last_batch_id"])


def _add_missing_delta_columns(spark: Any, target_path: str, source_df: Any) -> None:
    from delta.tables import DeltaTable

    existing = {field.name for field in DeltaTable.forPath(spark, target_path).toDF().schema.fields}
    reserved = {"op", "source_ts_ms"}
    missing = [field for field in source_df.schema.fields if field.name not in existing and field.name not in reserved]
    if not missing:
        return
    additions = ", ".join(
        f"`{_identifier(field.name)}` {field.dataType.simpleString()}" for field in missing
    )
    spark.sql(f"ALTER TABLE delta.`{target_path}` ADD COLUMNS ({additions})")


def merge_order_changes(
    batch_df: Any,
    target_path: str | Path,
    *,
    batch_id: int,
    transaction_app_id: str,
) -> bool:
    """Apply one micro-batch and record its txnAppId/txnVersion idempotently.

    The MERGE itself is safe to replay because it is keyed by the PK and only
    applies newer `(source_lsn, transaction_order)` values. A separate Delta
    transaction ledger records `(transaction_app_id, batch_id)` atomically for
    marker writes. If a process stops after MERGE but before the marker commit,
    replaying the MERGE is still a no-op on table state.
    """
    if batch_id < 0:
        raise ValueError("batch_id must be non-negative")
    if not transaction_app_id.strip():
        raise ValueError("transaction_app_id must be non-empty")


    prepared = prepare_merge_batch(batch_df).persist()
    try:
        if prepared.rdd.isEmpty():
            return False

        path = str(target_path)
        marker_path = f"{path}_transactions"
        last_batch = _latest_recorded_batch(
            prepared.sparkSession, marker_path, transaction_app_id
        )
        if last_batch is not None and last_batch >= batch_id:
            return False

        source = prepared.drop("source_ts_ms") if "source_ts_ms" in prepared.columns else prepared
        payload_columns = [column for column in source.columns if column != "op"]
        if not _has_delta_table(prepared.sparkSession, path):
            (
                source.select(*payload_columns)
                .limit(0)
                .write.format("delta")
                .mode("errorifexists")
                .save(path)
            )
        _add_missing_delta_columns(prepared.sparkSession, path, source)

        from delta.tables import DeltaTable

        updates = {column: f"s.`{column}`" for column in payload_columns}
        newer = build_newer_version_condition()
        (
            DeltaTable.forPath(prepared.sparkSession, path)
            .alias("t")
            .merge(source.alias("s"), build_merge_condition())
            .whenMatchedDelete(condition=f"s.op = 'd' AND ({newer})")
            .whenMatchedUpdate(condition=f"s.op <> 'd' AND ({newer})", set=updates)
            .whenNotMatchedInsert(
                condition="s.op <> 'd'",
                values=updates,
            )
            .execute()
        )

        marker = prepared.sparkSession.createDataFrame(
            [(transaction_app_id, int(batch_id))], "app_id STRING, batch_id LONG"
        )
        marker_writer = marker.write.format("delta").mode("append")
        marker_writer.option("txnAppId", transaction_app_id).option(
            "txnVersion", int(batch_id)
        ).save(marker_path)
        return True
    finally:
        prepared.unpersist()
