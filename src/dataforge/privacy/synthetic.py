"""Generate and optionally load synthetic Vietnamese customer profiles.

The plan is local-only by default. Raw fixture values are generated in memory
and may be loaded only into `restricted_pii.customer_profile` after explicit
integrator preflight. Receipts contain counts and job IDs, never values.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from faker import Faker

from dataforge.privacy.pseudonymize import (
    PseudonymizationError,
    hmac_customer_cccd,
    load_hmac_key_from_secret_manager,
)
from dataforge.settings import ROOT

EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
EXPECTED_PROJECT_NUMBER = "955038620072"
EXPECTED_REGION = "us-central1"
EXPECTED_DATASET = "restricted_pii"
EXPECTED_TABLE = "customer_profile"
EXPECTED_SECRET_NAME = "w9-pii-hmac-key"
DEFAULT_SEED = 20261118
DEFAULT_COUNT = 5
FIXTURE_AS_OF = date(2026, 11, 18)
CCCD_RESERVED_PREFIX = "999"
EMAIL_DOMAIN = "example.com"
PHONE_UNALLOCATED_PREFIX = "+84-000-"
POLICY_TAG_GROUPS = {
    "identity": ("full_name", "cccd"),
    "email": ("email",),
    "phone": ("phone",),
    "birth_date": ("birth_date",),
}
_TARGET_FILE = ROOT / "docs" / "cloud" / "target.json"
_PROVINCES = ("HCM", "HN", "DN")


class SyntheticPiiError(RuntimeError):
    """Raised when the synthetic-only PII contract is not satisfied."""


@dataclass(frozen=True, repr=False)
class CustomerProfile:
    fixture_id: str
    customer_token: str
    full_name: str
    cccd: str
    email: str
    phone: str
    birth_date: date
    province_id: str
    age_band: str
    data_classification: str
    generated_at: datetime

    def as_load_row(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "customer_token": self.customer_token,
            "full_name": self.full_name,
            "cccd": self.cccd,
            "email": self.email,
            "phone": self.phone,
            "birth_date": self.birth_date.isoformat(),
            "province_id": self.province_id,
            "age_band": self.age_band,
            "data_classification": self.data_classification,
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
        }

    def __repr__(self) -> str:
        return f"CustomerProfile(fixture_id={self.fixture_id!r}, values=<redacted>)"


def _read_target() -> dict[str, Any]:
    try:
        target = json.loads(_TARGET_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyntheticPiiError("The approved DataForge target file is missing or invalid") from exc
    if (
        target.get("project_id") != EXPECTED_PROJECT
        or target.get("project_number") != EXPECTED_PROJECT_NUMBER
        or target.get("region") != EXPECTED_REGION
    ):
        raise SyntheticPiiError("Synthetic PII load is restricted to the approved DataForge target")
    return target


def _age_band(birth_date: date, as_of: date) -> str:
    age = as_of.year - birth_date.year - ((as_of.month, as_of.day) < (birth_date.month, birth_date.day))
    if age < 25:
        return "18-24"
    if age < 35:
        return "25-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    return "55+"


def generate_customer_profiles(
    *, count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED, key: bytes,
    as_of: date = FIXTURE_AS_OF,
) -> list[CustomerProfile]:
    """Generate deterministic `vi_VN` Faker profiles with non-routable test IDs."""
    if count < 1 or count > 10_000:
        raise SyntheticPiiError("count must be in the inclusive range 1..10000")
    if seed < 0:
        raise SyntheticPiiError("seed must be a non-negative integer")
    if len(key) < 32:
        raise SyntheticPiiError("The HMAC key must contain at least 32 bytes")

    fake = Faker("vi_VN", use_weighting=False)
    fake.seed_instance(seed)
    rng = random.Random(seed)
    generated_at = datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc)
    customers: list[CustomerProfile] = []
    for index in range(1, count + 1):
        fixture_id = f"w9g-{seed}-{index:04d}"
        cccd = CCCD_RESERVED_PREFIX + f"{rng.randrange(0, 1_000_000_000):09d}"
        email = f"customer{index:04d}@{EMAIL_DOMAIN}"
        phone = f"{PHONE_UNALLOCATED_PREFIX}{index:04d}"
        birth_date = fake.date_of_birth(minimum_age=18, maximum_age=75)
        try:
            token = hmac_customer_cccd(cccd, key)
        except PseudonymizationError as exc:
            raise SyntheticPiiError("Synthetic profile pseudonymization failed") from exc
        customers.append(
            CustomerProfile(
                fixture_id=fixture_id,
                customer_token=token,
                full_name=fake.name(),
                cccd=cccd,
                email=email,
                phone=phone,
                birth_date=birth_date,
                province_id=rng.choice(_PROVINCES),
                age_band=_age_band(birth_date, as_of),
                data_classification="synthetic",
                generated_at=generated_at,
            )
        )
    return customers


def _policy_tag_names() -> dict[str, str]:
    names = {
        group: os.environ.get(f"DATAFORGE_W9_POLICY_TAG_{group.upper()}", "").strip()
        for group in POLICY_TAG_GROUPS
    }
    pattern = re.compile(
        r"^projects/[^/]+/locations/us-central1/taxonomies/[0-9]+/policyTags/[0-9]+$"
    )
    if any(not pattern.fullmatch(value) for value in names.values()):
        raise SyntheticPiiError("All four BigQuery policy-tag IDs must be configured before loading")
    return names


def load_customer_profiles(
    *, count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED, project_id: str = EXPECTED_PROJECT
) -> dict[str, Any]:
    """Load raw synthetic PII only to `restricted_pii.customer_profile` with WRITE_EMPTY."""
    if project_id != EXPECTED_PROJECT:
        raise SyntheticPiiError("Synthetic PII load is restricted to the approved DataForge lab")
    if os.environ.get("DATAFORGE_W9_PII_LOAD_ENABLED") != "true":
        raise SyntheticPiiError("Set DATAFORGE_W9_PII_LOAD_ENABLED=true after integrator preflight")
    _read_target()
    policy_tags = _policy_tag_names()
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover - requires the optional gcp extra
        raise SyntheticPiiError("BigQuery load requires google-cloud-bigquery from the [gcp] extra") from exc

    key = load_hmac_key_from_secret_manager(project_id)
    customers = generate_customer_profiles(count=count, seed=seed, key=key)
    del key
    rows = [profile.as_load_row() for profile in customers]
    tags = {
        field: bigquery.PolicyTagList(names=[policy_tags[group]])
        for group, fields in POLICY_TAG_GROUPS.items()
        for field in fields
    }
    destination = f"{project_id}.{EXPECTED_DATASET}.{EXPECTED_TABLE}"
    schema = [
        bigquery.SchemaField("fixture_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("customer_token", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("full_name", "STRING", mode="REQUIRED", policy_tags=tags["full_name"]),
        bigquery.SchemaField("cccd", "STRING", mode="REQUIRED", policy_tags=tags["cccd"]),
        bigquery.SchemaField("email", "STRING", mode="REQUIRED", policy_tags=tags["email"]),
        bigquery.SchemaField("phone", "STRING", mode="REQUIRED", policy_tags=tags["phone"]),
        bigquery.SchemaField("birth_date", "DATE", mode="REQUIRED", policy_tags=tags["birth_date"]),
        bigquery.SchemaField("province_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("age_band", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("data_classification", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("generated_at", "TIMESTAMP", mode="REQUIRED"),
    ]
    client = bigquery.Client(project=project_id)
    job = client.load_table_from_json(
        rows,
        destination,
        job_config=bigquery.LoadJobConfig(
            schema=schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_EMPTY,
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        ),
    )
    job.result(timeout=120)
    return {
        "status": "LOADED_SYNTHETIC_ONLY",
        "destination": f"{EXPECTED_DATASET}.{EXPECTED_TABLE}",
        "row_count": len(rows),
        "job_id": job.job_id,
        "raw_values_emitted": False,
    }


def build_load_plan(*, count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    if count < 1 or count > 10_000 or seed < 0:
        raise SyntheticPiiError("Plan requires count in 1..10000 and a non-negative seed")
    return {
        "status": "LOCAL_SYNTHETIC_PLAN",
        "project_id": EXPECTED_PROJECT,
        "region": EXPECTED_REGION,
        "seed": seed,
        "row_count": count,
        "raw_destination": f"{EXPECTED_DATASET}.{EXPECTED_TABLE}",
        "pseudonymization": f"HMAC-SHA256 from Secret Manager secret {EXPECTED_SECRET_NAME}",
        "safe_destination": "pii_safe.dim_customer_profile_safe (dbt materialization)",
        "synthetic_controls": {
            "cccd_prefix": CCCD_RESERVED_PREFIX,
            "email_domain": f"@{EMAIL_DOMAIN}",
            "phone_prefix": PHONE_UNALLOCATED_PREFIX,
        },
        "cloud_writes": False,
        "pii_values_emitted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--execute", action="store_true", help="load fixture rows to restricted_pii")
    args = parser.parse_args(argv)
    try:
        result = (
            load_customer_profiles(count=args.count, seed=args.seed)
            if args.execute
            else build_load_plan(count=args.count, seed=args.seed)
        )
    except (SyntheticPiiError, PseudonymizationError) as exc:
        print(f"W9_PII_STATUS=UNVERIFIED reason={exc}", file=sys.stderr)
        return 2
    print("W9_PII_RECEIPT=" + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
