"""Independent, bounded Python/Decimal oracle for the Week 6 Spark job.

This module deliberately does not import Spark transformation code. It is
intended for deterministic subsets and oracle reconciliation, not full TLC
scale processing.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NY_ZONE = "America/New_York"
DEFAULT_PERIOD_START = date(2024, 1, 1)
DEFAULT_PERIOD_END = date(2024, 5, 1)  # exclusive
MAX_TRIP_SECONDS = 24 * 60 * 60
DISTANCE_QUANTUM = Decimal("0.001")
MONEY_QUANTUM = Decimal("0.01")
DURATION_QUANTUM = Decimal("0.001")
MONETARY_FIELDS = (
    "fare_amount",
    "extra",
    "mta_tax",
    "tip_amount",
    "tolls_amount",
    "improvement_surcharge",
    "total_amount",
    "congestion_surcharge",
    "airport_fee",
    "cbd_congestion_fee",
)
CRITICAL_FIELDS = (
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "PULocationID",
    "DOLocationID",
    "trip_distance",
    "fare_amount",
    "total_amount",
)
REJECTION_REASONS = (
    "null_critical",
    "invalid_timestamp",
    "out_of_period",
    "dst_nonexistent",
    "dst_ambiguous",
    "dst_crossing",
    "invalid_duration",
    "unknown_zone",
    "invalid_distance",
    "invalid_money",
)


class OracleContractError(ValueError):
    """The bounded oracle received a malformed zone lookup or input contract."""


@dataclass(frozen=True)
class OracleResult:
    input_rows: int
    accepted_rows: int
    rejected_rows: int
    rejection_counts: dict[str, int]
    negative_adjustment_rows: int
    negative_amount_field_counts: dict[str, int]
    exact_full_row_duplicate_like_rows: int
    aggregates: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_rows": self.input_rows,
            "accepted_rows": self.accepted_rows,
            "rejected_rows": self.rejected_rows,
            "accepted_plus_rejected": self.accepted_rows + self.rejected_rows,
            "rejection_counts": self.rejection_counts,
            "negative_adjustment_rows": self.negative_adjustment_rows,
            "negative_amount_field_counts": self.negative_amount_field_counts,
            "exact_full_row_duplicate_like_rows": self.exact_full_row_duplicate_like_rows,
            "aggregates": [
                {key: _json_value(value) for key, value in row.items()}
                for row in self.aggregates
            ],
        }


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _quantize(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _parse_local_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    # TLC's trip timestamps represent local wall-clock values without offsets.
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return None
    return parsed.replace(tzinfo=None)


def _localize_wall_clock(value: datetime, zone: ZoneInfo) -> tuple[datetime | None, str | None]:
    """Return a unique aware instant, or classify a gap/fold local clock."""

    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
        if round_trip == value:
            candidates.append(candidate)
    if not candidates:
        return None, "dst_nonexistent"
    offsets = {candidate.utcoffset() for candidate in candidates}
    if len(offsets) > 1:
        return None, "dst_ambiguous"
    return candidates[0], None


def _zone_lookup(zone_records: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, str]]:
    lookup: dict[int, dict[str, str]] = {}
    for record in zone_records:
        try:
            location_id = int(record["LocationID"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OracleContractError("zone lookup needs integer LocationID values") from exc
        if location_id in lookup:
            raise OracleContractError(f"zone lookup contains duplicate LocationID {location_id}")
        lookup[location_id] = {
            "borough": str(record.get("Borough") or "").strip(),
            "zone": str(record.get("Zone") or "").strip(),
        }
    return lookup


def _is_mapped_zone(location_id: int, lookup: Mapping[int, Mapping[str, str]]) -> bool:
    zone = lookup.get(location_id)
    if zone is None or not 1 <= location_id <= 263:
        return False
    return all(
        zone.get(field, "").strip().casefold() not in {"", "n/a", "unknown"}
        for field in ("borough", "zone")
    )


def _location_id(value: Any) -> int | None:
    parsed = _as_decimal(value)
    if parsed is None or parsed != parsed.to_integral_value():
        return None
    try:
        return int(parsed)
    except (OverflowError, ValueError):
        return None


def _row_fingerprint(row: Mapping[str, Any]) -> str:
    """Hash every supplied source column; this is diagnostic, never a key."""

    def canonical(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, float) and not math.isfinite(value):
            return repr(value)
        return value

    items = [
        (str(key), canonical(value))
        for key, value in sorted(row.items(), key=lambda item: str(item[0]))
    ]
    serialized = json.dumps(items, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _negative_fields(row: Mapping[str, Any]) -> tuple[str, ...]:
    fields: list[str] = []
    lookup = {str(key).casefold(): key for key in row}
    for field in dict.fromkeys(MONETARY_FIELDS):
        actual_key = lookup.get(field.casefold())
        if actual_key is None:
            continue
        value = _as_decimal(row[actual_key])
        if value is not None and value < 0:
            fields.append(str(actual_key))
    return tuple(fields)


def _classify_row(
    row: Mapping[str, Any],
    zone_lookup: Mapping[int, Mapping[str, str]],
    zone: ZoneInfo,
    period_start: date,
    period_end: date,
) -> tuple[dict[str, Any] | None, str | None, tuple[str, ...]]:
    if any(row.get(field) is None for field in CRITICAL_FIELDS):
        return None, "null_critical", ()

    pickup = _parse_local_datetime(row.get("tpep_pickup_datetime"))
    dropoff = _parse_local_datetime(row.get("tpep_dropoff_datetime"))
    if pickup is None or dropoff is None:
        return None, "invalid_timestamp", ()
    if not period_start <= pickup.date() < period_end:
        return None, "out_of_period", ()

    pickup_instant, pickup_error = _localize_wall_clock(pickup, zone)
    dropoff_instant, dropoff_error = _localize_wall_clock(dropoff, zone)
    for error in (pickup_error, dropoff_error):
        if error:
            return None, error, ()
    assert pickup_instant is not None and dropoff_instant is not None

    if dropoff <= pickup:
        return None, "invalid_duration", ()
    elapsed = (dropoff_instant.astimezone(UTC) - pickup_instant.astimezone(UTC)).total_seconds()
    if pickup_instant.utcoffset() != dropoff_instant.utcoffset():
        return None, "dst_crossing", ()
    if elapsed <= 0 or elapsed > MAX_TRIP_SECONDS:
        return None, "invalid_duration", ()

    pickup_zone = _location_id(row.get("PULocationID"))
    dropoff_zone = _location_id(row.get("DOLocationID"))
    if (
        pickup_zone is None
        or dropoff_zone is None
        or not _is_mapped_zone(pickup_zone, zone_lookup)
        or not _is_mapped_zone(dropoff_zone, zone_lookup)
    ):
        return None, "unknown_zone", ()

    distance = _as_decimal(row.get("trip_distance"))
    if distance is None or distance <= 0:
        return None, "invalid_distance", ()

    fare = _as_decimal(row.get("fare_amount"))
    total = _as_decimal(row.get("total_amount"))
    if fare is None or total is None:
        return None, "invalid_money", ()

    distance = _quantize(distance, DISTANCE_QUANTUM)
    fare = _quantize(fare, MONEY_QUANTUM)
    total = _quantize(total, MONEY_QUANTUM)
    negative_fields = _negative_fields(row)
    return (
        {
            "pickup_date": pickup.date(),
            "pickup_hour": pickup.hour,
            "pickup_zone": pickup_zone,
            "pickup_borough": zone_lookup[pickup_zone]["borough"],
            "trip_distance_miles": distance,
            "fare_amount": fare,
            "total_amount": total,
            "duration_minutes": Decimal(str(elapsed)) / Decimal(60),
            "negative_amount_fields": negative_fields,
        },
        None,
        negative_fields,
    )


def _nearest_rank(values: list[Decimal], quantile: Decimal) -> Decimal:
    ordered = sorted(values)
    rank = max(1, math.ceil(float(quantile * len(ordered))))
    return _quantize(ordered[rank - 1], DURATION_QUANTUM)


def run_oracle(
    rows: Iterable[Mapping[str, Any]],
    zone_records: Iterable[Mapping[str, Any]],
    *,
    period_start: date = DEFAULT_PERIOD_START,
    period_end: date = DEFAULT_PERIOD_END,
    timezone_name: str = NY_ZONE,
) -> OracleResult:
    """Classify a bounded raw subset and independently aggregate accepted rows.

    The interval is `[period_start, period_end)` and applies to pickup local
    dates. A valid drop-off may cross the source-month boundary. Repeated or
    absent New York wall-clock times and a trip whose endpoint offsets cross
    a DST transition are rejected because the TLC timestamps carry no UTC
    offset with which to resolve them.
    """

    if period_start >= period_end:
        raise ValueError("period_start must be earlier than period_end")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA timezone: {timezone_name}") from exc
    lookup = _zone_lookup(zone_records)
    rejection_counts: Counter[str] = Counter()
    negative_field_counts: Counter[str] = Counter()
    fingerprints: Counter[str] = Counter()
    groups: dict[tuple[date, int, int, str], dict[str, Any]] = defaultdict(
        lambda: {
            "trip_count": 0,
            "distance_miles_sum": Decimal("0.000"),
            "fare_amount_sum": Decimal("0.00"),
            "total_amount_sum": Decimal("0.00"),
            "durations": [],
        }
    )
    input_rows = 0
    accepted_rows = 0
    negative_adjustment_rows = 0

    for row in rows:
        if not isinstance(row, Mapping):
            raise OracleContractError("each raw row must be a mapping")
        input_rows += 1
        fingerprints[_row_fingerprint(row)] += 1
        negative_fields = _negative_fields(row)
        if negative_fields:
            negative_adjustment_rows += 1
            negative_field_counts.update(negative_fields)
        normalized, reason, _ = _classify_row(row, lookup, zone, period_start, period_end)
        if reason:
            rejection_counts[reason] += 1
            continue
        assert normalized is not None
        accepted_rows += 1

        key = (
            normalized["pickup_date"],
            normalized["pickup_hour"],
            normalized["pickup_zone"],
            normalized["pickup_borough"],
        )
        aggregate = groups[key]
        aggregate["trip_count"] += 1
        aggregate["distance_miles_sum"] += normalized["trip_distance_miles"]
        aggregate["fare_amount_sum"] += normalized["fare_amount"]
        aggregate["total_amount_sum"] += normalized["total_amount"]
        aggregate["durations"].append(normalized["duration_minutes"])

    output: list[dict[str, Any]] = []
    for (pickup_date, pickup_hour, pickup_zone, pickup_borough), aggregate in sorted(
        groups.items()
    ):
        durations = aggregate.pop("durations")
        output.append(
            {
                "pickup_date": pickup_date.isoformat(),
                "pickup_hour": pickup_hour,
                "pickup_zone": pickup_zone,
                "pickup_borough": pickup_borough,
                "trip_count": aggregate["trip_count"],
                "distance_miles_sum": _quantize(
                    aggregate["distance_miles_sum"], DISTANCE_QUANTUM
                ),
                "fare_amount_sum": _quantize(aggregate["fare_amount_sum"], MONEY_QUANTUM),
                "total_amount_sum": _quantize(aggregate["total_amount_sum"], MONEY_QUANTUM),
                "duration_p50_minutes": _nearest_rank(durations, Decimal("0.50")),
                "duration_p95_minutes": _nearest_rank(durations, Decimal("0.95")),
            }
        )

    rejected_rows = input_rows - accepted_rows
    if accepted_rows + rejected_rows != input_rows:
        raise AssertionError("oracle accounting invariant failed")
    return OracleResult(
        input_rows=input_rows,
        accepted_rows=accepted_rows,
        rejected_rows=rejected_rows,
        rejection_counts={reason: rejection_counts.get(reason, 0) for reason in REJECTION_REASONS},
        negative_adjustment_rows=negative_adjustment_rows,
        negative_amount_field_counts=dict(sorted(negative_field_counts.items())),
        exact_full_row_duplicate_like_rows=sum(
            count - 1 for count in fingerprints.values() if count > 1
        ),
        aggregates=tuple(output),
    )
