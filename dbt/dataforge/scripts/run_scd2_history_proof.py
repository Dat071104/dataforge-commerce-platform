"""Run a guarded three-version dbt snapshot proof on isolated synthetic tables."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_PROJECT_ID = "dataforge-p7-lab-d0f725"
EXPECTED_REGION = "us-central1"
INPUT_DATASET = "dbt_scd2_proof_input"
HISTORY_DATASET = "dbt_scd2_proof_history"
SOURCE_TABLE = "orders"
SNAPSHOT_TABLE = "week7_scd2_proof_history"
MAX_BYTES_BILLED = 32 * 1024 * 1024


class ProofError(RuntimeError):
    """Raised when the proof could not run safely or its assertions failed."""


def _dataset(client: bigquery.Client, dataset_id: str) -> bigquery.Dataset:
    try:
        dataset = client.get_dataset(f"{EXPECTED_PROJECT_ID}.{dataset_id}")
    except NotFound as exc:
        raise ProofError(
            f"Required isolated dataset is missing: {EXPECTED_PROJECT_ID}.{dataset_id}; "
            "provision it through the reviewed Terraform change first"
        ) from exc
    if dataset.location != EXPECTED_REGION:
        raise ProofError(f"Dataset {dataset_id} is in an unexpected location")
    return dataset


def _table_id(dataset_id: str, table_id: str) -> str:
    return f"{EXPECTED_PROJECT_ID}.{dataset_id}.{table_id}"


def _assert_absent(client: bigquery.Client, table_id: str) -> None:
    try:
        client.get_table(table_id)
    except NotFound:
        return
    raise ProofError(
        f"Refusing to replace pre-existing proof table {table_id}; preserve it and "
        "select a fresh isolated dataset for a new proof"
    )


def _run_dbt_command(
    dbt_executable: str,
    *,
    action: str,
    selector: str,
    phase: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="dataforge-dbt-profile-") as profile_dir:
        shutil.copyfile(
            REPO_ROOT / "dbt" / "dataforge" / "profiles.example.yml",
            Path(profile_dir) / "profiles.yml",
        )
        command = [
            dbt_executable,
            action,
            "--project-dir",
            str(REPO_ROOT / "dbt" / "dataforge"),
            "--profiles-dir",
            profile_dir,
            "--target",
            "scd2_proof",
            "--select",
            selector,
            "--no-use-colors",
        ]
        environment = os.environ.copy()
        environment["DBT_DATAFORGE_PROJECT_ID"] = EXPECTED_PROJECT_ID
        environment["DBT_DATAFORGE_LOCATION"] = EXPECTED_REGION
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode != 0:
        raise ProofError(f"dbt {action} phase {phase!r} failed with exit {result.returncode}")
    return {"action": action, "phase": phase, "exit_code": result.returncode}


def _run_snapshot(dbt_executable: str, *, phase: str) -> dict[str, Any]:
    return _run_dbt_command(
        dbt_executable,
        action="snapshot",
        selector=SNAPSHOT_TABLE,
        phase=phase,
    )


def _run_proof_tests(dbt_executable: str, *, phase: str) -> dict[str, Any]:
    return _run_dbt_command(
        dbt_executable,
        action="test",
        selector="tag:scd2_proof",
        phase=phase,
    )


def _query(
    client: bigquery.Client,
    sql: str,
    *,
    parameters: list[bigquery.ScalarQueryParameter] | None = None,
) -> tuple[list[bigquery.Row], str]:
    job = client.query(
        sql,
        location=EXPECTED_REGION,
        job_config=bigquery.QueryJobConfig(
            maximum_bytes_billed=MAX_BYTES_BILLED,
            query_parameters=parameters or [],
            labels={"application": "dataforge", "phase": "week7", "action": "scd2proof"},
        ),
    )
    rows = list(job.result(timeout=120))
    return rows, job.job_id


def _mutate_source(client: bigquery.Client, *, status: str, deleted: bool) -> str:
    table_id = f"`{_table_id(INPUT_DATASET, SOURCE_TABLE)}`"
    sql = f"""
        UPDATE {table_id}
        SET order_status = @order_status,
            is_deleted = @is_deleted,
            business_effective_at = TIMESTAMP_ADD(business_effective_at, INTERVAL 1 DAY),
            updated_at = TIMESTAMP_ADD(updated_at, INTERVAL 1 DAY)
        WHERE order_id = 'DEMO-ORDER-1'
    """
    rows, job_id = _query(
        client,
        sql,
        parameters=[
            bigquery.ScalarQueryParameter("order_status", "STRING", status),
            bigquery.ScalarQueryParameter("is_deleted", "BOOL", deleted),
        ],
    )
    del rows
    return job_id


def _read_versions(client: bigquery.Client) -> tuple[list[dict[str, Any]], str]:
    table_id = f"`{_table_id(HISTORY_DATASET, SNAPSHOT_TABLE)}`"
    sql = f"""
        SELECT
            order_id,
            order_status,
            CAST(order_amount AS STRING) AS order_amount,
            is_deleted,
            business_effective_at,
            updated_at,
            dbt_valid_from,
            dbt_valid_to,
            dbt_scd_id
        FROM {table_id}
        WHERE order_id = 'DEMO-ORDER-1'
        ORDER BY dbt_valid_from, dbt_scd_id
    """
    rows, job_id = _query(client, sql)
    return [dict(row.items()) for row in rows], job_id


def _count_overlaps(client: bigquery.Client) -> tuple[int, str]:
    table_id = f"`{_table_id(HISTORY_DATASET, SNAPSHOT_TABLE)}`"
    sql = f"""
        SELECT COUNT(*) AS overlap_count
        FROM {table_id} AS left_version
        JOIN {table_id} AS right_version
          ON left_version.order_id = right_version.order_id
         AND left_version.dbt_scd_id < right_version.dbt_scd_id
         AND left_version.dbt_valid_from < COALESCE(
             right_version.dbt_valid_to, TIMESTAMP '9999-12-31 00:00:00+00'
         )
         AND right_version.dbt_valid_from < COALESCE(
             left_version.dbt_valid_to, TIMESTAMP '9999-12-31 00:00:00+00'
         )
        WHERE left_version.order_id = 'DEMO-ORDER-1'
    """
    rows, job_id = _query(client, sql)
    return int(rows[0]["overlap_count"]), job_id


def _assert_history(versions: list[dict[str, Any]]) -> None:
    if len(versions) != 3:
        raise ProofError(f"Expected three observed SCD2 versions, got {len(versions)}")
    if sum(row["dbt_valid_to"] is None for row in versions) != 1:
        raise ProofError("Expected exactly one current SCD2 version")
    if [row["order_status"] for row in versions] != ["CREATED", "PROCESSING", "CANCELLED"]:
        raise ProofError("Observed version states differ from the controlled source mutations")
    if [bool(row["is_deleted"]) for row in versions] != [False, False, True]:
        raise ProofError("Soft-delete tombstone state did not produce the expected final version")
    for index, row in enumerate(versions):
        valid_from = row["dbt_valid_from"]
        valid_to = row["dbt_valid_to"]
        if valid_to is not None and valid_to <= valid_from:
            raise ProofError("An SCD2 validity interval is empty or inverted")
        if index and versions[index - 1]["dbt_valid_to"] != valid_from:
            raise ProofError("Adjacent SCD2 versions do not meet at the observed update boundary")


def run_proof(*, execute: bool, project_id: str, output: Path) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "status": "DRY_RUN_NO_CLOUD_WRITE",
        "project_id": project_id,
        "location": EXPECTED_REGION,
        "input_table": _table_id(INPUT_DATASET, SOURCE_TABLE),
        "snapshot_table": _table_id(HISTORY_DATASET, SNAPSHOT_TABLE),
        "source_is_synthetic": True,
        "authoritative_week5_tables_touched": False,
        "expected_versions": 3,
        "observed_versions": None,
        "current_version_count": None,
        "validity_windows_verified": False,
        "overlap_count": None,
        "unchanged_replay_added_version": None,
        "dbt_phases": [],
        "query_job_ids": [],
        "source_load_job_id": None,
        "executed_at_utc": None,
    }
    if project_id != EXPECTED_PROJECT_ID:
        raise ProofError("Refusing to use a project other than the approved DataForge lab")
    if not execute:
        receipt["planned_steps"] = [
            "create a new isolated synthetic source table in dbt_scd2_proof_input",
            "run the dedicated week7_scd2_proof_history snapshot",
            "advance updated_at and source state twice, snapshot after each change",
            "run an unchanged snapshot replay and assert no fourth version appears",
            "verify validity intervals, one current version, and zero overlaps",
        ]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return receipt

    dbt_binary = Path(sys.executable).with_name("dbt.exe" if os.name == "nt" else "dbt")
    dbt_executable = str(dbt_binary) if dbt_binary.is_file() else shutil.which("dbt")
    if dbt_executable is None:
        raise ProofError("dbt executable is unavailable in the active Python environment")

    client = bigquery.Client(project=EXPECTED_PROJECT_ID)
    _dataset(client, INPUT_DATASET)
    _dataset(client, HISTORY_DATASET)
    input_table_id = _table_id(INPUT_DATASET, SOURCE_TABLE)
    history_table_id = _table_id(HISTORY_DATASET, SNAPSHOT_TABLE)
    _assert_absent(client, input_table_id)
    _assert_absent(client, history_table_id)

    schema = [
        bigquery.SchemaField("order_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("order_status", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("order_amount", "NUMERIC", mode="REQUIRED"),
        bigquery.SchemaField("is_deleted", "BOOL", mode="REQUIRED"),
        bigquery.SchemaField("business_effective_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    ]
    source = bigquery.Table(input_table_id, schema=schema)
    source.expires = datetime.now(timezone.utc) + timedelta(days=7)
    client.create_table(source, exists_ok=False)
    load_job = client.load_table_from_json(
        [
            {
                "order_id": "DEMO-ORDER-1",
                "order_status": "CREATED",
                "order_amount": "100.00",
                "is_deleted": False,
                "business_effective_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ],
        input_table_id,
        job_config=bigquery.LoadJobConfig(
            schema=schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_EMPTY,
        ),
    )
    load_job.result(timeout=120)
    receipt["source_load_job_id"] = load_job.job_id

    receipt["status"] = "RUNNING"
    receipt["dbt_phases"].append(_run_snapshot(dbt_executable, phase="initial"))
    job_id = _mutate_source(client, status="PROCESSING", deleted=False)
    receipt["query_job_ids"].append(job_id)
    receipt["dbt_phases"].append(_run_snapshot(dbt_executable, phase="status_update"))
    job_id = _mutate_source(client, status="CANCELLED", deleted=True)
    receipt["query_job_ids"].append(job_id)
    receipt["dbt_phases"].append(_run_snapshot(dbt_executable, phase="soft_delete_tombstone"))
    versions, job_id = _read_versions(client)
    receipt["query_job_ids"].append(job_id)
    _assert_history(versions)
    overlap_count, job_id = _count_overlaps(client)
    receipt["query_job_ids"].append(job_id)
    if overlap_count != 0:
        raise ProofError(f"Expected no overlapping SCD2 intervals, got {overlap_count}")
    receipt["dbt_phases"].append(_run_proof_tests(dbt_executable, phase="history_assertions"))

    receipt["dbt_phases"].append(_run_snapshot(dbt_executable, phase="unchanged_replay"))
    receipt["dbt_phases"].append(
        _run_proof_tests(dbt_executable, phase="unchanged_replay_assertions")
    )
    replayed_versions, job_id = _read_versions(client)
    receipt["query_job_ids"].append(job_id)
    if len(replayed_versions) != len(versions):
        raise ProofError("An unchanged source replay created an additional SCD2 version")
    replay_overlap_count, job_id = _count_overlaps(client)
    receipt["query_job_ids"].append(job_id)
    if replay_overlap_count != 0:
        raise ProofError("Unchanged replay introduced an overlapping SCD2 interval")
    receipt["status"] = "PASS"
    receipt["observed_versions"] = [
        {
            "order_status": row["order_status"],
            "order_amount": row["order_amount"],
            "is_deleted": row["is_deleted"],
            "business_effective_at": row["business_effective_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
            "dbt_valid_from": row["dbt_valid_from"].isoformat(),
            "dbt_valid_to": row["dbt_valid_to"].isoformat() if row["dbt_valid_to"] else None,
        }
        for row in replayed_versions
    ]
    receipt["current_version_count"] = sum(row["dbt_valid_to"] is None for row in replayed_versions)
    receipt["validity_windows_verified"] = True
    receipt["overlap_count"] = replay_overlap_count
    receipt["unchanged_replay_added_version"] = False
    receipt["executed_at_utc"] = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=EXPECTED_PROJECT_ID)
    parser.add_argument("--execute", action="store_true", help="Write only to the two isolated proof datasets")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "docs" / "cloud" / "week7" / "closure" / "dbt_scd2_history_receipt.json",
    )
    args = parser.parse_args()
    try:
        receipt = run_proof(execute=args.execute, project_id=args.project_id, output=args.output)
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(receipt, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
