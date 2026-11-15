terraform {
  required_version = "= 1.17.1"

  # The bootstrap root moves into its own prefix after the bucket is verified.
  backend "gcs" {}

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 8.9.0"
    }
  }
}

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
}
