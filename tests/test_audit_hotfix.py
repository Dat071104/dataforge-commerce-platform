"""Regression tests for the independently reproduced P5 ingestion defects."""
from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

import dataforge.weather as weather
from dataforge.generator import generate
from dataforge.weather import fetch


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generate_refuses_non_synthetic_marker_without_touching_csv(tmp_path):
    source = tmp_path / "orders.csv"
    source.write_text("manual_business_source\n", encoding="utf-8")
    marker = tmp_path / "_DATAFORGE_SOURCE.json"
    marker.write_text(json.dumps({
        "dataset_class": "unverified_manual",
        "file_sha256": {"orders": _hash(source)},
    }), encoding="utf-8")
    original = source.read_bytes()

    with pytest.raises(FileExistsError, match="not an explicitly synthetic fixture"):
        generate(count=1, dest=tmp_path)

    assert source.read_bytes() == original


def test_generate_refuses_malformed_marker_without_touching_csv(tmp_path):
    source = tmp_path / "orders.csv"
    source.write_text("manual_business_source\n", encoding="utf-8")
    marker = tmp_path / "_DATAFORGE_SOURCE.json"
    marker.write_text("{not json", encoding="utf-8")
    original = source.read_bytes()

    with pytest.raises(ValueError, match="invalid provenance marker"):
        generate(count=1, dest=tmp_path)

    assert source.read_bytes() == original
    assert marker.read_text(encoding="utf-8") == "{not json"


@pytest.mark.parametrize("marker_text", ["null", "[]", '"manual"'])
def test_generate_rejects_non_object_marker_without_touching_csv(tmp_path, marker_text):
    source = tmp_path / "orders.csv"
    source.write_text("manual_business_source\n", encoding="utf-8")
    marker = tmp_path / "_DATAFORGE_SOURCE.json"
    marker.write_text(marker_text, encoding="utf-8")
    original = source.read_bytes()

    with pytest.raises(FileExistsError, match="not an explicitly synthetic fixture"):
        generate(count=1, dest=tmp_path)

    assert source.read_bytes() == original
    assert marker.read_text(encoding="utf-8") == marker_text


def test_generate_refuses_external_weather_override_without_touching_csv(tmp_path):
    generate(count=4, seed=42, dest=tmp_path)
    marker_path = tmp_path / "_DATAFORGE_SOURCE.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["source_overrides"]["weather_daily"] = "open_meteo_era5"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    source = tmp_path / "weather_daily.csv"
    original = source.read_bytes()

    with pytest.raises(FileExistsError, match="externally sourced data"):
        generate(count=5, seed=43, dest=tmp_path)

    assert source.read_bytes() == original


@pytest.mark.parametrize("marker_field, field_value", [
    ("file_sha256", None),
    ("file_sha256", []),
    ("source_overrides", None),
    ("source_overrides", []),
])
def test_generate_rejects_malformed_provenance_fields(tmp_path, marker_field, field_value):
    generate(count=4, seed=42, dest=tmp_path)
    marker_path = tmp_path / "_DATAFORGE_SOURCE.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker[marker_field] = field_value
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    source = tmp_path / "orders.csv"
    original = source.read_bytes()

    with pytest.raises(ValueError, match="invalid"):
        generate(count=5, seed=43, dest=tmp_path)

    assert source.read_bytes() == original


@pytest.mark.parametrize("tamper", [
    "modified", "missing_hash", "mismatched_hash", "unexpected_csv",
])
def test_generate_rejects_unrecorded_or_changed_csv_without_rewriting_sources(tmp_path, tamper):
    generate(count=4, seed=42, dest=tmp_path)
    source = tmp_path / "orders.csv"
    marker_path = tmp_path / "_DATAFORGE_SOURCE.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if tamper == "modified":
        with source.open("a", encoding="utf-8") as stream:
            stream.write("manual modification\n")
    elif tamper == "missing_hash":
        marker["file_sha256"].pop("orders")
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
    elif tamper == "mismatched_hash":
        marker["file_sha256"]["orders"] = "0" * 64
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
    else:
        source = tmp_path / "manual.csv"
        source.write_text("manual source\n", encoding="utf-8")
    original_source = source.read_bytes()
    original_orders = (tmp_path / "orders.csv").read_bytes()

    with pytest.raises(FileExistsError, match="not the recorded synthetic fixture"):
        generate(count=5, seed=43, dest=tmp_path)

    assert source.read_bytes() == original_source
    assert (tmp_path / "orders.csv").read_bytes() == original_orders


