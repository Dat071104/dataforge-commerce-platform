variable "project_id" {
  description = "The approved DataForge project. No default project is inferred."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be an explicit lowercase Google Cloud project ID."
  }
}

variable "region" {
  description = "Approved deployment region."
  type        = string
  default     = "us-central1"
}















variable "enable_budget" {
  description = "Create the approved USD 20 monthly budget and thresholds. Defaults off."
  type        = bool
  default     = false

  validation {
    condition     = !var.enable_budget || (var.billing_account_id != null && var.notification_email != null)
    error_message = "Budget creation requires a verified billing account ID and the C9 notification email supplied outside version control."
  }
}

variable "billing_account_id" {
  description = "Verified billing account resource ID. Never infer it from the default gcloud account."
  type        = string
  default     = null
  nullable    = true
}

variable "enable_alerting" {
  description = "Create permanent Week-7 workflow and Airflow failure alert policies. Defaults off."
  type        = bool
  default     = false

  validation {
    condition     = !var.enable_alerting || var.notification_email != null
    error_message = "Permanent alerting requires the C9 destination to be supplied outside version control."
  }
}

variable "notification_email" {
  description = "C9 notification destination. Supply at apply time using a protected local variable source; never commit it."
  type        = string
  default     = null
  nullable    = true
  sensitive   = true

  validation {
    condition     = var.notification_email == null || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.notification_email))
    error_message = "notification_email must be one valid email address."
  }
}

variable "airflow_container_label" {
  description = "Docker gcplogs container_name label emitted by the reviewed Airflow runtime bundle."
  type        = string
  default     = "airflow-scheduler"
}

variable "runbook_url" {
  description = "Public runbook location recorded in alert policy documentation."
  type        = string
  default     = "https://github.com/Dat071104/dataforge-commerce-platform/blob/main/docs/cloud/week7/ops/README.md"
}
