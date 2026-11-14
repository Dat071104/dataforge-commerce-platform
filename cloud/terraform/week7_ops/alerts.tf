locals {
  week7_workflow_name = "dataforge-week7-weather-orchestrator"
}

resource "google_logging_metric" "week7_workflow_failed" {
  count       = var.enable_alerting ? 1 : 0
  project     = var.project_id
  name        = "dataforge_week7_workflows_failed"
  description = "Counts error-severity executions for the Week-7 Mini3 Workflow."
  filter      = <<-EOT
    resource.type="workflows.googleapis.com/Workflow"
    AND resource.labels.workflow_id="${local.week7_workflow_name}"
    AND severity>=ERROR
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "DataForge Week-7 Workflow failures"
  }
}

resource "google_logging_metric" "week7_airflow_failed" {
  count       = var.enable_alerting ? 1 : 0
  project     = var.project_id
  name        = "dataforge_week7_airflow_pipeline_failed"
  description = "Counts terminal Airflow PIPELINE_FAILED events from the scoped gcplogs container."
  filter      = <<-EOT
    resource.type="gce_instance"
    AND labels.container_name="${var.airflow_container_label}"
    AND (
      textPayload:"PIPELINE_FAILED"
      OR jsonPayload.event_type="PIPELINE_FAILED"
      OR jsonPayload.message:"PIPELINE_FAILED"
    )
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "DataForge Airflow PIPELINE_FAILED events"
  }
}

resource "google_logging_metric" "week7_airflow_deadline_missed" {
  count       = var.enable_alerting ? 1 : 0
  project     = var.project_id
  name        = "dataforge_week7_airflow_pipeline_deadline_missed"
  description = "Counts Airflow PIPELINE_DEADLINE_MISSED events from the scoped gcplogs container."
  filter      = <<-EOT
    resource.type="gce_instance"
    AND labels.container_name="${var.airflow_container_label}"
    AND (
      textPayload:"PIPELINE_DEADLINE_MISSED"
      OR jsonPayload.event_type="PIPELINE_DEADLINE_MISSED"
      OR jsonPayload.message:"PIPELINE_DEADLINE_MISSED"
    )
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "DataForge Airflow deadline events"
  }
}

resource "google_monitoring_alert_policy" "week7_workflow_failed" {
  count        = var.enable_alerting ? 1 : 0
  project      = var.project_id
  display_name = "DataForge Week-7 Mini3 Workflows FAILED"
  combiner     = "OR"
  enabled      = true
  severity     = "ERROR"

  notification_channels = [google_monitoring_notification_channel.week7_ops_email[0].name]

  documentation {
    content   = "Week-7 Mini3 Workflow failed. Use the runbook: ${var.runbook_url}"
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Workflow execution error"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.week7_workflow_failed[0].name}\" AND resource.type=\"workflows.googleapis.com/Workflow\""
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
}

resource "google_monitoring_alert_policy" "week7_airflow_failed" {
  count        = var.enable_alerting ? 1 : 0
  project      = var.project_id
  display_name = "DataForge Airflow PIPELINE_FAILED"
  combiner     = "OR"
  enabled      = true
  severity     = "ERROR"

  notification_channels = [google_monitoring_notification_channel.week7_ops_email[0].name]

  documentation {
    content   = "Airflow reported a terminal Mini3 failure. Inspect the task and runbook: ${var.runbook_url}"
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Terminal Airflow failure event"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.week7_airflow_failed[0].name}\" AND resource.type=\"gce_instance\""
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
}

resource "google_monitoring_alert_policy" "week7_airflow_deadline_missed" {
  count        = var.enable_alerting ? 1 : 0
  project      = var.project_id
  display_name = "DataForge Airflow PIPELINE_DEADLINE_MISSED"
  combiner     = "OR"
  enabled      = true
  severity     = "WARNING"

  notification_channels = [google_monitoring_notification_channel.week7_ops_email[0].name]

  documentation {
    content   = "The Airflow DagRun missed its deadline. Inspect the runbook: ${var.runbook_url}"
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Airflow deadline event"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.week7_airflow_deadline_missed[0].name}\" AND resource.type=\"gce_instance\""
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
}
