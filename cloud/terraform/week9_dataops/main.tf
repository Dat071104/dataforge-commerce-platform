data "google_project" "target" {
  project_id = var.project_id
}

resource "google_service_account" "ci_dbt" {
  project      = var.project_id
  account_id   = "dataforge-w9-ci-dbt"
  display_name = "DataForge W9 dbt CI"
  description  = "Keyless GitHub Actions identity for isolated Week 9 dbt CI."

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "meta_read" {
  project      = var.project_id
  account_id   = "dataforge-w9-meta-read"
  display_name = "DataForge W9 metadata reader"
  description  = "Keyless GitHub Actions identity for read-only metadata ingestion."

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_project_iam_custom_role" "w9_dataset_creator" {
  project     = var.project_id
  role_id     = "w9DatasetCreator"
  title       = "DataForge W9 isolated dataset creator"
  description = "Can create PR-scoped BigQuery datasets; grants no data access."
  permissions = ["bigquery.datasets.create"]
  stage       = "GA"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_project_iam_member" "ci_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.ci_dbt.email}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_project_iam_member" "ci_dataset_creator" {
  project = var.project_id
  role    = google_project_iam_custom_role.w9_dataset_creator.name
  member  = "serviceAccount:${google_service_account.ci_dbt.email}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_project_iam_member" "ci_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.ci_dbt.email}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_project_iam_member" "meta_metadata_viewer" {
  project = var.project_id
  role    = "roles/bigquery.metadataViewer"
  member  = "serviceAccount:${google_service_account.meta_read.email}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_project_iam_member" "meta_catalog_viewer" {
  project = var.project_id
  role    = "roles/datacatalog.viewer"
  member  = "serviceAccount:${google_service_account.meta_read.email}"

  lifecycle {
    prevent_destroy = true
  }
}
