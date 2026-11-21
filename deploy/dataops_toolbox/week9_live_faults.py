"""Run F07 and F10 as isolated BigQuery-only Week 9 fault tests in CI."""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from run_cost_guard import RunCostGuardError, build_usage_artifact, guard_usage_records

PROJECT = "dataforge-p7-lab-d0f725"
LOCATION = "us-central1"
MAXIMUM_BYTES_BILLED = 1024**3
RUN_USAGE_RECORDS: list[dict[str, Any]] = []
RUN_UNKNOWN_QUERY_CAP_COUNT = 0


class FaultMissError(RuntimeError):
    """Expected detector did not fire for its isolated fault."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def table(project: str, dataset: str, name: str) -> str:
    if project != PROJECT:
        raise ValueError("fault SQL is restricted to the approved project")
    if dataset != "w9_drill":
        raise ValueError("live fault SQL is restricted to the isolated w9_drill dataset")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,1023}", name):
        raise ValueError("invalid BigQuery table identifier")
    return f"`{project}.{dataset}.{name}`"


def run_query(client: Any, sql: str, label: str) -> list[Any]:
    from google.cloud import bigquery

    config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        labels={"application": "dataforge", "phase": "w9", "fault": label},
    )
    job = client.query(sql, job_config=config, location=LOCATION)
    try:
        return list(job.result())
    finally:
        RUN_USAGE_RECORDS.append(
            {
                "job_id": getattr(job, "job_id", None),
                "bytes_billed": getattr(job, "total_bytes_billed", None),
            }
        )


def bigquery_ready_parquet(fixture: Path) -> io.BytesIO:
    """Return the fixture with nanosecond timestamps narrowed to microseconds.

    The captured fixture stores ``landed_at`` as ``timestamp[ns, UTC]``. BigQuery has no
    nanosecond TIMESTAMP, so a Parquet load turned it into INT64 and every downstream
    model failed with "Invalid cast from INT64 to TIMESTAMP" (R-18).
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pq.read_table(fixture)
    for index, field in enumerate(table.schema):
        if pa.types.is_timestamp(field.type) and field.type.unit == "ns":
            table = table.set_column(
                index, field.name, table.column(index).cast(pa.timestamp("us", tz=field.type.tz))
            )
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    buffer.seek(0)
    return buffer


def source_slice(client: Any, dataset: str) -> None:
    from google.cloud import bigquery

    table_id = f"{PROJECT}.{dataset}.weather_landing"
    fixture = Path(__file__).resolve().parents[2] / "tests" / "week9" / "faults" / "weather_7date_slice.parquet"
    if not fixture.is_file():
        raise RuntimeError("captured seven-date fixture is missing")
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_file(
        bigquery_ready_parquet(fixture),
        table_id,
        job_config=job_config,
        location=LOCATION,
    )
    job.result(timeout=300)
    loaded = {field.name: field.field_type for field in client.get_table(table_id).schema}
    if loaded.get("landed_at") != "TIMESTAMP":
        raise RuntimeError("isolated source slice did not load landed_at as TIMESTAMP")


def as_of_date(client: Any, dataset: str) -> date:
    rows = run_query(
        client,
        f"SELECT MAX(observation_date) AS as_of_date FROM {table(PROJECT, dataset, 'weather_landing')}",
        "f07",
    )
    if not rows or rows[0]["as_of_date"] is None:
        raise RuntimeError("isolated source slice has no observation date")
    return rows[0]["as_of_date"]


def published_gold_hash(client: Any, dataset: str, as_of: date) -> str:
    mart = table(PROJECT, dataset, "mart_weather_province_daily")
    rows = run_query(
        client,
        f"""
        SELECT TO_HEX(SHA256(COALESCE(
          STRING_AGG(TO_JSON_STRING(t), '\\n' ORDER BY t.province_id, t.observation_date),
          ''
        ))) AS gold_hash
        FROM {mart} AS t
        WHERE t.observation_date BETWEEN DATE_SUB(DATE '{as_of.isoformat()}', INTERVAL 6 DAY)
          AND DATE '{as_of.isoformat()}'
        """,
        "gold-hash",
    )
    return str(rows[0]["gold_hash"] or "") if rows else ""


