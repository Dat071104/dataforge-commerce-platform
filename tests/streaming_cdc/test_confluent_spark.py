from __future__ import annotations

import pytest

pytest.importorskip("pyspark", reason="Week 8 CI installs the lane's Spark test dependency")

from labs.streaming_cdc.stream import _confluent_frame_columns


def test_confluent_spark_frame_extracts_schema_id_and_binary_payload(spark):
    framed_value = b"\x00\x00\x00\x00\x2aavro"
    source = spark.createDataFrame([(framed_value,)], ["value"])
    schema_id, payload = _confluent_frame_columns()

    decoded = source.select(schema_id.alias("schema_id"), payload.alias("payload")).first()

    assert decoded.schema_id == 42
    assert decoded.payload == b"avro"
