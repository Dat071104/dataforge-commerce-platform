"""Read-only Week 9 monitors over DQ results, INFORMATION_SCHEMA, and weather."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import requests

from .results import require_isolated_dataset

PROJECT_ID = "dataforge-p7-lab-d0f725"
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = REPO_ROOT / "contracts" / "weather_landing.v1.yaml"
RUNBOOK_BASE_URL = (
    "https://github.com/Dat071104/dataforge-commerce-platform/blob/main/docs/week9/runbooks"
)
_RUNBOOKS = {
    "DQ_GATE_FAILED": "DQ_GATE_FAILED.md",
    "SCHEMA_DRIFT": "SCHEMA_DRIFT.md",
    "FRESHNESS_BREACH": "FRESHNESS_BREACH.md",
    "VOLUME_ANOMALY": "VOLUME_ANOMALY.md",
    "DQ_HEARTBEAT": "DQ_HEARTBEAT.md",
}
_EVENT_TYPE_BY_CHECK = {
    "G1.LANDING.SCHEMA": "SCHEMA_DRIFT",
    "G1.LANDING.SCHEMA_ADDITIVE": "SCHEMA_DRIFT",
    "G1.LANDING.ROWS_PER_DATE": "VOLUME_ANOMALY",
    "G2.SOURCE.FRESHNESS": "FRESHNESS_BREACH",
    "MONITOR.WEATHER.TEMP_DISTRIBUTION": "VOLUME_ANOMALY",
}


@dataclass(frozen=True)
class DQEvent:
    event_type: str
    run_id: str
    check_id: str
    severity: str
    status: str
    dataset: str
    event_date: str
    runbook_url: str
    failing_rows: int
    observed: dict[str, Any]
    threshold: Any
    published: bool | None
    failing_rows_query: str

    def as_log_payload(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "run_id": self.run_id,
            "check_id": self.check_id,
            "severity": self.severity,
            "status": self.status,
            "dataset": self.dataset,
            "date": self.event_date,
            "runbook_url": self.runbook_url,
            "failing_rows": self.failing_rows,
            "observed": self.observed,
            "threshold": self.threshold,
            "published": self.published,
            "failing_rows_query": self.failing_rows_query,
        }


class MonitorSource(Protocol):
    def read_dq_results(self, run_date: date) -> list[dict[str, Any]]: ...

    def read_columns(self, dataset: str) -> list[dict[str, Any]]: ...

    def read_latest_landed_at(self, dataset: str) -> datetime | None: ...

    def read_temperature_distribution(
        self, dataset: str, as_of_date: date
    ) -> list[dict[str, Any]]: ...


class EventSink(Protocol):
    def write(self, event: DQEvent) -> None: ...


class JsonlEventSink:
    """Local structured-event sink for tests and offline evidence."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, event: DQEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event.as_log_payload(), sort_keys=True) + "\n")


class CloudLoggingEventSink:
    """Write one structured event per finding without exposing credentials."""

    def __init__(self, project: str = PROJECT_ID, http=None) -> None:
        if project != PROJECT_ID:
            raise ValueError("DQ event logs are restricted to the approved DataForge project")
        self.project = project
        self.http = http or requests

    def write(self, event: DQEvent) -> None:
        from google.auth import default
        from google.auth.transport.requests import Request

        try:
            credentials, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            credentials.refresh(Request())
        except Exception:
            raise RuntimeError("Cloud Logging credentials could not be refreshed") from None
        payload = {
            "entries": [
                {
                    "logName": f"projects/{self.project}/logs/dataforge-week9-dq",
                    "resource": {
                        "type": "global",
                        "labels": {"project_id": self.project},
                    },
                    "severity": _logging_severity(event),
                    "jsonPayload": event.as_log_payload(),
                }
            ]
        }
        try:
            response = self.http.post(
                "https://logging.googleapis.com/v2/entries:write",
                headers={"Authorization": f"Bearer {credentials.token}"},
                json=payload,
                timeout=(5, 20),
            )
        except requests.RequestException:
            raise RuntimeError("structured DQ log write failed") from None
        if not 200 <= response.status_code < 300:
            raise RuntimeError("structured DQ log write was rejected")


