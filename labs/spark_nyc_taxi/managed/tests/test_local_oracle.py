from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from labs.spark_nyc_taxi.managed.local_oracle import _summary
from labs.spark_nyc_taxi.managed.local_oracle import (
    LocalOracleContractError,
    _load_zone_records,
)
from labs.spark_nyc_taxi.managed.preflight import aggregate_checksum
from labs.spark_nyc_taxi.oracle import run_aggregate_oracle, run_oracle


class LocalOracleZoneLookupTests(unittest.TestCase):
    def test_loads_the_fixed_tlc_zone_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "taxi_zone_lookup.csv"
            path.write_text(
                "LocationID,Borough,Zone,service_zone\n"
                "1,Manhattan,Test Zone,Yellow Zone\n",
                encoding="utf-8",
            )

            self.assertEqual(
                _load_zone_records(path),
                [
                    {
                        "LocationID": "1",
                        "Borough": "Manhattan",
                        "Zone": "Test Zone",
                        "service_zone": "Yellow Zone",
                    }
                ],
            )

    def test_rejects_changed_column_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "taxi_zone_lookup.csv"
            path.write_text(
                "Borough,LocationID,Zone,service_zone\n"
                "Manhattan,1,Test Zone,Yellow Zone\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(LocalOracleContractError, "column order changed"):
                _load_zone_records(path)

    def test_rejects_empty_zone_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "taxi_zone_lookup.csv"
            path.write_text(
                "LocationID,Borough,Zone,service_zone\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(LocalOracleContractError, "is empty"):
                _load_zone_records(path)

    def test_aggregate_only_oracle_matches_full_oracle(self) -> None:
        zones = [
            {"LocationID": "1", "Borough": "Manhattan", "Zone": "One"},
            {"LocationID": "2", "Borough": "Manhattan", "Zone": "Two"},
        ]
        rows = [
            {
                "tpep_pickup_datetime": "2024-01-02T10:00:00",
                "tpep_dropoff_datetime": "2024-01-02T10:12:00",
                "PULocationID": "1",
                "DOLocationID": "2",
                "trip_distance": "1.20",
                "fare_amount": "10.00",
                "total_amount": "12.50",
            },
            {
                "tpep_pickup_datetime": "2024-01-02T10:20:00",
                "tpep_dropoff_datetime": "2024-01-02T10:45:00",
                "PULocationID": "1",
                "DOLocationID": "2",
                "trip_distance": "2.30",
                "fare_amount": "20.00",
                "total_amount": "25.00",
            },
            {
                "tpep_pickup_datetime": "2024-02-01T10:00:00",
                "tpep_dropoff_datetime": "2024-02-01T10:10:00",
                "PULocationID": "1",
                "DOLocationID": "2",
                "trip_distance": "1.00",
                "fare_amount": "5.00",
                "total_amount": "6.00",
            },
        ]
        period = {"period_start": date(2024, 1, 1), "period_end": date(2024, 2, 1)}

        full = run_oracle(rows, zones, **period)
        aggregate_only = run_aggregate_oracle(rows, zones, **period)

        self.assertEqual(aggregate_only.input_rows, full.input_rows)
        self.assertEqual(aggregate_only.accepted_rows, full.accepted_rows)
        self.assertEqual(aggregate_only.rejected_rows, full.rejected_rows)
        self.assertEqual(aggregate_only.rejection_counts, full.rejection_counts)
        self.assertEqual(aggregate_checksum(aggregate_only.aggregates), aggregate_checksum(full.aggregates))
        self.assertEqual(_summary(aggregate_only), _summary(full))


if __name__ == "__main__":
    unittest.main()
