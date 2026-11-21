"""Plan and locally model a synthetic-only personal-data erasure drill."""

from __future__ import annotations

import re
from typing import Any

ERASURE_RELATIONS = {
    "raw": "restricted_pii.customer_profile",
    "staging": "restricted_pii.customer_profile_restricted",
    "mart": "pii_safe.dim_customer_profile_safe",
    "scd2_snapshot": "restricted_pii.customer_profile_history",
}
BIGQUERY_TIME_TRAVEL_DEFAULT_DAYS = 7
BIGQUERY_TIME_TRAVEL_MIN_DAYS = 2
BIGQUERY_TIME_TRAVEL_MAX_DAYS = 7
BIGQUERY_FAIL_SAFE_DAYS = 7


class ErasureDrillError(RuntimeError):
    """Raised when the synthetic erasure fixture does not meet the drill contract."""


def _validate_fixture(
    rows_by_layer: dict[str, list[dict[str, Any]]], customer_token: str
) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", customer_token):
        raise ErasureDrillError("subject token must be a 64-character lowercase HMAC-shaped value")
    if set(rows_by_layer) != set(ERASURE_RELATIONS):
        raise ErasureDrillError("fixture must contain exactly raw, staging, mart, and snapshot layers")
    for layer, rows in rows_by_layer.items():
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or "customer_token" not in row for row in rows
        ):
            raise ErasureDrillError(f"synthetic erasure fixture is malformed for {layer}")


def plan_erasure(
    rows_by_layer: dict[str, list[dict[str, Any]]], customer_token: str
) -> dict[str, Any]:
    """Return sanitized per-layer counts and actions; never mutates input rows."""
    _validate_fixture(rows_by_layer, customer_token)
    actions = {
        "raw": "delete the matching raw profile row",
        "staging": "re-evaluate the source-backed view and verify it returns no row",
        "mart": "delete the matching minimized customer row",
        "scd2_snapshot": "delete every historical version for the subject token",
    }
    layers = []
    for layer, relation in ERASURE_RELATIONS.items():
        matching_rows = sum(row["customer_token"] == customer_token for row in rows_by_layer[layer])
        layers.append(
            {
                "layer": layer,
                "relation": relation,
                "matching_rows": matching_rows,
                "action": actions[layer],
            }
        )
    return {
        "check_id": "G9-P2-ERASURE-PLAN-001",
        "status": "DRY_RUN_ONLY",
        "layers": layers,
        "subject_token_emitted": False,
        "cloud_mutations": False,
        "physical_erasure_claimed": False,
        "time_travel": {
            "default_days": BIGQUERY_TIME_TRAVEL_DEFAULT_DAYS,
            "configurable_min_days": BIGQUERY_TIME_TRAVEL_MIN_DAYS,
            "configurable_max_days": BIGQUERY_TIME_TRAVEL_MAX_DAYS,
            "fail_safe_days_after_time_travel": BIGQUERY_FAIL_SAFE_DAYS,
        },
        "crypto_shredding": (
            "Not implemented: the shared HMAC key pseudonymizes identifiers but does not encrypt raw fields. "
            "Deleting that shared key would break joins for every subject and would not purge BigQuery history."
        ),
    }


def simulate_local_erasure(
    rows_by_layer: dict[str, list[dict[str, Any]]], customer_token: str
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """Remove only matching rows from in-memory synthetic fixtures."""
    _validate_fixture(rows_by_layer, customer_token)
    remaining: dict[str, list[dict[str, Any]]] = {}
    removed: dict[str, int] = {}
    for layer, rows in rows_by_layer.items():
        remaining[layer] = [row for row in rows if row["customer_token"] != customer_token]
        removed[layer] = len(rows) - len(remaining[layer])
    return remaining, removed
