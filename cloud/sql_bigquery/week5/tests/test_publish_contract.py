"""Offline contract checks for the BigQuery Week-5 SQL templates."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (ROOT / "001_schema.sql").read_text(encoding="utf-8")
PUBLISH = (ROOT / "publish.sql").read_text(encoding="utf-8")


class Week5SqlContractTests(unittest.TestCase):
    def test_single_staging_identifier_placeholder_and_parameter_contract(self) -> None:
        self.assertEqual(PUBLISH.count("{{STAGING_TABLE_ID}}"), 1)
        expected = {
            "run_id",
            "execution_id",
            "batch_id",
            "run_mode",
            "source_run_id",
            "attempt",
            "manifest_uri",
            "lower_seq",
            "upper_seq",
            "row_value_sha256",
            "manifest_sha256",
            "manifest_generation",
            "object_sha256",
            "object_generation",
            "expected_row_count",
            "stage_table_id",
            "stage_load_job_id",
            "stage_verify_job_id",
            "publish_job_id",
            "published_check_job_id",
            "fail_after_merge_once",
            "fail_before_publish",
        }
        declared = set(re.findall(r"DECLARE p_\w+ \w+ DEFAULT @(\w+);", PUBLISH))
        self.assertEqual(declared, expected)

    def test_stage_validation_fails_closed_before_dml(self) -> None:
        validation_end = PUBLISH.index("CREATE TEMP TABLE latest_events")
        preflight = PUBLISH[:validation_end]
        self.assertIn("COUNT(DISTINCT change_seq)", preflight)
        self.assertIn("COUNT(DISTINCT change_id)", preflight)
        self.assertIn("change_seq < p_lower_seq OR change_seq > p_upper_seq", preflight)
        self.assertNotIn("p_upper_seq - p_lower_seq + 1", PUBLISH)
        self.assertIn("SAFE.PARSE_JSON(payload)", preflight)
        self.assertIn("SHA256(CAST(payload AS BYTES))", preflight)
        self.assertIn("schema_version != '1'", preflight)
        self.assertNotIn("EXECUTE IMMEDIATE", PUBLISH)

    def test_latest_event_per_key_is_ordered_by_journal_sequence(self) -> None:
        self.assertRegex(
            PUBLISH,
            r"PARTITION BY source_table, business_key\s+ORDER BY change_seq DESC",
        )
        self.assertEqual(PUBLISH.count("MERGE silver.week5_"), 2)
        self.assertIn("source.change_seq > target.effective_seq", PUBLISH)
        self.assertIn("source.operation = 'D'", PUBLISH)

    def test_publish_mutations_share_one_transaction_and_failure_rolls_back(self) -> None:
        begin = PUBLISH.index("BEGIN TRANSACTION")
        orders_merge = PUBLISH.index("MERGE silver.week5_orders")
        payments_merge = PUBLISH.index("MERGE silver.week5_payment_events")
        failure_injection = PUBLISH.index("IF v_should_fail_after_merge THEN")
        gold_merge = PUBLISH.index("MERGE gold.week5_order_controls")
        checkpoint = PUBLISH.index("UPDATE ops.pipeline_checkpoints")
        published_event = PUBLISH.index("'PUBLISHED', p_run_mode")
        commit = PUBLISH.index("COMMIT TRANSACTION")
        self.assertLess(begin, orders_merge)
        self.assertLess(orders_merge, payments_merge)
        self.assertLess(payments_merge, failure_injection)
        self.assertLess(failure_injection, gold_merge)
        self.assertLess(gold_merge, checkpoint)
        self.assertLess(checkpoint, published_event)
        self.assertLess(published_event, commit)
        exception_start = PUBLISH.index("EXCEPTION WHEN ERROR THEN")
        rollback = PUBLISH.index("ROLLBACK TRANSACTION", exception_start)
        failed_event = PUBLISH.index("'FAILED', p_run_mode", exception_start)
        rethrow = PUBLISH.index("RAISE;", exception_start)
        self.assertLess(rollback, failed_event)
        self.assertLess(failed_event, rethrow)

    def test_published_replay_is_noop_and_returns_expected_status(self) -> None:
        self.assertIn("FROM ops.week5_run_events", PUBLISH)
        self.assertIn("status = 'PUBLISHED'", PUBLISH)
        self.assertIn("'NO_OP' AS publication_status", PUBLISH)
        self.assertIn("'PUBLISHED' AS publication_status", PUBLISH)
        self.assertIn("LOWER(TO_HEX(SHA256(CAST(CONCAT(", PUBLISH)

    def test_schema_covers_ops_silver_gold_grains_and_numeric_controls(self) -> None:
        for table_name in (
            "ops.pipeline_checkpoints",
            "ops.writer_locks",
            "ops.week5_run_events",
            "silver.week5_orders",
            "silver.week5_payment_events",
            "gold.week5_order_controls",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table_name}", SCHEMA)
        self.assertIn("status STRING NOT NULL", SCHEMA)
        self.assertIn("order_net_amount NUMERIC(18, 2)", SCHEMA)
        self.assertIn("amount NUMERIC(18, 2)", SCHEMA)
        self.assertIn("delivered_sales_proxy NUMERIC", SCHEMA)
        self.assertIn("collection_variance NUMERIC", SCHEMA)
        self.assertIn("is_deleted BOOL NOT NULL", SCHEMA)


if __name__ == "__main__":
    unittest.main()
