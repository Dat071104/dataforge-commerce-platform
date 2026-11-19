locals {
  week9_dq_p1_alerts = {
    dq_gate_failed = {
      event_type = "DQ_GATE_FAILED"
      title      = "P1 DQ gate failure"
      runbook    = "DQ_GATE_FAILED.md"
    }
    schema_drift = {
      event_type = "SCHEMA_DRIFT"
      title      = "P1 schema drift"
      runbook    = "SCHEMA_DRIFT.md"
    }
    freshness_breach = {
      event_type = "FRESHNESS_BREACH"
      title      = "P1 freshness breach"
      runbook    = "FRESHNESS_BREACH.md"
    }
    volume_anomaly = {
      event_type = "VOLUME_ANOMALY"
      title      = "P1 volume anomaly"
      runbook    = "VOLUME_ANOMALY.md"
    }
  }
}

resource "google_monitoring_alert_policy" "week9_dq_p1" {
  for_each = {
    for policy_id, policy in local.week9_dq_p1_alerts : policy_id => policy
    if var.enable_dq_alerting && (policy_id != "freshness_breach" || var.enable_dq_freshness_alert)
  }

  project      = var.project_id
  display_name = "DataForge W9 ${each.value.title}"
  combiner     = "OR"
  enabled      = true
  severity     = "ERROR"

  notification_channels = [var.c9_email_notification_channel_name]

  documentation {
    content   = <<-EOT
      A Week 9 P1 data-quality event was recorded for an isolated dataset.
      Event type: ${each.value.event_type}
      Route: Slack from the DQ runner and this existing C9 Monitoring email channel.
      Runbook: https://github.com/Dat071104/dataforge-commerce-platform/blob/main/docs/week9/runbooks/${each.value.runbook}
    EOT
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "P1 failure for ${each.value.event_type}"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"logging.googleapis.com/user/${google_logging_metric.week9_dq_event[each.value.event_type].name}\"",
        "resource.type=\"global\"",
        "metric.label.severity=\"P1\"",
        "metric.label.status=\"FAIL\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close           = "3600s"
    notification_prompts = ["OPENED"]
  }

  user_labels = {
    application = "dataforge"
    phase       = "week9"
    severity    = "p1"
  }
}

resource "google_monitoring_alert_policy" "week9_dq_deadman" {
  count = var.enable_dq_alerting ? 1 : 0

  project      = var.project_id
  display_name = "DataForge W9 DQ heartbeat missing"
  combiner     = "OR"
  enabled      = var.enable_dq_deadman
  severity     = "WARNING"

  notification_channels = [var.c9_email_notification_channel_name]

  documentation {
    content   = <<-EOT
      No successful Week 9 DQ heartbeat has been logged for 23.5 hours.
      This policy is disabled unless enable_dq_deadman=true. Keep it disabled while the pipeline is intentionally stopped;
      use the documented maintenance window before enabling it after a schedule is established.
      Runbook: https://github.com/Dat071104/dataforge-commerce-platform/blob/main/docs/week9/runbooks/DQ_HEARTBEAT.md
    EOT
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "No isolated DQ heartbeat for 23.5 hours"

    condition_absent {
      filter = format(
        "metric.type=\"logging.googleapis.com/user/%s\" AND resource.type=\"global\"",
        google_logging_metric.week9_dq_event["DQ_HEARTBEAT"].name,
      )
      duration = "84600s"

      aggregations {
        alignment_period     = "84600s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close           = "3600s"
    notification_prompts = ["OPENED"]
  }

  user_labels = {
    application = "dataforge"
    phase       = "week9"
    severity    = "p3"
  }
}
