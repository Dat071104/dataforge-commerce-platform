from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_CONFIG = REPO_ROOT / "dbt" / "dataforge" / "models" / "week9_tests.yml"
PK_TEST_MACROS = REPO_ROOT / "dbt" / "dataforge" / "macros" / "dq_pk_tests.sql"
EXPECTED_KEYS = {
    "stg_week5_run_events": "event_id",
    "stg_week5_pipeline_checkpoints": "source_id",
}


def test_required_model_primary_keys_have_blocking_tests_with_env_gated_storage():
    document = yaml.safe_load(TEST_CONFIG.read_text(encoding="utf-8"))
    models = {model["name"]: model for model in document["models"]}
    for model_name, column_name in EXPECTED_KEYS.items():
        model = models[model_name]
        column = next(item for item in model["columns"] if item["name"] == column_name)
        tests = {next(iter(test)): next(iter(test.values())) for test in column["data_tests"]}
        assert set(tests) == {"dq_week9_not_null", "dq_week9_unique"}
        for test_name, test in tests.items():
            config = test["config"]
            assert config["tags"] == ["tier_blocking"]
            assert config["severity"] == "error"
            assert config["error_if"] == ">0"
            assert "store_failures" not in config
            assert config["schema"] == "dataforge_dq"
            metadata = config["meta"]
            assert metadata["layer"] == "G2"
            assert metadata["w9_severity"] == "P1"
            assert metadata["check_id"].endswith(
                f"{column_name.upper()}_{'NOT_NULL' if test_name.endswith('not_null') else 'UNIQUE'}"
            )
    macro_source = PK_TEST_MACROS.read_text(encoding="utf-8")
    assert macro_source.count("DATAFORGE_DQ_RESULTS_ENABLED") == 2
    assert macro_source.count("env_var('DATAFORGE_DQ_RESULTS_ENABLED', 'false')") == 2
