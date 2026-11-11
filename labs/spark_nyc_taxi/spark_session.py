"""Pinned local Spark session settings for the isolated NYC TLC lab."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

SPARK_VERSION = "3.5.9"
DELTA_VERSION = "3.3.3"
LOCAL_MASTER = "local[4]"
DEFAULT_SHUFFLE_PARTITIONS = 96
NEW_YORK_TIME_ZONE = "America/New_York"


def _file_uri(path: Path) -> str:
    return path.resolve().as_uri()


def create_spark(
    *,
    app_name: str = "dataforge-week6-nyc-taxi",
    event_log_dir: str | Path | None = None,
    ui_port: int | None = None,
    shuffle_partitions: int = DEFAULT_SHUFFLE_PARTITIONS,
    adaptive_enabled: bool = True,
    enable_delta: bool = False,
) -> SparkSession:
    """Create a bounded local Spark session with durable event logging.

    The environment overrides are intentionally narrow so CI and the full TLC
    run share the same execution code while retaining isolated scratch paths.
    The caller owns stopping the returned session.
    """
    if shuffle_partitions < 1:
        raise ValueError("shuffle_partitions must be positive")

    from pyspark.sql import SparkSession

    configured_log_dir = event_log_dir or os.environ.get(
        "DATAFORGE_SPARK_EVENTLOG_DIR",
        str(Path(__file__).resolve().parent / "data" / "eventlogs"),
    )
    log_dir = Path(configured_log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    configured_ui_port = ui_port or int(os.environ.get("DATAFORGE_SPARK_UI_PORT", "4040"))
    master = os.environ.get("DATAFORGE_SPARK_MASTER", LOCAL_MASTER)
    builder = (
        SparkSession.builder.appName(app_name)
        .master(master)
        .config("spark.sql.session.timeZone", NEW_YORK_TIME_ZONE)
        .config("spark.sql.parquet.inferTimestampNTZ.enabled", "true")
        .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
        .config("spark.sql.adaptive.enabled", str(adaptive_enabled).lower())
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        .config("spark.sql.autoBroadcastJoinThreshold", "-1")
        .config("spark.sql.adaptive.autoBroadcastJoinThreshold", "-1")
        .config("spark.eventLog.enabled", "true")
        .config("spark.eventLog.dir", _file_uri(log_dir))
        .config("spark.eventLog.compress", "false")
        .config("spark.ui.enabled", "true")
        .config("spark.ui.port", str(configured_ui_port))
        .config("spark.ui.bindAddress", "0.0.0.0")
        .config("spark.driver.bindAddress", "0.0.0.0")
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.sql.execution.arrow.pyspark.enabled", "false")
    )

    if enable_delta:
        try:
            from delta import configure_spark_with_delta_pip
        except ImportError as exc:
            raise RuntimeError(
                f"Delta Lake {DELTA_VERSION} is required for the table-format demo"
            ) from exc
        builder = builder.config(
            "spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension"
        ).config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        builder = configure_spark_with_delta_pip(builder, extra_packages=[])

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel(os.environ.get("DATAFORGE_SPARK_LOG_LEVEL", "WARN"))
    return spark
