"""Run the bounded Week 9 lineage build in the fixed w9_drill dataset."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

PROJECT_ID = "dataforge-p7-lab-d0f725"
LOCATION = "us-central1"
SOURCE_DATASET = "weather_mini3"
TARGET_DATASET = "w9_drill"
TABLE_NAME = "weather_landing"
MAXIMUM_BYTES_BILLED = 1024**3
MAX_RUN_BYTES_BILLED = 5 * 1024**3

EXPECTED_SOURCE_SCHEMA = {
    "province_id": ("STRING", "REQUIRED"),
    "observation_date": ("DATE", "REQUIRED"),
    "precipitation_mm": ("FLOAT", "NULLABLE"),
    "temp_max_c": ("FLOAT", "NULLABLE"),
    "source": ("STRING", "REQUIRED"),
    "model": ("STRING", "REQUIRED"),
    "request_id": ("STRING", "REQUIRED"),
    "source_sha256": ("STRING", "REQUIRED"),
    "manifest_uri": ("STRING", "REQUIRED"),
    "manifest_generation": ("INTEGER", "REQUIRED"),
    "landed_at": ("TIMESTAMP", "REQUIRED"),
}
EXPECTED_OUTPUT_TYPES = {name: field_type for name, (field_type, _) in EXPECTED_SOURCE_SCHEMA.items()}


class LineageBuildError(RuntimeError):
    """A safe-to-log failure for a fixed Week 9 lineage operation."""


def _normalize_type(value: str) -> str:
    return {"FLOAT64": "FLOAT", "INT64": "INTEGER"}.get(value.upper(), value.upper())


def schema_signature(fields: Sequence[Any], *, include_mode: bool) -> dict[str, Any]:
    signature = {}
    for field in fields:
        if isinstance(field, dict):
            name = field.get("name")
            field_type = field.get("type", field.get("field_type", ""))
            mode = field.get("mode", "NULLABLE")
        else:
            name = getattr(field, "name", None)
            field_type = getattr(field, "field_type", "")
            mode = getattr(field, "mode", "NULLABLE")
        if not name or not field_type or name in signature:
            raise LineageBuildError("BigQuery table schema is missing or has duplicate fields")
        normalized_type = _normalize_type(str(field_type))
        signature[name] = (normalized_type, str(mode).upper()) if include_mode else normalized_type
    return signature


def partition_literals(partition_ids: Sequence[str]) -> tuple[str, date]:
    if len(partition_ids) != 7 or len(set(partition_ids)) != 7:
        raise LineageBuildError("Expected exactly seven distinct date partitions")
    dates = []
    for value in partition_ids:
        if re.fullmatch(r"[0-9]{8}", value) is None:
            raise LineageBuildError("Partition metadata contains an invalid date partition")
        try:
            dates.append(datetime.strptime(value, "%Y%m%d").date())
        except ValueError:
            raise LineageBuildError("Partition metadata contains an invalid calendar date") from None
    return ", ".join(f"DATE '{value.isoformat()}'" for value in dates), dates[0]


def validate_manifest(manifest: dict[str, Any]) -> int:
    weather_models = [
        node
        for node in manifest.get("nodes", {}).values()
        if node.get("resource_type") == "model" and "weather_mini3" in node.get("tags", [])
    ]
    if not weather_models:
        raise LineageBuildError("No weather_mini3 dbt models resolved for the lineage build")
    if any(
        node.get("database") != PROJECT_ID or node.get("schema") != TARGET_DATASET
        for node in weather_models
    ):
        raise LineageBuildError("Weather model destinations are outside the fixed w9_drill dataset")
    weather_sources = [
        source
        for source in manifest.get("sources", {}).values()
        if source.get("source_name") == "weather_mini3" and source.get("name") == TABLE_NAME
    ]
    if len(weather_sources) != 1:
        raise LineageBuildError("Expected exactly one weather_mini3.weather_landing source")
    source = weather_sources[0]
    if source.get("database") != PROJECT_ID or source.get("schema") != TARGET_DATASET:
        raise LineageBuildError("dbt source is not fixed to w9_drill.weather_landing")
    return len(weather_models)


def summarize_dbt_results(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    job_ids = set()
    billed_by_job: dict[str, int] = {}
    unidentified_billed_results = 0
    unidentified_billed_count = 0
    for item in results:
        adapter = item.get("adapter_response") or {}
        job_id = adapter.get("job_id")
        if not isinstance(job_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", job_id) is None:
            job_id = None
        if job_id is not None:
            job_ids.add(job_id)
        billed = adapter.get("bytes_billed")
        if billed is not None:
            try:
                billed_value = int(billed)
            except (TypeError, ValueError):
                continue
            if job_id is None:
                unidentified_billed_results += billed_value
                unidentified_billed_count += 1
            else:
                billed_by_job[job_id] = max(billed_by_job.get(job_id, 0), billed_value)
    return {
        "dbt_jobs_seen": len(job_ids),
        "dbt_jobs_with_billing": len(billed_by_job),
        "adapter_bytes_billed": sum(billed_by_job.values()) + unidentified_billed_results,
        "dbt_results_with_billing_without_job_id": unidentified_billed_count,
        "dbt_job_ids": sorted(job_ids),
        "usage_records": [
            {"job_id": job_id, "bytes_billed": billed_by_job[job_id]}
            for job_id in sorted(billed_by_job)
        ],
    }


def _finalize_run_cost(summary: dict[str, Any]) -> dict[str, Any]:
    dbt = summary.get("dbt") if isinstance(summary.get("dbt"), dict) else {}
    jobs_seen = int(dbt.get("dbt_jobs_seen", 0) or 0)
    jobs_with_billing = int(dbt.get("dbt_jobs_with_billing", 0) or 0)
    unidentified = int(dbt.get("dbt_results_with_billing_without_job_id", 0) or 0)
    if jobs_seen != jobs_with_billing or unidentified:
        raise LineageBuildError("Per-run BigQuery billing metadata is incomplete")

    records = []
    for query in summary.get("bigquery_queries", []):
        records.append(
            {"job_id": query.get("job_id"), "bytes_billed": query.get("bytes_billed")}
        )
    records.extend(dbt.get("usage_records", []))

    billed_by_job: dict[str, int] = {}
    for record in records:
        job_id = record.get("job_id")
        bytes_billed = record.get("bytes_billed")
        if (
            not isinstance(job_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", job_id) is None
            or not isinstance(bytes_billed, int)
            or isinstance(bytes_billed, bool)
            or bytes_billed < 0
        ):
            raise LineageBuildError("Per-run BigQuery usage record is incomplete")
        billed_by_job[job_id] = max(billed_by_job.get(job_id, 0), bytes_billed)

    total = sum(billed_by_job.values())
    if total > MAX_RUN_BYTES_BILLED:
        raise LineageBuildError("Per-run BigQuery billed bytes exceeded the 5 GiB ceiling")
    return {
        "paid_job": "lineage-build",
        "guard_status": "PASS",
        "total_bytes_billed": total,
        "max_run_bytes_billed": MAX_RUN_BYTES_BILLED,
        "usage_records": [
            {"job_id": job_id, "bytes_billed": billed_by_job[job_id]}
            for job_id in sorted(billed_by_job)
        ],
    }


def _query_config(action: str):
    from google.cloud import bigquery

    return bigquery.QueryJobConfig(
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        labels={"application": "dataforge", "phase": "w9", "action": action},
    )


def _run_dbt(args: list[str], *, env: dict[str, str], stage: str) -> int:
    try:
        completed = subprocess.run(
            ["dbt", *args],
            cwd="/workspace",
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        raise LineageBuildError(f"dbt {stage} could not start") from None
    return completed.returncode


def _record_query_usage(summary: dict[str, Any], stage: str, job: Any) -> None:
    job_id = str(getattr(job, "job_id", ""))
    if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", job_id) is None:
        job_id = "UNAVAILABLE"
    try:
        bytes_billed = getattr(job, "total_bytes_billed", None)
        if bytes_billed is not None:
            bytes_billed = int(bytes_billed)
    except Exception:
        bytes_billed = None
    summary["bigquery_queries"].append(
        {"stage": stage, "job_id": job_id, "bytes_billed": bytes_billed}
    )
    print(f"{stage} query complete: job_id={job_id}; bytes_billed={bytes_billed}", flush=True)


def run_lineage_build(summary: dict[str, Any]) -> None:
    from google.cloud import bigquery

    if (Path("/workspace/dbt/dataforge") / "packages.yml").exists():
        raise LineageBuildError("dbt package declarations need a committed lock before this lineage path can run")

    client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    try:
        dataset = client.get_dataset(f"{PROJECT_ID}.{TARGET_DATASET}")
        source = client.get_table(f"{PROJECT_ID}.{SOURCE_DATASET}.{TABLE_NAME}")
    except Exception as error:
        raise LineageBuildError(f"Fixed dataset/source metadata read failed ({type(error).__name__})") from None
    if dataset.location != LOCATION:
        raise LineageBuildError("w9_drill is not in the expected us-central1 location")
    source_schema = schema_signature(source.schema, include_mode=True)
    if source_schema != EXPECTED_SOURCE_SCHEMA:
        raise LineageBuildError("Source weather_landing schema does not match the G1/dbt contract")
    if (
        source.time_partitioning is None
        or source.time_partitioning.type_ != "DAY"
        or source.time_partitioning.field != "observation_date"
        or source.require_partition_filter is not True
    ):
        raise LineageBuildError("Source weather_landing partition contract is invalid")

    partition_sql = (
        f"SELECT partition_id FROM `{PROJECT_ID}.{SOURCE_DATASET}.INFORMATION_SCHEMA.PARTITIONS` "
        f"WHERE table_name = '{TABLE_NAME}' AND partition_id IS NOT NULL "
        "AND REGEXP_CONTAINS(partition_id, r'^[0-9]{8}$') "
        "ORDER BY partition_id DESC LIMIT 7"
    )
    try:
        partition_job = client.query(partition_sql, job_config=_query_config("lineage-partitions"), location=LOCATION)
        try:
            partition_ids = [str(row["partition_id"]) for row in partition_job.result(timeout=300)]
        finally:
            _record_query_usage(summary, "partition_metadata", partition_job)
    except Exception as error:
        if isinstance(error, LineageBuildError):
            raise
        raise LineageBuildError(f"Partition metadata query failed ({type(error).__name__})") from None
    literal_filter, _ = partition_literals(partition_ids)
    print(f"Partition metadata validated: count={len(partition_ids)}; job_id={partition_job.job_id}", flush=True)

    copy_sql = (
        f"CREATE OR REPLACE TABLE `{PROJECT_ID}.{TARGET_DATASET}.{TABLE_NAME}` AS "
        f"SELECT * FROM `{PROJECT_ID}.{SOURCE_DATASET}.{TABLE_NAME}` "
        f"WHERE observation_date IN ({literal_filter})"
    )
    try:
        copy_job = client.query(copy_sql, job_config=_query_config("lineage-copy"), location=LOCATION)
        try:
            copy_job.result(timeout=300)
        finally:
            _record_query_usage(summary, "source_copy", copy_job)
        copied_table = client.get_table(f"{PROJECT_ID}.{TARGET_DATASET}.{TABLE_NAME}")
    except Exception as error:
        if isinstance(error, LineageBuildError):
            raise
        raise LineageBuildError(f"Bounded w9_drill source copy failed ({type(error).__name__})") from None
    if schema_signature(copied_table.schema, include_mode=False) != EXPECTED_OUTPUT_TYPES:
        raise LineageBuildError("Copied w9_drill.weather_landing schema is incompatible with G1/dbt")
    print(
        f"w9_drill source copy validated: rows={copied_table.num_rows}; job_id={copy_job.job_id}; "
        f"bytes_billed={copy_job.total_bytes_billed or 0}",
        flush=True,
    )
    summary["partition_count"] = len(partition_ids)
    summary["copied_rows"] = int(copied_table.num_rows)

    as_of_sql = (
        f"SELECT MAX(observation_date) AS as_of_date "
        f"FROM `{PROJECT_ID}.{TARGET_DATASET}.{TABLE_NAME}`"
    )
    try:
        as_of_job = client.query(as_of_sql, job_config=_query_config("lineage-asof"), location=LOCATION)
        try:
            result = next(iter(as_of_job.result(timeout=300)), None)
        finally:
            _record_query_usage(summary, "as_of_date", as_of_job)
    except Exception as error:
        if isinstance(error, LineageBuildError):
            raise
        raise LineageBuildError(f"w9_drill date query failed ({type(error).__name__})") from None
    if result is None or result["as_of_date"] is None:
        raise LineageBuildError("w9_drill source has no observation date")
    as_of_date = result["as_of_date"]
    if not isinstance(as_of_date, date):
        raise LineageBuildError("w9_drill source date has an unexpected type")
    print(f"w9_drill observation date resolved; job_id={as_of_job.job_id}", flush=True)

    env = os.environ.copy()
    env.update(
        {
            "DBT_DATAFORGE_PROJECT_ID": PROJECT_ID,
            "DBT_DATAFORGE_TARGET_DATASET": TARGET_DATASET,
            "DBT_WEATHER_LANDING_SCHEMA": TARGET_DATASET,
            "DBT_DATAFORGE_LOCATION": LOCATION,
            "DATAFORGE_PROJECT_ID": PROJECT_ID,
            "DATAFORGE_DQ_RESULTS_ENABLED": "false",
            "DBT_PROFILES_DIR": "/profiles",
            "DBT_TARGET_PATH": "/tmp/dbt-target",
            "DBT_LOG_PATH": "/tmp/dbt-logs",
        }
    )
    target_path = Path(env["DBT_TARGET_PATH"])
    target_path.mkdir(parents=True, exist_ok=True)
    common = [
        "--project-dir", "/workspace/dbt/dataforge",
        "--profiles-dir", "/profiles",
        "--target", "w9_ci",
        "--no-partial-parse",
        "--no-send-anonymous-usage-stats",
        "--no-version-check",
    ]
    parse_code = _run_dbt(["parse", *common], env=env, stage="parse")
    if parse_code != 0:
        raise LineageBuildError(f"dbt parse failed (exit {parse_code}); output suppressed")
    try:
        manifest = json.loads((target_path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise LineageBuildError("dbt destination manifest is missing or invalid") from None
    model_count = validate_manifest(manifest)
    summary["weather_models"] = model_count
    print(f"dbt destinations validated: weather_models={model_count}; dataset={TARGET_DATASET}", flush=True)

    dbt_vars = json.dumps({"weather_observation_date": as_of_date.isoformat()}, separators=(",", ":"))
    build_code = _run_dbt(
        ["build", *common, "--select", "tag:weather_mini3", "--vars", dbt_vars],
        env=env,
        stage="build",
    )
    try:
        run_results = json.loads((target_path / "run_results.json").read_text(encoding="utf-8"))
        results = run_results.get("results", [])
    except (OSError, json.JSONDecodeError):
        results = []
    summary["dbt"].update(summarize_dbt_results(results))
    summary["dbt"]["build_status"] = "PASS" if build_code == 0 else "FAIL"
    if build_code != 0:
        raise LineageBuildError(f"dbt build failed (exit {build_code}); output suppressed")
    print(f"dbt build passed: dataset={TARGET_DATASET}", flush=True)


def _safe_run_value(name: str) -> str:
    value = os.environ.get(name, "")
    return value if re.fullmatch(r"[0-9]{1,32}", value) else "UNVERIFIED"


def _write_summary(summary: dict[str, Any]) -> None:
    try:
        path = Path("/summary/w9-lineage-summary.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    except OSError:
        print("::warning::Sanitized cost summary could not be written", flush=True)


def main() -> int:
    summary: dict[str, Any] = {
        "workflow_run_id": _safe_run_value("GITHUB_RUN_ID"),
        "workflow_run_attempt": _safe_run_value("GITHUB_RUN_ATTEMPT"),
        "pr_number": _safe_run_value("PR_NUMBER"),
        "project": PROJECT_ID,
        "dataset": TARGET_DATASET,
        "status": "UNVERIFIED",
        "billing_sku": "UNVERIFIED",
        "partition_count": 0,
        "copied_rows": 0,
        "weather_models": 0,
        "bigquery_queries": [],
        "dbt": {"build_status": "UNVERIFIED"},
    }
    try:
        run_lineage_build(summary)
        summary["status"] = "PASS"
    except LineageBuildError as error:
        summary["status"] = "FAIL"
        summary["failure"] = str(error)
        print(f"::error::{error}", flush=True)
    except Exception as error:
        summary["status"] = "FAIL"
        summary["failure"] = f"unhandled_{type(error).__name__}"
        print(f"::error::Lineage build failed ({type(error).__name__}); details suppressed", flush=True)
    finally:
        try:
            summary.update(_finalize_run_cost(summary))
        except LineageBuildError as error:
            summary["guard_status"] = "FAIL"
            summary["cost_guard_failure"] = str(error)
            summary["status"] = "FAIL"
        _write_summary(summary)
    return 0 if summary["status"] == "PASS" and summary.get("guard_status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
