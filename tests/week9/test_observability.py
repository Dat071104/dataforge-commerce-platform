from __future__ import annotations

import json
from datetime import date, datetime, timezone

from dataforge.dq.observability import (
    DQEvent,
    JsonlEventSink,
    deliver_alerts,
    event_from_result,
    run_monitors,
    schema_drift_events,
    temperature_distribution_event,
)

AS_OF = date(2026, 11, 18)


def result_row(check_id, *, layer="G1", severity="P1", status="FAIL", observed=None):
    return {
        "run_id": "run-safe-id",
        "check_id": check_id,
        "layer": layer,
        "severity": severity,
        "status": status,
        "observed": json.dumps(observed or {"dataset": "w9_drill", "date": AS_OF.isoformat()}),
        "threshold": json.dumps({"expected": "contract threshold"}),
        "failing_rows": 2 if status == "FAIL" else 0,
        "contract_version": "1.0.0",
        "ts": datetime(2026, 11, 18, 10, tzinfo=timezone.utc),
    }


def test_result_reader_maps_cataloged_checks_to_monitor_event_types():
    checks = {
        "G2.SOURCE.FRESHNESS": "FRESHNESS_BREACH",
        "G1.LANDING.ROWS_PER_DATE": "VOLUME_ANOMALY",
        "G1.LANDING.SCHEMA": "SCHEMA_DRIFT",
        "G1.LANDING.PROVINCE_DOMAIN": "DQ_GATE_FAILED",
    }
    for check_id, expected_type in checks.items():
        event = event_from_result(result_row(check_id), dataset="w9_drill", fallback_date=AS_OF)
        assert event is not None
        assert event.event_type == expected_type
        assert event.event_date == AS_OF.isoformat()
        assert event.dataset == "w9_drill"
        assert "run-safe-id" in event.failing_rows_query


def test_result_monitor_skips_other_or_unattributed_datasets():
    event = event_from_result(
        result_row("G1.LANDING.PROVINCE_DOMAIN", observed={"dataset": "dbt_ci_pr_12"}),
        dataset="w9_drill",
        fallback_date=AS_OF,
    )
    unattributed = event_from_result(
        result_row("G1.LANDING.PROVINCE_DOMAIN", observed={"failing_rows": 2}),
        dataset="w9_drill",
        fallback_date=AS_OF,
    )
    assert event is None
    assert unattributed is None


def test_schema_drift_emits_p1_for_breaking_and_p2_for_nullable_addition():
    expected = {"province_id": "STRING", "temp_max_c": "FLOAT64"}
    actual = [
        {"column_name": "province_id", "data_type": "STRING", "is_nullable": "NO"},
        {"column_name": "temp_max_c", "data_type": "FLOAT64", "is_nullable": "YES"},
        {"column_name": "added_nullable", "data_type": "STRING", "is_nullable": "YES"},
    ]
    events = schema_drift_events(
        expected,
        actual,
        run_id="monitor-test",
        dataset="w9_drill",
        event_date=AS_OF,
    )
    assert len(events) == 1
    assert events[0].check_id == "G1.LANDING.SCHEMA_ADDITIVE"
    assert events[0].severity == "P2"
    assert events[0].status == "WARN"

    broken = [
        {"column_name": "province_id", "data_type": "INT64", "is_nullable": "NO"},
    ]
    breaking_events = schema_drift_events(
        expected,
        broken,
        run_id="monitor-test",
        dataset="w9_drill",
        event_date=AS_OF,
    )
    assert breaking_events[0].check_id == "G1.LANDING.SCHEMA"
    assert breaking_events[0].severity == "P1"
    assert breaking_events[0].status == "FAIL"
    assert schema_drift_events(
        expected,
        [],
        run_id="monitor-test",
        dataset="w9_drill",
        event_date=AS_OF,
    ) == []


def test_distribution_monitor_is_p2_only_and_requires_baseline_volume():
    event = temperature_distribution_event(
        [
            {
                "province_id": "HCM",
                "baseline_days": 30,
                "recent_days": 30,
                "mean_z_score": 3.5,
                "stddev_z_score": 0.2,
            }
        ],
        dataset="w9_drill",
        event_date=AS_OF,
        run_id="monitor-test",
    )
    clean = temperature_distribution_event(
        [], dataset="w9_drill", event_date=AS_OF, run_id="monitor-test"
    )
    assert event.event_type == "VOLUME_ANOMALY"
    assert event.severity == "P2"
    assert event.status == "WARN"
    assert clean.status == "PASS"
    assert clean.severity == "P2"


def test_monitor_reads_existing_results_and_emits_a_heartbeat_only_after_g2_success():
    class FakeSource:
        def read_dq_results(self, run_date):
            assert run_date == AS_OF
            return [
                result_row("G2.SOURCE.FRESHNESS", layer="G2", severity="P2", status="WARN"),
                result_row(
                    "G2.WEATHER.RAIN_PRECIP_CONSISTENCY",
                    layer="G2",
                    severity="P1",
                    status="PASS",
                ),
            ]

        def read_columns(self, dataset):
            assert dataset == "w9_drill"
            return [{"column_name": "province_id", "data_type": "STRING", "is_nullable": "NO"}]

        def read_latest_landed_at(self, dataset):
            assert dataset == "w9_drill"
            return datetime(2026, 11, 17, 14, tzinfo=timezone.utc)

        def read_temperature_distribution(self, dataset, as_of_date):
            assert dataset == "w9_drill"
            assert as_of_date == AS_OF
            return []

    events = run_monitors(
        FakeSource(),
        dataset="w9_drill",
        run_date=AS_OF,
        contract_columns={"province_id": "STRING"},
    )
    freshness = next(event for event in events if event.event_type == "FRESHNESS_BREACH")
    assert freshness.observed["latest_landed_at"] == "2026-11-17T14:00:00+00:00"
    assert freshness.observed["age_hours"] > 0
    assert any(event.event_type == "DQ_HEARTBEAT" for event in events)
    assert any(event.status == "PASS" and event.event_type == "SCHEMA_DRIFT" for event in events)


