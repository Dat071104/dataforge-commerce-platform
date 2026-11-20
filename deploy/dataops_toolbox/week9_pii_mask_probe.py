"""Verify that the WIF CI identity receives only masked synthetic PII."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from run_cost_guard import RunCostGuardError, guard_usage_records

EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
RAW_TABLE = "restricted_pii.customer_profile"
MAXIMUM_BYTES_BILLED = 1024**3
MAX_RUN_BYTES_BILLED = 5 * 1024**3
POLICY_FIELDS = {"full_name", "cccd", "email", "phone", "birth_date"}


class PiiMaskProbeError(RuntimeError):
    """A sanitized failure for the CI service account policy-tag probe."""


def _safe_query_record(job: Any) -> dict[str, Any]:
    job_id = getattr(job, "job_id", None)
    bytes_billed = getattr(job, "total_bytes_billed", None)
    if (
        not isinstance(job_id, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", job_id) is None
        or isinstance(bytes_billed, bool)
        or not isinstance(bytes_billed, int)
        or bytes_billed < 0
    ):
        raise PiiMaskProbeError("CI PII probe billing metadata is unavailable")
    return {"job_id": job_id, "bytes_billed": bytes_billed}


def verify_masked_access() -> dict[str, Any]:
    from google.api_core.exceptions import Forbidden, PermissionDenied
    from google.cloud import bigquery

    client = bigquery.Client(project=EXPECTED_PROJECT)
    table = client.get_table(f"{EXPECTED_PROJECT}.{RAW_TABLE}")
    tagged_fields = {
        field.name.lower()
        for field in table.schema
        if field.policy_tags and field.policy_tags.names
    }
    if not POLICY_FIELDS.issubset(tagged_fields):
        raise PiiMaskProbeError("Raw synthetic table is missing required column policy tags")

    query = f"""
        SELECT full_name, cccd, email, phone, birth_date
        FROM `{EXPECTED_PROJECT}.{RAW_TABLE}`
        LIMIT 20
    """
    config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        labels={"application": "dataforge", "phase": "w9", "action": "ci-pii-mask"},
    )
    usage_records: list[dict[str, Any]] = []
    unknown_query_cap_count = 0
    try:
        job = client.query(query, job_config=config, job_id_prefix="w9-ci-pii-mask-")
        rows = list(job.result())
        usage_records.append(_safe_query_record(job))
    except (Forbidden, PermissionDenied) as exc:
        detail = str(exc).lower()
        if not any(token in detail for token in ("policy tag", "fine-grained", "categoryfinegrainedreader")):
            raise PiiMaskProbeError("CI raw-column denial was not identified as a policy-tag denial") from None
        unknown_query_cap_count = 1
        guarded = guard_usage_records([], unknown_query_cap_count=unknown_query_cap_count)
        return {
            "status": "DENIED_BY_POLICY_TAG",
            "rows_checked": 0,
            "raw_columns_visible": False,
            **guarded,
        }

    if not rows:
        raise PiiMaskProbeError("Synthetic raw table is empty; CI masking probe is unverified")

    raw_visible = False
    for row in rows:
        email = row["email"]
        phone = row["phone"]
        birth_date = row["birth_date"]
        raw_visible = raw_visible or any(
            (
                row["full_name"] is not None,
                row["cccd"] is not None,
                email is not None and "*" not in str(email),
                phone is not None and (str(phone).startswith("+84-000-") or len(str(phone)) > 4),
                birth_date is not None and (birth_date.month != 1 or birth_date.day != 1),
            )
        )
    if raw_visible:
        raise PiiMaskProbeError("CI service account received a raw policy-tagged value")

    guarded = guard_usage_records(usage_records, unknown_query_cap_count=unknown_query_cap_count)
    return {
        "status": "MASKED",
        "rows_checked": len(rows),
        "raw_columns_visible": False,
        **guarded,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = verify_masked_access()
    except (PiiMaskProbeError, RunCostGuardError) as exc:
        print(f"W9_CI_PII_MASK=UNVERIFIED reason={exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    print(
        "W9_CI_PII_MASK=PASS "
        f"status={receipt['status']} rows={receipt['rows_checked']} "
        f"raw_columns_visible={str(receipt['raw_columns_visible']).lower()} "
        f"bytes_billed={receipt['total_bytes_billed']} "
        f"guarded_upper_bound={receipt['guarded_bytes_upper_bound']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
