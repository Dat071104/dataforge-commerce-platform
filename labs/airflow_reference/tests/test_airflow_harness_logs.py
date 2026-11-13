from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[1] / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from run_scheduler_harness import _failure_event_payload  # noqa: E402


class FailureEventPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.marker = "DATAFORGE_AIRFLOW_WEATHER_FAILURE "
        self.payload = {
            "dag_id": "dataforge_week7_weather_cloud",
            "event_type": "PIPELINE_FAILED",
            "task_id": "execute_api_ingest",
            "try_number": 1,
        }

    def test_decodes_json_with_airflow_logger_suffix(self) -> None:
        line = (
            "ERROR "
            + self.marker
            + json.dumps(self.payload, sort_keys=True)
            + " [airflow.task] dag_id=dataforge_week7_weather_cloud"
        )
        self.assertEqual(_failure_event_payload(line, self.marker), self.payload)

    def test_decodes_escaped_json_inside_structured_log(self) -> None:
        escaped = json.dumps(self.payload, separators=(",", ":")).replace('"', r'\"')
        line = '{"message":"' + self.marker + escaped + '"}'
        self.assertEqual(_failure_event_payload(line, self.marker), self.payload)


if __name__ == "__main__":
    unittest.main()
