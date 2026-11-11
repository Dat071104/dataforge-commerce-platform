"""Safely seed the Terraform-created Week-7 control singletons using ADC."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from dataforge.settings import ROOT

TARGET_FILE = ROOT / "docs" / "cloud" / "target.json"
BOOTSTRAP_SQL = ROOT / "cloud" / "sql_bigquery" / "week7" / "001_initialize.sql"
CURRENTNESS_VIEW_SQL = ROOT / "cloud" / "sql_bigquery" / "week7" / "002_current_publication_view.sql"
EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
EXPECTED_PROJECT_NUMBER = "955038620072"
EXPECTED_REGION = "us-central1"
MAXIMUM_BYTES_BILLED = 268_435_456


class Week7BootstrapError(RuntimeError):
    """A target or bootstrap contract failed closed."""


def _load_approved_target(path: Path = TARGET_FILE) -> dict[str, Any]:
    try:
        target = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Week7BootstrapError("The approved cloud target file is missing or invalid") from exc
    if (
        target.get("project_id") != EXPECTED_PROJECT
        or target.get("project_number") != EXPECTED_PROJECT_NUMBER
        or target.get("region") != EXPECTED_REGION
    ):
        raise Week7BootstrapError("Week-7 bootstrap is restricted to the approved project and region")
    return target


def _load_approved_sql(target: dict[str, Any], path: Path = BOOTSTRAP_SQL) -> str:
    try:
        sql = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Week7BootstrapError("Week-7 bootstrap SQL is missing") from exc
    required_tables = (
        f"`{target['project_id']}.ops.week7_publish_lock`",
        f"`{target['project_id']}.gold_week7.week7_publication_pointer`",
    )
    if not sql.strip() or any(table not in sql for table in required_tables):
        raise Week7BootstrapError("Bootstrap SQL does not match the approved Week-7 control tables")
    sql_without_comments = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql_without_comments = re.sub(r"(?m)--.*$", "", sql_without_comments)
    if re.search(
        r"\b(DROP|DELETE|TRUNCATE|CREATE\s+OR\s+REPLACE)\b",
        sql_without_comments,
        re.IGNORECASE,
    ):
        raise Week7BootstrapError("Bootstrap SQL contains a destructive or replacing statement")
    return sql


def _load_currentness_view_sql(target: dict[str, Any], path: Path = CURRENTNESS_VIEW_SQL) -> str:
    try:
        sql = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Week7BootstrapError("Publication currentness view SQL is missing") from exc
    required_relations = (
        f"`{target['project_id']}.gold_week7.week7_order_reconciliation_versions`",
        f"`{target['project_id']}.gold_week7.week7_publication_pointer`",
        f"`{target['project_id']}.gold_week7.published_order_reconciliation`",
    )
    sql_without_comments = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql_without_comments = re.sub(r"(?m)--.*$", "", sql_without_comments)
    normalized = re.sub(r"\s+", " ", sql_without_comments).strip().rstrip(";")
    if (
        any(relation not in sql for relation in required_relations)
        or ";" in normalized
        or not re.match(
            rf"(?is)^CREATE\s+OR\s+REPLACE\s+VIEW\s+`{re.escape(target['project_id'])}\.gold_week7\.published_order_reconciliation`\s+AS\b",
            normalized,
        )
        or re.search(r"\b(DROP|DELETE|TRUNCATE|UPDATE|INSERT|MERGE|ALTER)\b", sql_without_comments, re.IGNORECASE)
        or "pointer.publication_is_current IS TRUE" not in sql_without_comments
    ):
        raise Week7BootstrapError("Currentness view SQL may replace only the approved filtered view")
    return sql


def _receipt(
    *,
    target: dict[str, Any],
    sql_sha256: str,
    status: str,
    bootstrap_job_id: str | None = None,
    bytes_billed: int | None = None,
    verification_job_id: str | None = None,
    verification_bytes_billed: int | None = None,
    lock_rows: int | None = None,
    lock_version: int | None = None,
    pointer_rows: int | None = None,
    pointer_version: int | None = None,
    publication_is_current: bool | None = None,
    view_refresh_status: str | None = None,
    view_refresh_job_id: str | None = None,
    view_refresh_bytes_billed: int | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "project_id": target["project_id"],
        "project_number": target["project_number"],
        "region": target["region"],
        "bootstrap_sql_sha256": sql_sha256,
        "bootstrap_job_id": bootstrap_job_id,
        "bytes_billed": bytes_billed,
        "verification_job_id": verification_job_id,
        "verification_bytes_billed": verification_bytes_billed,
        "maximum_bytes_billed": MAXIMUM_BYTES_BILLED,
        "lock_rows": lock_rows,
        "lock_version": lock_version,
        "pointer_rows": pointer_rows,
        "pointer_version": pointer_version,
        "publication_is_current": publication_is_current,
        "view_refresh_status": view_refresh_status,
        "view_refresh_job_id": view_refresh_job_id,
        "view_refresh_bytes_billed": view_refresh_bytes_billed,
    }


def initialize_week7(*, execute: bool, output: Path | None = None) -> dict[str, Any]:
    target = _load_approved_target()
    sql = _load_approved_sql(target)
    view_sql = _load_currentness_view_sql(target)
    sql_sha256 = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    if not execute:
        result = _receipt(
            target=target,
            sql_sha256=sql_sha256,
            status="DRY_RUN_NO_CLOUD_WRITE",
            view_refresh_status="DRY_RUN_NOT_APPLIED",
        )
    else:
        try:
            import google.auth
            from google.auth.transport.requests import Request
            from google.cloud import bigquery
        except ImportError as exc:
            raise Week7BootstrapError("Cloud bootstrap requires the project's [gcp] dependencies") from exc

        credentials, adc_project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(Request())
        if adc_project and adc_project != target["project_id"]:
            raise Week7BootstrapError("ADC project differs from the approved DataForge project")

        client = bigquery.Client(
            project=target["project_id"],
            credentials=credentials,
            location=target["region"],
        )
        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAXIMUM_BYTES_BILLED),
            location=target["region"],
        )
        list(job.result())
        verify = client.query(
            f"""
            SELECT
              (SELECT COUNT(*) FROM `{target['project_id']}.ops.week7_publish_lock`
               WHERE lock_name = 'week7-dbt-publication') AS lock_rows,
              (SELECT MAX(lock_version) FROM `{target['project_id']}.ops.week7_publish_lock`
               WHERE lock_name = 'week7-dbt-publication') AS lock_version,
              (SELECT COUNT(*) FROM `{target['project_id']}.gold_week7.week7_publication_pointer`
               WHERE pointer_name = 'current_order_reconciliation') AS pointer_rows,
              (SELECT MAX(pointer_version) FROM `{target['project_id']}.gold_week7.week7_publication_pointer`
               WHERE pointer_name = 'current_order_reconciliation') AS pointer_version,
              (SELECT LOGICAL_AND(publication_is_current)
               FROM `{target['project_id']}.gold_week7.week7_publication_pointer`
               WHERE pointer_name = 'current_order_reconciliation') AS publication_is_current
            """,
            job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAXIMUM_BYTES_BILLED),
            location=target["region"],
        )
        row = next(iter(verify.result()))
        lock_rows = int(row["lock_rows"] or 0)
        pointer_rows = int(row["pointer_rows"] or 0)
        if lock_rows != 1 or pointer_rows != 1:
            raise Week7BootstrapError("Bootstrap verification found an invalid singleton row count")
        result = _receipt(
            target=target,
            sql_sha256=sql_sha256,
            status="BOOTSTRAP_COMPLETE",
            bootstrap_job_id=job.job_id,
            bytes_billed=int(job.total_bytes_billed or 0),
            verification_job_id=verify.job_id,
            verification_bytes_billed=int(verify.total_bytes_billed or 0),
            lock_rows=lock_rows,
            lock_version=int(row["lock_version"] or 0),
            pointer_rows=pointer_rows,
            pointer_version=int(row["pointer_version"] or 0),
            publication_is_current=bool(row["publication_is_current"]),
        )
        if int(row["pointer_version"] or 0) > 0:
            view_job = client.query(
                view_sql,
                job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAXIMUM_BYTES_BILLED),
                location=target["region"],
            )
            list(view_job.result())
            result.update(
                {
                    "view_refresh_status": "CURRENTNESS_FENCE_APPLIED",
                    "view_refresh_job_id": view_job.job_id,
                    "view_refresh_bytes_billed": int(view_job.total_bytes_billed or 0),
                }
            )
        else:
            result["view_refresh_status"] = "NOT_YET_PUBLISHED_NO_VIEW_TO_REPLACE"

    encoded = json.dumps(result, indent=2, sort_keys=True)
    if output:
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run the Week-7 control bootstrap, or execute it once with --execute."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="submit the idempotent BigQuery singleton bootstrap; no tables are dropped or reset",
    )
    parser.add_argument("--output", type=Path, help="optional sanitized JSON receipt path")
    args = parser.parse_args(argv)
    try:
        initialize_week7(execute=args.execute, output=args.output)
    except Week7BootstrapError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
