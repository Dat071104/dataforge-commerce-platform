from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
import requests

from cloud.jobs.week7_weather import weather_job
from cloud.jobs.week7_weather.validation import (
    G0_COMPLETENESS,
    G0_SCHEMA,
    PayloadValidationError,
    validate_open_meteo_response,
)
from dataforge.weather import fetch

CAPTURE_DIR = Path(__file__).parent / "faults" / "captures"
CAPTURE_PATH = CAPTURE_DIR / "open_meteo_hcm_2026-11-05.json"
METADATA_PATH = CAPTURE_DIR / "open_meteo_hcm_2026-11-05.metadata.json"
REQUESTED_DATE = "2026-11-05"


def load_capture():
    raw = CAPTURE_PATH.read_bytes()
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == metadata["response_sha256"]
    assert metadata["http_status"] == 200
    return raw, json.loads(raw)


def test_real_captured_response_passes_g0_contract():
    _, payload = load_capture()
    summary = validate_open_meteo_response(payload, requested_dates=[REQUESTED_DATE])
    assert summary["date_count"] == 1
    assert summary["units_validated"] is True


@pytest.mark.parametrize("mutation", ["remove_required_array", "change_unit"])
def test_f05a_breaking_schema_is_detected_from_real_capture(mutation):
    _, captured = load_capture()
    payload = copy.deepcopy(captured)
    if mutation == "remove_required_array":
        payload["daily"].pop("temperature_2m_max")
    else:
        payload["daily_units"]["temperature_2m_max"] = "°F"
    with pytest.raises(PayloadValidationError) as exc_info:
        validate_open_meteo_response(payload, requested_dates=[REQUESTED_DATE])
    assert exc_info.value.check_id == G0_SCHEMA


@pytest.mark.parametrize("mutation", ["empty", "missing_requested_date"])
def test_f11_http_200_incomplete_response_is_detected_from_real_capture(mutation):
    _, captured = load_capture()
    payload = copy.deepcopy(captured)
    if mutation == "empty":
        payload["daily"]["time"] = []
        payload["daily"]["precipitation_sum"] = []
        payload["daily"]["temperature_2m_max"] = []
        expected_dates = [REQUESTED_DATE]
    else:
        expected_dates = [REQUESTED_DATE, "2026-11-06"]
    with pytest.raises(PayloadValidationError) as exc_info:
        validate_open_meteo_response(payload, requested_dates=expected_dates)
    assert exc_info.value.check_id == G0_COMPLETENESS


class FakeResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return json.loads(self.content)


def test_f_t1_retries_one_503_then_accepts_captured_response(tmp_path, monkeypatch):
    raw, _ = load_capture()
    responses = iter([FakeResponse(503, b"service unavailable"), FakeResponse(200, raw)])
    monkeypatch.setattr("dataforge.weather.time.sleep", lambda _: None)
    count = fetch(
        date(2026, 11, 5),
        date(2026, 11, 5),
        provinces=["HCM"],
        dest=tmp_path,
        requester=lambda *_args, **_kwargs: next(responses),
        response_validator=lambda payload, requested, _province: validate_open_meteo_response(
            payload, requested_dates=requested
        ),
    )
    provenance = json.loads(
        (tmp_path / ".open_meteo" / "weather_provenance.json").read_text(encoding="utf-8")
    )
    assert count == 1
    assert [entry["http_status"] for entry in provenance["responses"]] == [503, 200]
    assert [entry["attempt"] for entry in provenance["responses"]] == [1, 2]


@pytest.mark.parametrize(
    "fault_id, expected_check",
    [("F05a", G0_SCHEMA), ("F11", G0_COMPLETENESS)],
)
def test_default_weather_job_callsite_reports_contract_failure_before_parse(
    monkeypatch, fault_id, expected_check
):
    _, captured = load_capture()
    payload = copy.deepcopy(captured)
    if fault_id == "F05a":
        payload["daily_units"].pop("temperature_2m_max")
    else:
        payload["daily"]["time"] = []
        payload["daily"]["precipitation_sum"] = []
        payload["daily"]["temperature_2m_max"] = []
    records = []
    monkeypatch.delenv("DATAFORGE_DQ_RESULTS_ENABLED", raising=False)
    monkeypatch.setattr(weather_job, "_record_g0_result", lambda **kwargs: records.append(kwargs))
    monkeypatch.setattr(weather_job, "_gcs_clients", lambda storage_client=None: (None, None))
    monkeypatch.setattr(
        weather_job,
        "_replay_execution_receipt",
        lambda *_args, **_kwargs: None,
    )

    def fetch_with_response(_start, _end, *, provinces, dest, response_validator):
        response_validator(payload, [REQUESTED_DATE], provinces[0])

    monkeypatch.setattr(weather_job, "fetch", fetch_with_response)
    with pytest.raises(weather_job.WeatherJobError, match=expected_check):
        weather_job.ingest(
            observation_date=REQUESTED_DATE,
            provinces="HCM",
            invocation_id="q-f11-callsite",
        )
    assert len(records) == 1
    assert records[0]["check_id"] == expected_check
    assert records[0]["status"] == "FAIL"
