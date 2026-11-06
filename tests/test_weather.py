import hashlib
import json
from datetime import date

import pytest
import requests

from dataforge import weather
from dataforge.weather import fetch, parse_daily


def test_weather_parser_safeguards():
    with pytest.raises(ValueError):
        parse_daily({"daily": {"time": ["2022-01-01"], "precipitation_sum": []}}, "HCM")
    assert parse_daily({"daily": {"time": ["2022-01-01"], "precipitation_sum": [12.0],
                                  "temperature_2m_max": [30.0]}}, "HCM") == [
                                      ("HCM", "2022-01-01", 12.0, 30.0, "open_meteo_era5")]
    with pytest.raises(ValueError, match="JSON object"):
        parse_daily(["not", "an", "object"], "HCM")
    with pytest.raises(ValueError, match="JSON arrays"):
        parse_daily({"daily": {"time": "2022-01-01", "precipitation_sum": [1],
                               "temperature_2m_max": [30]}}, "HCM")
    with pytest.raises(ValueError, match="invalid observation date"):
        parse_daily({"daily": {"time": ["2022-02-30"], "precipitation_sum": [1],
                               "temperature_2m_max": [30]}}, "HCM")
    with pytest.raises(ValueError, match="non-canonical observation date"):
        parse_daily({"daily": {"time": ["20220101"], "precipitation_sum": [1],
                               "temperature_2m_max": [30]}}, "HCM")
    with pytest.raises(ValueError, match="invalid precipitation"):
        parse_daily({"daily": {"time": ["2022-01-01"], "precipitation_sum": [-1],
                               "temperature_2m_max": [30]}}, "HCM")
    with pytest.raises(ValueError, match="invalid maximum temperature"):
        parse_daily({"daily": {"time": ["2022-01-01"], "precipitation_sum": [1],
                               "temperature_2m_max": [float("inf")]}}, "HCM")


def test_weather_fetch_mock_no_network(tmp_path):
    body = (b'{"daily":{"time":["2022-01-01"],"precipitation_sum":[2.3],'
            b'"temperature_2m_max":[34.0]}}')
    observed_params = []

    class Response:
        status_code = 200
        content = body

        def raise_for_status(self): pass
        def json(self):
            return json.loads(self.content)

    def mock_get(url, params, timeout):
        assert params["timezone"] == "Asia/Ho_Chi_Minh"
        assert params["models"] == "era5"
        assert params["daily"] == "precipitation_sum,temperature_2m_max"
        assert url.endswith("/v1/archive")
        observed_params.append(params)
        return Response()

    marker_path = tmp_path / "_DATAFORGE_SOURCE.json"
    marker_path.write_text(json.dumps({"dataset_class": "synthetic",
                                       "file_sha256": {"orders": "keep-this-hash"},
                                       "source_overrides": {"orders": "synthetic"}}),
                           encoding="utf-8")
    assert fetch(date(2022, 1, 1), date(2022, 1, 1), ["HCM"], tmp_path, mock_get) == 1
    assert "open_meteo_era5" in (tmp_path / "weather_daily.csv").read_text()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["dataset_class"] == "synthetic"
    assert marker["file_sha256"]["orders"] == "keep-this-hash"
    assert marker["file_sha256"]["weather_daily"] == hashlib.sha256(
        (tmp_path / "weather_daily.csv").read_bytes()).hexdigest()
    assert marker["source_overrides"]["orders"] == "synthetic"
    assert marker["source_overrides"]["weather_daily"] == "open_meteo_era5"
    provenance_path = tmp_path / weather.PROVENANCE_DIR / "weather_provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["status"] == "complete"
    assert provenance["endpoint"] == weather.API
    assert provenance["date_range"] == {"start": "2022-01-01", "end": "2022-01-01"}
    assert provenance["requested_provinces"] == [{
        "province_id": "HCM", "latitude": weather.CITY_LOCATIONS["HCM"][0],
        "longitude": weather.CITY_LOCATIONS["HCM"][1],
    }]
    assert provenance["daily_fields"] == ["precipitation_sum", "temperature_2m_max"]
    assert provenance["timezone"] == "Asia/Ho_Chi_Minh"
    assert provenance["model"] == "era5"
    assert provenance["weather_csv_sha256"] == marker["file_sha256"]["weather_daily"]
    assert provenance["weather_csv_rows"] == 1
    assert "Open-Meteo.com" in provenance["attribution"]["text"]
    assert provenance["attribution"]["data_license"] == "CC BY 4.0"
    response = provenance["responses"][0]
    assert response["province_id"] == "HCM"
    assert response["attempt"] == 1
    assert response["http_status"] == 200
    assert response["response_sha256"] == hashlib.sha256(body).hexdigest()
    assert response["hash_basis"] == "response_content"
    raw_response_path = tmp_path / response["raw_response_json"]
    assert raw_response_path.read_bytes() == body
    assert observed_params == [{
        "latitude": weather.CITY_LOCATIONS["HCM"][0],
        "longitude": weather.CITY_LOCATIONS["HCM"][1],
        "start_date": "2022-01-01", "end_date": "2022-01-01",
        "daily": "precipitation_sum,temperature_2m_max",
        "timezone": "Asia/Ho_Chi_Minh", "models": "era5",
    }]
    assert "api_key" not in json.dumps(provenance).lower()


def test_weather_rejects_invalid_range(tmp_path):
    with pytest.raises(ValueError):
        fetch(date(2023, 1, 2), date(2023, 1, 1), ["HCM"], tmp_path)


