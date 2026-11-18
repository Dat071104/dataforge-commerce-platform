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
