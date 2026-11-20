variable "project_id" {
  description = "Explicit authorized W9 project; pass dataforge-p7-lab-d0f725 at plan time."
  type        = string

  validation {
    condition     = var.project_id == "dataforge-p7-lab-d0f725"
    error_message = "This module is authorized only for project dataforge-p7-lab-d0f725."
  }
}

variable "region" {
  description = "Authorized W9 dataset region."
  type        = string
  default     = "us-central1"

  validation {
    condition     = var.region == "us-central1"
    error_message = "Week 9 resources are authorized only in us-central1."
  }
}

variable "enable_dq_alerting" {
  description = "Create Week 9 DQ log metrics and alert policies. Defaults off until the C9 channel and live event schema are reviewed."
  type        = bool
  default     = false

  validation {
    condition = !var.enable_dq_alerting || (
      var.c9_email_notification_channel_name != null &&
      can(regex(
        "^projects/${var.project_id}/notificationChannels/[0-9]+$",
        var.c9_email_notification_channel_name
      ))
    )
    error_message = "Week 9 DQ alerting requires the full C9 notification-channel name from the same project."
  }
}

variable "enable_dq_deadman" {
  description = "Enable the daily no-DQ-heartbeat policy. Keep false until a live schedule and maintenance window are verified."
  type        = bool
  default     = false

  validation {
    condition     = !var.enable_dq_deadman || var.enable_dq_alerting
    error_message = "The DQ dead-man policy requires enable_dq_alerting=true and the reviewed C9 channel."
  }
}

variable "enable_dq_freshness_alert" {
  description = "Create the P1 freshness policy after the data schedule is active. Keep false while the pipeline is intentionally stopped."
  type        = bool
  default     = false

  validation {
    condition     = !var.enable_dq_freshness_alert || var.enable_dq_alerting
    error_message = "The freshness policy requires enable_dq_alerting=true and the reviewed C9 channel."
  }
}

variable "c9_email_notification_channel_name" {
  description = "Full resource name of the existing C9 email channel, supplied at plan/apply time; never create a duplicate channel here."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.c9_email_notification_channel_name == null || can(regex(
      "^projects/${var.project_id}/notificationChannels/[0-9]+$",
      var.c9_email_notification_channel_name
    ))
    error_message = "C9 channel name must be projects/<project_id>/notificationChannels/<numeric-id>."
  }
}