def test_weather_retries_timeout_and_transient_http(monkeypatch, tmp_path):
    calls = []
    delays = []

    class Response:
        def __init__(self, status):
            self.status_code = status
            self.content = (b'{"error":"rate limited"}' if status == 429 else
                            b'{"daily":{"time":["2022-01-01"],"precipitation_sum":[2.3],'
                            b'"temperature_2m_max":[30.0]}}')

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

        def json(self):
            return json.loads(self.content)

    def mock_get(url, params, timeout):
        calls.append((url, params, timeout))
        if len(calls) == 1:
            raise requests.Timeout("temporary timeout")
        if len(calls) == 2:
            return Response(429)
        return Response(200)

    monkeypatch.setattr(weather.time, "sleep", delays.append)
    assert fetch(date(2022, 1, 1), date(2022, 1, 1), ["HCM"], tmp_path, mock_get) == 1
    assert len(calls) == 3
    assert delays == [1, 2]
    provenance = json.loads((tmp_path / weather.PROVENANCE_DIR / "weather_provenance.json")
                            .read_text(encoding="utf-8"))
    assert [item["http_status"] for item in provenance["responses"]] == [429, 200]
    assert [item["attempt"] for item in provenance["responses"]] == [2, 3]


def test_weather_does_not_retry_permanent_http_4xx(monkeypatch, tmp_path):
    calls = []
    delays = []

    class Response:
        status_code = 404

        def raise_for_status(self):
            raise requests.HTTPError("not found", response=self)

    def mock_get(url, params, timeout):
        calls.append(url)
        return Response()

    monkeypatch.setattr(weather.time, "sleep", delays.append)
    with pytest.raises(RuntimeError, match="non-retryable HTTP 404"):
        fetch(date(2022, 1, 1), date(2022, 1, 1), ["HCM"], tmp_path, mock_get)
    assert len(calls) == 1
    assert delays == []


def test_weather_stops_after_three_transient_failures(monkeypatch, tmp_path):
    calls = []
    delays = []

    def mock_get(url, params, timeout):
        calls.append(url)
        raise requests.Timeout("still unavailable")

    monkeypatch.setattr(weather.time, "sleep", delays.append)
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        fetch(date(2022, 1, 1), date(2022, 1, 1), ["HCM"], tmp_path, mock_get)
    assert len(calls) == 3
    assert delays == [1, 2]


def test_weather_recovers_after_malformed_json_and_http_503(monkeypatch, tmp_path):
    calls = []
    delays = []

    class Response:
        def __init__(self, status=200):
            self.status_code = status
            if len(calls) == 1:
                self.content = b"{malformed json"
            elif status == 503:
                self.content = b'{"error":"temporarily unavailable"}'
            else:
                self.content = (b'{"daily":{"time":["2022-01-01"],"precipitation_sum":[0.0],'
                                b'"temperature_2m_max":[30.0]}}')

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

        def json(self):
            if len(calls) == 1:
                raise requests.exceptions.JSONDecodeError("bad JSON", "", 0)
            return json.loads(self.content)

    def mock_get(url, params, timeout):
        calls.append(url)
        if len(calls) == 2:
            return Response(503)
        return Response(200)

    monkeypatch.setattr(weather.time, "sleep", delays.append)
    assert fetch(date(2022, 1, 1), date(2022, 1, 1), ["HN"], tmp_path, mock_get) == 1
    assert len(calls) == 3
    assert delays == [1, 2]
    assert "HN,2022-01-01,0.0,30.0,open_meteo_era5" in \
        (tmp_path / "weather_daily.csv").read_text(encoding="utf-8")
    provenance = json.loads((tmp_path / weather.PROVENANCE_DIR / "weather_provenance.json")
                            .read_text(encoding="utf-8"))
    assert [item["http_status"] for item in provenance["responses"]] == [200, 503, 200]
    assert [item["attempt"] for item in provenance["responses"]] == [1, 2, 3]
    assert [item["response_sha256"] for item in provenance["responses"]] == [
        hashlib.sha256(b"{malformed json").hexdigest(),
        hashlib.sha256(b'{"error":"temporarily unavailable"}').hexdigest(),
        hashlib.sha256(Response().content).hexdigest(),
    ]


def test_weather_rejects_malformed_success_body_without_overwriting_source(
        monkeypatch, tmp_path):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"daily": {"time": ["2022-01-01"], "precipitation_sum": [],
                              "temperature_2m_max": [30.0]}}

    def mock_get(url, params, timeout):
        calls.append(url)
        return Response()

    marker_path = tmp_path / "_DATAFORGE_SOURCE.json"
    marker_path.write_text(json.dumps({"file_sha256": {"orders": "unchanged"}}),
                           encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid daily data"):
        fetch(date(2022, 1, 1), date(2022, 1, 1), ["HCM"], tmp_path, mock_get)
    assert calls == [weather.API]
    assert not (tmp_path / "weather_daily.csv").exists()
    assert json.loads(marker_path.read_text(encoding="utf-8")) == {
        "file_sha256": {"orders": "unchanged"}}


def test_weather_rejects_malformed_provenance_before_request_or_source_overwrite(tmp_path):
    calls = []
    existing_source = tmp_path / "weather_daily.csv"
    existing_source.write_text("existing weather snapshot\n", encoding="utf-8")
    marker_path = tmp_path / "_DATAFORGE_SOURCE.json"
    marker_path.write_text("{not json", encoding="utf-8")

    def mock_get(url, params, timeout):
        calls.append(url)
        raise AssertionError("invalid marker must be rejected before requesting weather")

    with pytest.raises(json.JSONDecodeError):
        fetch(date(2022, 1, 1), date(2022, 1, 1), ["HCM"], tmp_path, mock_get)
    assert calls == []
    assert existing_source.read_text(encoding="utf-8") == "existing weather snapshot\n"
    assert marker_path.read_text(encoding="utf-8") == "{not json"
