from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from faults.cases import mutate_landing_frame

from dataforge.dq.gate import run_landing_gate
from dataforge.dq.results import MemoryResultSink

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "tests" / "week9" / "faults" / "weather_7date_slice.parquet"
AS_OF = date.today()
EXPECTED_FAILURES = {
    "F01": "G1.LANDING.PROVINCE_ID_NOT_NULL",
    "F02": "G1.LANDING.GRAIN_UNIQUE",
    "F03": "G1.LANDING.PHYSICAL_RANGE",
    "F04": "G1.LANDING.PROVINCE_DOMAIN",
    "F05a": "G1.LANDING.SCHEMA",
    "F06": "G1.LANDING.ROWS_PER_DATE",
    "F08": "G1.LANDING.NO_FUTURE_DATE",
    "F12": "G1.LANDING.TEMP_UNIT_RANGE",
}
STRING_COLUMNS = (
    "province_id",
    "source",
    "model",
    "request_id",
    "source_sha256",
    "manifest_uri",
)


@pytest.fixture
def clean_frame() -> pd.DataFrame:
    return pd.read_parquet(CAPTURE)


def run(frame: pd.DataFrame, *, enforce: str = "block"):
    sink = MemoryResultSink()
    report = run_landing_gate(
        frame,
        dataset="w9_drill",
        observation_date=AS_OF,
        enforce=enforce,
        result_sink=sink,
    )
    return report, sink


def _result_observed(result) -> dict[str, object]:
    import json

    return json.loads(result.observed)


def failed_ids(report) -> set[str]:
    return {
        result.check_id
        for result in report.results
        if result.status == "FAIL" and result.severity == "P1"
    }


def test_captured_clean_slice_has_no_p1_or_p2_findings(clean_frame):
    report, sink = run(clean_frame)
    assert not report.blocked
    assert not failed_ids(report)
    assert not [result for result in report.results if result.status == "WARN"]
    assert len(sink.results) == len(report.results)
    observed = json.loads(report.results[0].observed)
    assert observed["dataset"] == "w9_drill"
    assert observed["date"] == AS_OF.isoformat()
    assert observed["publish_action"] == "PUBLISH"


@pytest.mark.parametrize("string_dtype", ["object", "str", "string"])
def test_string_contract_accepts_pandas_2_and_3_representations(clean_frame, string_dtype):
    frame = clean_frame.copy(deep=True)
    for column in STRING_COLUMNS:
        frame[column] = frame[column].astype(string_dtype)

    report, _ = run(frame)

    schema = next(result for result in report.results if result.check_id == "G1.LANDING.SCHEMA")
    assert schema.status == "PASS"
    assert not report.blocked


def test_string_contract_rejects_mixed_object_values(clean_frame):
    frame = clean_frame.copy(deep=True)
    frame["source"] = frame["source"].astype(object)
    frame.loc[frame.index[0], "source"] = 42

    report, _ = run(frame)

    schema = next(result for result in report.results if result.check_id == "G1.LANDING.SCHEMA")
    assert schema.status == "FAIL"
    assert schema.failing_rows == 1
    assert "type_mismatch:source" in _result_observed(schema)["issues"]
    assert report.blocked


@pytest.mark.parametrize(
    "column", ["request_id", "source", "model", "source_sha256", "manifest_uri"]
)
def test_required_string_columns_reject_null_values(clean_frame, column):
    frame = clean_frame.copy(deep=True)
    frame.loc[frame.index[0], column] = None

    report, _ = run(frame)

    schema = next(result for result in report.results if result.check_id == "G1.LANDING.SCHEMA")
    assert schema.status == "FAIL"
    assert schema.failing_rows == 1
    assert f"missing_values:{column}" in _result_observed(schema)["issues"]
    assert report.blocked


def test_null_province_remains_owned_by_not_null_check(clean_frame):
    report, _ = run(mutate_landing_frame("F01", clean_frame))

    schema = next(result for result in report.results if result.check_id == "G1.LANDING.SCHEMA")
    province = next(
        result
        for result in report.results
        if result.check_id == "G1.LANDING.PROVINCE_ID_NOT_NULL"
    )
    assert schema.status == "PASS"
    assert province.status == "FAIL"


