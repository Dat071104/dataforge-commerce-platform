"""Safe, structured persistence for DataForge DQ results."""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

RESULT_TABLE = "dataforge_dq.dq_results"
_DATASET_ALLOWLIST = re.compile(r"^(?:w9_drill|dbt_ci_pr_[A-Za-z0-9_-]+)$")


@dataclass(frozen=True)
class DQResult:
    run_id: str
    check_id: str
    layer: str
    severity: str
    status: str
    observed: str
    threshold: str
    failing_rows: int
    contract_version: str
    ts: str

    def as_row(self) -> dict[str, object]:
        return asdict(self)


class ResultSink(Protocol):
    def write(self, results: list[DQResult]) -> None: ...


class MemoryResultSink:
    """In-process sink used by local tests and fault drills."""

    def __init__(self) -> None:
        self.results: list[DQResult] = []

    def write(self, results: list[DQResult]) -> None:
        self.results.extend(results)


class JsonlResultSink:
    """Local evidence sink; does not connect to cloud services."""

    def __init__(self, path: str) -> None:
        self.path = path

    def write(self, results: list[DQResult]) -> None:
        with open(self.path, "a", encoding="utf-8", newline="\n") as stream:
            for result in results:
                stream.write(json.dumps(result.as_row(), sort_keys=True) + "\n")


class BigQueryResultSink:
    """Append gate summaries to the dedicated W9 DQ dataset only."""

    def __init__(self, project: str, client=None) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
            raise ValueError("DATAFORGE_PROJECT_ID must be a valid project ID")
        self.project = project
        if client is None:
            from google.cloud import bigquery

            client = bigquery.Client(project=project)
        self.client = client

    @property
    def table_id(self) -> str:
        return f"{self.project}.{RESULT_TABLE}"

    def write(self, results: list[DQResult]) -> None:
        if not results:
            return
        from google.cloud import bigquery

        table = bigquery.Table(
            self.table_id,
            schema=[
                bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("check_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("layer", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("severity", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("observed", "STRING"),
                bigquery.SchemaField("threshold", "STRING"),
                bigquery.SchemaField("failing_rows", "INT64", mode="REQUIRED"),
                bigquery.SchemaField("contract_version", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("ts", "TIMESTAMP", mode="REQUIRED"),
            ],
        )
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="ts",
        )
        table.clustering_fields = ["check_id", "layer", "severity"]
        self.client.create_table(table, exists_ok=True)
        errors = self.client.insert_rows_json(
            self.table_id,
            [result.as_row() for result in results],
            row_ids=[f"{row.run_id}:{row.check_id}" for row in results],
        )
        if errors:
            raise RuntimeError("DQ result rows could not be persisted to dataforge_dq.dq_results")


def new_run_id() -> str:
    return uuid4().hex


def make_result(
    *,
    run_id: str,
    check_id: str,
    layer: str,
    severity: str,
    status: str,
    observed: object,
    threshold: object,
    failing_rows: int,
    contract_version: str,
) -> DQResult:
    """Create a result row without including raw source values."""
    if severity not in {"P1", "P2", "P3", "None"}:
        raise ValueError(f"unsupported DQ severity: {severity}")
    if status not in {"PASS", "FAIL", "WARN", "NOOP"}:
        raise ValueError(f"unsupported DQ result status: {status}")
    if failing_rows < 0:
        raise ValueError("failing_rows must be non-negative")
    return DQResult(
        run_id=run_id,
        check_id=check_id,
        layer=layer,
        severity=severity,
        status=status,
        observed=json.dumps(observed, sort_keys=True, default=str),
        threshold=json.dumps(threshold, sort_keys=True, default=str),
        failing_rows=failing_rows,
        contract_version=contract_version,
        ts=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def add_result_context(
    result: DQResult,
    *,
    dataset: str,
    event_date: str,
    publish_action: str,
) -> DQResult:
    """Add non-sensitive dataset/date context to the JSON ``observed`` field."""
    try:
        observed = json.loads(result.observed)
    except json.JSONDecodeError:
        observed = {"summary": result.observed}
    if not isinstance(observed, dict):
        observed = {"summary": observed}
    observed.update(
        {
            "dataset": dataset,
            "date": event_date,
            "publish_action": publish_action,
            "published": publish_action != "BLOCK",
        }
    )
    return replace(result, observed=json.dumps(observed, sort_keys=True, default=str))


def cloud_sink_from_env() -> BigQueryResultSink:
    dataset = os.environ.get("DATAFORGE_DQ_DATASET", "dataforge_dq")
    if dataset != "dataforge_dq":
        raise ValueError("DQ results may only be written to dataforge_dq")
    project = os.environ.get("DATAFORGE_PROJECT_ID", "dataforge-p7-lab-d0f725")
    if project != "dataforge-p7-lab-d0f725":
        raise ValueError("DQ result writes are restricted to the approved DataForge project")
    return BigQueryResultSink(project)


def require_isolated_dataset(dataset: str) -> None:
    if not _DATASET_ALLOWLIST.fullmatch(dataset):
        raise ValueError("DQ gates are restricted to w9_drill or dbt_ci_pr_* datasets")
