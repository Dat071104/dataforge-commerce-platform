"""Show a local synthetic-only P2 erasure plan across profile and SCD2 layers."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from typing import Any

from dataforge.privacy.erasure import ErasureDrillError, plan_erasure, simulate_local_erasure


def _synthetic_fixture() -> tuple[str, dict[str, list[dict[str, Any]]]]:
    """Create in-memory row markers only; no identifier values are persisted or printed."""
    token = hmac.new(
        b"dataforge-w9-g9-local-fixture-key",
        b"synthetic-customer-token",
        hashlib.sha256,
    ).hexdigest()
    marker = {"customer_token": token, "data_classification": "synthetic"}
    return token, {
        "raw": [marker.copy()],
        "staging": [marker.copy()],
        "mart": [marker.copy()],
        "scd2_snapshot": [
            {**marker, "snapshot_version": "v1"},
            {**marker, "snapshot_version": "v2"},
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--simulate-local-delete",
        action="store_true",
        help="simulate row removal from the in-memory fixture; never calls cloud APIs",
    )
    args = parser.parse_args(argv)

    try:
        token, fixture = _synthetic_fixture()
        plan = plan_erasure(fixture, token)
        if args.simulate_local_delete:
            remaining, removed = simulate_local_erasure(fixture, token)
            plan["local_simulation"] = {
                "status": "PASS" if all(not rows for rows in remaining.values()) else "FAIL",
                "rows_removed": removed,
                "all_fixture_layers_clear": all(not rows for rows in remaining.values()),
                "cloud_mutations": False,
            }
    except ErasureDrillError as exc:
        print(f"W9_PII_ERASURE_STATUS=FAIL reason={exc}", file=sys.stderr)
        return 1
    print("W9_PII_ERASURE=" + json.dumps(plan, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
