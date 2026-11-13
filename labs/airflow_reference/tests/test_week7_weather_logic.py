from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))

from dataforge_week7_weather_logic import (
    BRONZE_BUCKET,
    EXECUTION_RECEIPT_SCHEMA,
    PROVINCES,
    WEATHER_PREFIX,
    ContractError,
    ReceiptNotFound,
    ReceiptTimeout,
    cloud_opt_in_enabled,
    invocation_receipt_object,
    is_retryable_cloud_operation_error,
    is_retryable_http_status,
    make_invocation_id,
    resolve_request,
    validate_execution_receipt,
    wait_for_execution_receipt,
    weather_dbt_vars_argument,
)


def _receipt(invocation_id: str, observation_date: str) -> dict:
    request_id = "a" * 64
    return {
        "schema_version": EXECUTION_RECEIPT_SCHEMA,
        "status": "COMPLETE",
        "invocation_id": invocation_id,
        "observation_date": observation_date,
        "provinces": list(PROVINCES),
        "request_id": request_id,
        "manifest_uri": (
            f"gs://{BRONZE_BUCKET}/{WEATHER_PREFIX}/manifests/"
            f"observation_date={observation_date}/request_id={request_id}/manifest.json"
        ),
        "manifest_generation": 1712345678901234,
        "source_sha256": "b" * 64,
        "row_count": 3,
        "provider": "Open-Meteo",
        "model": "era5",
        "settling_lag_days": 7,
        "attribution_url": "https://open-meteo.com/",
    }


class WeatherRequestContractTests(unittest.TestCase):
    def test_dbt_partition_variable_is_canonical_json_and_rejects_bad_dates(self) -> None:
        self.assertEqual(
            weather_dbt_vars_argument("2026-11-05"),
            '{"weather_observation_date":"2026-11-05"}',
        )
        for invalid in ("2026-2-05", "tomorrow", 20261105):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ContractError, "ISO YYYY-MM-DD"
            ):
                weather_dbt_vars_argument(invalid)

    def test_scheduled_empty_params_are_valid_and_unsupported_keys_fail_closed(self) -> None:
        interval_end = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
        request = resolve_request(
            params={},
            dag_id="dataforge_week7_weather_cloud",
            run_id="scheduled__2026-11-12T09:00:00+07:00",
            logical_date=interval_end,
            data_interval_end=interval_end,
        )
        self.assertEqual(request["mode"], "scheduled")
        self.assertEqual(request["observation_date"], "2026-11-06")

        with self.assertRaisesRegex(ContractError, "unsupported keys"):
            resolve_request(
                params={"mode": "manual", "credentials": "never-allowed"},
                dag_id="dataforge_week7_weather_cloud",
                run_id="manual__offline",
                logical_date=interval_end,
                data_interval_end=interval_end,
            )

    def test_manual_date_override_uses_fixed_project_allowlist_and_stable_id(self) -> None:
        interval_end = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
        params = {"mode": "manual", "observation_date": "2026-11-05"}
        request = resolve_request(
            params=params,
            dag_id="dataforge_week7_weather_cloud",
            run_id="manual__airflow-test",
            logical_date=interval_end,
            data_interval_end=interval_end,
        )
        replay = resolve_request(
            params=params,
            dag_id="dataforge_week7_weather_cloud",
            run_id="manual__airflow-test",
            logical_date=interval_end,
            data_interval_end=interval_end,
        )
        self.assertEqual(request["project_id"], "dataforge-p7-lab-d0f725")
        self.assertEqual(request["region"], "us-central1")
        self.assertEqual(request["provinces"], list(PROVINCES))
        self.assertEqual(request["observation_date"], "2026-11-05")
        self.assertEqual(request["invocation_id"], replay["invocation_id"])
        self.assertEqual(
            request["invocation_id"],
            make_invocation_id("dataforge_week7_weather_cloud", "manual__airflow-test"),
        )
        self.assertEqual(len(request), 8)
        self.assertEqual(
            invocation_receipt_object(request["invocation_id"]),
            f"{WEATHER_PREFIX}/executions/invocation_id={request['invocation_id']}.json",
        )
        duplicate = resolve_request(
            params=params,
            dag_id="dataforge_week7_weather_cloud",
            run_id="manual__airflow-test__duplicate",
            logical_date=interval_end,
            data_interval_end=interval_end,
        )
        self.assertNotEqual(request["invocation_id"], duplicate["invocation_id"])

    def test_default_date_uses_fixed_interval_end_not_wall_clock(self) -> None:
        interval_end = datetime(2026, 11, 13, 2, tzinfo=timezone.utc)
        request = resolve_request(
            params={"mode": "scheduled"},
            dag_id="dataforge_week7_weather_cloud",
            run_id="scheduled__fixed-interval",
            logical_date=interval_end,
            data_interval_end=interval_end,
        )
        self.assertEqual(request["observation_date"], "2026-11-06")
        with self.assertRaisesRegex(ContractError, "timezone-aware"):
            resolve_request(
                params={"mode": "scheduled"},
                dag_id="dataforge_week7_weather_cloud",
                run_id="scheduled__bad-timezone",
                logical_date=datetime(2026, 11, 12, 9),
                data_interval_end=interval_end,
            )

    def test_dates_fail_closed_for_scheduled_override_new_and_noncanonical_values(self) -> None:
        interval_end = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
        for params in (
            {"mode": "scheduled", "observation_date": "2026-11-05"},
            {"mode": "invalid"},
            {"mode": []},
            {"mode": "manual", "project_id": "other-project"},
            {"mode": "manual", "bucket": "public-bucket"},
            {"mode": "manual", "observation_date": "2026-11-07"},
            {"mode": "manual", "observation_date": "2026-2-05"},
            {"mode": "manual", "observation_date": "not-a-date"},
            {"mode": "manual", "observation_date": "1939-12-31"},
        ):
            with self.subTest(params=params), self.assertRaises(ContractError):
                resolve_request(
                    params=params,
                    dag_id="dataforge_week7_weather_cloud",
                    run_id="manual__invalid-date",
                    logical_date=interval_end,
                    data_interval_end=interval_end,
                )


