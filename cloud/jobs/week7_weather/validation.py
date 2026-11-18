"""G0 validation for captured Open-Meteo archive responses."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

G0_SCHEMA = "G0.API.SCHEMA"
G0_COMPLETENESS = "G0.API.RESPONSE_COMPLETENESS"
EXPECTED_TIMEZONE = "Asia/Ho_Chi_Minh"
EXPECTED_UNITS = {
    "precipitation_sum": "mm",
    "temperature_2m_max": "°C",
}
EXPECTED_DAILY_FIELDS = tuple(EXPECTED_UNITS)


@dataclass(frozen=True)
class PayloadValidationError(ValueError):
    check_id: str
    reason: str

    def __str__(self) -> str:
        return self.reason


def _schema_error(reason: str) -> PayloadValidationError:
    return PayloadValidationError(G0_SCHEMA, reason)


def _completeness_error(reason: str) -> PayloadValidationError:
    return PayloadValidationError(G0_COMPLETENESS, reason)


def validate_open_meteo_response(
    payload: object,
    *,
    requested_dates: Iterable[str | date],
    expected_timezone: str = EXPECTED_TIMEZONE,
) -> dict[str, Any]:
    """Validate response shape, units, timezone, and exact requested-date coverage.

    Call this only for an HTTP 200 response. It does not replace ``parse_daily``;
    the latter still validates values and converts them to typed rows.
    """
    if not isinstance(payload, dict):
        raise _schema_error("response must be a JSON object")
    for coordinate in ("latitude", "longitude"):
        value = payload.get(coordinate)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise _schema_error(f"response field `{coordinate}` must be a finite number")
    if payload.get("timezone") != expected_timezone:
        raise _schema_error("response timezone differs from the requested local timezone")

    units = payload.get("daily_units")
    if not isinstance(units, dict):
        raise _schema_error("response is missing daily_units metadata")
    for field, expected_unit in EXPECTED_UNITS.items():
        if not isinstance(units.get(field), str) or units[field] != expected_unit:
            raise _schema_error(f"response unit metadata is invalid for `{field}`")

    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise _schema_error("response is missing the daily object")
    values_by_field: dict[str, list[Any]] = {}
    for field in ("time", *EXPECTED_DAILY_FIELDS):
        values = daily.get(field)
        if not isinstance(values, list):
            raise _schema_error(f"daily field `{field}` must be an array")
        values_by_field[field] = values

    expected = [value.isoformat() if isinstance(value, date) else value for value in requested_dates]
    if not expected:
        raise ValueError("at least one requested date is required")
    dates = values_by_field["time"]
    if not dates:
        raise _completeness_error("HTTP 200 response contains an empty daily time array")
    if any(not isinstance(value, str) for value in dates):
        raise _schema_error("daily time values must be ISO date strings")
    try:
        parsed_dates = [date.fromisoformat(value) for value in dates]
    except ValueError as exc:
        raise _schema_error("daily time contains an invalid ISO date") from exc
    if any(parsed.isoformat() != raw for parsed, raw in zip(parsed_dates, dates)):
        raise _schema_error("daily time values must use canonical YYYY-MM-DD form")

    lengths = {field: len(values) for field, values in values_by_field.items()}
    if len(set(lengths.values())) != 1:
        raise _completeness_error("daily arrays have different lengths")
    if dates != expected or len(set(dates)) != len(dates):
        raise _completeness_error("daily dates do not exactly cover the requested date range")
    return {
        "date_count": len(dates),
        "daily_fields": list(EXPECTED_DAILY_FIELDS),
        "timezone": expected_timezone,
        "units_validated": True,
    }
