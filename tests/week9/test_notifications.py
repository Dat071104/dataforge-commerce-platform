from __future__ import annotations

from dataforge.dq.notifications import (
    MemoryAlertStateStore,
    MemoryDigestSink,
    NotificationRouter,
    SlackWebhookNotifier,
)
from dataforge.dq.observability import DQEvent


def event(*, severity: str, status: str, check_id: str = "G1.LANDING.PROVINCE_DOMAIN") -> DQEvent:
    return DQEvent(
        event_type="DQ_GATE_FAILED",
        run_id="run-safe-id",
        check_id=check_id,
        severity=severity,
        status=status,
        dataset="w9_drill",
        event_date="2026-11-18",
        runbook_url="https://example.invalid/runbook",
        failing_rows=2 if status == "FAIL" else 0,
        observed={"failing_rows": 2},
        threshold={"rule": "test"},
        published=False,
        failing_rows_query="SELECT check_id FROM dataforge_dq.dq_results",
    )


class FakeWebhookProvider:
    def read_webhook(self):
        return "https://example.invalid/webhook-secret-placeholder"


class FakeResponse:
    status_code = 200


class FakeHTTP:
    def __init__(self):
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()


def test_p1_and_p2_route_to_slack_and_deduplicate_by_check_date():
    http = FakeHTTP()
    state = MemoryAlertStateStore()
    router = NotificationRouter(
        state_store=state,
        slack=SlackWebhookNotifier(FakeWebhookProvider(), http=http),
        digest=MemoryDigestSink(),
    )
    p1 = event(severity="P1", status="FAIL")
    assert router.route(p1) == "SLACK_AND_MONITORING_EMAIL"
    assert router.route(p1) == "DEDUPLICATED"
    assert len(http.calls) == 1
    p2 = event(severity="P2", status="WARN", check_id="G1.LANDING.SCHEMA_ADDITIVE")
    assert router.route(p2) == "SLACK"
    assert len(http.calls) == 2
    assert "webhook-secret-placeholder" not in http.calls[0]["json"]["text"]


def test_pass_after_open_failure_sends_resolve_message():
    http = FakeHTTP()
    router = NotificationRouter(
        state_store=MemoryAlertStateStore(),
        slack=SlackWebhookNotifier(FakeWebhookProvider(), http=http),
        digest=MemoryDigestSink(),
    )
    failed = event(severity="P1", status="FAIL")
    passed = event(severity="P1", status="PASS")
    assert router.route(failed) == "SLACK_AND_MONITORING_EMAIL"
    assert router.route(passed) == "RESOLVED"
    assert len(http.calls) == 2
    assert "RESOLVED" in http.calls[1]["json"]["text"]


def test_p3_events_are_added_to_digest_without_immediate_slack():
    http = FakeHTTP()
    digest = MemoryDigestSink()
    router = NotificationRouter(
        state_store=MemoryAlertStateStore(),
        slack=SlackWebhookNotifier(FakeWebhookProvider(), http=http),
        digest=digest,
    )
    p3 = event(severity="P3", status="WARN", check_id="MONITOR.INFO")
    assert router.route(p3) == "DIGEST"
    assert digest.events == [p3]
    assert not http.calls