def dbt_command(target_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    target_path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DBT_TARGET_PATH"] = str(target_path)
    env["DBT_LOG_PATH"] = str(target_path / "logs")
    env["DBT_PROFILES_DIR"] = env.get("DBT_PROFILES_DIR", "/profiles")
    env["DBT_DATAFORGE_PROJECT_ID"] = PROJECT
    env["DBT_DATAFORGE_TARGET_DATASET"] = env["FAULT_DATASET"]
    env["DBT_WEATHER_LANDING_SCHEMA"] = env["FAULT_DATASET"]
    env["DBT_DATAFORGE_LOCATION"] = LOCATION
    env["DATAFORGE_PROJECT_ID"] = PROJECT
    env["DATAFORGE_DQ_RESULTS_ENABLED"] = "true"
    completed = subprocess.run(
        [
            "dbt",
            *args,
            "--project-dir",
            "/workspace/dbt/dataforge",
            "--profiles-dir",
            env["DBT_PROFILES_DIR"],
            "--target",
            "w9_ci",
            "--no-partial-parse",
            "--no-send-anonymous-usage-stats",
            "--no-version-check",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
        env=env,
    )
    _record_dbt_usage(target_path, args)
    return completed


def _record_dbt_usage(target_path: Path, args: tuple[str, ...]) -> None:
    global RUN_UNKNOWN_QUERY_CAP_COUNT
    if "source" in args and "freshness" in args:
        # The dbt source-freshness result does not include adapter job statistics.
        # Reserve its configured per-query maximum in the run-level guard.
        RUN_UNKNOWN_QUERY_CAP_COUNT += 1
        return
    if not any(command in args for command in ("build", "run", "test")):
        return
    results_path = target_path / "run_results.json"
    if not results_path.is_file():
        RUN_USAGE_RECORDS.append({"job_id": "dbt-run-results-missing", "bytes_billed": None})
        return
    try:
        results = json.loads(results_path.read_text(encoding="utf-8")).get("results", [])
    except (OSError, json.JSONDecodeError):
        RUN_USAGE_RECORDS.append({"job_id": "dbt-run-results-invalid", "bytes_billed": None})
        return
    for index, item in enumerate(results):
        adapter = item.get("adapter_response") or {}
        job_id = adapter.get("job_id")
        bytes_billed = adapter.get("bytes_billed")
        if job_id is None and bytes_billed is None:
            continue
        if not isinstance(job_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", job_id) is None:
            job_id = f"dbt-usage-{index}"
        if bytes_billed is not None:
            try:
                bytes_billed = int(bytes_billed)
            except (TypeError, ValueError):
                bytes_billed = None
        RUN_USAGE_RECORDS.append({"job_id": job_id, "bytes_billed": bytes_billed})


def make_row(
    fault: str,
    *,
    injected_at: str,
    detected_at: str,
    action: str,
    gold_before: str,
    gold_after: str,
    result: str,
    evidence: str,
) -> dict[str, str]:
    detector = (
        "G2.SOURCE.FRESHNESS"
        if fault == "F07"
        else "G2.WEATHER.RAIN_PRECIP_CONSISTENCY"
    )
    return {
        "fault": fault,
        "run_id": f"ci-{os.environ.get('GITHUB_RUN_ID', 'run')}-{fault.lower()}",
        "manifest_path": f"{os.environ.get('FAULT_DATASET', 'UNVERIFIED')}.weather_landing",
        "as_of_date": "isolated seven-date slice",
        "injected_at": injected_at,
        "detector": detector,
        "detected_at": detected_at,
        "channel": "NOT_ATTEMPTED (gate test only)",
        "received_at": "NOT_ATTEMPTED",
        "action": action,
        "gold_hash_before": gold_before,
        "gold_hash_after": gold_after,
        "result": result,
        "evidence": evidence,
    }


def run_f07(client: Any, dataset: str, target_root: Path) -> dict[str, str]:
    source_slice(client, dataset)
    build = dbt_command(target_root / "f07-build", "build", "--select", "tag:weather_mini3")
    if build.returncode != 0:
        raise RuntimeError("F07 could not build the clean isolated weather mart")
    as_of = as_of_date(client, dataset)
    before = published_gold_hash(client, dataset, as_of)
    injected_at = utc_now()
    source = table(PROJECT, dataset, "weather_landing")
    try:
        run_query(
            client,
            f"""
            CREATE TEMP TABLE w9_stale_rows AS
            SELECT * REPLACE(TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 73 HOUR) AS landed_at)
            FROM {source};
            CREATE OR REPLACE TABLE {source} AS
            SELECT * FROM w9_stale_rows
            """,
            "f07",
        )
        target_path = target_root / "f07"
        command = dbt_command(
            target_path,
            "source",
            "freshness",
            "--select",
            "source:weather_mini3.weather_landing",
        )
        source_path = target_path / "sources.json"
        if not source_path.is_file():
            raise RuntimeError("dbt source freshness did not write sources.json")
        results = json.loads(source_path.read_text(encoding="utf-8")).get("results", [])
        matching = [
            item for item in results
            if item.get("unique_id") == "source.dataforge.weather_mini3.weather_landing"
        ]
        if len(matching) != 1:
            raise RuntimeError("dbt source freshness result is missing")
        status = str(matching[0].get("state", matching[0].get("status", ""))).lower()
        age = matching[0].get("max_loaded_at_time_ago_in_s")
        if status != "error" or command.returncode == 0:
            raise FaultMissError("F07 stale source did not produce the expected error state")
        if age is not None and float(age) < 72 * 60 * 60:
            raise FaultMissError("F07 source age did not exceed the 72-hour threshold")
        detected_at = utc_now()
    finally:
        source_slice(client, dataset)
    after = published_gold_hash(client, dataset, as_of)
    return make_row(
        "F07",
        injected_at=injected_at,
        detected_at=detected_at,
        action="P1 BLOCK_NEW_PUBLISH after 72 hours",
        gold_before=before,
        gold_after=after,
        result="PASS" if before == after else "FAIL",
        evidence="CI (isolated BigQuery w9_drill source freshness; synthetic 73-hour landed_at)",
    )


def check_f10_result(target_path: Path) -> tuple[bool, int]:
    manifest_path = target_path / "manifest.json"
    results_path = target_path / "run_results.json"
    if not manifest_path.is_file() or not results_path.is_file():
        raise RuntimeError("F10 dbt manifest or run_results.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_results = json.loads(results_path.read_text(encoding="utf-8"))
    entries = [
        item
        for item in run_results.get("results", [])
        if "assert_week9_rain_precip_consistency" in item.get("unique_id", "")
    ]
    if len(entries) != 1:
        raise RuntimeError("F10 singular dbt test result is missing or duplicated")
    unique_id = entries[0]["unique_id"]
    node = manifest.get("nodes", {}).get(unique_id, {})
    config = node.get("config", {})
    meta = config.get("meta", {})
    if (
        meta.get("check_id") != "G2.WEATHER.RAIN_PRECIP_CONSISTENCY"
        or meta.get("w9_severity") != "P1"
        or config.get("severity") != "error"
    ):
        raise RuntimeError("F10 test metadata did not match its P1 blocking catalog entry")
    failures = int(entries[0].get("failures") or 0)
    return entries[0].get("status") == "fail" and failures > 0, failures


def run_f10(client: Any, dataset: str, target_root: Path) -> dict[str, str]:
    source_slice(client, dataset)
    as_of = as_of_date(client, dataset)
    build = dbt_command(target_root / "f10-build", "build", "--select", "tag:weather_mini3")
    if build.returncode != 0:
        raise RuntimeError("F10 could not build the clean isolated weather mart")
    before = published_gold_hash(client, dataset, as_of)
    mart = table(PROJECT, dataset, "mart_weather_province_daily")
    rows = run_query(client, f"SELECT COUNT(*) AS row_count FROM {mart}", "f10")
    if not rows or int(rows[0]["row_count"]) == 0:
        raise RuntimeError("F10 has no isolated mart rows to mutate")
    injected_at = utc_now()
    mutation_started = True
    try:
        run_query(
            client,
            f"""
            CREATE TEMP TABLE w9_clean_mart AS SELECT * FROM {mart};
            CREATE TEMP TABLE w9_bad_mart AS
            SELECT * REPLACE(TRUE AS rain_day, CAST(0 AS FLOAT64) AS precipitation_mm)
            FROM w9_clean_mart;
            DROP VIEW IF EXISTS {mart};
            DROP TABLE IF EXISTS {mart};
            CREATE TABLE {mart} AS SELECT * FROM w9_bad_mart
            """,
            "f10",
        )
        target_path = target_root / "f10"
        command = dbt_command(
            target_path,
            "test",
            "--select",
            "assert_week9_rain_precip_consistency",
        )
        detected, failures = check_f10_result(target_path)
        if command.returncode == 0 or not detected:
            raise FaultMissError("F10 dbt test did not block the injected mismatch")
        detected_at = utc_now()
    finally:
        if mutation_started:
            client.delete_table(f"{PROJECT}.{dataset}.mart_weather_province_daily", not_found_ok=True)
            restore = dbt_command(
                target_root / "f10-restore",
                "run",
                "--select",
                "mart_weather_province_daily",
            )
            if restore.returncode != 0:
                raise RuntimeError("F10 failed to restore the clean PR mart view")
    after = published_gold_hash(client, dataset, as_of)
    return make_row(
        "F10",
        injected_at=injected_at,
        detected_at=detected_at,
        action=f"P1 BLOCK (dbt failures={failures})",
        gold_before=before,
        gold_after=after,
        result="PASS" if before == after else "FAIL",
        evidence="CI (isolated BigQuery w9_drill mart; synthetic rain/precipitation mismatch)",
    )


def write_report(
    rows: list[dict[str, str]], destination: Path, cost_summary: dict[str, Any]
) -> None:
    columns = [
        "fault", "run_id", "manifest_path", "as_of_date", "injected_at", "detector",
        "detected_at", "channel", "received_at", "action", "gold_hash_before",
        "gold_hash_after", "result", "evidence",
    ]
    lines = [
        "# Week 9 isolated BigQuery fault tests",
        "",
        "F07 and F10 use only the isolated w9_drill dataset and compare its restored Gold slice hash after each fault.",
        (
            "Per-run BigQuery billed-byte guard: "
            f"{cost_summary.get('guard_status', 'UNVERIFIED')}; observed="
            f"{cost_summary.get('total_bytes_billed', 'UNVERIFIED')}; upper bound="
            f"{cost_summary.get('guarded_bytes_upper_bound', 'UNVERIFIED')}; limit=5 GiB."
        ),
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[column]).replace("|", "\\|") for column in columns) + " |")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    import argparse

    from google.cloud import bigquery

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cost-summary", type=Path)
    args = parser.parse_args()
    if args.project != PROJECT or args.dataset != "w9_drill":
        raise SystemExit("Live fault injection is restricted to the approved project and isolated w9_drill.")

    catalog_path = Path("/workspace/tests/week9/faults/manifest.yml")
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    expected = {
        "F07": ("G2.SOURCE.FRESHNESS", "P2/P1"),
        "F10": ("G2.WEATHER.RAIN_PRECIP_CONSISTENCY", "P1"),
    }
    for fault, (check_id, severity) in expected.items():
        definition = catalog.get("faults", {}).get(fault, {})
        if definition.get("check_id") != check_id or definition.get("severity") != severity:
            raise SystemExit(f"Fault catalog mismatch for {fault}")

    client = bigquery.Client(project=PROJECT, location=LOCATION)
    RUN_USAGE_RECORDS.clear()
    global RUN_UNKNOWN_QUERY_CAP_COUNT
    RUN_UNKNOWN_QUERY_CAP_COUNT = 0
    rows: list[dict[str, str]] = []
    cost_guard_failure: str | None = None
    for fault, run in (("F07", run_f07), ("F10", run_f10)):
        try:
            rows.append(run(client, args.dataset, args.target_root))
        except FaultMissError:
            rows.append(
                make_row(
                    fault,
                    injected_at="UNVERIFIED",
                    detected_at="UNVERIFIED",
                    action="EXPECTED DETECTOR MISSED",
                    gold_before="UNVERIFIED",
                    gold_after="UNVERIFIED",
                    result="FAIL",
                    evidence="CI (isolated BigQuery w9_drill test ran; detector did not match)",
                )
            )
        except Exception as exc:  # avoid printing response bodies, query text, or tokens
            rows.append(
                make_row(
                    fault,
                    injected_at="UNVERIFIED",
                    detected_at="UNVERIFIED",
                    action=f"UNVERIFIED ({type(exc).__name__})",
                    gold_before="UNVERIFIED",
                    gold_after="UNVERIFIED",
                    result="UNVERIFIED",
                    evidence="CI (isolated BigQuery w9_drill test did not complete)",
                )
            )
        try:
            guard_usage_records(
                RUN_USAGE_RECORDS,
                unknown_query_cap_count=RUN_UNKNOWN_QUERY_CAP_COUNT,
            )
        except RunCostGuardError as error:
            cost_guard_failure = str(error)
            break

    run_id = os.environ.get("GITHUB_RUN_ID", "0")
    try:
        cost_summary = build_usage_artifact(
            run_id=run_id,
            job_name="fault-matrix",
            records=RUN_USAGE_RECORDS,
            unknown_query_cap_count=RUN_UNKNOWN_QUERY_CAP_COUNT,
        )
    except RunCostGuardError as error:
        cost_guard_failure = cost_guard_failure or str(error)
        cost_summary = {
            "workflow_run_id": run_id,
            "paid_job": "fault-matrix",
            "guard_status": "FAIL",
            "failure": cost_guard_failure,
            "unknown_query_cap_count": RUN_UNKNOWN_QUERY_CAP_COUNT,
            "usage_records": RUN_USAGE_RECORDS,
        }
    if cost_guard_failure:
        cost_summary["guard_status"] = "FAIL"
        cost_summary["failure"] = cost_guard_failure
    if args.cost_summary:
        args.cost_summary.parent.mkdir(parents=True, exist_ok=True)
        args.cost_summary.write_text(json.dumps(cost_summary, sort_keys=True), encoding="utf-8")
    write_report(rows, args.report, cost_summary)
    print("LIVE_FAULT_RESULTS=" + json.dumps({row["fault"]: row["result"] for row in rows}, sort_keys=True))
    return 0 if all(row["result"] == "PASS" for row in rows) and not cost_guard_failure else 1


if __name__ == "__main__":
    raise SystemExit(main())
