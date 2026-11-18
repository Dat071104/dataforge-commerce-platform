from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataforge.dq.results import (
    JsonlResultSink,
    MemoryResultSink,
    cloud_sink_from_env,
    make_result,
    require_isolated_dataset,
)


def test_result_row_has_contract_fields_and_summary_only():
    row = make_result(
        run_id="unit-run",
        check_id="G1.LANDING.PROVINCE_ID_NOT_NULL",
        layer="G1",
        severity="P1",
        status="FAIL",
        observed={"failing_rows": 1},
        threshold={"condition": "province_id is not null"},
        failing_rows=1,
        contract_version="1.0.0",
    )
    assert set(row.as_row()) == {
        "run_id", "check_id", "layer", "severity", "status", "observed", "threshold",
        "failing_rows", "contract_version", "ts",
    }
    assert json.loads(row.observed) == {"failing_rows": 1}
    assert "province_id" not in row.observed
    assert row.ts.endswith("Z")


def test_local_sinks_persist_only_result_summaries(tmp_path):
    row = make_result(
        run_id="unit-run",
        check_id="G1.LANDING.ROWS_PER_DATE",
        layer="G1",
        severity="P1",
        status="PASS",
        observed={"observed_rows": 3},
        threshold={"rows_per_date": 3},
        failing_rows=0,
        contract_version="1.0.0",
    )
    memory = MemoryResultSink()
    memory.write([row])
    path = tmp_path / "dq_results.jsonl"
    JsonlResultSink(str(path)).write([row])
    parsed = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert memory.results == [row]
    assert parsed["check_id"] == row.check_id
    assert parsed["failing_rows"] == 0


def test_dq_writer_rejects_non_w9_project_or_dataset(monkeypatch):
    monkeypatch.setenv("DATAFORGE_DQ_DATASET", "weather_mini3")
    with pytest.raises(ValueError, match="only be written to dataforge_dq"):
        cloud_sink_from_env()
    monkeypatch.setenv("DATAFORGE_DQ_DATASET", "dataforge_dq")
    monkeypatch.setenv("DATAFORGE_PROJECT_ID", "another-project")
    with pytest.raises(ValueError, match="approved DataForge project"):
        cloud_sink_from_env()


def test_gate_dataset_guard_allows_only_w9_targets():
    for dataset in ("w9_drill", "dbt_ci_pr_42", "dbt_ci_pr_feature-1"):
        require_isolated_dataset(dataset)
    for dataset in ("weather_mini3", "dbt_weather_mini3", "dataforge_dq", "silver"):
        with pytest.raises(ValueError, match="w9_drill or dbt_ci_pr_"):
            require_isolated_dataset(dataset)


def test_dbt_result_hook_is_disabled_before_any_query_by_default():
    macro = (
        Path(__file__).resolve().parents[2]
        / "dbt"
        / "dataforge"
        / "macros"
        / "dq_write_results.sql"
    ).read_text(encoding="utf-8")
    guard = macro.index("DATAFORGE_DQ_RESULTS_ENABLED")
    query = macro.index("run_query(")
    assert guard < query
    assert "env_var('DATAFORGE_DQ_RESULTS_ENABLED', 'false')" in macro
