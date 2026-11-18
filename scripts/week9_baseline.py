"""Summarize Week 9 baseline coverage from a dbt manifest.

Run from the repository root after `dbt parse --target offline`.
This uses only the standard library and does not connect to BigQuery.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MANIFEST = Path("dbt/dataforge/target/manifest.json")
GRAIN_UNIQUENESS_TESTS = {
    "assert_mart_weather_province_daily_grain_unique",
    "assert_mini3_weather_grains_unique",
    "assert_mini3_weather_landing_request_keys",
}


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percent": round(100 * numerator / denominator, 1) if denominator else None,
    }


def main() -> int:
    if not MANIFEST.is_file():
        raise SystemExit(
            f"Manifest not found: {MANIFEST}. Run dbt parse --target offline first."
        )

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    nodes: dict[str, dict[str, Any]] = manifest.get("nodes", {})
    models = {
        unique_id: node
        for unique_id, node in nodes.items()
        if node.get("resource_type") == "model"
    }
    tests = [
        node for node in nodes.values() if node.get("resource_type") == "test"
    ]
    sources = list(manifest.get("sources", {}).values())
    unit_tests = manifest.get("unit_tests", {})

    model_ids_with_grain_check: set[str] = set()
    singular_test_count = 0
    for test in tests:
        metadata = test.get("test_metadata") or {}
        name = metadata.get("name", test.get("name", ""))
        if not metadata:
            singular_test_count += 1
        if name not in {"unique", "unique_combination_of_columns"} | GRAIN_UNIQUENESS_TESTS:
            continue
        for dependency in test.get("depends_on", {}).get("nodes", []):
            if dependency in models:
                model_ids_with_grain_check.add(dependency)

    described_models = sum(
        bool((model.get("description") or "").strip()) for model in models.values()
    )
    gold_models = [
        model for model in models.values() if "gold" in set(model.get("tags", []))
    ]
    gold_columns = [
        column
        for model in gold_models
        for column in model.get("columns", {}).values()
    ]
    documented_gold_columns = sum(
        bool((column.get("description") or "").strip()) for column in gold_columns
    )
    fault_fixture_dir = Path("tests/week9/faults")
    fault_fixture_files = (
        sorted(
            path.name
            for path in fault_fixture_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".json", ".yaml", ".yml"}
        )
        if fault_fixture_dir.is_dir()
        else []
    )

    result = {
        "models": len(models),
        "models_with_pk_or_grain_uniqueness_check": _ratio(
            len(model_ids_with_grain_check), len(models)
        ),
        "models_with_description": _ratio(described_models, len(models)),
        "gold_columns_with_description": _ratio(
            documented_gold_columns, len(gold_columns)
        ),
        "sources_with_freshness": _ratio(
            sum(bool(source.get("freshness")) for source in sources), len(sources)
        ),
        "dbt_test_nodes": len(tests),
        "singular_dbt_tests": singular_test_count,
        "dbt_unit_tests": len(unit_tests),
        "week9_fault_fixture_files": fault_fixture_files,
        "week9_fault_fixture_count": len(fault_fixture_files),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
