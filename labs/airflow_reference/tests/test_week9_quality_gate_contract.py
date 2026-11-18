from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from airflow.sdk.exceptions import AirflowFailException

REFERENCE_ROOT = Path(__file__).resolve().parents[1]
DAGS_DIR = REFERENCE_ROOT / "dags"
sys.path.insert(0, str(DAGS_DIR))

import dataforge_week7_weather_cloud as weather_cloud  # noqa: E402


class Week9AirflowGateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dag = weather_cloud.dataforge_week7_weather_cloud()
        cls.gate = cls.dag.get_task("quality_gate_landing").python_callable

    def setUp(self) -> None:
        self.request = {"observation_date": "2026-11-06"}
        self.landing = {"status": "COMPLETE"}

    def test_gate_is_disabled_by_default_without_calling_adapter(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(weather_cloud, "_run_week9_landing_gate") as adapter,
        ):
            result = self.gate(self.request, self.landing)

        self.assertEqual(result["status"], "DISABLED")
        self.assertEqual(result["published"], None)
        adapter.assert_not_called()

    def test_enabled_gate_without_isolated_adapter_fails_closed(self) -> None:
        with patch.dict(os.environ, {"DATAFORGE_DQ_GATE_ENABLED": "true"}, clear=True):
            with self.assertRaises(weather_cloud.Week9DQGateFailure) as caught:
                self.gate(self.request, self.landing)

        self.assertEqual(caught.exception.check_id, "ALERTING.DQ_GATE_ADAPTER_UNAVAILABLE")
        self.assertIsInstance(caught.exception, AirflowFailException)

    def test_test_adapter_p1_failure_blocks_before_downstream_build(self) -> None:
        failure = {
            "status": "FAIL",
            "check_id": "G1.LANDING.PHYSICAL_RANGE",
            "severity": "P1",
            "dataset": "w9_drill",
            "date": "2026-11-06",
            "failing_rows": 1,
        }
        with (
            patch.dict(os.environ, {"DATAFORGE_DQ_GATE_ENABLED": "true"}, clear=True),
            patch.object(weather_cloud, "_run_week9_landing_gate", return_value=failure),
        ):
            with self.assertRaises(weather_cloud.Week9DQGateFailure) as caught:
                self.gate(self.request, self.landing)

        self.assertEqual(caught.exception.check_id, "G1.LANDING.PHYSICAL_RANGE")
        self.assertEqual(caught.exception.severity, "P1")
        self.assertEqual(caught.exception.dataset, "w9_drill")

    def test_test_adapter_cannot_target_a_nonisolated_dataset(self) -> None:
        success = {
            "status": "PASS",
            "check_id": "G1.LANDING.PHYSICAL_RANGE",
            "severity": "P1",
            "dataset": "weather_mini3",
            "date": "2026-11-06",
            "failing_rows": 0,
        }
        with (
            patch.dict(os.environ, {"DATAFORGE_DQ_GATE_ENABLED": "true"}, clear=True),
            patch.object(weather_cloud, "_run_week9_landing_gate", return_value=success),
        ):
            with self.assertRaises(weather_cloud.Week9DQGateFailure) as caught:
                self.gate(self.request, self.landing)

        self.assertEqual(caught.exception.check_id, "ALERTING.DQ_GATE_ADAPTER_UNAVAILABLE")

    def test_gate_failure_callback_emits_only_sanitized_metadata(self) -> None:
        exception = weather_cloud.Week9DQGateFailure(
            check_id="G1.LANDING.PHYSICAL_RANGE",
            severity="P1",
            dataset="w9_drill",
            event_date="2026-11-06",
            failing_rows=1,
        )
        exception.args = ("raw row value must not be logged",)
        with patch.object(weather_cloud._LOGGER, "error") as logger:
            weather_cloud.local_dq_gate_failure_log(
                {
                    "task_instance": SimpleNamespace(task_id="quality_gate_landing"),
                    "dag_run": SimpleNamespace(run_id="manual__q10_gate_fail"),
                    "exception": exception,
                }
            )

        logger.assert_called_once()
        self.assertIn("DATAFORGE_AIRFLOW_DQ_GATE_FAILED", logger.call_args.args[0])
        payload = json.loads(logger.call_args.args[1])
        self.assertEqual(payload["event_type"], "DQ_GATE_FAILED")
        self.assertEqual(payload["check_id"], "G1.LANDING.PHYSICAL_RANGE")
        self.assertEqual(payload["run_id"], "manual__q10_gate_fail")
        self.assertEqual(payload["dataset"], "w9_drill")
        self.assertEqual(payload["failing_rows"], 1)
        self.assertFalse(payload["published"])
        self.assertFalse(payload["external_notification_sent"])
        self.assertNotIn("raw row value", logger.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