class BigQueryMonitorSource:
    """Read monitor inputs only from the W9 DQ table and isolated weather datasets."""

    def __init__(self, project: str = PROJECT_ID, client=None) -> None:
        if project != PROJECT_ID:
            raise ValueError("DQ monitors are restricted to the approved DataForge project")
        self.project = project
        if client is None:
            from google.cloud import bigquery

            client = bigquery.Client(project=project)
        self.client = client

    def _query(self, sql: str, parameters: list[Any]) -> list[dict[str, Any]]:
        from google.cloud import bigquery

        config = bigquery.QueryJobConfig(
            query_parameters=parameters,
            maximum_bytes_billed=1024**3,
            labels={"application": "dataforge", "phase": "week9", "action": "monitor"},
        )
        job = self.client.query(sql, job_config=config, location="us-central1")
        return [dict(row.items()) for row in job.result()]

    def read_dq_results(self, run_date: date) -> list[dict[str, Any]]:
        from google.cloud import bigquery

        return self._query(
            f"""
            SELECT run_id, check_id, layer, severity, status, observed, threshold,
                   failing_rows, contract_version, ts
            FROM `{self.project}.dataforge_dq.dq_results`
            WHERE DATE(ts) = @run_date
            ORDER BY ts, check_id
            """,
            [bigquery.ScalarQueryParameter("run_date", "DATE", run_date)],
        )

    def read_columns(self, dataset: str) -> list[dict[str, Any]]:
        from google.cloud import bigquery

        require_isolated_dataset(dataset)
        return self._query(
            f"""
            SELECT column_name, data_type, is_nullable
            FROM `{self.project}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name = @table_name
            ORDER BY ordinal_position
            """,
            [bigquery.ScalarQueryParameter("table_name", "STRING", "weather_landing")],
        )

    def read_latest_landed_at(self, dataset: str) -> datetime | None:
        require_isolated_dataset(dataset)
        rows = self._query(
            f"""
            SELECT MAX(landed_at) AS latest_landed_at
            FROM `{self.project}.{dataset}.weather_landing`
            WHERE observation_date >= DATE_SUB(
              CURRENT_DATE('Asia/Ho_Chi_Minh'), INTERVAL 60 DAY
            )
            """,
            [],
        )
        if not rows:
            return None
        return rows[0].get("latest_landed_at")

    def read_temperature_distribution(
        self, dataset: str, as_of_date: date
    ) -> list[dict[str, Any]]:
        from google.cloud import bigquery

        require_isolated_dataset(dataset)
        query = f"""
            WITH period_stats AS (
              SELECT
                province_id,
                AVG(IF(
                  observation_date BETWEEN DATE_SUB(@as_of_date, INTERVAL 60 DAY)
                    AND DATE_SUB(@as_of_date, INTERVAL 31 DAY),
                  temp_max_c, NULL
                )) AS baseline_mean_c,
                STDDEV_POP(IF(
                  observation_date BETWEEN DATE_SUB(@as_of_date, INTERVAL 60 DAY)
                    AND DATE_SUB(@as_of_date, INTERVAL 31 DAY),
                  temp_max_c, NULL
                )) AS baseline_stddev_c,
                COUNTIF(
                  observation_date BETWEEN DATE_SUB(@as_of_date, INTERVAL 60 DAY)
                    AND DATE_SUB(@as_of_date, INTERVAL 31 DAY)
                  AND temp_max_c IS NOT NULL
                ) AS baseline_days,
                AVG(IF(
                  observation_date BETWEEN DATE_SUB(@as_of_date, INTERVAL 30 DAY)
                    AND @as_of_date,
                  temp_max_c, NULL
                )) AS recent_mean_c,
                STDDEV_POP(IF(
                  observation_date BETWEEN DATE_SUB(@as_of_date, INTERVAL 30 DAY)
                    AND @as_of_date,
                  temp_max_c, NULL
                )) AS recent_stddev_c,
                COUNTIF(
                  observation_date BETWEEN DATE_SUB(@as_of_date, INTERVAL 30 DAY)
                    AND @as_of_date
                  AND temp_max_c IS NOT NULL
                ) AS recent_days
              FROM `{self.project}.{dataset}.weather_landing`
              WHERE observation_date BETWEEN DATE_SUB(@as_of_date, INTERVAL 60 DAY)
                AND @as_of_date
              GROUP BY province_id
            )
            SELECT
              province_id,
              baseline_mean_c,
              baseline_stddev_c,
              baseline_days,
              recent_mean_c,
              recent_stddev_c,
              recent_days,
              SAFE_DIVIDE(
                ABS(recent_mean_c - baseline_mean_c),
                GREATEST(baseline_stddev_c, 0.5)
              ) AS mean_z_score,
              SAFE_DIVIDE(
                ABS(recent_stddev_c - baseline_stddev_c),
                GREATEST(baseline_stddev_c, 0.5)
              ) AS stddev_z_score
            FROM period_stats
            WHERE baseline_days >= 20 AND recent_days >= 20
            """
        return self._query(
            query,
            [bigquery.ScalarQueryParameter("as_of_date", "DATE", as_of_date)],
        )