def test_generate_allows_intact_deterministic_synthetic_regeneration(tmp_path):
    counts = generate(count=4, seed=42, dest=tmp_path)
    first_hash = _hash(tmp_path / "orders.csv")
    repeated_counts = generate(count=4, seed=42, dest=tmp_path)

    assert repeated_counts == counts
    assert _hash(tmp_path / "orders.csv") == first_hash
    assert generate(count=5, seed=43, dest=tmp_path)["orders"] == 5


class _WeatherResponse:
    status_code = 200

    def __init__(self, days):
        self.payload = {"daily": {
            "time": days,
            "precipitation_sum": [0.0] * len(days),
            "temperature_2m_max": [30.0] * len(days),
        }}
        self.content = json.dumps(self.payload).encode("utf-8")

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


@pytest.mark.parametrize("returned_days", [
    ["2022-01-01"],  # missing requested day
    ["2022-01-01", "2022-01-01"],  # duplicate day
    ["2022-01-01", "2022-01-02", "2022-01-03"],  # extra day
    ["2021-12-31", "2022-01-01"],  # outside the requested range
    ["2022-01-02", "2022-01-01"],  # shuffled days
])
def test_weather_fetch_rejects_non_exact_daily_coverage_before_writes(tmp_path, returned_days):
    source = tmp_path / "weather_daily.csv"
    source.write_bytes(b"previous weather snapshot\n")
    marker = tmp_path / "_DATAFORGE_SOURCE.json"
    marker.write_text(json.dumps({"dataset_class": "synthetic", "file_sha256": {
        "weather_daily": _hash(source),
    }, "source_overrides": {}}), encoding="utf-8")
    weather_provenance = tmp_path / ".open_meteo" / "weather_provenance.json"
    weather_provenance.parent.mkdir()
    weather_provenance.write_text('{"status":"previous"}\n', encoding="utf-8")
    original_source = source.read_bytes()
    original_marker = marker.read_bytes()
    original_provenance = weather_provenance.read_bytes()
    calls = []

    def requester(url, params, timeout):
        calls.append((url, params, timeout))
        return _WeatherResponse(returned_days)

    with pytest.raises(RuntimeError, match="invalid daily data"):
        fetch(date(2022, 1, 1), date(2022, 1, 2), ["HCM"], tmp_path, requester)

    assert len(calls) == 1
    assert source.read_bytes() == original_source
    assert marker.read_bytes() == original_marker
    assert weather_provenance.read_bytes() == original_provenance


