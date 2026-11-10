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
