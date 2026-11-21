"""Tests for the synthetic PII proof's model and cost receipts."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOLBOX = ROOT / "deploy" / "dataops_toolbox"
sys.path.insert(0, str(TOOLBOX))

from run_cost_guard import RunCostGuardError  # noqa: E402
from week9_pii_cost_guard import (  # noqa: E402
    PII_SAFE_MART_TABLE,
    build_cost_receipt,
)


def _valid_receipts() -> tuple[dict, dict]:
    dbt_results = {
        "results": [
            {
                "unique_id": "model.dataforge.dim_synthetic_customer_safe",
                "status": "success",
                "adapter_response": {"job_id": "dbt_job_1", "bytes_billed": 128},
            }
        ]
    }
    mask_receipt = {
        "status": "MASKED",
        "raw_columns_visible": False,
        "usage_records": [{"job_id": "mask_job_1", "bytes_billed": 64}],
        "unknown_query_cap_count": 0,
    }
    return dbt_results, mask_receipt


def test_pii_cost_receipt_requires_successful_safe_mart_and_mask_probe() -> None:
    dbt_results, mask_receipt = _valid_receipts()

    artifact = build_cost_receipt(
        run_id="987654321",
        dbt_results=dbt_results,
        mask_receipt=mask_receipt,
        load_job_id="load_job_1",
    )

    assert PII_SAFE_MART_TABLE == "pii_safe.dim_customer_profile_safe"
    assert artifact["ci_mask_status"] == "MASKED"
    assert artifact["total_bytes_billed"] == 192
    assert artifact["guarded_bytes_upper_bound"] == 192


def test_pii_cost_receipt_ignores_jobless_dbt_project_hooks() -> None:
    # Regression for run 44865173398 (R-14): dbt-core writes on-run-end hooks into
    # run_results.json with an empty adapter_response, so the job count must skip them.
    dbt_results, mask_receipt = _valid_receipts()
    dbt_results["results"].extend(
        [
            {
                "unique_id": "model.dataforge.stg_customer_profile_restricted",
                "status": "success",
                "adapter_response": {"job_id": "dbt_view_job_1", "bytes_billed": 0},
            },
            {
                "unique_id": "operation.dataforge.dataforge-on-run-end-0",
                "status": "success",
                "adapter_response": {},
            },
        ]
    )

    artifact = build_cost_receipt(
        run_id="987654321",
        dbt_results=dbt_results,
        mask_receipt=mask_receipt,
        load_job_id="load_job_1",
    )

    assert artifact["dbt_jobs_seen"] == 2
    assert artifact["total_bytes_billed"] == 192


def test_pii_cost_receipt_fails_on_failed_jobless_hook() -> None:
    dbt_results, mask_receipt = _valid_receipts()
    dbt_results["results"].append(
        {"unique_id": "operation.dataforge.dataforge-on-run-end-0", "status": "error", "adapter_response": {}}
    )

    with pytest.raises(RunCostGuardError, match="hook did not finish"):
        build_cost_receipt(
            run_id="987654321",
            dbt_results=dbt_results,
            mask_receipt=mask_receipt,
            load_job_id="load_job_1",
        )


def test_pii_cost_receipt_still_fails_when_a_model_has_no_job_id() -> None:
    dbt_results, mask_receipt = _valid_receipts()
    dbt_results["results"].append(
        {"unique_id": "model.dataforge.stg_customer_profile_restricted", "status": "success", "adapter_response": {}}
    )

    with pytest.raises(RunCostGuardError, match="billed-byte metadata is incomplete"):
        build_cost_receipt(
            run_id="987654321",
            dbt_results=dbt_results,
            mask_receipt=mask_receipt,
            load_job_id="load_job_1",
        )


def test_pii_cost_receipt_fails_when_safe_mart_is_not_built() -> None:
    dbt_results, mask_receipt = _valid_receipts()
    dbt_results["results"][0]["unique_id"] = "test.dataforge.some_other_check"

    with pytest.raises(RunCostGuardError, match="Expected safe PII mart"):
        build_cost_receipt(
            run_id="987654321",
            dbt_results=dbt_results,
            mask_receipt=mask_receipt,
            load_job_id="load_job_1",
        )


def test_pii_cost_receipt_fails_when_safe_mart_build_failed() -> None:
    dbt_results, mask_receipt = _valid_receipts()
    dbt_results["results"][0]["status"] = "error"

    with pytest.raises(RunCostGuardError, match="Expected safe PII mart"):
        build_cost_receipt(
            run_id="987654321",
            dbt_results=dbt_results,
            mask_receipt=mask_receipt,
            load_job_id="load_job_1",
        )
