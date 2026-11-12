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

output "week7_image_repository" {
  description = "Private Week-7 dbt image repository, when enabled."
  value       = try(google_artifact_registry_repository.week7[0].id, null)
}

output "week7_cloud_run_job" {
  description = "Finite, one-task dbt runner job, when Week-7 orchestration is enabled."
  value       = try(google_cloud_run_v2_job.week7_dbt[0].name, null)
}

output "week7_workflow" {
  description = "Manual Week-7 workflow that validates an immutable Week-5 manifest and gates versioned publication."
  value       = try(google_workflows_workflow.week7[0].id, null)
}

output "week7_scheduler" {
  description = "Daily no-new-batch trigger, paused by default."
  value       = try(google_cloud_scheduler_job.week7[0].id, null)
}

output "week7_dataset_ids" {
  description = "Week-7 dbt and versioned Gold datasets, when enabled."
  value = var.week7_orchestration_enabled ? {
    incremental  = google_bigquery_dataset.dbt_week7[0].dataset_id
    full_refresh = google_bigquery_dataset.dbt_week7_full[0].dataset_id
    gold         = google_bigquery_dataset.gold_week7[0].dataset_id
  } : null
}

output "week7_runtime_service_accounts" {
  description = "Keyless Week-7 runtime service accounts, when orchestration is enabled."
  value = var.week7_orchestration_enabled ? {
    dbt       = google_service_account.week7_dbt_runtime[0].email
    workflow  = google_service_account.week7_workflow[0].email
    scheduler = try(google_service_account.week7_scheduler[0].email, null)
  } : null
}

output "week7_ci_compile_service_account" {
  description = "Read-only, keyless GitHub OIDC identity used only for trusted P7 branch dbt compile checks."
  value       = try(google_service_account.week7_ci_compile[0].email, null)
}

output "week7_ci_workload_identity_provider" {
  description = "Constrained GitHub OIDC provider for upstream P7 branch pushes and main."
  value       = try(google_iam_workload_identity_pool_provider.week7_ci_github[0].name, null)
}
