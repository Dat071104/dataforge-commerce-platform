from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.week9_catalog_fallback import summarize_connector_result


@pytest.mark.parametrize("check_id", ["G6-OM-CATALOG-001"], ids=lambda value: value)
def test_openmetadata_catalog_profile_is_actions_only_and_manifest_matched(check_id: str) -> None:
    workflow_path = Path(".github/workflows/week9-catalog.yml")
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
    compose = yaml.safe_load(
        Path("governance/openmetadata/docker-compose.yml").read_text(encoding="utf-8")
    )
    service = json.loads(
        Path("governance/openmetadata/dataforge_service.json").read_text(encoding="utf-8")
    )
    dbt_config_path = Path("governance/openmetadata/dbt_ingestion.yaml")
    dbt_config = yaml.safe_load(dbt_config_path.read_text(encoding="utf-8"))
    bigquery_config = yaml.safe_load(
        Path("governance/openmetadata/bigquery_ingestion.yaml").read_text(encoding="utf-8")
    )
    connection = service["connection"]["config"]
    bigquery_source_config = bigquery_config["source"]["sourceConfig"]["config"]

    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["catalog"]["permissions"] == {
        "contents": "read",
        "id-token": "write",
    }
    assert set(compose["services"]) == {"postgresql", "opensearch", "migrate", "openmetadata-server"}
    assert "ingestion" not in compose["services"]
    assert compose["services"]["openmetadata-server"]["ports"] == [
        "127.0.0.1:8585:8585",
        "127.0.0.1:8586:8586",
    ]
    assert service["name"] == dbt_config["source"]["serviceName"] == "dataforge_w9_catalog"
    assert bigquery_config["source"]["serviceName"] == service["name"]
    assert connection["supportsMetadataExtraction"] is True
    assert connection["supportsUsageExtraction"] is False
    assert connection["supportsLineageExtraction"] is False
    assert connection["supportsDBTExtraction"] is True
    assert connection["supportsProfiler"] is False
    assert connection["supportsQueryComment"] is False
    assert connection["includePolicyTags"] is False
    assert connection["credentials"]["gcpConfig"]["type"] == "gcp_adc"
    assert "privateKey" not in json.dumps(service)
    assert bigquery_config["source"]["serviceConnection"]["config"]["credentials"]["gcpConfig"]["type"] == "gcp_adc"
    assert bigquery_source_config["type"] == "DatabaseMetadata"
    assert bigquery_source_config["databaseFilterPattern"]["includes"] == ["^dataforge-p7-lab-d0f725$"]
    assert bigquery_source_config["schemaFilterPattern"]["includes"] == [
        "^(w9_drill|dataforge_dq|restricted_pii|pii_safe|dbt_ci_pr_.*)$"
    ]
    assert bigquery_source_config["includeTables"] is True
    assert bigquery_source_config["includeViews"] is True
    assert bigquery_source_config["includeTags"] is False
    assert bigquery_source_config["includeDDL"] is False
    assert bigquery_source_config["includeOwners"] is False
    assert "profiler" not in bigquery_config and "usage" not in bigquery_config
    server_env = compose["services"]["migrate"]["environment"]
    assert server_env["AUTHENTICATION_PROVIDER"] == "basic"
    assert server_env["AUTHORIZER_CLASS_NAME"] == "org.openmetadata.service.security.DefaultAuthorizer"
    assert server_env["AUTHORIZER_REQUEST_FILTER"] == "org.openmetadata.service.security.JwtFilter"
    assert compose["services"]["openmetadata-server"]["environment"] == server_env
    for ingestion_config in (dbt_config, bigquery_config):
        server_config = ingestion_config["workflowConfig"]["openMetadataServerConfig"]
        assert server_config["authProvider"] == "openmetadata"
        assert server_config["securityConfig"] == {"jwtToken": "__OM_JWT_TOKEN__"}
    assert workflow_text.count("::add-mask::") >= 2
    assert 'Authorization: Bearer $OM_ADMIN_TOKEN' in workflow_text
    assert "ingest -c /om-config/dbt_ingestion.yaml" in workflow_text
    assert "ingest -c /om-config/bigquery_ingestion.yaml" in workflow_text
    assert 'rm -rf -- "$RUNNER_TEMP/om-config"' in workflow_text
    assert "no-auth" not in workflow_text
    assert "docker.getcollate.io/openmetadata/ingestion:2.0.7" in workflow_text
    assert "dbt parse" in workflow_text
    assert "google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093" in workflow_text
    assert "gcloud" not in workflow_text and "terraform" not in workflow_text
    assert "W9_META_READ_SA_EMAIL" in workflow_text
    assert "W9_WIF_PROVIDER" in workflow_text
    assert "week9_catalog_fallback.py" in workflow_text
    assert "openmetadata-bigquery-ingestion.log" in workflow_text
    openmetadata_readme = Path("governance/openmetadata/README.md").read_text(encoding="utf-8")
    assert "lists project dataset IDs" in openmetadata_readme
    assert "then applies the `schemaFilterPattern`" in openmetadata_readme
    for dataset in ("w9_drill", "dataforge_dq", "restricted_pii", "pii_safe", "dbt_ci_pr_*"):
        assert f"`{dataset}`" in openmetadata_readme


@pytest.mark.parametrize("check_id", ["G6-OM-PERMISSION-FALLBACK-001"], ids=lambda value: value)
def test_openmetadata_permission_denial_is_sanitized_for_dataplex_fallback(check_id: str) -> None:
    raw_log = (
        "403 Access Denied: User does not have bigquery.tables.getData permission "
        "on table project.sensitive_dataset.customer_contacts"
    )
    receipt = summarize_connector_result(
        auth_status="success",
        exit_code=1,
        log_text=raw_log,
    )

    rendered = json.dumps(receipt, sort_keys=True)
    assert receipt["status"] == "BLOCKED_PERMISSION"
    assert receipt["denied_permissions"] == ["bigquery.tables.getData"]
    assert "Dataplex" in receipt["dataplex_fallback_reason"]
    assert "bigquery.tables.getData" in receipt["dataplex_fallback_reason"]
    assert "sensitive_dataset" not in rendered
    assert "customer_contacts" not in rendered


@pytest.mark.parametrize("check_id", ["G6-OM-UNKNOWN-FAILURE-001"], ids=lambda value: value)
def test_openmetadata_unknown_failure_does_not_emit_raw_logs(check_id: str) -> None:
    raw_log = "Access denied for table project.sensitive_dataset.customer_contacts"
    receipt = summarize_connector_result(
        auth_status="success",
        exit_code=1,
        log_text=raw_log,
    )

    assert receipt["status"] == "UNVERIFIED_FAILURE"
    assert "sensitive_dataset" not in json.dumps(receipt)
    assert "customer_contacts" not in json.dumps(receipt)
