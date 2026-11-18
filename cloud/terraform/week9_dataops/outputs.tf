output "wif_provider_name" {
  description = "Full provider resource name for the integrator's GitHub Actions variable."
  value       = google_iam_workload_identity_pool_provider.github_oidc.name
}

output "ci_dbt_service_account_email" {
  description = "Keyless CI service account email for the integrator's repository variable."
  value       = google_service_account.ci_dbt.email
}

output "meta_read_service_account_email" {
  description = "Keyless metadata reader service account email."
  value       = google_service_account.meta_read.email
}

output "w9_dataset_ids" {
  description = "W9 datasets created by this Terraform root."
  value       = local.w9_dataset_ids
}

output "w9_secret_ids" {
  description = "Empty W9 secret containers; no secret versions are created."
  value       = local.w9_secret_ids
}

output "dq_logging_metric_names" {
  description = "Week 9 structured-event log metrics; empty while DQ alerting is disabled."
  value = {
    for event_type, metric in google_logging_metric.week9_dq_event : event_type => metric.name
  }
}

output "dq_alert_policy_names" {
  description = "Week 9 P1 and heartbeat policies; the heartbeat policy is disabled by default."
  value = concat(
    [for policy in values(google_monitoring_alert_policy.week9_dq_p1) : policy.name],
    [for policy in google_monitoring_alert_policy.week9_dq_deadman : policy.name],
  )
}
