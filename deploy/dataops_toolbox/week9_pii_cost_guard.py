"""Build the fail-closed per-run byte artifact for the synthetic PII proof."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from run_cost_guard import RunCostGuardError, build_usage_artifact
from week9_lineage_build import summarize_dbt_results

PII_SAFE_MODEL_ID = "model.dataforge.dim_synthetic_customer_safe"
PII_SAFE_MART_TABLE = "pii_safe.dim_customer_profile_safe"


def validate_safe_mart_build(results: Any) -> None:
    if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
        raise RunCostGuardError("PII dbt run results are invalid")
    matches = [item for item in results if item.get("unique_id") == PII_SAFE_MODEL_ID]
    if len(matches) != 1 or matches[0].get("status") != "success":
        raise RunCostGuardError("Expected safe PII mart was not built successfully")


def sql_node_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop dbt project hooks that ran no BigQuery job.

    dbt-core records every on-run-start/on-run-end hook in run_results.json with an
    empty adapter_response (dbt/task/run.py ``safe_run_hooks``). The W9 DQ results hook
    is a no-op when DATAFORGE_DQ_RESULTS_ENABLED=false, so it has no job ID to bill.
    A hook that did report an adapter response stays in the list and must be billed.
    """
    sql_results = []
    for item in results:
        is_hook = str(item.get("unique_id", "")).startswith("operation.")
        if is_hook and not item.get("adapter_response"):
            if item.get("status") not in {"success", "skipped"}:
                raise RunCostGuardError("A dbt project hook did not finish successfully")
            continue
        sql_results.append(item)
    return sql_results


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RunCostGuardError(f"{label} receipt is missing or invalid") from None
    if not isinstance(value, dict):
        raise RunCostGuardError(f"{label} receipt is invalid")
    return value


def build_cost_receipt(
    *, run_id: str, dbt_results: dict[str, Any], mask_receipt: dict[str, Any], load_job_id: str
) -> dict[str, Any]:
    if mask_receipt.get("status") not in {"MASKED", "DENIED_BY_POLICY_TAG"}:
        raise RunCostGuardError("CI policy-tag probe did not pass")
    if mask_receipt.get("raw_columns_visible") is not False:
        raise RunCostGuardError("CI policy-tag probe exposed a raw column")
    results = dbt_results.get("results", [])
    validate_safe_mart_build(results)
    results = sql_node_results(results)
    dbt = summarize_dbt_results(results)
    if (
        dbt["dbt_jobs_seen"] == 0
        or dbt["dbt_jobs_seen"] != len(results)
        or dbt["dbt_jobs_seen"] != dbt["dbt_jobs_with_billing"]
        or dbt["dbt_results_with_billing_without_job_id"]
    ):
        raise RunCostGuardError("PII dbt job or billed-byte metadata is incomplete")
    if not isinstance(load_job_id, str) or not load_job_id:
        raise RunCostGuardError("Synthetic load job ID is unavailable")
    records = list(dbt["usage_records"]) + list(mask_receipt.get("usage_records", []))
    records.append({"job_id": load_job_id, "bytes_billed": 0})
    artifact = build_usage_artifact(
        run_id=run_id,
        job_name="pii-proof",
        records=records,
        unknown_query_cap_count=mask_receipt.get("unknown_query_cap_count", 0),
    )
    artifact["dbt_jobs_seen"] = dbt["dbt_jobs_seen"]
    artifact["ci_mask_status"] = mask_receipt["status"]
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dbt-run-results", type=Path, required=True)
    parser.add_argument("--mask-receipt", type=Path, required=True)
    parser.add_argument("--load-receipt", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        dbt_results = _read_json(args.dbt_run_results, "dbt run_results")
        mask = _read_json(args.mask_receipt, "CI masking")
        load = _read_json(args.load_receipt, "synthetic load")
        if load.get("status") != "LOADED_SYNTHETIC_ONLY" or load.get("raw_values_emitted") is not False:
            raise RunCostGuardError("Synthetic load receipt is not safe")
        artifact = build_cost_receipt(
            run_id=args.run_id,
            dbt_results=dbt_results,
            mask_receipt=mask,
            load_job_id=load.get("job_id", ""),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
    except RunCostGuardError as error:
        print(f"W9_PII_RUN_COST_GUARD=FAIL reason={error}", file=sys.stderr)
        return 1
    print(
        "W9_PII_RUN_COST_GUARD=PASS "
        f"jobs={artifact['dbt_jobs_seen']} "
        f"bytes_billed={artifact['total_bytes_billed']} "
        f"guarded_upper_bound={artifact['guarded_bytes_upper_bound']} "
        f"limit={artifact['max_run_bytes_billed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
