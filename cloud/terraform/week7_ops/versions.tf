terraform {
  required_version = "= 1.17.1"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 8.9.0"
    }
  }

  # This root owns only Week-7 ops resources. Supply a verified, versioned
  # bucket and prefix through an ignored backend.hcl after C10 preflight.
  backend "gcs" {}
}

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
}
