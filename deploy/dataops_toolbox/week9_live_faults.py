"""Run F07 and F10 as isolated BigQuery-only Week 9 fault tests in CI."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT = "dataforge-p7-lab-d0f725"
LOCATION = "us-central1"
MAXIMUM_BYTES_BILLED = 1024**3


class FaultMissError(RuntimeError):
    """Expected detector did not fire for its isolated fault."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def table(project: str, dataset: str, name: str) -> str:
    if project != PROJECT:
        raise ValueError("fault SQL is restricted to the approved project")
    if not re.fullmatch(r"dbt_ci_pr_[0-9]+", dataset):
        raise ValueError("fault SQL is restricted to dbt_ci_pr_<n>")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,1023}", name):
        raise ValueError("invalid BigQuery table identifier")
    return f"`{project}.{dataset}.{name}`"


def run_query(client: Any, sql: str, label: str) -> list[Any]:
    from google.cloud import bigquery

    config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        labels={"application": "dataforge", "phase": "w9", "fault": label},
    )
    return list(client.query(sql, job_config=config, location=LOCATION).result())


def source_slice(client: Any, dataset: str) -> None:
    source = f"`{PROJECT}.weather_mini3.weather_landing`"
    target = table(PROJECT, dataset, "weather_landing")
    run_query(
        client,
        f"""
        CREATE OR REPLACE TABLE {target} AS
        SELECT *
        FROM {source}
        WHERE observation_date IN (
          SELECT observation_date
          FROM (SELECT DISTINCT observation_date FROM {source})
          ORDER BY observation_date DESC
          LIMIT 7
        )
        """,
        "f07",
    )


def as_of_date(client: Any, dataset: str) -> date:
    rows = run_query(
        client,
        f"SELECT MAX(observation_date) AS as_of_date FROM {table(PROJECT, dataset, 'weather_landing')}",
        "f07",
    )
    if not rows or rows[0]["as_of_date"] is None:
        raise RuntimeError("isolated source slice has no observation date")
    return rows[0]["as_of_date"]


def published_gold_hash(client: Any, as_of: date) -> str:
    mart = f"`{PROJECT}.dbt_weather_mini3.mart_weather_province_daily`"
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
    env["DBT_DATAFORGE_TARGET_DATASET"] = env["PR_DATASET"]
    env["DBT_WEATHER_LANDING_SCHEMA"] = env["PR_DATASET"]
    env["DBT_DATAFORGE_LOCATION"] = LOCATION
    env["DATAFORGE_PROJECT_ID"] = PROJECT
    env["DATAFORGE_DQ_RESULTS_ENABLED"] = "true"
    return subprocess.run(
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
        "manifest_path": f"{os.environ.get('PR_DATASET', 'UNVERIFIED')}.weather_landing",
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
    as_of = as_of_date(client, dataset)
    before = published_gold_hash(client, as_of)
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
    after = published_gold_hash(client, as_of)
    return make_row(
        "F07",
        injected_at=injected_at,
        detected_at=detected_at,
        action="P1 BLOCK_NEW_PUBLISH after 72 hours",
        gold_before=before,
        gold_after=after,
        result="PASS" if before == after else "FAIL",
        evidence="CI (isolated BigQuery source freshness; synthetic 73-hour landed_at)",
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
    as_of = as_of_date(client, dataset)
    before = published_gold_hash(client, as_of)
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
    after = published_gold_hash(client, as_of)
    return make_row(
        "F10",
        injected_at=injected_at,
        detected_at=detected_at,
        action=f"P1 BLOCK (dbt failures={failures})",
        gold_before=before,
        gold_after=after,
        result="PASS" if before == after else "FAIL",
        evidence="CI (isolated BigQuery PR mart; synthetic rain/precipitation mismatch)",
    )


def write_report(rows: list[dict[str, str]], destination: Path) -> None:
    columns = [
        "fault", "run_id", "manifest_path", "as_of_date", "injected_at", "detector",
        "detected_at", "channel", "received_at", "action", "gold_hash_before",
        "gold_hash_after", "result", "evidence",
    ]
    lines = [
        "# Week 9 isolated BigQuery fault tests",
        "",
        "F07 and F10 use only the per-PR dataset. Production tables are queried read-only for hash comparison.",
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
    args = parser.parse_args()
    if args.project != PROJECT or not re.fullmatch(r"dbt_ci_pr_[0-9]+", args.dataset):
        raise SystemExit("Live fault injection is restricted to the approved project and dbt_ci_pr_<n>.")

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
    rows: list[dict[str, str]] = []
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
                    evidence="CI (isolated BigQuery test ran; detector did not match)",
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
                    evidence="CI (isolated BigQuery test did not complete)",
                )
            )
    write_report(rows, args.report)
    print("LIVE_FAULT_RESULTS=" + json.dumps({row["fault"]: row["result"] for row in rows}, sort_keys=True))
    return 0 if all(row["result"] == "PASS" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
