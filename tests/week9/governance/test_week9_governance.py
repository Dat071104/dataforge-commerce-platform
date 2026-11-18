from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from jinja2 import Environment

from dataforge.privacy.pseudonymize import PseudonymizationError, hmac_customer_cccd
from dataforge.privacy.synthetic import (
    CCCD_RESERVED_PREFIX,
    DEFAULT_SEED,
    EMAIL_DOMAIN,
    PHONE_UNALLOCATED_PREFIX,
    POLICY_TAG_GROUPS,
    SyntheticPiiError,
    _policy_tag_names,
    build_load_plan,
    generate_customer_profiles,
)
from scripts.week9_classification_coverage import validate_classification
from scripts.week9_pii_guard import scan_manifest, scan_manifest_file

GOVERNANCE_FIXTURES = Path("tests/week9/governance/fixtures")

TEST_HMAC_KEY = b"week9-unit-test-hmac-key-do-not-use-in-production-32bytes"


@pytest.mark.parametrize("check_id", ["G1-CLASSIFICATION-001"], ids=lambda value: value)
def test_all_source_model_snapshot_and_gold_columns_are_classified(check_id: str) -> None:
    result = validate_classification()

    assert result["status"] == "PASS"
    assert result["source_tables"] == 8
    assert result["gold_coverage_percent"] == 100.0
    assert result["gold_meta_complete"] == result["gold_columns"]


@pytest.mark.parametrize("check_id", ["G3-DBT-SCHEMA-NAME-001"], ids=lambda value: value)
def test_pii_dataset_override_keeps_default_non_pii_schema_naming(check_id: str) -> None:
    macro = Path("dbt/dataforge/macros/generate_schema_name.sql").read_text(encoding="utf-8")
    module = Environment().from_string(macro).make_module(
        {"target": SimpleNamespace(schema="dbt_local")}
    )

    assert "['pii_safe', 'restricted_pii', 'dataforge_dq']" in macro
    assert str(module.generate_schema_name("pii_safe", None)).strip() == "pii_safe"
    assert str(module.generate_schema_name("restricted_pii", None)).strip() == "restricted_pii"
    assert str(module.generate_schema_name("dataforge_dq", None)).strip() == "dataforge_dq"
    assert str(module.generate_schema_name("custom_dev", None)).strip() == "dbt_local_custom_dev"


@pytest.mark.parametrize("check_id", ["G3-POLICY-TAG-001"], ids=lambda value: value)
def test_restricted_dbt_view_persists_policy_tags_on_direct_pii_columns(check_id: str) -> None:
    schema_path = Path("dbt/dataforge/models/pii/restricted/schema.yml")
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    model = next(
        item for item in schema["models"] if item["name"] == "stg_customer_profile_restricted"
    )
    tagged_columns = {
        column["name"] for column in model["columns"] if column.get("policy_tags")
    }

    assert model["config"]["persist_docs"]["columns"] is True
    assert tagged_columns == {"full_name", "cccd", "email", "phone", "birth_date"}
    tags_by_column = {
        column["name"]: column["policy_tags"][0]
        for column in model["columns"]
        if column.get("policy_tags")
    }
    assert tags_by_column["full_name"] == tags_by_column["cccd"]


@pytest.mark.parametrize("check_id", ["AF4-POLICY-CAP-001"], ids=lambda value: value)
def test_policy_tag_and_data_policy_groups_stay_within_af4_cap(check_id: str) -> None:
    terraform = Path("cloud/terraform/week9_dataops/policy_tags.tf").read_text(encoding="utf-8")
    start = terraform.index("week9_pii_masks = {")
    end = terraform.index("\n  }\n}", start)
    hcl_group_keys = set(
        re.findall(r"(?m)^\s{4}([a-z_]+)\s*=\s*\{", terraform[start:end])
    )

    assert set(POLICY_TAG_GROUPS) == {"identity", "email", "phone", "birth_date"}
    assert POLICY_TAG_GROUPS["identity"] == ("full_name", "cccd")
    assert hcl_group_keys == set(POLICY_TAG_GROUPS)
    assert len(hcl_group_keys) == 4


@pytest.mark.parametrize("check_id", ["AF4-LOADER-TAGS-001"], ids=lambda value: value)
def test_loader_requires_four_grouped_policy_tag_env_values(check_id: str, monkeypatch) -> None:
    for index, group in enumerate(POLICY_TAG_GROUPS, start=1):
        monkeypatch.setenv(
            f"DATAFORGE_W9_POLICY_TAG_{group.upper()}",
            f"projects/test/locations/us-central1/taxonomies/{index}/policyTags/{index}",
        )

    names = _policy_tag_names()

    assert set(names) == {"identity", "email", "phone", "birth_date"}
    assert len(names) == 4
    monkeypatch.delenv("DATAFORGE_W9_POLICY_TAG_IDENTITY")
    with pytest.raises(SyntheticPiiError):
        _policy_tag_names()


