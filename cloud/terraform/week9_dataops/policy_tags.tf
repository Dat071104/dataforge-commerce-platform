# Week-9 PII isolation and policy-tag plan. Opt in only after integrator
# preflight confirms project, APIs, identities, and retention. This file was
# intentionally not planned or applied by the governance worker.

variable "week9_pii_enabled" {
  description = "Opt in to the isolated Week-9 synthetic PII datasets, test identities, and column policies after integrator review."
  type        = bool
  default     = false
}

variable "week9_pii_test_impersonation_enabled" {
  description = "Temporarily grant the current operator TokenCreator on the two Week-9 PII test identities for the authorized G4 access check."
  type        = bool
  default     = false

  validation {
    condition     = !var.week9_pii_test_impersonation_enabled || var.week9_pii_enabled
    error_message = "Week-9 test impersonation can be enabled only while the PII test identities are enabled."
  }
}

locals {
  week9_pii_masks = {
    identity = {
      display_name          = "W9 synthetic name and CCCD"
      description           = "Synthetic name and CCCD are NULL to masked readers; HMAC token is the approved join key."
      predefined_expression = "ALWAYS_NULL"
    }
    email = {
      display_name          = "W9 synthetic email"
      description           = "Synthetic example.com e-mail; BigQuery e-mail masking."
      predefined_expression = "EMAIL_MASK"
    }
    phone = {
      display_name          = "W9 synthetic phone"
      description           = "Synthetic number using the fixture-only +84-000 prefix."
      predefined_expression = "LAST_FOUR_CHARACTERS"
    }
    birth_date = {
      display_name          = "W9 synthetic birth date"
      description           = "Synthetic date of birth; preserve year only for masked readers."
      predefined_expression = "DATE_YEAR_MASK"
    }
  }
}

resource "google_service_account" "week9_pii_analyst_test" {
  count        = var.week9_pii_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "dataforge-w9-analyst-test"
  display_name = "DataForge Week-9 PII analyst test identity"
  description  = "Can query only the minimized pii_safe dataset; no restricted_pii dataset grant."
}

resource "google_service_account" "week9_pii_privileged_test" {
  count        = var.week9_pii_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "dataforge-w9-privileged-test"
  display_name = "DataForge Week-9 privileged PII test identity"
  description  = "Can read the restricted synthetic fixture for the positive access check."
}

data "google_client_openid_userinfo" "week9_operator" {
  count = var.week9_pii_test_impersonation_enabled ? 1 : 0
}

resource "google_service_account_iam_member" "week9_pii_analyst_operator_token_creator" {
  count              = var.week9_pii_test_impersonation_enabled ? 1 : 0
  service_account_id = google_service_account.week9_pii_analyst_test[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "user:${data.google_client_openid_userinfo.week9_operator[0].email}"
}

resource "google_service_account_iam_member" "week9_pii_privileged_operator_token_creator" {
  count              = var.week9_pii_test_impersonation_enabled ? 1 : 0
  service_account_id = google_service_account.week9_pii_privileged_test[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "user:${data.google_client_openid_userinfo.week9_operator[0].email}"
}

resource "google_project_iam_member" "week9_pii_analyst_job_user" {
  count   = var.week9_pii_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.week9_pii_analyst_test[0].email}"
}

resource "google_project_iam_member" "week9_pii_privileged_job_user" {
  count   = var.week9_pii_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.week9_pii_privileged_test[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week9_pii_analyst_safe_reader" {
  count      = var.week9_pii_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.pii_safe.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week9_pii_analyst_test[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week9_pii_privileged_raw_reader" {
  count      = var.week9_pii_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.restricted_pii.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week9_pii_privileged_test[0].email}"
}

resource "google_data_catalog_taxonomy" "week9_pii" {
  count                  = var.week9_pii_enabled ? 1 : 0
  project                = var.project_id
  region                 = var.region
  display_name           = "DataForge Week-9 synthetic PII"
  description            = "Column classification and masking for restricted synthetic customer-profile fields."
  activated_policy_types = ["FINE_GRAINED_ACCESS_CONTROL"]
}

resource "google_data_catalog_policy_tag" "week9_pii" {
  for_each     = var.week9_pii_enabled ? local.week9_pii_masks : {}
  taxonomy     = google_data_catalog_taxonomy.week9_pii[0].id
  display_name = each.value.display_name
  description  = each.value.description
}

resource "google_bigquery_datapolicy_data_policy" "week9_pii_mask" {
  for_each         = var.week9_pii_enabled ? local.week9_pii_masks : {}
  project          = var.project_id
  location         = var.region
  data_policy_id   = "w9-pii-${replace(each.key, "_", "-")}-mask"
  policy_tag       = google_data_catalog_policy_tag.week9_pii[each.key].name
  data_policy_type = "DATA_MASKING_POLICY"
  data_masking_policy {
    predefined_expression = each.value.predefined_expression
  }
}

resource "google_data_catalog_policy_tag_iam_member" "week9_pii_privileged_raw_column_reader" {
  for_each   = var.week9_pii_enabled ? local.week9_pii_masks : {}
  policy_tag = google_data_catalog_policy_tag.week9_pii[each.key].name
  role       = "roles/datacatalog.categoryFineGrainedReader"
  member     = "serviceAccount:${google_service_account.week9_pii_privileged_test[0].email}"
}

output "week9_pii_policy_tag_names" {
  description = "Policy-tag resource names to pass to the synthetic loader after approved provisioning."
  value       = { for field, tag in google_data_catalog_policy_tag.week9_pii : field => tag.name }
}

output "week9_pii_data_policy_names" {
  description = "Data-policy resource names for the Week-9 synthetic PII mask rules."
  value       = { for field, policy in google_bigquery_datapolicy_data_policy.week9_pii_mask : field => policy.name }
}
