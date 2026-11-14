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

variable "zone" {
  description = "Single zone for the short-lived Airflow VM."
  type        = string
  default     = "us-central1-a"

  validation {
    condition     = startswith(var.zone, "${var.region}-")
    error_message = "zone must be in the configured region."
  }
}

variable "subnet_cidr" {
  description = "A CIDR verified against the project's current VPC inventory before apply."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.subnet_cidr == null || can(cidrhost(var.subnet_cidr, 0))
    error_message = "subnet_cidr must be an explicit, valid IPv4 CIDR when the VM is enabled."
  }
}

variable "enable_vm" {
  description = "Create the short-lived, IAP-only Airflow VM. Defaults off."
  type        = bool
  default     = false

  validation {
    condition = !var.enable_vm || (
      var.enable_secrets &&
      var.airflow_service_account_email != null &&
      var.airflow_image != null &&
      var.subnet_cidr != null &&
      var.destroy_by != null
    )
    error_message = "VM creation requires the VM secrets, existing scoped service account, digest-pinned image, verified subnet CIDR, and destroy_by."
  }
}

variable "enable_secrets" {
  description = "Create the three VM-only Secret Manager values. Defaults off; may be applied before the VM."
  type        = bool
  default     = false

  validation {
    condition     = !var.enable_secrets || var.airflow_service_account_email != null
    error_message = "C8 secrets require the verified existing VM service account."
  }
}

variable "airflow_service_account_email" {
  description = "The explicitly verified existing least-privilege Airflow service account. Do not create a key."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.airflow_service_account_email == null || can(regex(
      "^[a-z][a-z0-9-]*@${var.project_id}\\.iam\\.gserviceaccount\\.com$",
      var.airflow_service_account_email
    ))
    error_message = "airflow_service_account_email must belong to the explicit project."
  }
}

variable "airflow_image" {
  description = "CI-built Airflow runtime image, pinned by digest in the approved private Artifact Registry repository."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.airflow_image == null || can(regex(
      "^${var.region}-docker\\.pkg\\.dev/${var.project_id}/dataforge-week7/airflow@sha256:[0-9a-f]{64}$",
      var.airflow_image
    ))
    error_message = "airflow_image must be a digest-pinned image in the approved project's Week-7 repository."
  }
}

variable "airflow_startup_script" {
  description = "Optional startup script override. Defaults to the script bundled with the reviewed Airflow runtime image source."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.airflow_startup_script == null || length(trimspace(var.airflow_startup_script)) > 0
    error_message = "airflow_startup_script must be non-empty when explicitly overridden."
  }
}

variable "weather_cloud_enabled" {
  description = "Explicit Airflow cloud execution gate; keep false until the C5 schedule preflight is complete."
  type        = bool
  default     = false
}

variable "destroy_by" {
  description = "UTC RFC3339 deadline no more than 120 hours after VM creation; copied to the VM destroy_by label."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.destroy_by == null || can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.destroy_by))
    error_message = "destroy_by must be a UTC RFC3339 timestamp ending in Z."
  }
}

variable "machine_type" {
  description = "C4-authorized VM shape. e2-medium is the approved maximum."
  type        = string
  default     = "e2-medium"

  validation {
    condition     = contains(["e2-micro", "e2-small", "e2-medium"], var.machine_type)
    error_message = "Choose e2-medium or a smaller shared-core VM."
  }
}

variable "boot_disk_size_gb" {
  description = "C4-authorized boot disk size."
  type        = number
  default     = 30

  validation {
    condition     = var.boot_disk_size_gb >= 20 && var.boot_disk_size_gb <= 30 && floor(var.boot_disk_size_gb) == var.boot_disk_size_gb
    error_message = "The boot disk must be a whole number of GiB between 20 and 30."
  }
}

variable "boot_image" {
  description = "Google-maintained Debian image family for the VM host."
  type        = string
  default     = "projects/debian-cloud/global/images/family/debian-12"
}

variable "airflow_secret_payloads" {
  description = "One-time generated secret payloads keyed by the three approved secret IDs. Values use provider write-only secret_data_wo and are never output."
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "airflow_secret_data_version" {
  description = "Increment to add a new write-only version for each managed VM secret."
  type        = number
  default     = 1

  validation {
    condition     = var.airflow_secret_data_version >= 1
    error_message = "airflow_secret_data_version must be a positive integer."
  }
}
