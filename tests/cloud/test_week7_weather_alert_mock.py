from __future__ import annotations

import pytest

from scripts.week7_weather_alert_mock import (
    MemoryNotificationSink,
    prepare_mock_delivery,
)


@pytest.mark.parametrize("status", ["NO_NEW_BATCH", "SOURCE_NOT_READY"])
def test_normal_source_outcomes_do_not_prepare_an_alert(status: str) -> None:
    assert (
        prepare_mock_delivery(
            run_id="workflow-001",
            status=status,
            stage="ingest",
            error_category=None,
        )
        is None
    )


def test_terminal_failure_routes_only_redacted_metadata_to_in_memory_sink() -> None:
    delivery = prepare_mock_delivery(
        run_id="workflow-001",
        status="FAILED",
        stage="dbt_test",
        error_category="quality_gate",
    )
    assert delivery is not None

    sink = MemoryNotificationSink()
    sink.send(delivery)

    assert delivery.status == "MOCK_ONLY"
    assert sink.events == [
        {
            "event": "DATAFORGE_WEATHER_FAILURE",
            "run_id": "workflow-001",
            "stage": "dbt_test",
            "error_category": "quality_gate",
            "external_delivery": "false",
            "destination": "NOT_CONFIGURED",
        }
    ]
    assert "email" not in str(sink.events).lower()
    assert "NOT_CONFIGURED" in str(sink.events)


def test_mock_rejects_unbounded_or_unexpected_identifiers() -> None:
    with pytest.raises(ValueError, match="safe identifier"):
        prepare_mock_delivery(
            run_id="bad/run-id",
            status="FAILED",
            stage="ingest",
            error_category="provider_timeout",
        )

    with pytest.raises(ValueError, match="terminal FAILED"):
        prepare_mock_delivery(
            run_id="workflow-001",
            status="RUNNING",
            stage="ingest",
            error_category="provider_timeout",
        )
