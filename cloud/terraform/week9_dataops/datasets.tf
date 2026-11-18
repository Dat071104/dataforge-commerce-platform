locals {
  w9_dataset_ids = toset([
    "w9_drill",
    "dataforge_dq",
    "restricted_pii",
    "pii_safe",
  ])
}

resource "google_bigquery_dataset" "w9_drill" {
  project                     = var.project_id
  dataset_id                  = "w9_drill"
  location                    = var.region
  default_table_expiration_ms = 604800000
  labels                      = { week = "w9" }
  description                 = "Isolated Week 9 fault-injection dataset; synthetic data only."
}

resource "google_bigquery_dataset" "dataforge_dq" {
  project                    = var.project_id
  dataset_id                 = "dataforge_dq"
  location                   = var.region
  delete_contents_on_destroy = false
  deletion_policy            = "PREVENT"
  labels                     = { week = "w9" }
  description                = "Week 9 data-quality results and evidence metadata."

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_bigquery_dataset" "restricted_pii" {
  project                     = var.project_id
  dataset_id                  = "restricted_pii"
  location                    = var.region
  default_table_expiration_ms = 604800000
  delete_contents_on_destroy  = false
  deletion_policy             = "PREVENT"
  labels                      = { week = "w9" }
  description                 = "Week 9 synthetic restricted-data examples; no real personal data."

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_bigquery_dataset" "pii_safe" {
  project                    = var.project_id
  dataset_id                 = "pii_safe"
  location                   = var.region
  delete_contents_on_destroy = false
  deletion_policy            = "PREVENT"
  labels                     = { week = "w9" }
  description                = "Week 9 synthetic de-identified data examples."

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_bigquery_dataset_iam_member" "ci_write_dataforge_dq" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.dataforge_dq.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.ci_dbt.email}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_bigquery_dataset_iam_member" "ci_write_w9_drill" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.w9_drill.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.ci_dbt.email}"
}

resource "google_bigquery_dataset_iam_member" "ci_read_weather_datasets" {
  for_each = toset(["weather_mini3", "dbt_weather_mini3"])

  project    = var.project_id
  dataset_id = each.value
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.ci_dbt.email}"

  lifecycle {
    prevent_destroy = true
  }
}
