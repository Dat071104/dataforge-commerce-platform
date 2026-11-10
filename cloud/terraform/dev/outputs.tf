output "bronze_bucket" {
  description = "Private regional bucket for immutable source Parquet and manifests."
  value       = google_storage_bucket.bronze.name
}

output "dataset_ids" {
  description = "BigQuery datasets created by the Week-4 foundation."
  value = {
    staging = google_bigquery_dataset.staging.dataset_id
    silver  = google_bigquery_dataset.silver.dataset_id
    gold    = google_bigquery_dataset.gold.dataset_id
  }
}

output "runtime_service_account" {
  description = "Runtime service account email; no key is created."
  value       = google_service_account.runtime.email
}
