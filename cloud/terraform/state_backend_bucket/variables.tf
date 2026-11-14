variable "project_id" {
  description = "The explicitly approved DataForge project."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be an explicit lowercase Google Cloud project ID."
  }
}

variable "region" {
  description = "Region for the versioned Terraform state bucket."
  type        = string
  default     = "us-central1"
}

variable "bucket_name" {
  description = "Globally unique, dedicated Terraform-state bucket name. Verify it does not exist before planning."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name)) && !strcontains(var.bucket_name, "..")
    error_message = "bucket_name must be a valid lowercase GCS bucket name."
  }
}
