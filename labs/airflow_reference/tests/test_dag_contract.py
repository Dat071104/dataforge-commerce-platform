from __future__ import annotations

import sys
import unittest
from pathlib import Path

REFERENCE_ROOT = Path(__file__).resolve().parents[1]
DAGS_DIR = REFERENCE_ROOT / "dags"
sys.path.insert(0, str(DAGS_DIR))

from dataforge_week7_logic import (  # noqa: E402
    FIXTURE_PATH,
    build_local_manifest,
    consume_local_silver,
    publication_fence,
    transform_local_silver,
    validate_local_transformation,
)
from dataforge_week7_reference import DAG_ID, dataforge_week7_local_reference  # noqa: E402


class DagStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dag = dataforge_week7_local_reference()

    def test_dag_has_schedule_bounds_and_ordered_pipeline_stages(self) -> None:
        self.assertEqual(self.dag.dag_id, DAG_ID)
        self.assertIsNotNone(self.dag.schedule)
        self.assertFalse(self.dag.catchup)
        self.assertEqual(self.dag.max_active_runs, 1)
        self.assertEqual(
            set(self.dag.task_ids),
            {
                "resolve_manifest",
                "consume_silver",
                "dbt_transform",
                "validate_quality",
                "publication_fence",
                "record_run_metadata",
                "recovery_alert_hook",
            },
        )

        expected_edges = {
            "resolve_manifest": set(),
            "consume_silver": {"resolve_manifest"},
            "dbt_transform": {"resolve_manifest", "consume_silver"},
            "validate_quality": {"resolve_manifest", "dbt_transform"},
            "publication_fence": {"resolve_manifest", "validate_quality"},
            "record_run_metadata": {
                "resolve_manifest",
                "consume_silver",
                "dbt_transform",
                "validate_quality",
                "publication_fence",
            },
            "recovery_alert_hook": {"record_run_metadata"},
        }
        for task_id, upstream_ids in expected_edges.items():
            with self.subTest(task_id=task_id):
                self.assertEqual(self.dag.get_task(task_id).upstream_task_ids, upstream_ids)

    def test_tasks_have_bounded_retry_timeout_and_local_failure_hook(self) -> None:
        for task in self.dag.tasks:
            with self.subTest(task_id=task.task_id):
                self.assertEqual(task.retries, 1)
                self.assertEqual(task.retry_delay.total_seconds(), 5)
                self.assertGreater(task.execution_timeout.total_seconds(), 0)
                callbacks = task.on_failure_callback
                if not isinstance(callbacks, list):
                    callbacks = [callbacks]
                self.assertEqual([callback.__name__ for callback in callbacks], ["local_failure_alert"])


class LocalContractTests(unittest.TestCase):
    def test_no_new_batch_is_successful_noop_contract_and_preserves_previous_gold(self) -> None:
        manifest = build_local_manifest(
            run_id="manual__local-test",
            logical_date="2026-11-11T06:00:00+00:00",
            conf={},
        )
        silver = consume_local_silver(manifest)
        transformed = transform_local_silver(manifest, silver)
        quality = validate_local_transformation(manifest, transformed)
        publication = publication_fence(manifest, quality)

        self.assertEqual(manifest["source_status"], "NO_NEW_BATCH")
        self.assertEqual(transformed["dbt_execution"], "NOT_RUN")
        self.assertEqual(quality["status"], "SKIPPED_NO_NEW_BATCH")
        self.assertEqual(publication["status"], "NO_NEW_BATCH_PREVIOUS_GOLD_PRESERVED")
        self.assertFalse(publication["did_publish"])
        self.assertTrue(publication["previous_publication_unchanged"])

    def test_local_fixture_uses_separate_payment_aggregation_and_never_publishes(self) -> None:
        manifest = build_local_manifest(
            run_id="manual__fixture-test",
            logical_date="2026-11-11T06:00:00+00:00",
            conf={"mode": "local_fixture"},
        )
        silver = consume_local_silver(manifest)
        transformed = transform_local_silver(manifest, silver)
        quality = validate_local_transformation(manifest, transformed)
        publication = publication_fence(manifest, quality)

        self.assertEqual(manifest["source_status"], "LOCAL_FIXTURE_READY")
        self.assertEqual(silver["status"], "LOCAL_FIXTURE_CONSUMED")
        self.assertEqual(transformed["dbt_execution"], "NOT_RUN")
        self.assertEqual(transformed["row_count"], 1)
        self.assertEqual(
            transformed["rows"][0],
            {
                "order_id": "LOCAL-W7-ORDER-0001",
                "order_is_deleted": False,
                "delivered_sales_proxy": "100.00",
                "collected_amount": "100.00",
                "collection_variance": "0.00",
                "active_payment_count": 2,
                "successful_payment_count": 2,
            },
        )
        self.assertEqual(quality["status"], "PASS")
        self.assertEqual(publication["status"], "LOCAL_FIXTURE_VALIDATED_NOT_PUBLISHED")
        self.assertFalse(publication["did_publish"])
        self.assertTrue(publication["previous_publication_unchanged"])

    def test_invalid_run_modes_and_unrecognized_configuration_fail_closed(self) -> None:
        base = {
            "run_id": "manual__bad-input",
            "logical_date": "2026-11-11T06:00:00+00:00",
        }
        for conf in (
            {"mode": "gcp"},
            {"mode": ["local_fixture"]},
            {"unexpected": True},
            {"simulate_transient_once": "yes"},
        ):
            with self.subTest(conf=conf), self.assertRaises(ValueError):
                build_local_manifest(**base, conf=conf)

    def test_fixture_mutation_between_resolution_and_consume_is_rejected(self) -> None:
        manifest = build_local_manifest(
            run_id="manual__tamper-test",
            logical_date="2026-11-11T06:00:00+00:00",
            conf={"mode": "local_fixture"},
        )
        self.assertTrue(FIXTURE_PATH.is_file())
        # The helper verifies the recorded fixture digest before it passes rows onward.
        manifest["fixture_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "changed after manifest resolution"):
            consume_local_silver(manifest)


if __name__ == "__main__":
    unittest.main()
