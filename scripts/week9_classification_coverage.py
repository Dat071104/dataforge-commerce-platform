"""Validate source/model column-classification metadata and Gold coverage."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from dataforge.settings import ROOT

SOURCE_FILE = ROOT / "dbt" / "dataforge" / "models" / "sources.yml"
MODEL_SCHEMA_FILE = ROOT / "dbt" / "dataforge" / "models" / "schema.yml"
WEATHER_SCHEMA_FILE = ROOT / "dbt" / "dataforge" / "models" / "weather" / "marts" / "schema.yml"
PII_SCHEMA_FILE = ROOT / "dbt" / "dataforge" / "models" / "pii" / "marts" / "schema.yml"
RESTRICTED_PII_SCHEMA_FILE = ROOT / "dbt" / "dataforge" / "models" / "pii" / "restricted" / "schema.yml"
CLASSIFICATION_FILE = ROOT / "governance" / "classification.yml"
REQUIRED_META = {"classification", "pii_type", "purpose", "retention_days"}
ALLOWED_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
GOLD_MODELS = {
    "fct_week7_order_reconciliation",
    "fct_week7_build_receipt",
    "fct_mini3_weather_daily",
    "mart_weather_province_daily",
    "dim_customer_profile_safe",
}


class ClassificationError(RuntimeError):
    """Raised when column-level metadata is missing or inconsistent."""


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ClassificationError(f"Could not parse classification document: {path.name}") from exc
    if not isinstance(value, dict):
        raise ClassificationError(f"Expected a YAML mapping in {path.name}")
    return value


def _columns_by_name(columns: list[dict[str, Any]], owner: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for column in columns:
        name = column.get("name")
        meta = column.get("meta")
        if not isinstance(name, str) or not isinstance(meta, dict) or set(meta) != REQUIRED_META:
            raise ClassificationError(f"Column metadata is incomplete for {owner}.{name}")
        if (
            meta["classification"] not in ALLOWED_CLASSIFICATIONS
            or not isinstance(meta["pii_type"], str)
            or not isinstance(meta["purpose"], str)
            or not meta["purpose"].strip()
            or not isinstance(meta["retention_days"], int)
            or meta["retention_days"] < 1
        ):
            raise ClassificationError(f"Column metadata is invalid for {owner}.{name}")
        if name in result:
            raise ClassificationError(f"Duplicate column classification for {owner}.{name}")
        result[name] = meta
    return result


def _sources(document: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    found: dict[str, dict[str, dict[str, Any]]] = {}
    for source in document.get("sources", []):
        for table in source.get("tables", []):
            key = f"{source['name']}.{table['name']}"
            found[key] = _columns_by_name(table.get("columns", []), key)
    return found


def _models(documents: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    found: dict[str, dict[str, dict[str, Any]]] = {}
    for document in documents:
        for model in document.get("models", []):
            name = model["name"]
            if name in found:
                raise ClassificationError(f"Duplicate model classification block: {name}")
            found[name] = _columns_by_name(model.get("columns", []), name)
    return found


def _snapshots(document: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        snapshot["name"]: _columns_by_name(snapshot.get("columns", []), snapshot["name"])
        for snapshot in document.get("snapshots", [])
    }


def _compare_registry(
    kind: str,
    discovered: dict[str, dict[str, dict[str, Any]]],
    registry: dict[str, dict[str, dict[str, Any]]],
) -> None:
    if set(discovered) != set(registry):
        missing = sorted(set(discovered) - set(registry))
        extra = sorted(set(registry) - set(discovered))
        raise ClassificationError(f"{kind} registry keys differ (missing={missing}, extra={extra})")
    for owner, columns in discovered.items():
        if set(columns) != set(registry[owner]):
            missing = sorted(set(columns) - set(registry[owner]))
            extra = sorted(set(registry[owner]) - set(columns))
            raise ClassificationError(
                f"{kind} columns differ for {owner} (missing={missing}, extra={extra})"
            )
        for column, meta in columns.items():
            if meta != registry[owner][column]:
                raise ClassificationError(f"{kind} metadata differs for {owner}.{column}")


def validate_classification() -> dict[str, Any]:
    source_doc = _read_yaml(SOURCE_FILE)
    model_doc = _read_yaml(MODEL_SCHEMA_FILE)
    weather_doc = _read_yaml(WEATHER_SCHEMA_FILE)
    pii_doc = _read_yaml(PII_SCHEMA_FILE)
    restricted_pii_doc = _read_yaml(RESTRICTED_PII_SCHEMA_FILE)
    registry = _read_yaml(CLASSIFICATION_FILE)
    source_columns = _sources(source_doc)
    model_columns = _models([model_doc, weather_doc, pii_doc, restricted_pii_doc])
    snapshot_columns = _snapshots(model_doc)
    _compare_registry("source", source_columns, registry.get("sources", {}))
    _compare_registry("model", model_columns, registry.get("models", {}))
    _compare_registry("snapshot", snapshot_columns, registry.get("snapshots", {}))

    gold_columns = [
        column
        for name, columns in model_columns.items()
        if name in GOLD_MODELS
        for column in columns.values()
    ]
    classified_gold = sum(bool(column) for column in gold_columns)
    coverage = 100.0 if not gold_columns else 100.0 * classified_gold / len(gold_columns)
    if classified_gold != len(gold_columns):
        raise ClassificationError("Gold column classification coverage is below 100 percent")
    return {
        "status": "PASS",
        "source_tables": len(source_columns),
        "source_columns": sum(len(columns) for columns in source_columns.values()),
        "models": len(model_columns),
        "model_columns": sum(len(columns) for columns in model_columns.values()),
        "snapshots": len(snapshot_columns),
        "snapshot_columns": sum(len(columns) for columns in snapshot_columns.values()),
        "total_columns": sum(len(columns) for _, columns in [*source_columns.items(), *model_columns.items(), *snapshot_columns.items()]),
        "gold_columns": len(gold_columns),
        "gold_meta_complete": classified_gold,
        "gold_coverage_percent": coverage,
    }


def main() -> int:
    try:
        result = validate_classification()
    except ClassificationError as exc:
        print(f"CLASSIFICATION_STATUS=FAIL reason={exc}", file=sys.stderr)
        return 1
    print("CLASSIFICATION_STATUS=" + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
