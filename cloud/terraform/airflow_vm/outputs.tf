output "airflow_vm_self_link" {
  description = "The short-lived IAP-only Airflow VM, if enabled."
  value       = try(google_compute_instance.airflow[0].self_link, null)
}

output "airflow_vm_internal_ip" {
  description = "Private IP only; the VM has no external access_config."
  value       = try(google_compute_instance.airflow[0].network_interface[0].network_ip, null)
}

output "airflow_secret_names" {
  description = "Secret resource names only; secret payloads are never output."
  value       = var.enable_secrets ? [for secret in google_secret_manager_secret.airflow : secret.id] : []
}

output "airflow_vm_image_digest" {
  description = "Digest-pinned VM runtime image reference; no mutable tag is emitted."
  value       = var.airflow_image
}