def _as_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"summary": value}
        return parsed if isinstance(parsed, dict) else {"summary": parsed}
    return {"summary": value}


def _event_type(check_id: str) -> str:
    return _EVENT_TYPE_BY_CHECK.get(check_id, "DQ_GATE_FAILED")


def _event_date(row: dict[str, Any], observed: dict[str, Any], fallback: date) -> str:
    value = observed.get("date")
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return value
        except ValueError:
            pass
    ts = row.get("ts")
    if isinstance(ts, datetime):
        return ts.date().isoformat()
    if isinstance(ts, str) and len(ts) >= 10:
        return ts[:10]
    return fallback.isoformat()


def _failing_rows_query(project: str, run_id: str, check_id: str) -> str:
    safe_run = run_id.replace("'", "''")
    safe_check = check_id.replace("'", "''")
    return (
        f"SELECT run_id, check_id, failing_rows, observed, threshold "
        f"FROM `{project}.dataforge_dq.dq_results` "
        f"WHERE run_id = '{safe_run}' AND check_id = '{safe_check}' LIMIT 5"
    )


def event_from_result(
    row: dict[str, Any], *, dataset: str, fallback_date: date, project: str = PROJECT_ID
) -> DQEvent | None:
    """Map recorded DQ results to an event; do not re-evaluate the gate."""
    check_id = str(row.get("check_id") or "")
    severity = str(row.get("severity") or "None")
    status = str(row.get("status") or "").upper()
    if not check_id or severity == "None" or status not in {"PASS", "FAIL", "WARN"}:
        return None
    observed = _as_object(row.get("observed"))
    row_dataset = observed.get("dataset")
    if row_dataset != dataset:
        return None
    run_id = str(row.get("run_id") or "unknown-run")
    event_type = _event_type(check_id)
    event_date = _event_date(row, observed, fallback_date)
    publish_action = observed.get("publish_action")
    published_value = observed.get("published")
    if isinstance(published_value, bool):
        published = published_value
    elif publish_action == "BLOCK":
        published = False
    elif status == "WARN":
        published = True
    else:
        published = not (severity == "P1" and status == "FAIL")
    return DQEvent(
        event_type=event_type,
        run_id=run_id,
        check_id=check_id,
        severity=severity,
        status=status,
        dataset=dataset,
        event_date=event_date,
        runbook_url=f"{RUNBOOK_BASE_URL}/{_RUNBOOKS[event_type]}",
        failing_rows=int(row.get("failing_rows") or 0),
        observed=observed,
        threshold=_as_object(row.get("threshold")),
        published=published,
        failing_rows_query=_failing_rows_query(project, run_id, check_id),
    )


def load_weather_contract(path: Path = CONTRACT_PATH) -> dict[str, str]:
    import yaml

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    tables = document.get("schema", [])
    if not tables or not isinstance(tables[0].get("properties"), list):
        raise ValueError("weather landing contract does not contain property definitions")
    return {
        str(prop["name"]): str(prop["physicalType"]).upper()
        for prop in tables[0]["properties"]
    }


def _schema_event(
    *,
    check_id: str,
    severity: str,
    status: str,
    run_id: str,
    dataset: str,
    event_date: date,
    observed: dict[str, Any],
    threshold: Any,
    failing_rows: int,
    project: str,
) -> DQEvent:
    return DQEvent(
        event_type="SCHEMA_DRIFT",
        run_id=run_id,
        check_id=check_id,
        severity=severity,
        status=status,
        dataset=dataset,
        event_date=event_date.isoformat(),
        runbook_url=f"{RUNBOOK_BASE_URL}/SCHEMA_DRIFT.md",
        failing_rows=failing_rows,
        observed={**observed, "date": event_date.isoformat(), "dataset": dataset},
        threshold=threshold,
        published=(status != "FAIL" or severity != "P1"),
        failing_rows_query=(
            f"SELECT column_name, data_type, is_nullable FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS` "
            "WHERE table_name = 'weather_landing'"
        ),
    )


