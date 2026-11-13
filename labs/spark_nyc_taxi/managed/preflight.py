"""Offline cost guard and comparable aggregate checksums for managed Spark.

Pricing inputs are the standard ``us-central1`` rates listed by the official
Managed Service for Apache Spark pricing page. GCS, network, and output charges
must be supplied as a separate upper bound from measured bytes before a batch
can be marked safe to submit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping

STANDARD_DCU_USD_PER_HOUR = Decimal("0.06")
STANDARD_SHUFFLE_USD_PER_GIB_HOUR = Decimal("0.000054795")
MIN_BATCH_DCUS = 12
MAX_TTL_MINUTES = 30
MAX_ATTEMPTS = 2
C7_CAP_USD = Decimal("5.00")
C7_STOP_USD = C7_CAP_USD * Decimal("0.80")


class PreflightError(ValueError):
    """Raised when a managed Spark request violates the bounded plan."""


def estimate_worst_case(
    *,
    dcus: int,
    ttl_minutes: int,
    attempts: int,
    max_shuffle_gib: Decimal | str | int | float,
    other_services_upper_bound_usd: Decimal | str | int | float | None,
) -> dict[str, str | int | bool]:
    """Calculate a gross upper bound and fail closed on missing cost inputs."""

    if dcus < MIN_BATCH_DCUS:
        raise PreflightError(f"dcus must include the {MIN_BATCH_DCUS}-DCU serverless minimum")
    if ttl_minutes < 1 or ttl_minutes > MAX_TTL_MINUTES:
        raise PreflightError(f"ttl_minutes must be in 1..{MAX_TTL_MINUTES}")
    if attempts < 1 or attempts > MAX_ATTEMPTS:
        raise PreflightError(f"attempts must be in 1..{MAX_ATTEMPTS}")
    try:
        shuffle_gib = Decimal(str(max_shuffle_gib))
    except InvalidOperation as exc:
        raise PreflightError("max_shuffle_gib must be a finite non-negative number") from exc
    if not shuffle_gib.is_finite() or shuffle_gib < 0:
        raise PreflightError("max_shuffle_gib must be a finite non-negative number")

    hours = Decimal(ttl_minutes) / Decimal(60)
    compute_cost = Decimal(dcus) * STANDARD_DCU_USD_PER_HOUR * hours * Decimal(attempts)
    shuffle_cost = shuffle_gib * STANDARD_SHUFFLE_USD_PER_GIB_HOUR * hours * Decimal(attempts)

    if other_services_upper_bound_usd is None:
        return {
            "status": "BLOCKED_MISSING_NONCOMPUTE_BOUND",
            "submit_allowed": False,
            "compute_usd": str(compute_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
            "shuffle_usd": str(shuffle_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
            "total_usd": "UNKNOWN",
            "stop_threshold_usd": str(C7_STOP_USD),
            "cap_usd": str(C7_CAP_USD),
        }

    try:
        other_cost = Decimal(str(other_services_upper_bound_usd))
    except InvalidOperation as exc:
        raise PreflightError("other_services_upper_bound_usd must be a finite non-negative number") from exc
    if not other_cost.is_finite() or other_cost < 0:
        raise PreflightError("other_services_upper_bound_usd must be a finite non-negative number")

    total = compute_cost + shuffle_cost + other_cost
    submit_allowed = total < C7_STOP_USD
    status = "PASS_WITHIN_80_PERCENT_STOP" if submit_allowed else "ABORT_AT_OR_ABOVE_80_PERCENT_STOP"
    if total > C7_CAP_USD:
        status = "ABORT_OVER_C7_CAP"
    return {
        "status": status,
        "submit_allowed": submit_allowed,
        "compute_usd": str(compute_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "shuffle_usd": str(shuffle_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "other_services_upper_bound_usd": str(other_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "total_usd": str(total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "stop_threshold_usd": str(C7_STOP_USD),
        "cap_usd": str(C7_CAP_USD),
    }


def _money(value: Any, *, quantum: Decimal) -> str:
    if value is None:
        value = 0
    return format(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP), "f")


def canonical_aggregate_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project matching key/count/money fields and sort for stable checksums.

    Duration percentiles are intentionally excluded from the cross-engine
    checksum because Spark ``percentile_approx`` and the local exact rank
    oracle can differ while count and money aggregates remain reconciled.
    """

    normalized: list[dict[str, Any]] = []
    for row in rows:
        pickup_date = row["pickup_date"]
        if hasattr(pickup_date, "isoformat"):
            pickup_date = pickup_date.isoformat()
        normalized.append(
            {
                "pickup_date": str(pickup_date),
                "pickup_hour": int(row["pickup_hour"]),
                "pickup_zone": int(row["pickup_zone"]),
                "pickup_borough": str(row["pickup_borough"]),
                "trip_count": int(row["trip_count"]),
                "distance_miles_sum": _money(row["distance_miles_sum"], quantum=Decimal("0.001")),
                "fare_amount_sum": _money(row["fare_amount_sum"], quantum=Decimal("0.01")),
                "total_amount_sum": _money(row["total_amount_sum"], quantum=Decimal("0.01")),
            }
        )
    return sorted(
        normalized,
        key=lambda row: (row["pickup_date"], row["pickup_hour"], row["pickup_zone"]),
    )


def aggregate_checksum(rows: Iterable[Mapping[str, Any]]) -> str:
    canonical = canonical_aggregate_rows(rows)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dcus", type=int, default=MIN_BATCH_DCUS)
    parser.add_argument("--ttl-minutes", type=int, default=MAX_TTL_MINUTES)
    parser.add_argument("--attempts", type=int, default=MAX_ATTEMPTS)
    parser.add_argument("--max-shuffle-gib", required=True, type=Decimal)
    parser.add_argument(
        "--other-services-upper-bound-usd",
        required=True,
        type=Decimal,
        help="Upper bound for GCS staging/output, network, and other non-DCU charges.",
    )
    args = parser.parse_args(argv)
    try:
        result = estimate_worst_case(
            dcus=args.dcus,
            ttl_minutes=args.ttl_minutes,
            attempts=args.attempts,
            max_shuffle_gib=args.max_shuffle_gib,
            other_services_upper_bound_usd=args.other_services_upper_bound_usd,
        )
    except PreflightError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["submit_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
