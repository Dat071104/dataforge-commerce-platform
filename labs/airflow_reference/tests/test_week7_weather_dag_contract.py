from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from airflow.sdk import DeadlineAlert
from airflow.sdk.bases.sensor import PokeReturnValue
from airflow.sdk.exceptions import (
    AirflowException,
    AirflowFailException,
    AirflowSkipException,
)

REFERENCE_ROOT = Path(__file__).resolve().parents[1]
DAGS_DIR = REFERENCE_ROOT / "dags"
sys.path.insert(0, str(DAGS_DIR))

import dataforge_week7_weather_cloud as weather_cloud  # noqa: E402
from dataforge_week7_weather_cloud import (  # noqa: E402
    DAG_ID,
    CloudRunExecutionReceiptSensor,
    dataforge_week7_weather_cloud,
)


class _Response:
    def __init__(self, status_code: int, body: object | None = None) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> object:
        return self._body


class WeatherCloudDagStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dag = dataforge_week7_weather_cloud()

    def test_dag_has_validated_params_daily_interval_and_secure_default(self) -> None:
        self.assertEqual(self.dag.dag_id, DAG_ID)
        self.assertEqual(self.dag.schedule, "0 9 * * *")
        self.assertEqual(self.dag.timezone.name, "Asia/Ho_Chi_Minh")
        self.assertFalse(self.dag.catchup)
        self.assertEqual(self.dag.max_active_runs, 1)
        self.assertTrue(self.dag.is_paused_upon_creation)
        self.assertEqual(self.dag.dagrun_timeout, timedelta(hours=2))
        self.assertEqual(len(self.dag.deadline), 1)
        self.assertIsInstance(self.dag.deadline[0], DeadlineAlert)
        self.assertEqual(self.dag.deadline[0].interval, timedelta(minutes=90))
        self.assertIn("data_interval_end", self.dag.doc_md)
        self.assertIn("legacy SLA", self.dag.doc_md)
        self.assertEqual(self.dag.params["mode"], "scheduled")
        self.assertEqual(
            self.dag.params.get_param("mode").schema["enum"],
            ["scheduled", "manual"],
        )
        self.assertIsNone(self.dag.params["observation_date"])
        self.assertEqual(
            self.dag.params.get_param("observation_date").schema["type"],
            ["null", "string"],
        )

    def test_real_integration_stages_are_distinct_and_cloud_gate_precedes_calls(self) -> None:
        expected = {
            "resolve_cloud_request",
            "authorize_cloud_execution",
            "verify_gcp_schedule_paused",
            "execute_api_ingest",
            "wait_for_api_ingest",
            "read_execution_receipt",
            "load_bigquery_landing",
            "wait_for_bigquery_landing",
            "verify_landing_reconciliation",
            "wait_for_landing_reconciliation",
            "dbt_weather_build",
            "wait_for_dbt_weather_build",
            "publish_weather_gold",
            "wait_for_publish_weather_gold",
            "verify_published_gold",
            "record_airflow_execution_receipt",
        }
        self.assertEqual(set(self.dag.task_ids), expected)
        self.assertEqual(
            self.dag.get_task("authorize_cloud_execution").upstream_task_ids,
            {"resolve_cloud_request"},
        )
        self.assertEqual(
            self.dag.get_task("verify_gcp_schedule_paused").upstream_task_ids,
            {"authorize_cloud_execution"},
        )
        self.assertEqual(
            self.dag.get_task("execute_api_ingest").upstream_task_ids,
            {"resolve_cloud_request", "verify_gcp_schedule_paused"},
        )
        ingest_sensor = self.dag.get_task("wait_for_api_ingest")
        self.assertEqual(ingest_sensor.mode, "reschedule")
        self.assertEqual(
            ingest_sensor.upstream_task_ids,
            {"resolve_cloud_request", "execute_api_ingest"},
        )
        self.assertEqual(ingest_sensor.job_name, weather_cloud.INGEST_JOB)
        self.assertTrue(ingest_sensor.require_receipt)
        self.assertEqual(
            self.dag.get_task("read_execution_receipt").upstream_task_ids,
            {"resolve_cloud_request", "wait_for_api_ingest"},
        )
        for upstream, downstream in (
            ("load_bigquery_landing", "wait_for_bigquery_landing"),
            ("wait_for_bigquery_landing", "verify_landing_reconciliation"),
            ("verify_landing_reconciliation", "wait_for_landing_reconciliation"),
            ("wait_for_landing_reconciliation", "dbt_weather_build"),
            ("dbt_weather_build", "wait_for_dbt_weather_build"),
            ("wait_for_dbt_weather_build", "publish_weather_gold"),
            ("publish_weather_gold", "wait_for_publish_weather_gold"),
            ("wait_for_publish_weather_gold", "verify_published_gold"),
        ):
            with self.subTest(upstream=upstream, downstream=downstream):
                self.assertIn(downstream, self.dag.get_task(upstream).downstream_task_ids)
        receipt = self.dag.get_task("record_airflow_execution_receipt")
        for task_id in (
            "resolve_cloud_request",
            "verify_gcp_schedule_paused",
            "wait_for_api_ingest",
            "read_execution_receipt",
            "wait_for_bigquery_landing",
            "wait_for_landing_reconciliation",
            "wait_for_dbt_weather_build",
            "wait_for_publish_weather_gold",
            "verify_published_gold",
        ):
            with self.subTest(receipt_upstream=task_id):
                self.assertIn(task_id, receipt.upstream_task_ids)
        self.assertFalse(receipt.downstream_task_ids)
        for task_id in (
            "execute_api_ingest",
            "load_bigquery_landing",
            "verify_landing_reconciliation",
            "dbt_weather_build",
            "publish_weather_gold",
        ):
            task = self.dag.get_task(task_id)
            self.assertEqual(task.pool, weather_cloud._CLOUD_RUN_SUBMISSION_POOL)
            self.assertEqual(task.execution_timeout, timedelta(minutes=2))
            self.assertTrue(task.doc_md)
        for task_id in (
            "wait_for_api_ingest",
            "wait_for_bigquery_landing",
            "wait_for_landing_reconciliation",
            "wait_for_dbt_weather_build",
            "wait_for_publish_weather_gold",
        ):
            sensor = self.dag.get_task(task_id)
            self.assertEqual(sensor.mode, "reschedule")
            self.assertEqual(sensor.timeout, weather_cloud._CLOUD_RUN_SENSOR_TIMEOUT_SECONDS)
            self.assertEqual(sensor.execution_timeout, weather_cloud._CLOUD_RUN_TASK_TIMEOUT)
            self.assertEqual(sensor.retries, 0)
            self.assertTrue(sensor.doc_md)
        self.assertNotIn("wait_for_gcs_invocation_receipt", self.dag.task_ids)

    def test_cloud_off_is_an_explicit_no_op_and_starts_no_cloud_client(self) -> None:
        request = {
            "mode": "scheduled",
            "observation_date": "2026-11-06",
            "invocation_id": "a" * 64,
        }
        with (
            patch.dict(os.environ, {"DATAFORGE_WEATHER_CLOUD_ENABLED": "false"}),
            patch.object(weather_cloud, "_authorized_session") as session,
            patch.object(weather_cloud._LOGGER, "info") as logger,
        ):
            with self.assertRaises(AirflowSkipException):
                self.dag.get_task("authorize_cloud_execution").python_callable(request)

        session.assert_not_called()
        event = json.loads(logger.call_args.args[1])
        self.assertEqual(event["status"], "DISABLED")
        self.assertEqual(event["mode"], "scheduled")
        self.assertEqual(event["observation_date"], "2026-11-06")

    def test_invalid_opt_in_and_wrong_target_fail_before_cloud_calls(self) -> None:
        with patch.dict(os.environ, {"DATAFORGE_WEATHER_CLOUD_ENABLED": "yes"}):
            with self.assertRaises(AirflowFailException):
                weather_cloud._require_cloud_authorization()
        with patch.dict(
            os.environ,
            {
                "DATAFORGE_WEATHER_CLOUD_ENABLED": "true",
                "DATAFORGE_WEATHER_PROJECT_ID": "wrong-project",
            },
        ):
            with self.assertRaises(AirflowFailException):
                weather_cloud._require_cloud_authorization()

    def test_attached_identity_mode_uses_metadata_principal_without_adc_file(self) -> None:
        from google.auth.compute_engine.credentials import Credentials as ComputeEngineCredentials

        expected = "dataforge-week7-airflow@dataforge-p7-lab-d0f725.iam.gserviceaccount.com"
        credentials = ComputeEngineCredentials(service_account_email=expected)
        env = {
            "DATAFORGE_WEATHER_CLOUD_ENABLED": "true",
            "DATAFORGE_WEATHER_PROJECT_ID": weather_cloud.PROJECT_ID,
            "DATAFORGE_WEATHER_REGION": weather_cloud.REGION,
            "DATAFORGE_AIRFLOW_IDENTITY_MODE": "attached_service_account",
            "DATAFORGE_AIRFLOW_ATTACHED_SERVICE_ACCOUNT": expected,
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("google.auth.default", return_value=(credentials, weather_cloud.PROJECT_ID)),
            patch.object(credentials, "refresh") as refresh,
        ):
            authorized = weather_cloud._authorized_credentials()

        self.assertIs(authorized, credentials)
        refresh.assert_called_once()

    def test_attached_identity_mode_rejects_wrong_metadata_principal_and_adc_file(self) -> None:
        from google.auth.compute_engine.credentials import Credentials as ComputeEngineCredentials

        expected = "dataforge-week7-airflow@dataforge-p7-lab-d0f725.iam.gserviceaccount.com"
        wrong_credentials = ComputeEngineCredentials(
            service_account_email="another-account@dataforge-p7-lab-d0f725.iam.gserviceaccount.com"
        )
        env = {
            "DATAFORGE_WEATHER_CLOUD_ENABLED": "true",
            "DATAFORGE_WEATHER_PROJECT_ID": weather_cloud.PROJECT_ID,
            "DATAFORGE_WEATHER_REGION": weather_cloud.REGION,
            "DATAFORGE_AIRFLOW_IDENTITY_MODE": "attached_service_account",
            "DATAFORGE_AIRFLOW_ATTACHED_SERVICE_ACCOUNT": expected,
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("google.auth.default", return_value=(wrong_credentials, weather_cloud.PROJECT_ID)),
            patch.object(wrong_credentials, "refresh"),
        ):
            with self.assertRaises(AirflowFailException):
                weather_cloud._authorized_credentials()

        env_with_file = {**env, "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/forbidden-adc.json"}
        with (
            patch.dict(os.environ, env_with_file, clear=True),
            patch("google.auth.default") as default_credentials,
        ):
            with self.assertRaises(AirflowFailException):
                weather_cloud._require_cloud_authorization()
        default_credentials.assert_not_called()

    def test_retryable_and_terminal_http_failures_map_to_airflow_classes(self) -> None:
        for status in (408, 429, 500, 503):
            with self.subTest(status=status), self.assertRaises(AirflowException) as raised:
                weather_cloud._raise_cloud_http_failure("test operation", status)
            self.assertIs(type(raised.exception), AirflowException)
        for status in (400, 401, 403, 404, 422):
            with self.subTest(status=status), self.assertRaises(AirflowFailException):
                weather_cloud._raise_cloud_http_failure("test operation", status)

    def test_transient_operation_poll_retries_same_operation_then_succeeds(self) -> None:
        operation_name = (
            "projects/dataforge-p7-lab-d0f725/locations/us-central1/operations/op-123"
        )
        execution_name = (
            "projects/dataforge-p7-lab-d0f725/locations/us-central1/jobs/"
            "dataforge-week7-weather-ingest/executions/ex-123"
        )
        session = Mock()
        session.post.return_value = _Response(200, {"name": operation_name})
        session.get.side_effect = [
            _Response(503, {}),
            _Response(200, {"done": True, "response": {"name": execution_name}}),
        ]
        with (
            patch.object(weather_cloud, "_authorized_session", return_value=session),
            patch.object(weather_cloud.time, "monotonic", side_effect=[0.0, 1.0, 2.0]),
            patch.object(weather_cloud.time, "sleep"),
        ):
            result = weather_cloud._execute_cloud_run_job(
                "dataforge-week7-weather-ingest", ["ingest", "--observation-date", "2026-11-06"]
            )
        self.assertEqual(result["execution_name"], execution_name)
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(session.get.call_count, 2)

    def test_cloud_run_submission_classifies_http_failures(self) -> None:
        for status, error_type in (
            (429, AirflowException),
            (503, AirflowException),
            (403, AirflowFailException),
        ):
            with self.subTest(status=status):
                session = Mock()
                session.post.return_value = _Response(status, {})
                with patch.object(weather_cloud, "_authorized_session", return_value=session):
                    with self.assertRaises(error_type):
                        weather_cloud._submit_cloud_run_job(
                            "dataforge-week7-weather-ingest",
                            ["ingest", "--observation-date", "2026-11-06"],
                        )
                session.get.assert_not_called()

    def test_transient_submission_retry_reuses_the_same_invocation_arguments(self) -> None:
        operation_name = (
            "projects/dataforge-p7-lab-d0f725/locations/us-central1/operations/op-retry"
        )
        session = Mock()
        session.post.side_effect = [
            _Response(503, {}),
            _Response(200, {"name": operation_name}),
        ]
        request = {
            "observation_date": "2026-11-06",
            "invocation_id": "a" * 64,
        }
        task = self.dag.get_task("execute_api_ingest")
        with patch.object(weather_cloud, "_authorized_session", return_value=session):
            with self.assertRaises(AirflowException):
                task.python_callable(request)
            result = task.python_callable(request)

        submitted_args = [
            call.kwargs["json"]["overrides"]["containerOverrides"][0]["args"]
            for call in session.post.call_args_list
        ]
        self.assertEqual(submitted_args[0], submitted_args[1])
        self.assertEqual(submitted_args[0][-1], request["invocation_id"])
        self.assertEqual(result, operation_name)
        session.get.assert_not_called()

    def test_reschedule_sensor_pokes_operation_execution_and_receipt(self) -> None:
        operation_name = (
            "projects/dataforge-p7-lab-d0f725/locations/us-central1/operations/op-sensor"
        )
        execution_name = (
            "projects/dataforge-p7-lab-d0f725/locations/us-central1/jobs/"
            "dataforge-week7-weather-ingest/executions/ex-sensor"
        )
        request = {
            "observation_date": "2026-11-06",
            "invocation_id": "a" * 64,
        }
        sensor = CloudRunExecutionReceiptSensor(
            task_id="test_wait_for_api_ingest",
            job_name=weather_cloud.INGEST_JOB,
            operation_name=operation_name,
            request=request,
            require_receipt=True,
            mode="reschedule",
            poke_interval=1,
            timeout=30,
            do_xcom_push=True,
        )
        session = Mock()
        operation_done = _Response(200, {"done": True, "response": {"name": execution_name}})
        session.get.side_effect = [
            _Response(200, {"done": False}),
            operation_done,
            _Response(200, {"completionStatus": "EXECUTION_RUNNING"}),
            operation_done,
            _Response(200, {"completionStatus": "EXECUTION_SUCCEEDED"}),
            _Response(404, {}),
            operation_done,
            _Response(200, {"completionStatus": "EXECUTION_SUCCEEDED"}),
            _Response(200, {"generation": "123"}),
        ]
        with patch.object(weather_cloud, "_authorized_session", return_value=session):
            self.assertFalse(sensor.poke({}))
            self.assertFalse(sensor.poke({}))
            self.assertFalse(sensor.poke({}))
            completed = sensor.poke({})

        self.assertIsInstance(completed, PokeReturnValue)
        self.assertTrue(completed.is_done)
        self.assertEqual(
            completed.xcom_value,
            {"execution_name": execution_name, "receipt_generation": 123},
        )
        self.assertEqual(session.get.call_count, 9)

    def test_reschedule_sensor_fails_fast_for_failed_execution(self) -> None:
        operation_name = (
            "projects/dataforge-p7-lab-d0f725/locations/us-central1/operations/op-failed"
        )
        execution_name = (
            "projects/dataforge-p7-lab-d0f725/locations/us-central1/jobs/"
            "dataforge-week7-weather-ingest/executions/ex-failed"
        )
        sensor = CloudRunExecutionReceiptSensor(
            task_id="test_wait_for_failed_execution",
            job_name=weather_cloud.INGEST_JOB,
            operation_name=operation_name,
            mode="reschedule",
            poke_interval=1,
            timeout=30,
        )
        session = Mock()
        session.get.side_effect = [
            _Response(200, {"done": True, "response": {"name": execution_name}}),
            _Response(200, {"completionStatus": "EXECUTION_FAILED"}),
        ]
        with patch.object(weather_cloud, "_authorized_session", return_value=session):
            with self.assertRaises(AirflowFailException):
                sensor.poke({})
        self.assertEqual(session.get.call_count, 2)

    def test_deadline_callback_emits_one_redacted_local_event(self) -> None:
        with patch.object(weather_cloud._LOGGER, "error") as logger:
            weather_cloud.local_deadline_log(
                context={
                    "dag_run": {"dag_id": DAG_ID, "run_id": "scheduled__example"},
                    "deadline": {"deadline_time": "2026-11-13T10:30:00+00:00"},
                }
            )
        logger.assert_called_once()
        payload = json.loads(logger.call_args.args[1])
        self.assertEqual(payload["event_type"], "PIPELINE_DEADLINE_MISSED")
        self.assertEqual(payload["dag_id"], DAG_ID)
        self.assertEqual(payload["workflow_run_id"], "scheduled__example")
        self.assertEqual(payload["deadline_time"], "2026-11-13T10:30:00+00:00")
        self.assertEqual(payload["event_destination"], "local_airflow_log_only")
        self.assertFalse(payload["external_notification_sent"])

    def test_terminal_job_failure_is_reported_before_receipt_read(self) -> None:
        session = Mock()
        session.post.return_value = _Response(
            200,
            {
                "name": (
                    "projects/dataforge-p7-lab-d0f725/locations/us-central1/"
                    "operations/op-failed"
                )
            },
        )
        session.get.return_value = _Response(200, {"done": True, "error": {"code": 3}})
        with patch.object(weather_cloud, "_authorized_session", return_value=session):
            with self.assertRaises(AirflowFailException):
                weather_cloud._execute_cloud_run_job(
                    "dataforge-week7-weather-ingest",
                    ["ingest", "--observation-date", "2026-11-06"],
                )
        session.get.assert_called_once()

    def test_cloud_run_poll_timeout_fails_closed_for_manual_recovery(self) -> None:
        session = Mock()
        session.post.return_value = _Response(
            200,
            {
                "name": (
                    "projects/dataforge-p7-lab-d0f725/locations/us-central1/"
                    "operations/op-stuck"
                )
            },
        )
        session.get.return_value = _Response(200, {"done": False})
        with (
            patch.object(weather_cloud, "_authorized_session", return_value=session),
            patch.object(weather_cloud, "_CLOUD_RUN_POLL_TIMEOUT_SECONDS", 10),
            patch.object(weather_cloud.time, "monotonic", side_effect=[0.0, 0.0, 10.0]),
            patch.object(weather_cloud.time, "sleep"),
        ):
            with self.assertRaises(AirflowFailException):
                weather_cloud._execute_cloud_run_job(
                    "dataforge-week7-weather-ingest",
                    ["ingest", "--observation-date", "2026-11-06"],
                )
        session.post.assert_called_once()
        session.get.assert_called_once()

    def test_failure_callback_emits_one_redacted_local_event(self) -> None:
        with patch.object(weather_cloud._LOGGER, "error") as logger:
            weather_cloud.local_failure_log(
                {
                    "task_instance": SimpleNamespace(task_id="ingest", try_number=2),
                    "dag_run": SimpleNamespace(
                        dag_id=DAG_ID,
                        run_id="manual__example",
                    ),
                    "exception": ValueError("do-not-log-this-sensitive-message"),
                }
            )
        logger.assert_called_once()
        payload = json.loads(logger.call_args.args[1])
        self.assertEqual(payload["event_type"], "PIPELINE_FAILED")
        self.assertEqual(payload["terminal_state"], "FAILED")
        self.assertEqual(payload["workflow_run_id"], "manual__example")
        self.assertEqual(payload["event_destination"], "local_airflow_log_only")
        self.assertFalse(payload["external_notification_sent"])
        self.assertNotIn("do-not-log-this-sensitive-message", logger.call_args.args[1])

    def test_integration_tasks_use_redacted_failure_hook_and_bounded_retries(self) -> None:
        for task in self.dag.tasks:
            with self.subTest(task_id=task.task_id):
                callbacks = task.on_failure_callback
                if not isinstance(callbacks, list):
                    callbacks = [callbacks]
                self.assertEqual(
                    [callback.__name__ for callback in callbacks],
                    ["local_failure_log"],
                )
        for task_id in (
            "execute_api_ingest",
            "load_bigquery_landing",
            "verify_landing_reconciliation",
            "dbt_weather_build",
            "publish_weather_gold",
        ):
            with self.subTest(task_id=task_id):
                self.assertEqual(self.dag.get_task(task_id).retries, 1)
        self.assertEqual(self.dag.get_task("resolve_cloud_request").retries, 0)
        self.assertEqual(self.dag.get_task("authorize_cloud_execution").retries, 0)
        for task_id in (
            "wait_for_api_ingest",
            "wait_for_bigquery_landing",
            "wait_for_landing_reconciliation",
            "wait_for_dbt_weather_build",
            "wait_for_publish_weather_gold",
        ):
            self.assertEqual(self.dag.get_task(task_id).retries, 0)

    def test_dbt_build_runs_weather_tests_once_before_publication(self) -> None:
        dag_source = (DAGS_DIR / "dataforge_week7_weather_cloud.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"tag:weather_mini3"', dag_source)
        self.assertEqual(
            dag_source.count('weather_dbt_vars_argument(request["observation_date"])'), 1
        )
        self.assertNotIn("dbt_weather_test", self.dag.task_ids)
        self.assertIn(
            "landing >> reconciliation_operation >> landing_reconciliation >> build_operation",
            dag_source,
        )
        self.assertIn("build >> publish_operation >> publish >> gold", dag_source)


if __name__ == "__main__":
    unittest.main()