def test_monitor_keeps_only_the_newest_result_per_check_and_date():
    # R-16: a FAIL fixed by a later PASS on the same day must not be re-sent as an alert.
    class FakeSource:
        def read_dq_results(self, run_date):
            return [
                result_row("G1.LANDING.ROW_COUNT", status="FAIL"),
                result_row("G1.LANDING.ROW_COUNT", status="PASS"),
                result_row(
                    "G1.LANDING.ROW_COUNT",
                    status="FAIL",
                    observed={"dataset": "w9_drill", "date": "2026-11-17"},
                ),
            ]

        def read_columns(self, dataset):
            return []

        def read_latest_landed_at(self, dataset):
            return None

        def read_temperature_distribution(self, dataset, as_of_date):
            return []

    events = run_monitors(
        FakeSource(),
        dataset="w9_drill",
        run_date=AS_OF,
        contract_columns={"province_id": "STRING"},
    )
    row_count = {
        event.event_date: event.status
        for event in events
        if event.check_id == "G1.LANDING.ROW_COUNT"
    }
    assert row_count == {AS_OF.isoformat(): "PASS", "2026-11-17": "FAIL"}
    assert sum(event.check_id == "G1.LANDING.ROW_COUNT" for event in events) == 2


def test_monitor_since_watermark_skips_earlier_results():
    # R-20: gate-test rows written earlier in the day must not be routed as incidents.
    early = result_row("G2.WEATHER.RAIN_PRECIP_CONSISTENCY", layer="G2", status="FAIL")
    late = result_row("G1.LANDING.ROWS_PER_DATE", status="FAIL")
    late["ts"] = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)

    class FakeSource:
        def read_dq_results(self, run_date):
            return [early, late]

        def read_columns(self, dataset):
            return []

        def read_latest_landed_at(self, dataset):
            return None

        def read_temperature_distribution(self, dataset, as_of_date):
            return []

    events = run_monitors(
        FakeSource(),
        dataset="w9_drill",
        run_date=AS_OF,
        contract_columns={"province_id": "STRING"},
        since=datetime(2026, 11, 18, 11, tzinfo=timezone.utc),
    )
    failed = {event.check_id for event in events if event.status == "FAIL"}
    assert failed == {"G1.LANDING.ROWS_PER_DATE"}


def test_slack_outage_does_not_suppress_logging_or_email():
    # F-A1: a webhook failure must not stop later events from being logged (email path)
    # and must itself emit a P1 delivery-failure event.
    failing = event_from_result(
        result_row("G1.LANDING.ROWS_PER_DATE", status="FAIL"), dataset="w9_drill", fallback_date=AS_OF
    )
    passing = event_from_result(
        result_row("G1.LANDING.SCHEMA", status="PASS"), dataset="w9_drill", fallback_date=AS_OF
    )

    class Sink:
        def __init__(self):
            self.written = []

        def write(self, event):
            self.written.append(event)

    class BrokenRouter:
        def route(self, event):
            if event.status == "FAIL":
                raise RuntimeError("Slack webhook delivery failed")
            return "NO_ALERT"

    sink = Sink()
    routes, failures = deliver_alerts([failing, passing], sink, BrokenRouter())

    assert failures == 1
    assert routes == {"DELIVERY_FAILED": 1, "NO_ALERT": 1}
    assert [event.check_id for event in sink.written[:2]] == [failing.check_id, passing.check_id]
    alert = sink.written[2]
    assert (alert.check_id, alert.event_type, alert.severity, alert.status) == (
        "ALERTING.DELIVERY_FAILED",
        "DQ_GATE_FAILED",
        "P1",
        "FAIL",
    )
    assert alert.observed["failed_check_id"] == "G1.LANDING.ROWS_PER_DATE"


def test_jsonl_sink_writes_one_structured_event_line(tmp_path):
    event = DQEvent(
        event_type="DQ_GATE_FAILED",
        run_id="run-safe-id",
        check_id="G1.LANDING.PROVINCE_DOMAIN",
        severity="P1",
        status="FAIL",
        dataset="w9_drill",
        event_date=AS_OF.isoformat(),
        runbook_url="https://example.invalid/runbook",
        failing_rows=1,
        observed={"failing_rows": 1},
        threshold={"allowed_values": ["HCM", "HN", "DN"]},
        published=False,
        failing_rows_query="SELECT * FROM dataforge_dq.dq_results",
    )
    path = tmp_path / "events.jsonl"
    JsonlEventSink(path).write(event)
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["event_type"] == "DQ_GATE_FAILED"
    assert line["run_id"] == "run-safe-id"
    assert "secret" not in json.dumps(line).lower()
