"""Pure local helpers for the Week-7 Airflow orchestration reference.

These helpers deliberately operate on a checked-in synthetic fixture. They do
not import Airflow, read credentials, access the network, or write publication
state, so they can be unit-tested independently of an Airflow installation.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "silver_snapshot.json"
FIXTURE_NAME = "week7-silver-snapshot-v1"
ALLOWED_MODES = {"no_new_batch", "local_fixture"}


def build_local_manifest(
    *, run_id: str, logical_date: str, conf: Mapping[str, Any], fixture_path: Path = FIXTURE_PATH
) -> dict[str, Any]:
    """Resolve the default no-op or a deliberately local fixture manifest."""
    if not isinstance(conf, Mapping):
        raise ValueError("DAG run configuration must be a JSON object")

    unknown_keys = set(conf) - {"mode", "simulate_transient_once"}
    if unknown_keys:
        raise ValueError("DAG run configuration contains unsupported keys")

    mode = conf.get("mode", "no_new_batch")
    if not isinstance(mode, str) or mode not in ALLOWED_MODES:
        raise ValueError("mode must be 'no_new_batch' or 'local_fixture'")
    if "simulate_transient_once" in conf and not isinstance(conf["simulate_transient_once"], bool):
        raise ValueError("simulate_transient_once must be a JSON boolean")

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "logical_date": logical_date,
        "source_status": "NO_NEW_BATCH",
        "batch_id": None,
        "manifest_generation": None,
        "source_high_watermark": None,
        "fixture_sha256": None,
        "fixture_name": None,
    }
    if mode == "no_new_batch":
        return manifest

    try:
        fixture_bytes = fixture_path.read_bytes()
        fixture = json.loads(fixture_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("local Silver fixture is missing or invalid") from exc

    if not isinstance(fixture, dict) or fixture.get("fixture_name") != FIXTURE_NAME:
        raise ValueError("local Silver fixture does not match the declared contract")

    fixture_sha256 = hashlib.sha256(fixture_bytes).hexdigest()
    batch_seed = f"{FIXTURE_NAME}|{fixture_sha256}".encode("utf-8")
    return {
        **manifest,
        "source_status": "LOCAL_FIXTURE_READY",
        "batch_id": hashlib.sha256(batch_seed).hexdigest(),
        "manifest_generation": 1,
        "source_high_watermark": int(fixture["source_high_watermark"]),
        "fixture_sha256": fixture_sha256,
        "fixture_name": FIXTURE_NAME,
    }


def consume_local_silver(
    manifest: Mapping[str, Any], *, fixture_path: Path = FIXTURE_PATH
) -> dict[str, Any]:
    """Read the immutable local Silver fixture without mutating a source."""
    if manifest.get("source_status") == "NO_NEW_BATCH":
        return {
            "status": "NO_NEW_BATCH",
            "fixture_name": None,
            "source_high_watermark": None,
            "orders": [],
            "payment_events": [],
        }
    if manifest.get("source_status") != "LOCAL_FIXTURE_READY":
        raise ValueError("manifest status is not supported by the local reference")

    try:
        fixture_bytes = fixture_path.read_bytes()
        actual_sha256 = hashlib.sha256(fixture_bytes).hexdigest()
        fixture = json.loads(fixture_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("local Silver fixture is missing or invalid") from exc

    if actual_sha256 != manifest.get("fixture_sha256"):
        raise ValueError("local Silver fixture changed after manifest resolution")
    if fixture.get("fixture_name") != manifest.get("fixture_name"):
        raise ValueError("local Silver fixture identity changed after manifest resolution")

    orders = fixture.get("orders")
    payment_events = fixture.get("payment_events")
    if not isinstance(orders, list) or not isinstance(payment_events, list):
        raise ValueError("local Silver fixture must contain orders and payment_events arrays")
    return {
        "status": "LOCAL_FIXTURE_CONSUMED",
        "fixture_name": fixture["fixture_name"],
        "source_high_watermark": fixture["source_high_watermark"],
        "orders": orders,
        "payment_events": payment_events,
    }


def transform_local_silver(
    manifest: Mapping[str, Any], silver_snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    """Calculate a tiny order-grain control from fixture rows, with separate fact aggregation."""
    if manifest.get("source_status") == "NO_NEW_BATCH":
        return {
            "status": "SKIPPED_NO_NEW_BATCH",
            "dbt_execution": "NOT_RUN",
            "model_name": "dbt_week7.fct_week7_order_reconciliation",
            "row_count": 0,
            "rows": [],
        }
    if silver_snapshot.get("status") != "LOCAL_FIXTURE_CONSUMED":
        raise ValueError("dbt reference stage requires a consumed local Silver fixture")

    orders = silver_snapshot["orders"]
    payments = silver_snapshot["payment_events"]
    if not isinstance(orders, list) or not isinstance(payments, list):
        raise ValueError("local Silver rows must be arrays")

    # Keep the two grains separate: aggregate payments first, then reconcile
    # their order-level totals to each unique order, mirroring the local contract.
    payments_by_order: dict[str, list[Mapping[str, Any]]] = {}
    for payment in payments:
        if not isinstance(payment, Mapping) or not isinstance(payment.get("order_id"), str):
            raise ValueError("local payment row is missing its order key")
        payments_by_order.setdefault(payment["order_id"], []).append(payment)

    output_rows: list[dict[str, Any]] = []
    for order in orders:
        if not isinstance(order, Mapping) or not isinstance(order.get("order_id"), str):
            raise ValueError("local order row is missing its order key")
        order_id = order["order_id"]
        if not isinstance(order.get("is_deleted"), bool):
            raise ValueError("local order tombstone flag must be boolean")
        deleted = order["is_deleted"]
        try:
            order_amount = Decimal(str(order["order_net_amount"]))
        except (KeyError, InvalidOperation) as exc:
            raise ValueError("local order amount is invalid") from exc
        delivered_sales_proxy = (
            order_amount if not deleted and order.get("order_status") == "delivered" else Decimal("0.00")
        )
        active_payments = [p for p in payments_by_order.get(order_id, []) if not p.get("is_deleted")]
        successful_payments = [p for p in active_payments if p.get("payment_status") == "success"]
        try:
            collected_amount = sum(
                (Decimal(str(payment["amount"])) for payment in successful_payments), Decimal("0.00")
            )
        except (KeyError, InvalidOperation) as exc:
            raise ValueError("local payment amount is invalid") from exc

        output_rows.append(
            {
                "order_id": order_id,
                "order_is_deleted": deleted,
                "delivered_sales_proxy": format(delivered_sales_proxy, ".2f"),
                "collected_amount": format(collected_amount, ".2f"),
                "collection_variance": (
                    format(collected_amount - delivered_sales_proxy, ".2f") if not deleted else None
                ),
                "active_payment_count": len(active_payments),
                "successful_payment_count": len(successful_payments),
            }
        )

    return {
        "status": "LOCAL_REFERENCE_ONLY",
        "dbt_execution": "NOT_RUN",
        "model_name": "dbt_week7.fct_week7_order_reconciliation",
        "row_count": len(output_rows),
        "rows": output_rows,
    }


def validate_local_transformation(
    manifest: Mapping[str, Any], transformed: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply a bounded order-grain and exact Decimal check to the local fixture result."""
    if manifest.get("source_status") == "NO_NEW_BATCH":
        return {
            "status": "SKIPPED_NO_NEW_BATCH",
            "checks": {},
            "row_count": 0,
            "publish_allowed": False,
        }
    rows = transformed.get("rows")
    if transformed.get("status") != "LOCAL_REFERENCE_ONLY" or not isinstance(rows, list):
        raise ValueError("local transformation result does not match the expected contract")

    order_ids = [row.get("order_id") for row in rows if isinstance(row, Mapping)]
    unique_order_grain = len(order_ids) == len(rows) and len(set(order_ids)) == len(rows)
    variance_reconciles = True
    for row in rows:
        if not isinstance(row, Mapping):
            variance_reconciles = False
            continue
        if row.get("order_is_deleted"):
            variance_reconciles = variance_reconciles and row.get("collection_variance") is None
            continue
        try:
            variance_reconciles = variance_reconciles and Decimal(
                str(row["collection_variance"])
            ) == Decimal(str(row["collected_amount"])) - Decimal(
                str(row["delivered_sales_proxy"])
            )
        except (KeyError, InvalidOperation):
            variance_reconciles = False

    checks = {
        "unique_order_grain": unique_order_grain,
        "decimal_collection_reconciliation": variance_reconciles,
        "row_count_matches_transform": transformed.get("row_count") == len(rows),
    }
    passed = bool(rows) and all(checks.values())
    return {
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "row_count": len(rows),
        "publish_allowed": passed,
    }


def publication_fence(
    manifest: Mapping[str, Any], quality: Mapping[str, Any]
) -> dict[str, Any]:
    """Describe the publication decision; this local DAG never writes a Gold pointer."""
    if manifest.get("source_status") == "NO_NEW_BATCH":
        return {
            "status": "NO_NEW_BATCH_PREVIOUS_GOLD_PRESERVED",
            "did_publish": False,
            "previous_publication_unchanged": True,
        }
    if quality.get("status") != "PASS" or quality.get("publish_allowed") is not True:
        return {
            "status": "QUALITY_BLOCKED_PREVIOUS_GOLD_PRESERVED",
            "did_publish": False,
            "previous_publication_unchanged": True,
        }
    return {
        "status": "LOCAL_FIXTURE_VALIDATED_NOT_PUBLISHED",
        "did_publish": False,
        "previous_publication_unchanged": True,
    }