def schema_drift_events(
    expected: dict[str, str],
    actual_rows: list[dict[str, Any]],
    *,
    run_id: str,
    dataset: str,
    event_date: date,
    project: str = PROJECT_ID,
) -> list[DQEvent]:
    """Compare INFORMATION_SCHEMA metadata with the ODCS physical schema."""
    if not actual_rows:
        # An absent isolated table is setup-incomplete, not evidence of schema drift.
        return []
    actual = {
        str(row["column_name"]): {
            "data_type": str(row["data_type"]).upper(),
            "nullable": str(row["is_nullable"]).upper() == "YES",
        }
        for row in actual_rows
    }
    missing = sorted(set(expected) - set(actual))
    type_changes = sorted(
        name
        for name in set(expected) & set(actual)
        if actual[name]["data_type"] != expected[name]
    )
    additions = sorted(set(actual) - set(expected))
    required_additions = [name for name in additions if not actual[name]["nullable"]]
    nullable_additions = [name for name in additions if actual[name]["nullable"]]
    events: list[DQEvent] = []
    if missing or type_changes or required_additions:
        events.append(
            _schema_event(
                check_id="G1.LANDING.SCHEMA",
                severity="P1",
                status="FAIL",
                run_id=run_id,
                dataset=dataset,
                event_date=event_date,
                observed={
                    "missing_columns": missing,
                    "type_changes": {
                        name: {"expected": expected[name], "actual": actual[name]["data_type"]}
                        for name in type_changes
                    },
                    "unexpected_required_columns": required_additions,
                },
                threshold={"required_columns": expected},
                failing_rows=len(missing) + len(type_changes) + len(required_additions),
                project=project,
            )
        )
    if nullable_additions:
        events.append(
            _schema_event(
                check_id="G1.LANDING.SCHEMA_ADDITIVE",
                severity="P2",
                status="WARN",
                run_id=run_id,
                dataset=dataset,
                event_date=event_date,
                observed={"nullable_additions": nullable_additions},
                threshold={"unknown_nullable_columns": "warn and publish"},
                failing_rows=0,
                project=project,
            )
        )
    if not events:
        for check_id, severity in (
            ("G1.LANDING.SCHEMA", "P1"),
            ("G1.LANDING.SCHEMA_ADDITIVE", "P2"),
        ):
            events.append(
                _schema_event(
                    check_id=check_id,
                    severity=severity,
                    status="PASS",
                    run_id=run_id,
                    dataset=dataset,
                    event_date=event_date,
                    observed={},
                    threshold={"required_columns": expected},
                    failing_rows=0,
                    project=project,
                )
            )
    return events


def temperature_distribution_event(
    rows: list[dict[str, Any]], *, dataset: str, event_date: date, run_id: str
) -> DQEvent:
    """Create a P2 finding from the monitor's 30-day baseline query output."""
    anomalies = []
    for row in rows:
        mean_z = float(row.get("mean_z_score") or 0)
        stddev_z = float(row.get("stddev_z_score") or 0)
        if mean_z > 3 or stddev_z > 3:
            anomalies.append(
                {
                    "province_id": row.get("province_id"),
                    "mean_z_score": round(mean_z, 3),
                    "stddev_z_score": round(stddev_z, 3),
                    "baseline_days": int(row.get("baseline_days") or 0),
                    "recent_days": int(row.get("recent_days") or 0),
                }
            )
    return DQEvent(
        event_type="VOLUME_ANOMALY",
        run_id=run_id,
        check_id="MONITOR.WEATHER.TEMP_DISTRIBUTION",
        severity="P2",
        status="WARN" if anomalies else "PASS",
        dataset=dataset,
        event_date=event_date.isoformat(),
        runbook_url=f"{RUNBOOK_BASE_URL}/VOLUME_ANOMALY.md",
        failing_rows=len(anomalies),
        observed={
            "monitor_type": "temperature_distribution",
            "anomalies": anomalies,
            "date": event_date.isoformat(),
            "dataset": dataset,
        },
        threshold={"minimum_days_per_window": 20, "max_z_score": 3},
        published=True,
        failing_rows_query=(
            f"SELECT province_id, observation_date, temp_max_c FROM `{PROJECT_ID}.{dataset}.weather_landing` "
            f"WHERE observation_date BETWEEN DATE_SUB(DATE '{event_date.isoformat()}', INTERVAL 30 DAY) "
            f"AND DATE '{event_date.isoformat()}' ORDER BY province_id, observation_date LIMIT 5"
        ),
    )


def heartbeat_event(*, dataset: str, event_date: date, run_id: str) -> DQEvent:
    return DQEvent(
        event_type="DQ_HEARTBEAT",
        run_id=run_id,
        check_id="ALERTING.DQ_HEARTBEAT",
        severity="P3",
        status="PASS",
        dataset=dataset,
        event_date=event_date.isoformat(),
        runbook_url=f"{RUNBOOK_BASE_URL}/DQ_HEARTBEAT.md",
        failing_rows=0,
        observed={"date": event_date.isoformat(), "dataset": dataset},
        threshold={"successful_g2_result": "present"},
        published=True,
        failing_rows_query=(
            f"SELECT run_id, check_id, status, ts FROM `{PROJECT_ID}.dataforge_dq.dq_results` "
            "WHERE status = 'PASS' AND layer = 'G2' ORDER BY ts DESC LIMIT 5"
        ),
    )


