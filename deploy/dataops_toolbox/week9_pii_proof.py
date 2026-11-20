"""Run the fixed synthetic PII load, dbt mart build, and CI mask probe."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from dataforge.privacy.synthetic import EXPECTED_PROJECT, load_customer_profiles
from run_cost_guard import RunCostGuardError
from week9_pii_cost_guard import PII_SAFE_MART_TABLE, build_cost_receipt
from week9_pii_mask_probe import verify_masked_access

JOB_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,256}")
DBT_PROJECT_DIR = Path("/workspace/dbt/dataforge")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def run() -> dict[str, Any]:
    if os.environ.get("DATAFORGE_W9_PII_LOAD_ENABLED") != "true":
        raise RunCostGuardError("Synthetic PII load opt-in is missing")
    if os.environ.get("DBT_DATAFORGE_PROJECT_ID") != EXPECTED_PROJECT:
        raise RunCostGuardError("PII dbt project is outside the approved W9 project")
    target_path = Path(os.environ.get("DBT_TARGET_PATH", "/runner-temp/pii-target"))
    profiles_dir = Path(os.environ.get("DBT_PROFILES_DIR", "/profiles"))
    logs_path = Path(os.environ.get("DBT_LOG_PATH", "/runner-temp/pii-logs"))
    cost_path = Path(os.environ.get("DATAFORGE_W9_COST_ARTIFACT_PATH", "/runner-temp/run-cost-pii-proof.json"))
    summary_path = Path(os.environ.get("DATAFORGE_W9_PII_SUMMARY_PATH", "/runner-temp/pii-proof-summary.json"))

    stage = "synthetic-load"
    load_receipt = load_customer_profiles()
    if (
        load_receipt.get("status") != "LOADED_SYNTHETIC_ONLY"
        or load_receipt.get("destination") != "restricted_pii.customer_profile"
        or load_receipt.get("raw_values_emitted") is not False
        or int(load_receipt.get("row_count", 0)) < 1
    ):
        raise RunCostGuardError("Synthetic loader did not return a safe load receipt")
    load_job_id = load_receipt.get("job_id")
    if not isinstance(load_job_id, str) or JOB_ID_RE.fullmatch(load_job_id) is None:
        raise RunCostGuardError("Synthetic load job ID is missing")

    stage = "pii-dbt-build"
    target_path.mkdir(parents=True, exist_ok=True)
    logs_path.mkdir(parents=True, exist_ok=True)
    dbt_env = os.environ.copy()
    dbt_env["DATAFORGE_DQ_RESULTS_ENABLED"] = "false"
    command = [
        "dbt",
        "build",
        "--project-dir",
        str(DBT_PROJECT_DIR),
        "--profiles-dir",
        str(profiles_dir),
        "--target",
        "w9_ci",
        "--target-path",
        str(target_path),
        "--select",
        "path:models/pii",
        "--no-partial-parse",
        "--no-send-anonymous-usage-stats",
        "--no-version-check",
    ]
    process = subprocess.run(
        command,
        cwd=DBT_PROJECT_DIR,
        env=dbt_env,
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise RunCostGuardError(f"PII dbt build failed with exit {process.returncode}")

    run_results_path = target_path / "run_results.json"
    try:
        run_results = json.loads(run_results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RunCostGuardError("PII dbt run_results.json is missing or invalid") from None
    stage = "ci-policy-tag-mask-probe"
    mask = verify_masked_access()
    if mask.get("status") not in {"MASKED", "DENIED_BY_POLICY_TAG"}:
        raise RunCostGuardError("CI identity did not prove the policy-tag mask boundary")
    if mask.get("raw_columns_visible") is not False:
        raise RunCostGuardError("CI identity observed a raw policy-tagged column")

    artifact = build_cost_receipt(
        run_id=os.environ.get("GITHUB_RUN_ID", ""),
        dbt_results=run_results,
        mask_receipt=mask,
        load_job_id=load_job_id,
    )
    _write_json(cost_path, artifact)
    summary = {
        "status": "PASS",
        "destination": "restricted_pii.customer_profile",
        "synthetic_rows": int(load_receipt.get("row_count", 0)),
        "safe_mart": PII_SAFE_MART_TABLE,
        "dbt_jobs": artifact["dbt_jobs_seen"],
        "ci_mask_status": mask["status"],
        "raw_policy_tagged_values_visible": False,
        "guard_status": artifact["guard_status"],
        "total_bytes_billed": artifact["total_bytes_billed"],
        "guarded_bytes_upper_bound": artifact["guarded_bytes_upper_bound"],
        "max_run_bytes_billed": artifact["max_run_bytes_billed"],
        "raw_values_emitted": False,
    }
    _write_json(summary_path, summary)
    return summary


def main() -> int:
    try:
        summary = run()
    except Exception as exc:  # keep logs free of raw values and credentials
        print(f"W9_PII_PROOF=FAIL error_class={type(exc).__name__}", file=sys.stderr)
        return 1
    print(
        "W9_PII_PROOF=PASS "
        f"rows={summary['synthetic_rows']} dbt_jobs={summary['dbt_jobs']} "
        f"ci_mask={summary['ci_mask_status']} "
        f"bytes_billed={summary['total_bytes_billed']} "
        f"guarded_upper_bound={summary['guarded_bytes_upper_bound']} "
        f"limit={summary['max_run_bytes_billed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
