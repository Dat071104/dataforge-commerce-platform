output "budget_id" {
  description = "C2 budget resource name, if enabled."
  value       = try(google_billing_budget.week7[0].id, null)
}

output "alert_policy_names" {
  description = "C3 permanent policy resource names; no alert destinations are output."
  value = var.enable_alerting ? [
    google_monitoring_alert_policy.week7_workflow_failed[0].name,
    google_monitoring_alert_policy.week7_airflow_failed[0].name,
    google_monitoring_alert_policy.week7_airflow_deadline_missed[0].name,
  ] : []
}