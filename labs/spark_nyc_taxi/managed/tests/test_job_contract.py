from __future__ import annotations

import unittest

from labs.spark_nyc_taxi.download import monthly_url
from labs.spark_nyc_taxi.managed.job import (
    MONTH_FILE,
    ZONE_FILE,
    ManagedJobContractError,
    _verify_oracle,
    validate_source_contract,
)


class ManagedSparkJobContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sha256 = "a" * 64
        self.batch_id = "dataforge-test-batch"
        self.manifest = {
            "status": "COMPLETE",
            "schema_period": "2024-01 through 2024-01",
            "source_manifest_uri": "gs://dataforge-p7-lab-d0f725-bronze/tlc_managed/source/manifest.json",
            "files": [
                {
                    "name": MONTH_FILE,
                    "source_url": monthly_url(2024, 1),
                    "bytes": 100,
                    "sha256": self.sha256,
                    "generation": "1700000000000000",
                },
                {
                    "name": ZONE_FILE,
                    "source_url": "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv",
                    "bytes": 100,
                    "sha256": "b" * 64,
                    "generation": "1700000000000001",
                },
            ],
        }

    def _validate(self, **overrides: str) -> None:
        values = {
            "trip_uri": "gs://dataforge-p7-lab-d0f725-bronze/tlc_managed/source/yellow_tripdata_2024-01.parquet",
            "zones_uri": "gs://dataforge-p7-lab-d0f725-bronze/tlc_managed/source/taxi_zone_lookup.csv",
            "expected_sha256": self.sha256,
            "expected_zone_sha256": "b" * 64,
            "expected_generation": "1700000000000000",
            "expected_zone_generation": "1700000000000001",
            "output_uri": f"gs://dataforge-p7-lab-d0f725-bronze/tlc_managed/2024-01/{self.batch_id}",
            "batch_id": self.batch_id,
        }
        values.update(overrides)
        validate_source_contract(self.manifest, **values)

    def test_fixed_january_source_and_isolated_output_pass(self) -> None:
        self._validate()

    def test_wrong_month_fails_before_spark_io(self) -> None:
        with self.assertRaises(ManagedJobContractError):
            self._validate(trip_uri="gs://dataforge-p7-lab-d0f725-bronze/tlc_managed/source/yellow_tripdata_2024-02.parquet")

    def test_wrong_digest_fails_closed(self) -> None:
        with self.assertRaises(ManagedJobContractError):
            self._validate(expected_sha256="c" * 64)

    def test_output_must_be_isolated_to_january_prefix_and_batch(self) -> None:
        with self.assertRaises(ManagedJobContractError):
            self._validate(output_uri="gs://dataforge-p7-lab-d0f725-bronze/tlc_managed/shared-output")

    def test_oracle_mismatch_blocks_publication(self) -> None:
        actual = {
            "source_sha256": self.sha256,
            "input_rows": 10,
            "accepted_rows": 8,
            "rejected_rows": 2,
            "aggregate_group_count": 3,
            "trip_count_sum": 8,
            "distance_miles_sum": "12.000",
            "fare_amount_sum": "20.00",
            "total_amount_sum": "30.00",
            "aggregate_checksum": "x",
        }
        oracle = {
            "source_sha256": self.sha256,
            "zone_sha256": "b" * 64,
            "oracle": {**actual, "aggregate_checksum": "different"},
        }
        with self.assertRaises(ManagedJobContractError):
            _verify_oracle(actual, oracle, source_sha256=self.sha256, zone_sha256="b" * 64)


if __name__ == "__main__":
    unittest.main()
