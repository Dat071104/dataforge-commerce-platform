variable "project_id" {
  description = "Explicitly approved Google Cloud project ID. No default project is inferred."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid lowercase Google Cloud project ID."
  }
}

variable "bucket_name" {
  description = "Globally unique name for the private Bronze bucket."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name)) && !strcontains(var.bucket_name, "..")
    error_message = "bucket_name must be a valid lowercase GCS bucket name."
  }
}

variable "region" {
  description = "Candidate single region for synthetic-only work; confirm approval and pricing before apply."
  type        = string
  default     = "us-central1"

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]$", var.region))
    error_message = "region must be a single-region location such as us-central1."
  }
}

variable "transfer_member" {
  description = "Optional principal for local ADC transfers, for example user:person@example.com."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.transfer_member == null || can(regex("^(user|serviceAccount|group):[^ ]+$", var.transfer_member))
    error_message = "transfer_member must be a user:, serviceAccount:, or group: IAM member."
  }
}

variable "runtime_test_member" {
  description = "Optional principal allowed to impersonate only the DataForge runtime service account for an authorized identity smoke test."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.runtime_test_member == null || can(regex("^(user|serviceAccount|group):[^ ]+$", var.runtime_test_member))
    error_message = "runtime_test_member must be a user:, serviceAccount:, or group: IAM member."
  }
}

variable "staging_table_expiration_ms" {
  description = "Default lifetime for disposable BigQuery staging tables; seven days by default."
  type        = number
  default     = 604800000

  validation {
    condition     = var.staging_table_expiration_ms >= 3600000
    error_message = "Staging table expiration must be at least one hour."
  }
}

variable "week5_container_image" {
  description = "Digest-pinned Week-5 processor image in the approved Artifact Registry repository. Update only after building and pushing a reviewed image."
  type        = string
  default     = "us-central1-docker.pkg.dev/dataforge-p7-lab-d0f725/dataforge-week5/processor@sha256:e94fe5c6a54a76568ad5760c45be4791c17aa7b4f43029aae6f081219fb1ecea"
  nullable    = false

  validation {
    condition = can(regex(
      "^${var.region}-docker\\.pkg\\.dev/${var.project_id}/dataforge-week5/processor(:[A-Za-z0-9_.-]{1,128}|@sha256:[0-9a-f]{64})$",
      var.week5_container_image
    ))
    error_message = "week5_container_image must be the Week-5 processor tag or sha256 digest in this project and region."
  }
}

variable "week5_job_enabled" {
  description = "Whether to create the finite Week-5 job. Disable only for the first additive apply that creates APIs and its image repository before the immutable image is pushed."
  type        = bool
  default     = true
}
