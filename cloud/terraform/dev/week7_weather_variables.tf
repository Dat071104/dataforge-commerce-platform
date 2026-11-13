variable "week7_weather_enabled" {
  description = "Whether to create the isolated Week-7 Mini-project 3 weather datasets, jobs, workflow, and least-privilege identities. Defaults off."
  type        = bool
  default     = false

  validation {
    condition = !var.week7_weather_enabled || (
      var.week7_orchestration_enabled &&
      var.week7_artifact_registry_enabled &&
      var.week7_weather_dbt_image != null &&
      var.week7_weather_ingest_image != null
    )
    error_message = "Mini-project 3 requires separate digest-pinned weather dbt and weather-ingest images in the existing Week-7 repository."
  }
}

variable "week7_weather_dbt_image" {
  description = "Digest-pinned dbt runner image built with the isolated Mini-project 3 weather models; kept separate from the accepted commerce dbt job image."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.week7_weather_dbt_image == null || can(regex(
      "^${var.region}-docker\\.pkg\\.dev/${var.project_id}/dataforge-week7/weather-dbt@sha256:[0-9a-f]{64}$",
      var.week7_weather_dbt_image
    ))
    error_message = "When set, week7_weather_dbt_image must be a digest-pinned isolated Mini3 dbt image in this project's existing Week-7 Artifact Registry repository."
  }
}

variable "week7_weather_ingest_image" {
  description = "Digest-pinned Mini-project 3 source-ingestion image in the existing private Week-7 Artifact Registry repository."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.week7_weather_ingest_image == null || can(regex(
      "^${var.region}-docker\\.pkg\\.dev/${var.project_id}/dataforge-week7/weather-ingest@sha256:[0-9a-f]{64}$",
      var.week7_weather_ingest_image
    ))
    error_message = "When set, week7_weather_ingest_image must be a digest-pinned weather-ingest image in this project's existing Week-7 Artifact Registry repository."
  }
}

variable "week7_weather_scheduler_enabled" {
  description = "Whether to create the temporary Mini-project 3 Scheduler trigger. Keep false except for the bounded timed demonstration."
  type        = bool
  default     = false

  validation {
    condition = !var.week7_weather_scheduler_enabled || (
      var.week7_weather_enabled && var.week7_weather_scheduler_creator_member != null
    )
    error_message = "The temporary Mini-project 3 Scheduler requires week7_weather_enabled and an explicitly configured creator member."
  }
}

variable "week7_weather_scheduler_paused" {
  description = "Whether the temporary Mini-project 3 Scheduler job is paused. Defaults to true."
  type        = bool
  default     = true
}

variable "week7_weather_schedule" {
  description = "Cron schedule for the temporary Mini-project 3 run; interpreted in Asia/Ho_Chi_Minh."
  type        = string
  default     = "0 9 * * *"

  validation {
    condition     = length(trimspace(var.week7_weather_schedule)) > 0
    error_message = "week7_weather_schedule must be a non-empty cron expression."
  }
}

variable "week7_weather_scheduler_creator_member" {
  description = "Explicit principal allowed to attach the Scheduler caller identity when the temporary job is created. Do not infer this value."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.week7_weather_scheduler_creator_member == null || can(regex(
      "^(user|serviceAccount|group):[^ ]+$",
      var.week7_weather_scheduler_creator_member
    ))
    error_message = "week7_weather_scheduler_creator_member must be an explicit user:, serviceAccount:, or group: IAM member."
  }
}

variable "week7_weather_airflow_impersonator_member" {
  description = "Optional explicitly supplied principal allowed to impersonate only the local Airflow integration service account. Do not infer this value."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.week7_weather_airflow_impersonator_member == null || can(regex(
      "^(user|serviceAccount|group):[^ ]+$",
      var.week7_weather_airflow_impersonator_member
    ))
    error_message = "week7_weather_airflow_impersonator_member must be an explicit user:, serviceAccount:, or group: IAM member."
  }
}

variable "week7_weather_alert_enabled" {
  description = "Whether to create the temporary failure-only Monitoring policy for the one user-approved alert test. Disable after delivery verification."
  type        = bool
  default     = false

  validation {
    condition = !var.week7_weather_alert_enabled || (
      var.week7_weather_enabled && (
        var.week7_weather_notification_channel_enabled ||
        length(var.week7_weather_notification_channel_ids) > 0
      )
    )
    error_message = "The temporary Mini-project 3 alert policy requires the weather pipeline and a user-approved channel."
  }
}

variable "week7_weather_notification_channel_enabled" {
  description = "Whether to create a temporary email channel for exactly one user-approved controlled alert test; defaults off and must be removed afterward."
  type        = bool
  default     = false

  validation {
    condition = !var.week7_weather_notification_channel_enabled || (
      var.week7_weather_enabled &&
      var.week7_weather_notification_email != null
    )
    error_message = "Creating the temporary email notification channel requires the Mini3 weather resources and an explicit approved email input."
  }
}

variable "week7_weather_notification_email" {
  description = "Sensitive, one-time user-approved email destination for the controlled alert test. Never commit this value or include it in receipts."
  type        = string
  default     = null
  nullable    = true
  sensitive   = true

  validation {
    condition = var.week7_weather_notification_email == null || can(regex(
      "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$",
      var.week7_weather_notification_email
    ))
    error_message = "The alert email must be a valid single address; the value is not displayed."
  }
}

variable "week7_weather_notification_channel_ids" {
  description = "Optional existing, user-approved Monitoring notification channel resource names. No destination is inferred."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for channel_id in var.week7_weather_notification_channel_ids : can(regex(
        "^projects/${var.project_id}/notificationChannels/[A-Za-z0-9_-]+$",
        channel_id
      ))
    ])
    error_message = "Each channel must be a full notification-channel resource name in the approved DataForge project."
  }
}
