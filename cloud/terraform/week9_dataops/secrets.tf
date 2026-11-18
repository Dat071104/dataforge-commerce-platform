locals {
  w9_secret_ids = toset([
    "w9-slack-webhook-url",
    "w9-pii-hmac-key",
  ])
}

resource "google_secret_manager_secret" "w9" {
  for_each = local.w9_secret_ids

  project   = var.project_id
  secret_id = each.value
  replication {
    auto {}
  }
  labels = { week = "w9" }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_secret_manager_secret_iam_member" "ci_secret_accessor" {
  for_each = google_secret_manager_secret.w9

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ci_dbt.email}"

  lifecycle {
    prevent_destroy = true
  }
}

# No google_secret_manager_secret_version resources belong here. Secret values
# are supplied through the approved out-of-band workflow after review.
