locals {
  # Verified from GitHub REST for Dat071104/dataforge-commerce-platform.
  github_repository_id       = "1446796465"
  github_repository_owner_id = "242334093"
  # Limit WIF to the AF9-approved workflow files; unrelated repo workflows cannot impersonate the CI SAs.
  github_allowed_events = ["pull_request_target", "push", "workflow_dispatch", "schedule"]
}

resource "google_iam_workload_identity_pool" "github_dataforge" {
  project                   = var.project_id
  workload_identity_pool_id = "github-dataforge"
  display_name              = "GitHub Actions - DataForge W9"
  description               = "Keyless identity federation restricted to this GitHub repository and owner IDs."
  disabled                  = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_iam_workload_identity_pool_provider" "github_oidc" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_dataforge.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC - DataForge W9"
  description                        = "Accepts GitHub OIDC only for the pinned numeric repository and owner IDs."

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.workflow_ref"        = "assertion.workflow_ref"
    "attribute.event_name"          = "assertion.event_name"
  }

  attribute_condition = "attribute.repository_id == '${local.github_repository_id}' && attribute.repository_owner_id == '${local.github_repository_owner_id}' && (attribute.workflow_ref.contains('/.github/workflows/week9-dataops.yml@') || attribute.workflow_ref.contains('/.github/workflows/week9-cleanup.yml@') || attribute.workflow_ref.contains('/.github/workflows/week9-cd.yml@') || attribute.workflow_ref.contains('/.github/workflows/week9-catalog.yml@')) && attribute.event_name in ${jsonencode(local.github_allowed_events)}"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account_iam_member" "ci_dbt_workload_identity_user" {
  service_account_id = google_service_account.ci_dbt.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_dataforge.name}/attribute.repository_id/${local.github_repository_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account_iam_member" "meta_read_workload_identity_user" {
  service_account_id = google_service_account.meta_read.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_dataforge.name}/attribute.repository_id/${local.github_repository_id}"

  lifecycle {
    prevent_destroy = true
  }
}
