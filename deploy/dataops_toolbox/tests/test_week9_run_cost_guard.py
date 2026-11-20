"""Tests for the cumulative Week 9 BigQuery billed-byte guard."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "deploy" / "dataops_toolbox" / "run_cost_guard.py"
SPEC = importlib.util.spec_from_file_location("run_cost_guard", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
run_cost_guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_cost_guard)


def test_run_guard_deduplicates_jobs_and_accepts_exact_limit() -> None:
    records = [
        {"job_id": "job_a", "bytes_billed": run_cost_guard.MAXIMUM_BYTES_BILLED_PER_QUERY - 10},
        {"job_id": "job_a", "bytes_billed": run_cost_guard.MAXIMUM_BYTES_BILLED_PER_QUERY - 20},
        {"job_id": "job_b", "bytes_billed": 10},
        *[
            {"job_id": f"job_{suffix}", "bytes_billed": run_cost_guard.MAXIMUM_BYTES_BILLED_PER_QUERY}
            for suffix in ("c", "d", "e", "f")
        ],
    ]

    summary = run_cost_guard.guard_usage_records(records)

    assert summary["total_bytes_billed"] == run_cost_guard.MAX_RUN_BYTES_BILLED
    assert summary["usage_records"] == [
        {"job_id": "job_a", "bytes_billed": run_cost_guard.MAXIMUM_BYTES_BILLED_PER_QUERY - 10},
        {"job_id": "job_b", "bytes_billed": 10},
        *[
            {"job_id": f"job_{suffix}", "bytes_billed": run_cost_guard.MAXIMUM_BYTES_BILLED_PER_QUERY}
            for suffix in ("c", "d", "e", "f")
        ],
    ]


def test_run_guard_rejects_more_than_five_gib() -> None:
    with pytest.raises(run_cost_guard.RunCostGuardError, match="exceeds the 5 GiB"):
        run_cost_guard.guard_usage_records(
            [
                {"job_id": f"job_{index}", "bytes_billed": run_cost_guard.MAXIMUM_BYTES_BILLED_PER_QUERY}
                for index in range(6)
            ]
        )


def test_run_guard_keeps_the_one_gib_per_query_cap() -> None:
    with pytest.raises(run_cost_guard.RunCostGuardError, match="1 GiB per-query cap"):
        run_cost_guard.guard_usage_records(
            [{"job_id": "job_a", "bytes_billed": run_cost_guard.MAXIMUM_BYTES_BILLED_PER_QUERY + 1}]
        )


def test_run_guard_counts_unknown_queries_at_the_per_query_cap() -> None:
    with pytest.raises(run_cost_guard.RunCostGuardError, match="billed-byte upper bound"):
        run_cost_guard.guard_usage_records(
            [
                {"job_id": f"job_{index}", "bytes_billed": run_cost_guard.MAXIMUM_BYTES_BILLED_PER_QUERY}
                for index in range(5)
            ],
            unknown_query_cap_count=1,
        )


def test_run_guard_fails_closed_when_billing_is_missing() -> None:
    with pytest.raises(run_cost_guard.RunCostGuardError, match="unavailable"):
        run_cost_guard.guard_usage_records([{"job_id": "job_a", "bytes_billed": None}])


def test_aggregate_guard_matches_run_and_combines_paid_job_artifacts(tmp_path: Path) -> None:
    artifact_a = run_cost_guard.build_usage_artifact(
        run_id="987654321",
        job_name="cloud-pr",
        records=[{"job_id": "job_a", "bytes_billed": 100}],
    )
    artifact_b = run_cost_guard.build_usage_artifact(
        run_id="987654321",
        job_name="fault-matrix",
        records=[{"job_id": "job_b", "bytes_billed": 200}],
    )
    (tmp_path / "cloud-pr.json").write_text(json.dumps(artifact_a), encoding="utf-8")
    (tmp_path / "fault-matrix.json").write_text(json.dumps(artifact_b), encoding="utf-8")

    summary = run_cost_guard.aggregate_run_artifacts(
        input_dir=tmp_path,
        expected_artifacts=2,
        run_id="987654321",
    )

    assert summary["paid_jobs"] == 2
    assert summary["total_bytes_billed"] == 300


def test_aggregate_guard_rejects_missing_paid_job_artifact(tmp_path: Path) -> None:
    with pytest.raises(run_cost_guard.RunCostGuardError, match="received 0"):
        run_cost_guard.aggregate_run_artifacts(
            input_dir=tmp_path,
            expected_artifacts=1,
            run_id="987654321",
        )


