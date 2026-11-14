terraform {
  required_version = "= 1.17.1"

  # C10 state migration is staged but not executed in Phase 2. Use an ignored
  # backend.hcl with the verified versioned state bucket and dev prefix.
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
