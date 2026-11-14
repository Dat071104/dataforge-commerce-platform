from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from labs.spark_nyc_taxi.managed.stage_manifest import (
    MONTH_FILE,
    MONTH_URL,
    ZONE_FILE,
    ZONE_URL,
    StagingManifestError,
    build_manifest,
)


class StageManifestTests(unittest.TestCase):
    def test_builds_sanitized_manifest_with_object_generations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trip = root / MONTH_FILE
            zones = root / ZONE_FILE
            trip.write_bytes(b"jan-parquet-fixture")
            zones.write_bytes(b"zone-csv-fixture")
            entries = []
            for path, source_url in ((trip, MONTH_URL), (zones, ZONE_URL)):
                body = path.read_bytes()
                entries.append(
                    {
                        "name": path.name,
                        "source_url": source_url,
                        "local_path": str(path),
                        "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "row_count": "NOT_RUN",
                    }
                )
            manifest = {
                "status": "COMPLETE",
                "schema_period": "2024-01 through 2024-01",
                "row_counts": "NOT_RUN",
                "files": entries,
            }

            staged = build_manifest(
                manifest,
                trip_generation="1700000000000000",
                zone_generation="1700000000000001",
            )

        self.assertEqual(staged["status"], "COMPLETE")
        self.assertEqual(staged["files"][0]["generation"], "1700000000000000")
        self.assertEqual(staged["files"][1]["generation"], "1700000000000001")
        self.assertNotIn("local_path", staged["files"][0])
        self.assertNotIn("local_path", staged["files"][1])

    def test_manifest_fails_on_modified_local_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trip = root / MONTH_FILE
            zones = root / ZONE_FILE
            trip.write_bytes(b"modified")
            zones.write_bytes(b"zone-csv-fixture")
            manifest = {
                "status": "COMPLETE",
                "row_counts": "NOT_RUN",
                "files": [
                    {
                        "name": MONTH_FILE,
                        "source_url": MONTH_URL,
                        "local_path": str(trip),
                        "bytes": 1,
                        "sha256": "0" * 64,
                    },
                    {
                        "name": ZONE_FILE,
                        "source_url": ZONE_URL,
                        "local_path": str(zones),
                        "bytes": zones.stat().st_size,
                        "sha256": hashlib.sha256(zones.read_bytes()).hexdigest(),
                    },
                ],
            }
            with self.assertRaises(StagingManifestError):
                build_manifest(
                    manifest,
                    trip_generation="1700000000000000",
                    zone_generation="1700000000000001",
                )


if __name__ == "__main__":
    unittest.main()
