from __future__ import annotations

import unittest
from decimal import Decimal

from labs.spark_nyc_taxi.managed.preflight import (
    PreflightError,
    aggregate_checksum,
    canonical_aggregate_rows,
    estimate_worst_case,
)


class ManagedSparkPreflightTests(unittest.TestCase):
    def test_two_full_ttl_attempts_cost_72_cents_before_other_services(self) -> None:
        result = estimate_worst_case(
            dcus=12,
            ttl_minutes=30,
            attempts=2,
            max_shuffle_gib=Decimal("10"),
            other_services_upper_bound_usd=Decimal("0"),
        )
        self.assertEqual(result["compute_usd"], "0.720000")
        self.assertEqual(result["status"], "PASS_WITHIN_80_PERCENT_STOP")
        self.assertTrue(result["submit_allowed"])

    def test_missing_noncompute_bound_blocks_submit(self) -> None:
        result = estimate_worst_case(
            dcus=12,
            ttl_minutes=30,
            attempts=2,
            max_shuffle_gib=Decimal("0"),
            other_services_upper_bound_usd=None,
        )
        self.assertEqual(result["status"], "BLOCKED_MISSING_NONCOMPUTE_BOUND")
        self.assertFalse(result["submit_allowed"])

    def test_eighty_percent_stop_threshold_blocks_submit(self) -> None:
        result = estimate_worst_case(
            dcus=12,
            ttl_minutes=30,
            attempts=2,
            max_shuffle_gib=Decimal("0"),
            other_services_upper_bound_usd=Decimal("3.28"),
        )
        self.assertEqual(result["total_usd"], "4.000000")
        self.assertEqual(result["status"], "ABORT_AT_OR_ABOVE_80_PERCENT_STOP")
        self.assertFalse(result["submit_allowed"])

    def test_ttl_and_attempt_count_are_bounded(self) -> None:
        for kwargs in (
            {"dcus": 12, "ttl_minutes": 31, "attempts": 1, "max_shuffle_gib": 0, "other_services_upper_bound_usd": 0},
            {"dcus": 12, "ttl_minutes": 30, "attempts": 3, "max_shuffle_gib": 0, "other_services_upper_bound_usd": 0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(PreflightError):
                estimate_worst_case(**kwargs)

    def test_aggregate_checksum_is_sorted_and_money_quantized(self) -> None:
        rows = [
            {
                "pickup_date": "2024-01-02",
                "pickup_hour": 9,
                "pickup_zone": 14,
                "pickup_borough": "Manhattan",
                "trip_count": 4,
                "distance_miles_sum": 5.5555,
                "fare_amount_sum": 6.235,
                "total_amount_sum": 8.105,
                "duration_p50_minutes": 3.1,
            },
            {
                "pickup_date": "2024-01-01",
                "pickup_hour": 10,
                "pickup_zone": 132,
                "pickup_borough": "Queens",
                "trip_count": 2,
                "distance_miles_sum": 1.2344,
                "fare_amount_sum": 2.345,
                "total_amount_sum": 3.456,
                "duration_p50_minutes": 4.2,
            },
        ]
        first = canonical_aggregate_rows(rows)
        second = canonical_aggregate_rows(reversed(rows))
        self.assertEqual(first, second)
        self.assertEqual(first[0]["fare_amount_sum"], "2.35")
        self.assertEqual(aggregate_checksum(rows), aggregate_checksum(reversed(rows)))


if __name__ == "__main__":
    unittest.main()
