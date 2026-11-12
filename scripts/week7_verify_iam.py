"""Capture applied Week-7 IAM, key, bucket, and Scheduler boundary evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import google.auth
import requests
from google.auth.transport.requests import Request

from dataforge.settings import ROOT

TARGET_FILE = ROOT / "docs" / "cloud" / "target.json"
EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
EXPECTED_PROJECT_NUMBER = "955038620072"
EXPECTED_REGION = "us-central1"
EXPECTED_BUCKET = "dataforge-p7-lab-d0f725-bronze"
SA_NAMES = {
    "week5_runtime": "dataforge-runtime",
    "workflow": "dataforge-week7-workflow",
    "dbt": "dataforge-week7-dbt",
    "ci_compile": "dataforge-week7-ci-compile",
}


class Week7IamCheckError(RuntimeError):
    """An approved target or required IAM check failed closed."""


def _read_target() -> dict[str, Any]:
    target = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    if (
        target.get("project_id") != EXPECTED_PROJECT
        or target.get("project_number") != EXPECTED_PROJECT_NUMBER
        or target.get("region") != EXPECTED_REGION
        or target.get("bucket") != EXPECTED_BUCKET
    ):
        raise Week7IamCheckError("IAM audit is restricted to the approved DataForge target")
    return target


def _get_json(url: str, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 404:
        return response.status_code, {}
    if response.status_code >= 400:
        raise Week7IamCheckError(f"Read-only IAM inspection returned HTTP {response.status_code}")
    return response.status_code, response.json()


def _get_bigquery_table_policy(
    *, project: str, dataset: str, table: str, headers: dict[str, str]
) -> dict[str, Any]:
    resource = f"projects/{project}/datasets/{dataset}/tables/{table}"
    response = requests.post(
        f"https://bigquery.googleapis.com/bigquery/v2/{resource}:getIamPolicy",
        headers={**headers, "Content-Type": "application/json"},
        json={"options": {"requestedPolicyVersion": 3}},
        timeout=30,
    )
    if response.status_code >= 400:
        raise Week7IamCheckError(
            f"BigQuery table IAM policy read returned HTTP {response.status_code} for {dataset}.{table}"
        )
    return response.json()


def _binding_has(policy: dict[str, Any], *, role: str, member: str) -> bool:
    return any(
        binding.get("role") == role and member in binding.get("members", [])
        for binding in policy.get("bindings", [])
    )


def verify_iam(*, output: Path | None = None) -> dict[str, Any]:
    target = _read_target()
    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    if adc_project and adc_project != target["project_id"]:
        raise Week7IamCheckError("ADC project differs from the approved target")
    headers = {"Authorization": f"Bearer {credentials.token}"}
    project = target["project_id"]
    base_sa = f"{project}.iam.gserviceaccount.com"

    role_ids = (
        "dataforge_week7_cloud_run_job_runner",
        "dataforge_week7_cloud_run_operation_reader",
        "dataforge_week7_manifest_reader",
    )
    roles: dict[str, Any] = {}
    for role_id in role_ids:
        status, role = _get_json(
            f"https://iam.googleapis.com/v1/projects/{project}/roles/{role_id}", headers
        )
        if status != 200:
            raise Week7IamCheckError(f"Expected Week-7 custom role is missing: {role_id}")
        roles[role_id] = sorted(role.get("includedPermissions", []))
    expected_roles = {
        "dataforge_week7_cloud_run_job_runner": ["run.jobs.run", "run.jobs.runWithOverrides"],
        "dataforge_week7_cloud_run_operation_reader": ["run.operations.get"],
        "dataforge_week7_manifest_reader": ["storage.objects.get"],
    }
    if roles != expected_roles:
        raise Week7IamCheckError("A Week-7 custom role contains unexpected permissions")

    job_policies: dict[str, Any] = {}
    for job_id in ("dataforge-week5-processor", "dataforge-week7-dbt"):
        url = (
            f"https://run.googleapis.com/v2/projects/{project}/locations/{target['region']}"
            f"/jobs/{job_id}:getIamPolicy"
        )
        status, policy = _get_json(url, headers)
        if status != 200:
            raise Week7IamCheckError(f"Could not inspect Cloud Run job policy: {job_id}")
        bindings = policy.get("bindings", [])
        expected_role = f"projects/{project}/roles/dataforge_week7_cloud_run_job_runner"
        workflow_member = f"serviceAccount:{SA_NAMES['workflow']}@{base_sa}"
        if not any(binding.get("role") == expected_role and workflow_member in binding.get("members", []) for binding in bindings):
            raise Week7IamCheckError(f"Workflow runner role is missing on {job_id}")
        job_policies[job_id] = [
            binding.get("role")
            for binding in bindings
            if workflow_member in binding.get("members", [])
        ]

    workflow_member = f"serviceAccount:{SA_NAMES['workflow']}@{base_sa}"
    events_policy = _get_bigquery_table_policy(
        project=project, dataset="ops", table="week7_publish_events", headers=headers
    )
    pointer_policy = _get_bigquery_table_policy(
        project=project, dataset="gold_week7", table="week7_publication_pointer", headers=headers
    )
    pointer_read_only = (
        _binding_has(pointer_policy, role="roles/bigquery.dataViewer", member=workflow_member)
        and not _binding_has(pointer_policy, role="roles/bigquery.dataEditor", member=workflow_member)
    )
    events_read_only = (
        _binding_has(events_policy, role="roles/bigquery.dataViewer", member=workflow_member)
        and not _binding_has(events_policy, role="roles/bigquery.dataEditor", member=workflow_member)
    )
    if not pointer_read_only or not events_read_only:
        raise Week7IamCheckError("Workflow pointer/event access is not the expected table-scoped read-only grant")

    bucket_status, bucket = _get_json(
        f"https://storage.googleapis.com/storage/v1/b/{target['bucket']}", headers
    )
    if bucket_status != 200:
        raise Week7IamCheckError("Could not inspect the approved Bronze bucket")
    bucket_iam_status, bucket_iam = _get_json(
        f"https://storage.googleapis.com/storage/v1/b/{target['bucket']}/iam", headers
    )
    if bucket_iam_status != 200:
        raise Week7IamCheckError("Could not inspect the approved Bronze bucket IAM policy")
    bucket_members = [
        member
        for binding in bucket_iam.get("bindings", [])
        for member in binding.get("members", [])
    ]
    public_members = [member for member in bucket_members if member in {"allUsers", "allAuthenticatedUsers"}]
    if public_members:
        raise Week7IamCheckError("The approved Bronze bucket has public IAM members")

    managed_keys: dict[str, int] = {}
    for label, account_id in SA_NAMES.items():
        email = f"{account_id}@{base_sa}"
        url = (
            f"https://iam.googleapis.com/v1/projects/{project}/serviceAccounts/"
            f"{quote(email, safe='')}/keys?keyTypes=USER_MANAGED"
        )
        status, result = _get_json(url, headers)
        if status != 200:
            raise Week7IamCheckError(f"Could not inspect user-managed keys for {label}")
        keys = result.get("keys", [])
        managed_keys[label] = len(keys)
        if keys:
            raise Week7IamCheckError(f"Found a user-managed key for {label}")

    provider_url = (
        f"https://iam.googleapis.com/v1/projects/{target['project_number']}"
        "/locations/global/workloadIdentityPools/dataforge-week7-ci/providers/github-actions"
    )
    provider_status, provider = _get_json(provider_url, headers)
    if provider_status != 200:
        raise Week7IamCheckError("The constrained GitHub Workload Identity provider is missing")
    provider_condition = provider.get("attributeCondition", "")
    for required in (
        "assertion.repository_id == '1446796465'",
        "assertion.repository_owner_id == '242334093'",
        "assertion.event_name == 'push'",
        "refs/heads/feature/p7-",
        ".github/workflows/week7-ci.yml@",
    ):
        if required not in provider_condition:
            raise Week7IamCheckError("The GitHub Workload Identity condition is broader than the approved repository flow")

    scheduler_status, _ = _get_json(
        f"https://cloudscheduler.googleapis.com/v1/projects/{project}/locations/{target['region']}"
        "/jobs/dataforge-week7-no-new-batch",
        headers,
    )
    result = {
        "status": "PASS",
        "project_id": project,
        "project_number": target["project_number"],
        "region": target["region"],
        "custom_roles": roles,
        "workflow_cloud_run_job_bindings": job_policies,
        "workflow_bigquery_read_only_tables": {
            "ops.week7_publish_events": events_read_only,
            "gold_week7.week7_publication_pointer": pointer_read_only,
        },
        "bucket": {
            "name": target["bucket"],
            "public_access_prevention": bucket.get("iamConfiguration", {}).get("publicAccessPrevention"),
            "uniform_bucket_level_access": bucket.get("iamConfiguration", {}).get("uniformBucketLevelAccess", {}).get("enabled"),
            "public_members": public_members,
        },
        "user_managed_service_account_keys": managed_keys,
        "github_wif_provider_condition": provider_condition,
        "scheduler_job_http_status": scheduler_status,
        "scheduler_job_absent": scheduler_status == 404,
        "limitations": [
            "This receipt inspects applied bindings and key inventory; it does not impersonate runtime identities for negative testIamPermissions probes.",
            "The GitHub WIF provider rejects PR/fork tokens by its repository/event/ref condition; pull-request jobs receive no GCP identity.",
        ],
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/cloud/week7/security_iam_receipt.json")
    args = parser.parse_args(argv)
    verify_iam(output=Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
