from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))

from dataforge_week7_weather_logic import (
    BRONZE_BUCKET,
    EXECUTION_RECEIPT_SCHEMA,
    PROVINCES,
    WEATHER_PREFIX,
    ContractError,
    invocation_receipt_object,
    make_invocation_id,
    resolve_request,
    validate_execution_receipt,
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

    def test_cloud_mode_requires_explicit_opt_in_and_rejects_extra_configuration(self) -> None:
        now = datetime(2026, 11, 12, 2, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ContractError, "cloud_integration"):
            resolve_request(
                conf={},
                dag_id="dataforge_week7_weather_cloud",
                run_id="manual__offline",
                logical_date=now,
                latest_safe_date=date(2026, 11, 5),
            )
        with self.assertRaisesRegex(ContractError, "unsupported keys"):
            resolve_request(
                conf={"mode": "cloud_integration", "credentials": "never-allowed"},
                dag_id="dataforge_week7_weather_cloud",
                run_id="manual__offline",
                logical_date=now,
                latest_safe_date=date(2026, 11, 5),
            )

    def test_safe_request_uses_fixed_project_allowlist_and_stable_path_safe_id(self) -> None:
        request = resolve_request(
            conf={"mode": "cloud_integration", "observation_date": "2026-11-05"},
            dag_id="dataforge_week7_weather_cloud",
            run_id="manual__airflow-test",
            logical_date=datetime(2026, 11, 12, 2, tzinfo=timezone.utc),
            latest_safe_date=date(2026, 11, 5),
        )
        self.assertEqual(request["project_id"], "dataforge-p7-lab-d0f725")
        self.assertEqual(request["region"], "us-central1")
        self.assertEqual(request["provinces"], list(PROVINCES))
        self.assertEqual(request["observation_date"], "2026-11-05")
        self.assertEqual(request["invocation_id"], make_invocation_id(
            "dataforge_week7_weather_cloud", "manual__airflow-test"
        ))
        self.assertEqual(len(request), 7)
        self.assertEqual(
            invocation_receipt_object(request["invocation_id"]),
            f"{WEATHER_PREFIX}/executions/invocation_id={request['invocation_id']}.json",
        )

    def test_default_date_uses_settled_logical_date_and_requires_timezone(self) -> None:
        request = resolve_request(
            conf={"mode": "cloud_integration"},
            dag_id="dataforge_week7_weather_cloud",
            run_id="scheduled__hcm",
            logical_date=datetime(2026, 11, 12, 9, tzinfo=timezone.utc),
            latest_safe_date=date(2026, 11, 5),
        )
        self.assertEqual(request["observation_date"], "2026-11-05")
        with self.assertRaisesRegex(ContractError, "timezone-aware"):
            resolve_request(
                conf={"mode": "cloud_integration"},
                dag_id="dataforge_week7_weather_cloud",
                run_id="scheduled__bad-timezone",
                logical_date=datetime(2026, 11, 12, 9),
                latest_safe_date=date(2026, 11, 5),
            )

    def test_date_validation_fails_closed_for_new_or_noncanonical_dates(self) -> None:
        for raw_date in ("2026-11-06", "2026-2-05", "not-a-date", "1939-12-31"):
            with self.subTest(raw_date=raw_date), self.assertRaises(ContractError):
                resolve_request(
                    conf={"mode": "cloud_integration", "observation_date": raw_date},
                    dag_id="dataforge_week7_weather_cloud",
                    run_id="manual__invalid-date",
                    logical_date=datetime(2026, 11, 12, 2, tzinfo=timezone.utc),
                    latest_safe_date=date(2026, 11, 5),
                )


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