@pytest.mark.parametrize(
    "check_id",
    ["G2-PII-001"],
    ids=lambda value: value,
)
def test_synthetic_fixture_is_deterministic_and_uses_reserved_patterns(check_id: str) -> None:
    first = generate_customer_profiles(count=12, seed=DEFAULT_SEED, key=TEST_HMAC_KEY)
    second = generate_customer_profiles(count=12, seed=DEFAULT_SEED, key=TEST_HMAC_KEY)

    assert first == second
    assert all(row.data_classification == "synthetic" for row in first)
    assert all(row.cccd.startswith(CCCD_RESERVED_PREFIX) and len(row.cccd) == 12 for row in first)
    assert all(row.email.endswith(f"@{EMAIL_DOMAIN}") for row in first)
    assert all(row.phone.startswith(PHONE_UNALLOCATED_PREFIX) for row in first)
    assert all(row.generated_at.date() == date(2026, 11, 18) for row in first)
    assert len({row.customer_token for row in first}) == len(first)
    assert all(len(row.customer_token) == 64 for row in first)
    assert "redacted" in repr(first[0])


@pytest.mark.parametrize("check_id", ["G3-PSEUDONYM-001"], ids=lambda value: value)
def test_hmac_token_requires_reserved_synthetic_input(check_id: str) -> None:
    cccd = "999123456789"
    token_one = hmac_customer_cccd(cccd, TEST_HMAC_KEY)
    token_two = hmac_customer_cccd(cccd, TEST_HMAC_KEY)

    assert token_one == token_two
    assert token_one != cccd
    assert len(token_one) == 64
    with pytest.raises(PseudonymizationError):
        hmac_customer_cccd("123123456789", TEST_HMAC_KEY)


@pytest.mark.parametrize("check_id", ["G2-PII-PLAN-001"], ids=lambda value: value)
def test_load_plan_is_local_only_and_never_emits_values(check_id: str) -> None:
    plan = build_load_plan(count=7, seed=41)

    assert plan["cloud_writes"] is False
    assert plan["pii_values_emitted"] is False
    assert plan["raw_destination"] == "restricted_pii.customer_profile"
    assert plan["row_count"] == 7
    assert "999" in plan["synthetic_controls"]["cccd_prefix"]


@pytest.mark.parametrize("check_id", ["G5-F13-001"], ids=lambda value: value)
def test_f13_manifest_is_rejected_and_safe_masked_manifest_passes(check_id: str) -> None:
    bad_manifest = scan_manifest_file(GOVERNANCE_FIXTURES / "f13_public_email_manifest.json")
    safe_manifest = scan_manifest_file(GOVERNANCE_FIXTURES / "safe_masked_manifest.json")

    assert [(finding.check_id, finding.model, finding.column) for finding in bad_manifest.findings] == [
        ("F13", "public_customer_contact", "email")
    ]
    assert safe_manifest.findings == []


@pytest.mark.parametrize("check_id", ["G5-INDIRECT-CUSTOMER-001"], ids=lambda value: value)
def test_confidential_customer_id_is_allowed_but_public_customer_id_is_blocked(check_id: str) -> None:
    import json

    manifest = json.loads((GOVERNANCE_FIXTURES / "safe_masked_manifest.json").read_text(encoding="utf-8"))
    model_id = "model.dataforge.dim_customer_profile_safe"
    manifest["nodes"][model_id]["schema"] = "gold"
    manifest["nodes"][model_id]["columns"]["customer_id"] = {
        "name": "customer_id",
        "meta": {
            "classification": "confidential",
            "pii_type": "indirect_customer_identifier",
            "purpose": "Order-to-cash reconciliation business key",
            "retention_days": 365,
        },
    }

    assert scan_manifest(manifest).findings == []
    manifest["nodes"][model_id]["columns"]["customer_id"]["meta"]["classification"] = "public"
    findings = scan_manifest(manifest).findings

    assert [(finding.column, finding.classification) for finding in findings] == [("customer_id", "public")]


@pytest.mark.parametrize("check_id", ["G4-ACCESS-PLAN-001"], ids=lambda value: value)
def test_access_plan_names_only_synthetic_privacy_checks(check_id: str) -> None:
    script = Path("scripts/week9_verify_access.py")

    assert script.is_file()
    assert "restricted_pii.customer_profile" in script.read_text(encoding="utf-8")
    assert "pii_safe.dim_customer_profile_safe" in script.read_text(encoding="utf-8")
