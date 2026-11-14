resource "google_storage_bucket" "terraform_state" {
  project                     = var.project_id
  name                        = var.bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  deletion_policy             = "PREVENT"

  versioning {
    enabled = true
  }

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    purpose     = "terraform-state"
    phase       = "week7"
  }
}
