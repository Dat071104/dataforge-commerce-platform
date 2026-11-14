locals {
  notification_channel_enabled = var.enable_budget || var.enable_alerting
}

data "google_project" "target" {
  project_id = var.project_id
}

# C2 API enablement is gated; Monitoring/Logging APIs are preflight-only because
# they are not in the C1 API list in this authorization block.
resource "google_project_service" "billingbudgets" {
  count   = var.enable_budget ? 1 : 0
  project = var.project_id
  service = "billingbudgets.googleapis.com"

  disable_on_destroy = false
}

resource "google_project_service" "cloudbilling" {
  count   = var.enable_budget ? 1 : 0
  project = var.project_id
  service = "cloudbilling.googleapis.com"

  disable_on_destroy = false
}

resource "google_monitoring_notification_channel" "week7_ops_email" {
  count        = local.notification_channel_enabled ? 1 : 0
  project      = var.project_id
  display_name = "DataForge Week 7 operations"
  type         = "email"
  enabled      = true
  description  = "C2 budget and C3 Week-7 failure notifications."

  labels = {
    email_address = var.notification_email
  }

  user_labels = {
    application = "dataforge"
    phase       = "week7"
  }
}

resource "google_billing_budget" "week7" {
  count           = var.enable_budget ? 1 : 0
  billing_account = var.billing_account_id
  display_name    = "DataForge Week 7 - USD 20"

  budget_filter {
    projects = [format("projects/%s", data.google_project.target.number)]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = "20"
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [
      google_monitoring_notification_channel.week7_ops_email[0].id,
    ]
    disable_default_iam_recipients = true
  }

  depends_on = [
    google_project_service.billingbudgets,
    google_project_service.cloudbilling,
  ]
}