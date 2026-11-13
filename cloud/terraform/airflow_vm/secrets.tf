resource "google_secret_manager_secret" "airflow" {
  for_each  = var.enable_secrets ? local.airflow_secret_ids : toset([])
  project   = var.project_id
  secret_id = "airflow-${replace(each.key, "_", "-")}"

  replication {
    auto {}
  }

  labels = {
    application = "dataforge"
    phase       = "week7"
    owner       = "airflow-vm"
  }

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_version" "airflow" {
  for_each = var.enable_secrets ? local.airflow_secret_ids : toset([])
  secret   = google_secret_manager_secret.airflow[each.key].id

  # Write-only payload bytes are not retained in Terraform state. Increment
  # airflow_secret_data_version only for an approved secret rotation.
  secret_data_wo         = var.airflow_secret_payloads[each.key]
  secret_data_wo_version = var.airflow_secret_data_version
  deletion_policy        = "DISABLE"
}

resource "google_secret_manager_secret_iam_member" "airflow_vm_accessor" {
  for_each  = var.enable_secrets ? local.airflow_secret_ids : toset([])
  project   = var.project_id
  secret_id = google_secret_manager_secret.airflow[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.airflow_service_account_email}"
}
