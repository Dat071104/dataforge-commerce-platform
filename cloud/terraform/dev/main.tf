resource "google_storage_bucket" "bronze" {
  project                     = var.project_id
  name                        = var.bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  deletion_policy             = "PREVENT"

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week4"
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }

    condition {
      age            = 30
      matches_prefix = ["tmp/"]
    }
  }
}

resource "google_bigquery_dataset" "staging" {
  project                     = var.project_id
  dataset_id                  = "staging"
  friendly_name               = "DataForge temporary staging"
  description                 = "Disposable synthetic-only batch landing tables; no published marts."
  location                    = var.region
  default_table_expiration_ms = var.staging_table_expiration_ms
  delete_contents_on_destroy  = false
  deletion_policy             = "PREVENT"

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week4"
  }
}

resource "google_bigquery_dataset" "silver" {
  project                    = var.project_id
  dataset_id                 = "silver"
  friendly_name              = "DataForge conformed Silver"
  description                = "Future typed/conformed data; created only, no Week-4 jobs write here."
  location                   = var.region
  delete_contents_on_destroy = false
  deletion_policy            = "PREVENT"

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week4"
  }
}

resource "google_bigquery_dataset" "gold" {
  project                    = var.project_id
  dataset_id                 = "gold"
  friendly_name              = "DataForge curated Gold"
  description                = "Future analytics marts; created only, no Week-4 jobs write here."
  location                   = var.region
  delete_contents_on_destroy = false
  deletion_policy            = "PREVENT"

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week4"
  }
}

resource "google_bigquery_dataset" "ops" {
  project                    = var.project_id
  dataset_id                 = "ops"
  friendly_name              = "DataForge Week-5 operations"
  description                = "Narrow Week-5 journal checkpoint, writer lock, and append-only run-event history."
  location                   = var.region
  delete_contents_on_destroy = false
  deletion_policy            = "PREVENT"

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week5"
  }
}

resource "google_project_service" "run" {
  project                    = var.project_id
  service                    = "run.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "artifact_registry" {
  project                    = var.project_id
  service                    = "artifactregistry.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_artifact_registry_repository" "week5" {
  project         = var.project_id
  location        = var.region
  repository_id   = "dataforge-week5"
  description     = "Private Docker images for the finite DataForge Week-5 BigQuery batch job."
  format          = "DOCKER"
  deletion_policy = "PREVENT"

  docker_config {
    immutable_tags = true
  }

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week5"
  }

  depends_on = [google_project_service.artifact_registry]
}

locals {
  week5_container_image = var.week5_container_image
}

resource "google_cloud_run_v2_job" "week5_processor" {
  count               = var.week5_job_enabled ? 1 : 0
  project             = var.project_id
  name                = "dataforge-week5-processor"
  location            = var.region
  deletion_protection = true

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week5"
  }

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.runtime.email
      max_retries     = 1
      timeout         = "600s"

      containers {
        image = local.week5_container_image

        env {
          name  = "DATAFORGE_PROJECT_ID"
          value = var.project_id
        }

        env {
          name  = "DATAFORGE_BRONZE_BUCKET"
          value = var.bucket_name
        }

        env {
          name  = "DATAFORGE_CLOUD_REGION"
          value = var.region
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        # Leave args unset; each execution supplies its immutable manifest
        # URI/generation through the approved per-execution --args override.
      }
    }
  }

  depends_on = [
    google_project_service.run,
    google_project_service.artifact_registry,
    google_artifact_registry_repository.week5,
  ]
}

resource "google_service_account" "runtime" {
  project         = var.project_id
  account_id      = "dataforge-runtime"
  display_name    = "DataForge future batch runtime"
  description     = "Week-5+ workload identity; no service-account key is created."
  deletion_policy = "PREVENT"
}

resource "google_service_account_iam_member" "runtime_test_token_creator" {
  count = var.runtime_test_member == null ? 0 : 1

  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = var.runtime_test_member
}

resource "google_storage_bucket_iam_member" "runtime_object_viewer" {
  bucket = google_storage_bucket.bronze.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket_iam_member" "runtime_bucket_viewer" {
  bucket = google_storage_bucket.bronze.name
  role   = "roles/storage.bucketViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_service_usage_consumer" {
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_bigquery_dataset_iam_member" "runtime_staging_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.staging.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_bigquery_dataset_iam_member" "runtime_silver_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.silver.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_bigquery_dataset_iam_member" "runtime_gold_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.gold.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_bigquery_dataset_iam_member" "runtime_ops_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.ops.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket_iam_member" "transfer_object_creator" {
  count  = var.transfer_member == null ? 0 : 1
  bucket = google_storage_bucket.bronze.name
  role   = "roles/storage.objectCreator"
  member = var.transfer_member
}

resource "google_storage_bucket_iam_member" "transfer_object_viewer" {
  count  = var.transfer_member == null ? 0 : 1
  bucket = google_storage_bucket.bronze.name
  role   = "roles/storage.objectViewer"
  member = var.transfer_member
}

resource "google_storage_bucket_iam_member" "transfer_bucket_viewer" {
  count  = var.transfer_member == null ? 0 : 1
  bucket = google_storage_bucket.bronze.name
  role   = "roles/storage.bucketViewer"
  member = var.transfer_member
}

resource "google_project_iam_member" "transfer_bigquery_job_user" {
  count   = var.transfer_member == null ? 0 : 1
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = var.transfer_member
}

resource "google_project_iam_member" "transfer_service_usage_consumer" {
  count   = var.transfer_member == null ? 0 : 1
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = var.transfer_member
}

resource "google_bigquery_dataset_iam_member" "transfer_staging_editor" {
  count      = var.transfer_member == null ? 0 : 1
  project    = var.project_id
  dataset_id = google_bigquery_dataset.staging.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = var.transfer_member
}
