"""Plan or verify the Week-9 analyst/privileged BigQuery PII boundary.

Execution is intentionally disabled until the integrator provisions the two
test service accounts, datasets, policy tags, safe mart, and scoped IAM.
Receipts contain checks and counts only; no identity values are printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

from dataforge.settings import ROOT

EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
EXPECTED_PROJECT_NUMBER = "955038620072"
EXPECTED_REGION = "us-central1"
ANALYST_SA = "dataforge-w9-pii-analyst-test"
PRIVILEGED_SA = "dataforge-w9-pii-privileged-test"
RAW_TABLE = "restricted_pii.customer_profile"
SAFE_TABLE = "pii_safe.dim_customer_profile_safe"
TARGET_FILE = ROOT / "docs" / "cloud" / "target.json"
EMAIL_MASK_RE = re.compile(r"^[A-Za-z0-9]\*{3}@example\.com$")
TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
AGE_BANDS = {"18-24", "25-34", "35-44", "45-54", "55+"}


class AccessCheckError(RuntimeError):
    """Raised when the approved target or PII access boundary is incorrect."""


def _read_target() -> dict[str, Any]:
    try:
        target = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AccessCheckError("The approved DataForge target file is missing or invalid") from exc
    if (
        target.get("project_id") != EXPECTED_PROJECT
        or target.get("project_number") != EXPECTED_PROJECT_NUMBER
        or target.get("region") != EXPECTED_REGION
    ):
        raise AccessCheckError("PII access check is restricted to the approved DataForge target")
    return target


def build_plan() -> dict[str, Any]:
    target = _read_target()
    return {
        "status": "UNVERIFIED",
        "project_id": target["project_id"],
        "region": target["region"],
        "analyst_identity": ANALYST_SA,
        "privileged_identity": PRIVILEGED_SA,
        "analyst_checks": [
            f"SELECT customer_token, age_band, province_id, email_masked FROM {SAFE_TABLE}",
            f"SELECT full_name, cccd, email, phone, birth_date FROM {RAW_TABLE} -- expect permission denied",
        ],
        "privileged_check": (
            f"SELECT COUNT(*) FROM {RAW_TABLE} WHERE REGEXP_CONTAINS(cccd, r'^999[0-9]{{9}}$')"
        ),
        "value_logging": False,
        "live_resources_present": False,
        "integrator_action_required": True,
    }


def _impersonated_client(service_account_email: str):
    try:
        import google.auth
        from google.auth import impersonated_credentials
        from google.auth.transport.requests import Request
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover - depends on the optional gcp extra
        raise AccessCheckError("Access verification requires google-auth and google-cloud-bigquery") from exc

    source_credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if adc_project and adc_project != EXPECTED_PROJECT:
        raise AccessCheckError("ADC project differs from the approved DataForge target")
    source_credentials.refresh(Request())
    credentials = impersonated_credentials.Credentials(
        source_credentials=source_credentials,
        target_principal=service_account_email,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=900,
    )
    return bigquery.Client(project=EXPECTED_PROJECT, credentials=credentials)


def verify_access() -> dict[str, Any]:
    target = _read_target()
    if os.environ.get("DATAFORGE_W9_PII_ACCESS_TEST_ENABLED") != "true":
        raise AccessCheckError(
            "Set DATAFORGE_W9_PII_ACCESS_TEST_ENABLED=true after integrator preflight"
        )

    analyst_email = f"{ANALYST_SA}@{EXPECTED_PROJECT}.iam.gserviceaccount.com"
    privileged_email = f"{PRIVILEGED_SA}@{EXPECTED_PROJECT}.iam.gserviceaccount.com"
    analyst = _impersonated_client(analyst_email)
    privileged = _impersonated_client(privileged_email)

    safe_table = analyst.get_table(f"{EXPECTED_PROJECT}.{SAFE_TABLE}")
    safe_column_names = {field.name.lower() for field in safe_table.schema}
    raw_columns = safe_column_names.intersection({"full_name", "cccd", "email", "phone", "birth_date"})
    if raw_columns:
        raise AccessCheckError("The pii_safe table schema contains raw personal-data columns")

    safe_query = f"""
        SELECT customer_token, age_band, province_id, email_masked
        FROM `{EXPECTED_PROJECT}.{SAFE_TABLE}`
        ORDER BY customer_token
        LIMIT 20
    """
    safe_rows = list(analyst.query(safe_query, job_config=None, job_id_prefix="w9pii-analyst-safe-").result())
    if not safe_rows:
        raise AccessCheckError("The pii_safe mart has no synthetic rows to verify")
    if any(
        not TOKEN_RE.fullmatch(row["customer_token"] or "")
        or row["age_band"] not in AGE_BANDS
        or row["province_id"] not in {"HCM", "HN", "DN"}
        or not EMAIL_MASK_RE.fullmatch(row["email_masked"] or "")
        for row in safe_rows
    ):
        raise AccessCheckError("The analyst result does not match the safe mart masking contract")

    denied_query = f"""
        SELECT full_name, cccd, email, phone, birth_date
        FROM `{EXPECTED_PROJECT}.{RAW_TABLE}`
        LIMIT 1
    """
    try:
        list(
            analyst.query(
                denied_query, job_config=None, job_id_prefix="w9pii-analyst-raw-deny-"
            ).result()
        )
    except Exception as exc:  # The permission failure class varies by client version/API path.
        if exc.__class__.__name__ not in {"Forbidden", "PermissionDenied"}:
            raise AccessCheckError("Analyst raw-dataset probe failed for a non-permission reason") from exc
        raw_denied = True
    else:
        raise AccessCheckError("Analyst unexpectedly read the restricted raw PII table")

    raw_query = f"""
        SELECT
          COUNT(*) AS row_count,
          COUNTIF(REGEXP_CONTAINS(cccd, r'^999[0-9]{{9}}$')) AS reserved_cccd_count,
          COUNTIF(REGEXP_CONTAINS(email, r'^[^@]+@example\\.com$')) AS example_email_count,
          COUNTIF(STARTS_WITH(phone, '+84-000-')) AS synthetic_phone_count
        FROM `{EXPECTED_PROJECT}.{RAW_TABLE}`
    """
    raw_result = list(
        privileged.query(raw_query, job_config=None, job_id_prefix="w9pii-privileged-raw-").result()
    )
    if not raw_result or raw_result[0]["row_count"] < 1:
        raise AccessCheckError("Privileged raw-data query returned no synthetic rows")
    summary = raw_result[0]
    if any(
        summary[key] != summary["row_count"]
        for key in ("reserved_cccd_count", "example_email_count", "synthetic_phone_count")
    ):
        raise AccessCheckError("Privileged raw-data probe found a non-synthetic fixture")
    return {
        "status": "PASS",
        "project_id": target["project_id"],
        "region": target["region"],
        "analyst_safe_rows_checked": len(safe_rows),
        "analyst_mask_contract": "PASS",
        "safe_table_raw_columns_absent": True,
        "analyst_raw_access_denied": raw_denied,
        "privileged_raw_access": "PASS",
        "synthetic_raw_rows_checked": int(summary["row_count"]),
        "raw_values_emitted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run impersonated checks after preflight")
    args = parser.parse_args(argv)
    try:
        receipt = verify_access() if args.execute else build_plan()
    except AccessCheckError as exc:
        print(f"W9_PII_ACCESS_STATUS=UNVERIFIED reason={exc}", file=sys.stderr)
        return 2
    print("W9_PII_ACCESS_RECEIPT=" + json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
