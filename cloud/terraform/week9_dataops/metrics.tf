locals {
  week9_dq_event_metrics = {
    DQ_GATE_FAILED   = "dq_gate_failed"
    SCHEMA_DRIFT     = "schema_drift"
    FRESHNESS_BREACH = "freshness_breach"
    VOLUME_ANOMALY   = "volume_anomaly"
    DQ_HEARTBEAT     = "heartbeat"
  }
}

resource "google_logging_metric" "week9_dq_event" {
  for_each = var.enable_dq_alerting ? local.week9_dq_event_metrics : {}

  project     = var.project_id
  name        = "dataforge_w9_dq_${each.value}"
  description = "Counts structured Week 9 ${each.key} events from isolated DQ runs."
  filter      = <<-EOT
    logName="projects/${var.project_id}/logs/dataforge-week9-dq"
    AND resource.type="global"
    AND jsonPayload.event_type="${each.key}"
    AND (jsonPayload.dataset="w9_drill" OR jsonPayload.dataset=~"^dbt_ci_pr_[A-Za-z0-9_-]+$")
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "DataForge W9 ${each.key} events"

    labels {
      key         = "severity"
      value_type  = "STRING"
      description = "DQ severity from the structured event."
    }

    labels {
      key         = "status"
      value_type  = "STRING"
      description = "DQ event status from the structured event."
    }
  }

  label_extractors = {
    severity = "EXTRACT(jsonPayload.severity)"
    status   = "EXTRACT(jsonPayload.status)"
  }
}