def run_monitors(
    source: MonitorSource,
    *,
    dataset: str,
    run_date: date,
    contract_columns: dict[str, str] | None = None,
) -> list[DQEvent]:
    """Build monitor events from persisted gate results and metadata."""
    require_isolated_dataset(dataset)
    expected = contract_columns or load_weather_contract()
    rows = source.read_dq_results(run_date)
    events = [
        event
        for row in rows
        if (
            event := event_from_result(
                row,
                dataset=dataset,
                fallback_date=run_date,
            )
        )
        is not None
    ]
    monitor_run_id = f"monitor-{uuid4().hex}"
    actual_columns = source.read_columns(dataset)
    if actual_columns:
        events.extend(
            schema_drift_events(
                expected,
                actual_columns,
                run_id=monitor_run_id,
                dataset=dataset,
                event_date=run_date,
            )
        )
    latest_landed_at = source.read_latest_landed_at(dataset)
    if latest_landed_at is not None:
        if isinstance(latest_landed_at, str):
            latest_landed_at = datetime.fromisoformat(latest_landed_at.replace("Z", "+00:00"))
        if latest_landed_at.tzinfo is None:
            latest_landed_at = latest_landed_at.replace(tzinfo=timezone.utc)
        age_hours = (
            datetime.now(timezone.utc) - latest_landed_at.astimezone(timezone.utc)
        ).total_seconds() / 3600
        events = [
            replace(
                event,
                observed={
                    **event.observed,
                    "latest_landed_at": latest_landed_at.isoformat(),
                    "age_hours": round(age_hours, 3),
                },
            )
            if event.event_type == "FRESHNESS_BREACH"
            else event
            for event in events
        ]
    events.append(
        temperature_distribution_event(
            source.read_temperature_distribution(dataset, run_date),
            dataset=dataset,
            event_date=run_date,
            run_id=monitor_run_id,
        )
    )
    has_gold_success = any(
        row.get("layer") == "G2"
        and row.get("status") == "PASS"
        and row.get("severity") not in {"None", None}
        and str(row.get("check_id", "")).startswith("G2.WEATHER.")
        and _as_object(row.get("observed")).get("dataset") == dataset
        for row in rows
    )
    if has_gold_success:
        events.append(heartbeat_event(dataset=dataset, event_date=run_date, run_id=monitor_run_id))
    return events


def _logging_severity(event: DQEvent) -> str:
    if event.status == "PASS" or event.severity == "P3":
        return "INFO"
    return "ERROR" if event.severity == "P1" else "WARNING"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--date", required=True, dest="run_date")
    parser.add_argument("--emit-logs", action="store_true")
    parser.add_argument("--send-alerts", action="store_true")
    args = parser.parse_args(argv)
    try:
        run_date = date.fromisoformat(args.run_date)
        if run_date.isoformat() != args.run_date:
            raise ValueError("date must use canonical YYYY-MM-DD")
        require_isolated_dataset(args.dataset)
        source = BigQueryMonitorSource()
        events = run_monitors(source, dataset=args.dataset, run_date=run_date)
        digest_events: list[DQEvent] = []
        if args.send_alerts:
            from .notifications import (
                BigQueryAlertStateStore,
                MemoryDigestSink,
                NotificationRouter,
                SecretManagerWebhookProvider,
                SlackWebhookNotifier,
            )

            router = NotificationRouter(
                state_store=BigQueryAlertStateStore(),
                slack=SlackWebhookNotifier(SecretManagerWebhookProvider()),
                digest=MemoryDigestSink(),
            )
            sink: EventSink = CloudLoggingEventSink()
            for event in events:
                sink.write(event)
                router.route(event)
            digest_events = router.digest.events
        elif args.emit_logs:
            sink = CloudLoggingEventSink()
            for event in events:
                sink.write(event)
        else:
            for event in events:
                print(json.dumps(event.as_log_payload(), sort_keys=True))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "events": len(events),
                "logged_to_cloud": args.emit_logs or args.send_alerts,
                "daily_digest_events": len(digest_events),
                "daily_digest": [event.as_log_payload() for event in digest_events],
            },
            sort_keys=True,
        )
    )
    return 0
