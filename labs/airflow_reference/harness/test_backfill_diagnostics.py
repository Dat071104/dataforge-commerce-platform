import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from run_scheduler_harness import (
    _backfill_failure_diagnostics,
    _backfill_poll_should_stop,
    _redact_task_log_line,
    _task_instances_for_runs,
    _task_log_excerpt,
)


class BackfillDiagnosticTests(unittest.TestCase):
    def test_poll_stops_on_failure_and_requires_five_successes(self) -> None:
        success_runs = [
            {"run_id": f"backfill__{day}", "run_type": "backfill", "state": "success"}
            for day in range(5)
        ]
        self.assertFalse(_backfill_poll_should_stop(success_runs[:4]))
        self.assertTrue(_backfill_poll_should_stop(success_runs))
        self.assertTrue(
            _backfill_poll_should_stop(
                [
                    {
                        "run_id": "backfill__failed",
                        "run_type": "backfill",
                        "state": "failed",
                    }
                ]
            )
        )
        self.assertTrue(_backfill_poll_should_stop(success_runs + success_runs[:1]))

    def test_failure_diagnostics_include_task_state_and_redacted_log_excerpt(self) -> None:
        run_id = "backfill__test-run"
        failed_runs = [
            {
                "run_id": run_id,
                "run_type": "backfill",
                "state": "failed",
                "logical_date": "2026-11-02 02:00:00.000000",
            }
        ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "airflow.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "CREATE TABLE task_instance "
                    "(dag_id TEXT, run_id TEXT, task_id TEXT, state TEXT, "
                    "try_number INTEGER, working_set INTEGER)"
                )
                connection.executemany(
                    "INSERT INTO task_instance VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            "dataforge_week7_weather_cloud",
                            run_id,
                            "resolve_cloud_request",
                            "success",
                            1,
                            1,
                        ),
                        (
                            "dataforge_week7_weather_cloud",
                            run_id,
                            "execute_api_ingest",
                            "failed",
                            1,
                            1,
                        ),
                        (
                            "dataforge_week7_weather_cloud",
                            "backfill__unrelated",
                            "execute_api_ingest",
                            "failed",
                            1,
                            1,
                        ),
                    ],
                )
                connection.commit()

            task_log = (
                root
                / "logs"
                / "dag_id=dataforge_week7_weather_cloud"
                / f"run_id={run_id}"
                / "task_id=execute_api_ingest"
                / "attempt=1.log"
            )
            task_log.parent.mkdir(parents=True)
            task_log.write_text(
                "Traceback (most recent call last):\n"
                "RuntimeError: password=private-value token: secret-value "
                "contact=user@example.com\n",
                encoding="utf-8",
            )

            instances = _task_instances_for_runs(database, [run_id])
            self.assertEqual(
                [row["task_id"] for row in instances],
                ["execute_api_ingest", "resolve_cloud_request"],
            )

            excerpt = _task_log_excerpt(root, run_id, "execute_api_ingest")
            self.assertIn("RuntimeError", excerpt)
            self.assertIn("<redacted>", excerpt)
            self.assertIn("<redacted-email>", excerpt)
            self.assertNotIn("private-value", excerpt)
            self.assertNotIn("secret-value", excerpt)
            self.assertNotIn("user@example.com", excerpt)

            authorization_line = _redact_task_log_line(
                "Authorization: Bearer abc.SECRET123"
            )
            self.assertNotIn("abc.SECRET123", authorization_line)
            self.assertIn("Authorization: <redacted>", authorization_line)

            cookie_line = _redact_task_log_line(
                "cookie: sessionid=abc; other=secret"
            )
            self.assertNotIn("sessionid=abc", cookie_line)
            self.assertNotIn("other=secret", cookie_line)

            json_values = {
                "password": "json-password-value",
                "secret": "json-secret-value",
                "token": "json-token-value",
                "api_key": "json-api-key-value",
                "authorization": "Bearer json-authorization-value",
                "cookie": "json-cookie-value",
                "email": "json-user@example.com",
            }
            json_line = "{" + ",".join(
                f'"{key}": "{value}"' for key, value in json_values.items()
            ) + "}"
            redacted_json = _redact_task_log_line(json_line)
            for value in json_values.values():
                self.assertNotIn(value, redacted_json)

            escaped_json = (
                r'payload="{\"password\":\"escaped-password-value\",'
                r'\"api_key\":\"escaped-api-key-value\"}"'
            )
            redacted_escaped_json = _redact_task_log_line(escaped_json)
            self.assertNotIn("escaped-password-value", redacted_escaped_json)
            self.assertNotIn("escaped-api-key-value", redacted_escaped_json)

            diagnostics = _backfill_failure_diagnostics(database, root, failed_runs)
            self.assertEqual(diagnostics["failed_runs"], failed_runs)
            self.assertEqual(len(diagnostics["task_instances"]), 2)
            self.assertEqual(len(diagnostics["task_log_excerpts"]), 1)
            self.assertIn(
                "<redacted-email>", diagnostics["task_log_excerpts"][0]["excerpt"]
            )


if __name__ == "__main__":
    unittest.main()
