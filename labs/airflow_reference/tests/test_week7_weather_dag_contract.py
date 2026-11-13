from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path

REFERENCE_ROOT = Path(__file__).resolve().parents[1]
DAGS_DIR = REFERENCE_ROOT / "dags"
sys.path.insert(0, str(DAGS_DIR))

from dataforge_week7_weather_cloud import (  # noqa: E402
    DAG_ID,
    GCSInvocationReceiptSensor,
    dataforge_week7_weather_cloud,
)


class WeatherCloudDagStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dag = dataforge_week7_weather_cloud()

    def test_dag_is_opt_in_daily_timezone_aware_and_bounded(self) -> None:
        self.assertEqual(self.dag.dag_id, DAG_ID)
        self.assertEqual(self.dag.schedule, "0 9 * * *")
        self.assertEqual(self.dag.timezone.name, "Asia/Ho_Chi_Minh")
        self.assertFalse(self.dag.catchup)
        self.assertEqual(self.dag.max_active_runs, 1)
        self.assertTrue(self.dag.is_paused_upon_creation)
        self.assertEqual(self.dag.dagrun_timeout, timedelta(hours=2))

    def test_real_integration_stages_are_distinct_and_ordered(self) -> None:
        expected = {
            "resolve_cloud_request",
            "verify_gcp_schedule_paused",
            "execute_api_ingest",
            "wait_for_gcs_invocation_receipt",
            "read_execution_receipt",
            "load_bigquery_landing",
            "verify_landing_reconciliation",
            "dbt_weather_build",
            "dbt_weather_test",
            "publish_weather_gold",
            "verify_published_gold",
            "record_airflow_execution_receipt",
        }
        self.assertEqual(set(self.dag.task_ids), expected)
        self.assertEqual(
            self.dag.get_task("execute_api_ingest").upstream_task_ids,
            {"resolve_cloud_request", "verify_gcp_schedule_paused"},
        )
        self.assertEqual(
            self.dag.get_task("wait_for_gcs_invocation_receipt").upstream_task_ids,
            {"resolve_cloud_request", "execute_api_ingest"},
        )
        self.assertEqual(
            self.dag.get_task("read_execution_receipt").upstream_task_ids,
            {"resolve_cloud_request", "wait_for_gcs_invocation_receipt"},
        )
        for upstream, downstream in (
            ("load_bigquery_landing", "verify_landing_reconciliation"),
            ("verify_landing_reconciliation", "dbt_weather_build"),
            ("dbt_weather_build", "dbt_weather_test"),
            ("dbt_weather_test", "publish_weather_gold"),
            ("publish_weather_gold", "verify_published_gold"),
        ):
            with self.subTest(upstream=upstream, downstream=downstream):
                self.assertIn(downstream, self.dag.get_task(upstream).downstream_task_ids)
        receipt = self.dag.get_task("record_airflow_execution_receipt")
        for task_id in (
            "resolve_cloud_request",
            "verify_gcp_schedule_paused",
            "execute_api_ingest",
            "read_execution_receipt",
            "verify_landing_reconciliation",
            "load_bigquery_landing",
            "dbt_weather_build",
            "dbt_weather_test",
            "publish_weather_gold",
            "verify_published_gold",
        ):
            with self.subTest(receipt_upstream=task_id):
                self.assertIn(task_id, receipt.upstream_task_ids)
        self.assertFalse(receipt.downstream_task_ids)

    def test_sensor_reschedules_with_a_fixed_timeout_and_cloud_tasks_are_bounded(self) -> None:
        sensor = self.dag.get_task("wait_for_gcs_invocation_receipt")
        self.assertIsInstance(sensor, GCSInvocationReceiptSensor)
        self.assertEqual(sensor.mode, "reschedule")
        self.assertEqual(sensor.timeout, 20 * 60)
        self.assertGreater(sensor.execution_timeout, timedelta(0))
        for task_id in (
            "execute_api_ingest",
            "load_bigquery_landing",
            "verify_landing_reconciliation",
            "dbt_weather_build",
            "dbt_weather_test",
            "publish_weather_gold",
        ):
            with self.subTest(task_id=task_id):
                self.assertGreater(self.dag.get_task(task_id).execution_timeout, timedelta(0))
                self.assertEqual(self.dag.get_task(task_id).retries, 1)

    def test_integration_tasks_use_a_redacted_local_failure_hook(self) -> None:
        for task in self.dag.tasks:
            with self.subTest(task_id=task.task_id):
                callbacks = task.on_failure_callback
                if not isinstance(callbacks, list):
                    callbacks = [callbacks]
                self.assertEqual(
                    [callback.__name__ for callback in callbacks],
                    ["local_failure_log"],
                )

    def test_dbt_build_and_tests_receive_the_bounded_partition_date(self) -> None:
        dag_source = (
            DAGS_DIR / "dataforge_week7_weather_cloud.py"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(dag_source.count('"--vars"'), 2)
        self.assertIn('weather_dbt_vars_argument(request["observation_date"])', dag_source)


if __name__ == "__main__":
    unittest.main()