def test_nullable_weather_metrics_may_remain_null(clean_frame):
    frame = clean_frame.copy(deep=True)
    frame.loc[frame.index[0], ["precipitation_mm", "temp_max_c"]] = None

    report, _ = run(frame)

    schema = next(result for result in report.results if result.check_id == "G1.LANDING.SCHEMA")
    assert schema.status == "PASS"
    assert not report.blocked


@pytest.mark.parametrize("string_dtype", ["object", "str", "string"])
def test_string_contract_accepts_pandas_2_and_3_representations(clean_frame, string_dtype):
    frame = clean_frame.copy(deep=True)
    for column in STRING_COLUMNS:
        frame[column] = frame[column].astype(string_dtype)

    report, _ = run(frame)

    schema = next(result for result in report.results if result.check_id == "G1.LANDING.SCHEMA")
    assert schema.status == "PASS"
    assert not report.blocked


def test_string_contract_rejects_mixed_object_values(clean_frame):
    frame = clean_frame.copy(deep=True)
    frame["source"] = frame["source"].astype(object)
    frame.loc[frame.index[0], "source"] = 42

    report, _ = run(frame)

    schema = next(result for result in report.results if result.check_id == "G1.LANDING.SCHEMA")
    assert schema.status == "FAIL"
    assert schema.failing_rows == 1
    assert "type_mismatch:source" in _result_observed(schema)["issues"]
    assert report.blocked


@pytest.mark.parametrize(
    "column", ["request_id", "source", "model", "source_sha256", "manifest_uri"]
)
def test_required_string_columns_reject_null_values(clean_frame, column):
    frame = clean_frame.copy(deep=True)
    frame.loc[frame.index[0], column] = None

    report, _ = run(frame)

    schema = next(result for result in report.results if result.check_id == "G1.LANDING.SCHEMA")
    assert schema.status == "FAIL"
    assert schema.failing_rows == 1
    assert f"missing_values:{column}" in _result_observed(schema)["issues"]
    assert report.blocked


def test_null_province_remains_owned_by_not_null_check(clean_frame):
    report, _ = run(mutate_landing_frame("F01", clean_frame))

    schema = next(result for result in report.results if result.check_id == "G1.LANDING.SCHEMA")
    province = next(
        result
        for result in report.results
        if result.check_id == "G1.LANDING.PROVINCE_ID_NOT_NULL"
    )
    assert schema.status == "PASS"
    assert province.status == "FAIL"


def test_nullable_weather_metrics_may_remain_null(clean_frame):
    frame = clean_frame.copy(deep=True)
    frame.loc[frame.index[0], ["precipitation_mm", "temp_max_c"]] = None

    report, _ = run(frame)

    schema = next(result for result in report.results if result.check_id == "G1.LANDING.SCHEMA")
    assert schema.status == "PASS"
    assert not report.blocked


@pytest.mark.parametrize("fault_id, expected_check", EXPECTED_FAILURES.items())
def test_catalogued_g1_faults_fail_their_owned_check(clean_frame, fault_id, expected_check):
    report, _ = run(mutate_landing_frame(fault_id, clean_frame))
    assert expected_check in failed_ids(report)
    assert report.blocked


def test_additive_nullable_column_warns_and_does_not_block(clean_frame):
    report, _ = run(mutate_landing_frame("F05b", clean_frame))
    additive = next(
        result for result in report.results if result.check_id == "G1.LANDING.SCHEMA_ADDITIVE"
    )
    assert additive.severity == "P2"
    assert additive.status == "WARN"
    assert not report.blocked


def test_shadow_mode_records_p1_without_blocking(clean_frame):
    report, _ = run(mutate_landing_frame("F04", clean_frame), enforce="warn")
    assert "G1.LANDING.PROVINCE_DOMAIN" in failed_ids(report)
    assert not report.blocked


def test_dataset_guard_rejects_production_dataset(clean_frame):
    with pytest.raises(ValueError, match="w9_drill or dbt_ci_pr_"):
        run_landing_gate(
            clean_frame,
            dataset="weather_mini3",
            observation_date=AS_OF,
            result_sink=MemoryResultSink(),
        )
