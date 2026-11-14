"""Local fixture oracle for the weather mart's calendar-window contract.

The dbt unit test in models/weather/marts/schema.yml exercises the SQL in
BigQuery. This credential-free test checks the fixture's expected rows against
an independent Python calendar-date oracle and guards the SQL frame boundaries.
"""

import csv
from datetime import date, timedelta
from pathlib import Path

PROJECT = Path(__file__).parents[1]
FIXTURES = PROJECT / "tests" / "fixtures"
MODEL = PROJECT / "models" / "weather" / "marts" / "mart_weather_province_daily.sql"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _number(value: str) -> float | None:
    return None if value == "" else float(value)


def _calendar_oracle(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for source_row in rows:
        row = {
            "province_id": source_row["province_id"],
            "observation_date": date.fromisoformat(source_row["observation_date"]),
            "precipitation_mm": _number(source_row["precipitation_mm"]),
            "temp_max_c": _number(source_row["temp_max_c"]),
        }
        grouped.setdefault(str(row["province_id"]), []).append(row)

    expected: list[dict[str, object]] = []
    for province_rows in grouped.values():
        province_rows.sort(key=lambda row: row["observation_date"])
        for current in province_rows:
            current_date = current["observation_date"]
            precipitation_window = [
                row
                for row in province_rows
                if current_date - timedelta(days=6) <= row["observation_date"] <= current_date
                and row["precipitation_mm"] is not None
            ]
            temperature_window = [
                row
                for row in province_rows
                if current_date - timedelta(days=29) <= row["observation_date"] <= current_date
                and row["temp_max_c"] is not None
            ]
            precipitation_count = len(precipitation_window)
            temperature_count = len(temperature_window)
            precipitation_7d = (
                sum(float(row["precipitation_mm"]) for row in precipitation_window)
                if precipitation_count == 7
                else None
            )
            temperature_mean = (
                sum(float(row["temp_max_c"]) for row in temperature_window) / 30
                if temperature_count == 30
                else None
            )
            current_temperature = current["temp_max_c"]
            temperature_anomaly = (
                float(current_temperature) - temperature_mean
                if temperature_mean is not None and current_temperature is not None
                else None
            )
            precipitation = current["precipitation_mm"]
            expected.append(
                {
                    "province_id": current["province_id"],
                    "observation_date": current_date.isoformat(),
                    "rain_day": None if precipitation is None else precipitation > 0,
                    "precipitation_observed_days_7d": precipitation_count,
                    "precipitation_7d_mm": precipitation_7d,
                    "temp_max_observed_days_30d": temperature_count,
                    "temp_max_30d_mean_c": temperature_mean,
                    "temp_max_30d_anomaly_c": temperature_anomaly,
                }
            )
    return expected


def _coerce_fixture_value(column: str, value: str) -> object:
    if value == "":
        return None
    if column == "rain_day":
        return value.lower() == "true"
    if column in {
        "precipitation_observed_days_7d",
        "temp_max_observed_days_30d",
    }:
        return int(value)
    if column in {
        "precipitation_7d_mm",
        "temp_max_30d_mean_c",
        "temp_max_30d_anomaly_c",
    }:
        return float(value)
    return value


def test_expected_csv_matches_independent_calendar_date_oracle():
    input_rows = _read_csv(FIXTURES / "mart_weather_province_daily_input.csv")
    expected_rows = _read_csv(FIXTURES / "mart_weather_province_daily_expected.csv")
    oracle_rows = _calendar_oracle(input_rows)

    assert len(input_rows) == 61
    assert len(expected_rows) == len(oracle_rows) == len(input_rows)
    for fixture_row, oracle_row in zip(expected_rows, oracle_rows, strict=True):
        for column, expected_value in oracle_row.items():
            assert _coerce_fixture_value(column, fixture_row[column]) == expected_value


def test_gap_fixture_distinguishes_calendar_windows_from_row_windows():
    expected_rows = _read_csv(FIXTURES / "mart_weather_province_daily_expected.csv")
    by_key = {
        (row["province_id"], row["observation_date"]): row
        for row in expected_rows
    }

    hcm_jan14 = by_key[("HCM", "2024-01-14")]
    assert hcm_jan14["precipitation_observed_days_7d"] == "7"
    assert hcm_jan14["precipitation_7d_mm"] == "7"

    hcm_jan16 = by_key[("HCM", "2024-01-16")]
    assert hcm_jan16["precipitation_observed_days_7d"] == "6"
    assert hcm_jan16["precipitation_7d_mm"] == ""

    hcm_jan31 = by_key[("HCM", "2024-01-31")]
    assert hcm_jan31["temp_max_observed_days_30d"] == "29"
    assert hcm_jan31["temp_max_30d_mean_c"] == ""

    hn_jan31 = by_key[("HN", "2024-01-31")]
    assert hn_jan31["temp_max_observed_days_30d"] == "30"
    assert hn_jan31["temp_max_30d_mean_c"] == "16.5"
    assert hn_jan31["temp_max_30d_anomaly_c"] == "14.5"

    dn_jan31 = by_key[("DN", "2024-01-31")]
    assert dn_jan31["rain_day"] == ""


def test_dbt_sql_uses_calendar_ranges_and_requires_complete_windows():
    sql = " ".join(MODEL.read_text(encoding="utf-8").lower().split())
    assert "range between 6 preceding and current row" in sql
    assert "range between 29 preceding and current row" in sql
    assert "precipitation_observed_days_7d = 7" in sql
    assert "temp_max_observed_days_30d = 30" in sql
    assert "temp_max_c - observed_temp_max_30d_mean_c" in sql
