terraform {
  required_version = "= 1.17.1"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 8.9.0"
    }
  }

  # The integrator supplies the reviewed C10 bucket and week9_dataops prefix.
  backend "gcs" {}
}

provider "google" {
  project               = var.project_id
  region                = var.region
  billing_project       = var.project_id
  user_project_override = true
}
