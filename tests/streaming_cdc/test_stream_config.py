from __future__ import annotations

from labs.streaming_cdc.stream import SPARK_EXTRA_PACKAGES, _configure_spark_builder


def test_delta_builder_receives_kafka_and_avro_packages():
    calls = {}

    def fake_delta_configurator(builder, *, extra_packages):
        calls["builder"] = builder
        calls["extra_packages"] = extra_packages
        return "configured-builder"

    result = _configure_spark_builder("spark-builder", fake_delta_configurator)

    assert result == "configured-builder"
    assert calls == {
        "builder": "spark-builder",
        "extra_packages": list(SPARK_EXTRA_PACKAGES),
    }
