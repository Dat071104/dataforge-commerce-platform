"""Severity routing and Slack delivery for structured Week 9 DQ events."""
from __future__ import annotations

import base64
from typing import Protocol

import requests

from .observability import PROJECT_ID, DQEvent

SECRET_ID = "w9-slack-webhook-url"
ALERT_STATE_TABLE = "alert_state"


class WebhookProvider(Protocol):
    def read_webhook(self) -> str: ...


class AlertStateStore(Protocol):
    def get_status(self, check_id: str, event_date: str) -> str | None: ...

    def set_status(
        self, check_id: str, event_date: str, status: str, severity: str, run_id: str
    ) -> None: ...


class DigestSink(Protocol):
    def write(self, event: DQEvent) -> None: ...


class MemoryAlertStateStore:
    """In-memory state for unit tests and short-lived offline runs."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str], str] = {}

    def get_status(self, check_id: str, event_date: str) -> str | None:
        return self._states.get((check_id, event_date))

    def set_status(
        self, check_id: str, event_date: str, status: str, severity: str, run_id: str
    ) -> None:
        del severity, run_id
        self._states[(check_id, event_date)] = status


class BigQueryAlertStateStore:
    """Persist alert deduplication keys in the authorized W9 DQ dataset."""

    def __init__(self, project: str = PROJECT_ID, client=None) -> None:
        if project != PROJECT_ID:
            raise ValueError("DQ alert state is restricted to the approved DataForge project")
        self.project = project
        if client is None:
            from google.cloud import bigquery

            client = bigquery.Client(project=project)
        self.client = client

    @property
    def table_id(self) -> str:
        return f"{self.project}.dataforge_dq.{ALERT_STATE_TABLE}"

    def _ensure_table(self) -> None:
        from google.cloud import bigquery

        table = bigquery.Table(
            self.table_id,
            schema=[
                bigquery.SchemaField("check_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("event_date", "DATE", mode="REQUIRED"),
                bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("severity", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
            ],
        )
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="event_date",
        )
        table.clustering_fields = ["check_id", "status"]
        self.client.create_table(table, exists_ok=True)

    def get_status(self, check_id: str, event_date: str) -> str | None:
        from google.cloud import bigquery

        self._ensure_table()
        query = f"""
            SELECT status
            FROM `{self.table_id}`
            WHERE check_id = @check_id AND event_date = @event_date
            LIMIT 1
        """
        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_id", "STRING", check_id),
                bigquery.ScalarQueryParameter("event_date", "DATE", event_date),
            ],
            maximum_bytes_billed=1024**3,
            labels={"application": "dataforge", "phase": "week9", "action": "alert-state-read"},
        )
        rows = list(self.client.query(query, job_config=config, location="us-central1").result())
        return str(rows[0]["status"]) if rows else None

    def set_status(
        self, check_id: str, event_date: str, status: str, severity: str, run_id: str
    ) -> None:
        from google.cloud import bigquery

        self._ensure_table()
        query = f"""
            MERGE `{self.table_id}` AS target
            USING (
              SELECT @check_id AS check_id, @event_date AS event_date,
                     @status AS status, @severity AS severity, @run_id AS run_id
            ) AS source
            ON target.check_id = source.check_id AND target.event_date = source.event_date
            WHEN MATCHED THEN UPDATE SET
              status = source.status,
              severity = source.severity,
              run_id = source.run_id,
              updated_at = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT
              (check_id, event_date, status, severity, run_id, updated_at)
              VALUES
              (source.check_id, source.event_date, source.status, source.severity,
               source.run_id, CURRENT_TIMESTAMP())
        """
        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_id", "STRING", check_id),
                bigquery.ScalarQueryParameter("event_date", "DATE", event_date),
                bigquery.ScalarQueryParameter("status", "STRING", status),
                bigquery.ScalarQueryParameter("severity", "STRING", severity),
                bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
            ],
            maximum_bytes_billed=1024**3,
            labels={"application": "dataforge", "phase": "week9", "action": "alert-state-write"},
        )
        self.client.query(query, job_config=config, location="us-central1").result()


class SecretManagerWebhookProvider:
    """Read the Slack webhook at runtime without returning it to logs."""

    def __init__(self, project: str = PROJECT_ID, http=None) -> None:
        if project != PROJECT_ID:
            raise ValueError("Slack secret access is restricted to the approved DataForge project")
        self.project = project
        self.http = http or requests

    def read_webhook(self) -> str:
        from google.auth import default
        from google.auth.transport.requests import Request

        try:
            credentials, _ = default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            credentials.refresh(Request())
            response = self.http.get(
                "https://secretmanager.googleapis.com/v1/projects/"
                f"{self.project}/secrets/{SECRET_ID}/versions/latest:access",
                headers={"Authorization": f"Bearer {credentials.token}"},
                timeout=(5, 15),
            )
            if not 200 <= response.status_code < 300:
                raise RuntimeError("Slack webhook secret access was rejected")
            payload = response.json()
            encoded = payload["payload"]["data"]
            webhook = base64.b64decode(encoded, validate=True).decode("utf-8").strip()
        except Exception:
            raise RuntimeError("Slack webhook secret could not be read") from None
        if not webhook.startswith("https://hooks.slack.com/services/"):
            raise RuntimeError("Slack webhook secret has an invalid format")
        return webhook


class SlackWebhookNotifier:
    """Send only sanitized alert summaries through a Secret Manager webhook."""

    def __init__(self, webhook_provider: WebhookProvider, http=None) -> None:
        self.webhook_provider = webhook_provider
        self.http = http or requests

    def send(self, event: DQEvent, *, resolved: bool = False) -> None:
        action = "RESOLVED" if resolved else "FAILED"
        impact = (
            "Gold was published"
            if event.published is True
            else "Gold publish was blocked/quarantined"
            if event.published is False
            else "Gold publish status is unknown"
        )
        message = (
            f"*DataForge DQ {action}* · `{event.check_id}` ({event.severity})\n"
            f"Impact: {impact}\n"
            f"run_id: `{event.run_id}` · date: `{event.event_date}` · dataset: `{event.dataset}`\n"
            f"Failing rows: {event.failing_rows}\n"
            f"Triage query: `{event.failing_rows_query}`\n"
            f"Runbook: {event.runbook_url}"
        )
        webhook = self.webhook_provider.read_webhook()
        try:
            response = self.http.post(webhook, json={"text": message}, timeout=(5, 15))
        except requests.RequestException:
            raise RuntimeError("Slack webhook delivery failed") from None
        if not 200 <= response.status_code < 300:
            raise RuntimeError("Slack webhook delivery was rejected")


class MemoryDigestSink:
    """P3 daily-digest collector for tests and offline monitoring runs."""

    def __init__(self) -> None:
        self.events: list[DQEvent] = []

    def write(self, event: DQEvent) -> None:
        self.events.append(event)


class NotificationRouter:
    """P1/P2 Slack routing, P1 email via Monitoring, and P3 digest handling."""

    def __init__(
        self,
        state_store: AlertStateStore,
        slack: SlackWebhookNotifier,
        digest: DigestSink,
    ) -> None:
        self.state_store = state_store
        self.slack = slack
        self.digest = digest

    def route(self, event: DQEvent) -> str:
        if event.severity == "P3":
            if event.status in {"FAIL", "WARN"}:
                self.digest.write(event)
            return "DIGEST" if event.status in {"FAIL", "WARN"} else "NO_ALERT"

        current = self.state_store.get_status(event.check_id, event.event_date)
        if event.status in {"FAIL", "WARN"}:
            if current == "OPEN":
                return "DEDUPLICATED"
            self.slack.send(event)
            self.state_store.set_status(
                event.check_id,
                event.event_date,
                "OPEN",
                event.severity,
                event.run_id,
            )
            # P1 email is delivered independently by the Monitoring policy.
            return "SLACK_AND_MONITORING_EMAIL" if event.severity == "P1" else "SLACK"
        if event.status == "PASS" and current == "OPEN":
            self.slack.send(event, resolved=True)
            self.state_store.set_status(
                event.check_id,
                event.event_date,
                "RESOLVED",
                event.severity,
                event.run_id,
            )
            return "RESOLVED"
        return "NO_ALERT"