class RuntimeSafetyContractTests(unittest.TestCase):
    def test_cloud_authorization_defaults_off_and_rejects_ambiguous_values(self) -> None:
        for value in (None, "", "false", "FALSE"):
            with self.subTest(value=value):
                self.assertFalse(cloud_opt_in_enabled(value))
        self.assertTrue(cloud_opt_in_enabled("true"))
        with self.assertRaisesRegex(ContractError, "must be exactly"):
            cloud_opt_in_enabled("yes")

    def test_http_retry_classifier_only_retries_transient_statuses(self) -> None:
        for status in (408, 429, 500, 503, 599):
            with self.subTest(status=status):
                self.assertTrue(is_retryable_http_status(status))
        for status in (200, 400, 401, 403, 404, 422, 600):
            with self.subTest(status=status):
                self.assertFalse(is_retryable_http_status(status))
        self.assertFalse(is_retryable_http_status(True))

    def test_cloud_operation_retry_classifier_uses_only_transient_rpc_codes(self) -> None:
        for code in (4, 8, 13, 14):
            with self.subTest(code=code):
                self.assertTrue(is_retryable_cloud_operation_error({"code": code}))
        for error in ({"code": 3}, {"code": 7}, {"code": "14"}, None, "error"):
            with self.subTest(error=error):
                self.assertFalse(is_retryable_cloud_operation_error(error))

    def test_receipt_wait_handles_delayed_object_with_bounded_polls(self) -> None:
        clock = Mock(side_effect=[0, 0, 1, 1, 2])
        sleeper = Mock()
        read = Mock(side_effect=[ReceiptNotFound(), ReceiptNotFound(), {"status": "COMPLETE"}])
        result = wait_for_execution_receipt(
            read,
            timeout_seconds=5,
            poll_interval_seconds=1,
            monotonic=clock,
            sleep=sleeper,
        )
        self.assertEqual(result, {"status": "COMPLETE"})
        self.assertEqual(read.call_count, 3)
        self.assertEqual(sleeper.call_count, 2)

    def test_missing_receipt_times_out_and_unexpected_reader_errors_are_not_retried(self) -> None:
        ticks = iter([0.0, 1.0, 2.0, 3.0])
        missing = Mock(side_effect=ReceiptNotFound())
        with self.assertRaisesRegex(ReceiptTimeout, "timed out"):
            wait_for_execution_receipt(
                missing,
                timeout_seconds=2,
                poll_interval_seconds=1,
                monotonic=lambda: next(ticks),
                sleep=lambda _seconds: None,
            )

        corrupt = Mock(side_effect=ValueError("bad JSON"))
        with self.assertRaisesRegex(ValueError, "bad JSON"):
            wait_for_execution_receipt(corrupt, monotonic=lambda: 0.0, sleep=lambda _: None)
        self.assertEqual(corrupt.call_count, 1)


class InvocationReceiptTests(unittest.TestCase):
    def test_complete_receipt_is_reduced_to_small_immutable_identifiers(self) -> None:
        invocation_id = make_invocation_id("weather", "manual__receipt")
        output = validate_execution_receipt(
            _receipt(invocation_id, "2026-11-05"),
            expected_invocation_id=invocation_id,
            expected_observation_date="2026-11-05",
            object_generation=123,
        )
        self.assertEqual(
            set(output),
            {
                "invocation_id",
                "observation_date",
                "request_id",
                "source_sha256",
                "manifest_uri",
                "manifest_generation",
                "invocation_receipt_generation",
                "row_count",
            },
        )
        self.assertNotIn("raw_response", output)
        self.assertEqual(output["row_count"], 3)

    def test_receipt_rejects_wrong_invocation_date_prefix_status_and_counts(self) -> None:
        invocation_id = make_invocation_id("weather", "manual__receipt")
        base = _receipt(invocation_id, "2026-11-05")
        for field, value in (
            ("invocation_id", "0" * 64),
            ("observation_date", "2026-11-04"),
            ("status", "PARTIAL"),
            ("row_count", 4),
            ("row_count", 3.0),
            ("provinces", ["HCM", "HN", "OTHER"]),
            ("manifest_generation", -1),
            ("manifest_uri", "gs://public-bucket/manifest.json"),
            ("request_id", "not-a-digest"),
            ("source_sha256", "not-a-digest"),
        ):
            candidate = deepcopy(base)
            candidate[field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_execution_receipt(
                    candidate,
                    expected_invocation_id=invocation_id,
                    expected_observation_date="2026-11-05",
                    object_generation=123,
                )

    def test_receipt_rejects_boolean_or_missing_generations_and_non_objects(self) -> None:
        invocation_id = make_invocation_id("weather", "manual__receipt")
        for candidate, generation in ((None, 123), (_receipt(invocation_id, "2026-11-05"), True)):
            with self.subTest(candidate_type=type(candidate).__name__), self.assertRaises(ContractError):
                validate_execution_receipt(
                    candidate,
                    expected_invocation_id=invocation_id,
                    expected_observation_date="2026-11-05",
                    object_generation=generation,
                )


if __name__ == "__main__":
    unittest.main()