def test_weather_fetch_accepts_exact_inclusive_daily_range(tmp_path):
    response = _WeatherResponse(["2022-01-01", "2022-01-02"])
    count = fetch(
        date(2022, 1, 1), date(2022, 1, 2), ["HCM"], tmp_path,
        lambda *args, **kwargs: response,
    )

    assert count == 2
    source = tmp_path / "weather_daily.csv"
    assert source.read_text(encoding="utf-8").splitlines()[1:] == [
        "HCM,2022-01-01,0.0,30.0,open_meteo_era5",
        "HCM,2022-01-02,0.0,30.0,open_meteo_era5",
    ]
    marker = json.loads((tmp_path / "_DATAFORGE_SOURCE.json").read_text(encoding="utf-8"))
    assert marker["file_sha256"]["weather_daily"] == _hash(source)
    provenance = json.loads(
        (tmp_path / ".open_meteo" / "weather_provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["date_range"] == {"start": "2022-01-01", "end": "2022-01-02"}
    assert provenance["weather_csv_rows"] == 2
    transactions = tmp_path / ".open_meteo" / "transactions"
    if transactions.exists():
        assert not list(transactions.iterdir())


def test_weather_later_province_failure_does_not_partially_publish(tmp_path):
    source = tmp_path / "weather_daily.csv"
    source.write_bytes(b"previous weather snapshot\n")
    marker = tmp_path / "_DATAFORGE_SOURCE.json"
    marker.write_text(json.dumps({"dataset_class": "synthetic", "file_sha256": {
        "weather_daily": _hash(source),
    }, "source_overrides": {}}), encoding="utf-8")
    weather_provenance = tmp_path / ".open_meteo" / "weather_provenance.json"
    weather_provenance.parent.mkdir()
    weather_provenance.write_text('{"status":"previous"}\n', encoding="utf-8")
    original_source = source.read_bytes()
    original_marker = marker.read_bytes()
    original_provenance = weather_provenance.read_bytes()
    calls = []

    def requester(url, params, timeout):
        calls.append(params["latitude"])
        days = (["2022-01-01"] if len(calls) == 1
                else ["2022-01-01", "2022-01-02"])
        return _WeatherResponse(days)

    with pytest.raises(RuntimeError, match="invalid daily data"):
        fetch(date(2022, 1, 1), date(2022, 1, 1), ["HCM", "HN"], tmp_path, requester)

    assert len(calls) == 2
    assert source.read_bytes() == original_source
    assert marker.read_bytes() == original_marker
    assert weather_provenance.read_bytes() == original_provenance


@pytest.mark.parametrize(("field", "value"), [
    ("file_sha256", None),
    ("file_sha256", []),
    ("file_sha256", {"orders": None}),
    ("source_overrides", None),
    ("source_overrides", []),
    ("source_overrides", {"weather_daily": None}),
    ("dataset_class", []),
])
def test_weather_rejects_malformed_nested_marker_before_request_or_writes(
    tmp_path, field, value,
):
    source = tmp_path / "weather_daily.csv"
    source.write_bytes(b"previous weather snapshot\n")
    marker_path = tmp_path / "_DATAFORGE_SOURCE.json"
    marker = {
        "dataset_class": "synthetic",
        "file_sha256": {"weather_daily": _hash(source)},
        "source_overrides": {},
    }
    marker[field] = value
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    provenance_path = tmp_path / ".open_meteo" / "weather_provenance.json"
    provenance_path.parent.mkdir()
    provenance_path.write_bytes(b'{"status":"previous"}\n')
    original_source = source.read_bytes()
    original_marker = marker_path.read_bytes()
    original_provenance = provenance_path.read_bytes()
    calls = []

    def requester(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("malformed marker must be rejected before requesting weather")

    with pytest.raises(ValueError, match="source provenance"):
        fetch(date(2022, 1, 1), date(2022, 1, 1), ["HCM"], tmp_path, requester)

    assert calls == []
    assert source.read_bytes() == original_source
    assert marker_path.read_bytes() == original_marker
    assert provenance_path.read_bytes() == original_provenance


@pytest.mark.parametrize("failed_output", [
    "weather_daily.csv",
    "_DATAFORGE_SOURCE.json",
    ".open_meteo/weather_provenance.json",
])
def test_weather_restores_previous_files_on_promotion_failure(tmp_path, monkeypatch, failed_output):
    source = tmp_path / "weather_daily.csv"
    source.write_bytes(b"previous weather snapshot\n")
    marker_path = tmp_path / "_DATAFORGE_SOURCE.json"
    marker_path.write_text(json.dumps({
        "dataset_class": "synthetic",
        "file_sha256": {"weather_daily": _hash(source)},
        "source_overrides": {},
    }), encoding="utf-8")
    provenance_path = tmp_path / ".open_meteo" / "weather_provenance.json"
    provenance_path.parent.mkdir()
    provenance_path.write_bytes(b'{"status":"previous"}\n')
    previous = {
        source: source.read_bytes(),
        marker_path: marker_path.read_bytes(),
        provenance_path: provenance_path.read_bytes(),
    }
    original_replace = weather._replace_staged
    injected = False

    def fail_once(staged, target):
        nonlocal injected
        if target.relative_to(tmp_path).as_posix() == failed_output and not injected:
            injected = True
            raise OSError("injected weather promotion failure")
        return original_replace(staged, target)

    monkeypatch.setattr(weather, "_replace_staged", fail_once)
    with pytest.raises(OSError, match="injected weather promotion failure"):
        fetch(
            date(2022, 1, 1), date(2022, 1, 1), ["HCM"], tmp_path,
            lambda *args, **kwargs: _WeatherResponse(["2022-01-01"]),
        )

    assert injected
    assert all(path.read_bytes() == content for path, content in previous.items())
    response_files = tmp_path / ".open_meteo" / "responses"
    if response_files.exists():
        assert not list(response_files.rglob("*.json"))
    transactions = tmp_path / ".open_meteo" / "transactions"
    if transactions.exists():
        assert not list(transactions.iterdir())
    assert not list(tmp_path.rglob("*.stage"))
