output "bronze_bucket" {
  description = "Private regional bucket for immutable source Parquet and manifests."
  value       = google_storage_bucket.bronze.name
}

output "dataset_ids" {
  description = "BigQuery staging, Silver, Gold, and Week-5 operations datasets."
  value = {
    staging = google_bigquery_dataset.staging.dataset_id
    silver  = google_bigquery_dataset.silver.dataset_id
    gold    = google_bigquery_dataset.gold.dataset_id
    ops     = google_bigquery_dataset.ops.dataset_id
  }
}

output "runtime_service_account" {
  description = "Runtime service account email; no key is created."
  value       = google_service_account.runtime.email
}

output "week5_image_repository" {
  description = "Private Artifact Registry repository for the finite Week-5 Cloud Run Job image."
  value       = google_artifact_registry_repository.week5.id
}

output "week5_container_image" {
  description = "Image reference configured on the Week-5 processor job; prefer a digest-pinned input for release execution."
  value       = local.week5_container_image
}

output "week5_cloud_run_job" {
  description = "Finite, one-task Week-5 BigQuery batch processor job."
  value       = try(google_cloud_run_v2_job.week5_processor[0].name, null)
}
