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

# Week-7 resources are additive. The dedicated Artifact Registry repository is
# provisioned separately so an image can be built and pushed before enabling
# Cloud Run/Workflows. Existing Week-4/5 resources are not replaced.
resource "google_project_service" "workflows" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                    = var.project_id
  service                    = "workflows.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "workflow_executions" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                    = var.project_id
  service                    = "workflowexecutions.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "cloud_scheduler" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                    = var.project_id
  service                    = "cloudscheduler.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "week7_iam" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                    = var.project_id
  service                    = "iam.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "week7_iam_credentials" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                    = var.project_id
  service                    = "iamcredentials.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_project_service" "week7_sts" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                    = var.project_id
  service                    = "sts.googleapis.com"
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_artifact_registry_repository" "week7" {
  count = var.week7_artifact_registry_enabled ? 1 : 0

  project         = var.project_id
  location        = var.region
  repository_id   = "dataforge-week7"
  description     = "Private, immutable container images for finite DataForge Week-7 dbt jobs."
  format          = "DOCKER"
  deletion_policy = "PREVENT"

  docker_config {
    immutable_tags = true
  }

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week7"
  }

  depends_on = [google_project_service.artifact_registry]
}

resource "google_bigquery_dataset" "dbt_week7" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                    = var.project_id
  dataset_id                 = "dbt_week7"
  friendly_name              = "DataForge Week-7 incremental dbt build"
  description                = "Finite Week-7 dbt staging and incremental build relations."
  location                   = var.region
  delete_contents_on_destroy = false
  deletion_policy            = "PREVENT"

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week7"
  }
}

resource "google_bigquery_dataset" "dbt_week7_full" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                    = var.project_id
  dataset_id                 = "dbt_week7_full"
  friendly_name              = "DataForge Week-7 full-refresh comparison"
  description                = "Isolated full-refresh comparison relations for Week-7 dbt correctness validation."
  location                   = var.region
  delete_contents_on_destroy = false
  deletion_policy            = "PREVENT"

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week7"
  }
}

resource "google_bigquery_dataset" "gold_week7" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                    = var.project_id
  dataset_id                 = "gold_week7"
  friendly_name              = "DataForge Week-7 validated Gold"
  description                = "Versioned dbt Week-7 reconciliation outputs and publication pointer."
  location                   = var.region
  delete_contents_on_destroy = false
  deletion_policy            = "PREVENT"

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week7"
  }
}

resource "google_bigquery_table" "week7_publish_lock" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project             = var.project_id
  dataset_id          = google_bigquery_dataset.ops.dataset_id
  table_id            = "week7_publish_lock"
  friendly_name       = "DataForge Week-7 publication lock"
  description         = "Singleton lease row serializing Week-7 dbt publication attempts. Seed through the controlled bootstrap SQL."
  deletion_protection = true
  deletion_policy     = "PREVENT"

  schema = jsonencode([
    { name = "lock_name", type = "STRING", mode = "REQUIRED" },
    { name = "lock_owner", type = "STRING", mode = "NULLABLE" },
    { name = "lock_expires_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "lock_version", type = "INT64", mode = "REQUIRED" },
    { name = "updated_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_table" "week7_publish_events" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project             = var.project_id
  dataset_id          = google_bigquery_dataset.ops.dataset_id
  table_id            = "week7_publish_events"
  friendly_name       = "DataForge Week-7 publication event ledger"
  description         = "Append-only execution, lock, validation, and publication evidence for Week-7 workflows."
  deletion_protection = true
  deletion_policy     = "PREVENT"

  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED" },
    { name = "workflow_run_id", type = "STRING", mode = "REQUIRED" },
    { name = "status", type = "STRING", mode = "REQUIRED" },
    { name = "run_mode", type = "STRING", mode = "NULLABLE" },
    { name = "event_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "batch_id", type = "STRING", mode = "NULLABLE" },
    { name = "manifest_generation", type = "INT64", mode = "NULLABLE" },
    { name = "upper_seq", type = "INT64", mode = "NULLABLE" },
    { name = "source_checkpoint_seq", type = "INT64", mode = "NULLABLE" },
    { name = "publication_id", type = "STRING", mode = "NULLABLE" },
    { name = "candidate_dataset", type = "STRING", mode = "NULLABLE" },
    { name = "candidate_row_count", type = "INT64", mode = "NULLABLE" },
    { name = "candidate_sha256", type = "STRING", mode = "NULLABLE" },
    { name = "pointer_version", type = "INT64", mode = "NULLABLE" },
    { name = "message", type = "STRING", mode = "NULLABLE" },
  ])

  time_partitioning {
    type  = "DAY"
    field = "event_at"
  }

  clustering = ["workflow_run_id", "status"]
}

resource "google_bigquery_table" "week7_publication_pointer" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project             = var.project_id
  dataset_id          = google_bigquery_dataset.gold_week7[0].dataset_id
  table_id            = "week7_publication_pointer"
  friendly_name       = "DataForge Week-7 current reconciliation pointer"
  description         = "Singleton pointer switched only after the candidate dbt build and quality tests pass."
  deletion_protection = true
  deletion_policy     = "PREVENT"

  schema = jsonencode([
    { name = "pointer_name", type = "STRING", mode = "REQUIRED" },
    { name = "pointer_version", type = "INT64", mode = "REQUIRED" },
    { name = "published_run_mode", type = "STRING", mode = "NULLABLE" },
    { name = "publication_id", type = "STRING", mode = "NULLABLE" },
    { name = "published_run_id", type = "STRING", mode = "NULLABLE" },
    { name = "batch_id", type = "STRING", mode = "NULLABLE" },
    { name = "manifest_generation", type = "INT64", mode = "NULLABLE" },
    { name = "upper_seq", type = "INT64", mode = "NULLABLE" },
    { name = "source_checkpoint_seq", type = "INT64", mode = "NULLABLE" },
    { name = "candidate_dataset", type = "STRING", mode = "NULLABLE" },
    { name = "candidate_row_count", type = "INT64", mode = "NULLABLE" },
    { name = "candidate_sha256", type = "STRING", mode = "NULLABLE" },
    { name = "published_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "publication_is_current", type = "BOOL", mode = "NULLABLE" },
  ])
}

resource "google_service_account" "week7_dbt_runtime" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project         = var.project_id
  account_id      = "dataforge-week7-dbt"
  display_name    = "DataForge Week-7 dbt runtime"
  description     = "Keyless Cloud Run identity for bounded dbt builds and validated Gold publication."
  deletion_policy = "PREVENT"
}

resource "google_service_account" "week7_workflow" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project         = var.project_id
  account_id      = "dataforge-week7-workflow"
  display_name    = "DataForge Week-7 Workflows runtime"
  description     = "Keyless identity limited to approved manifests and the two finite Cloud Run jobs."
  deletion_policy = "PREVENT"
}

resource "google_service_account" "week7_scheduler" {
  count = var.week7_orchestration_enabled && var.week7_scheduler_enabled ? 1 : 0

  project      = var.project_id
  account_id   = "dataforge-week7-scheduler"
  display_name = "DataForge Week-7 Scheduler caller"
  description  = "Keyless caller allowed to invoke only the Week-7 Workflows execution endpoint."
}

# Read-only GitHub Actions identity for dbt compilation. The external provider
# accepts direct pushes only; pull_request and fork tokens cannot impersonate it.
resource "google_service_account" "week7_ci_compile" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project         = var.project_id
  account_id      = "dataforge-week7-ci-compile"
  display_name    = "DataForge Week-7 read-only dbt CI compile"
  description     = "Keyless GitHub OIDC identity for metadata-only dbt compile; no write or deploy permissions."
  deletion_policy = "PREVENT"
}

resource "google_iam_workload_identity_pool" "week7_ci" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                   = var.project_id
  workload_identity_pool_id = "dataforge-week7-ci"
  display_name              = "DataForge Week-7 GitHub CI"
  description               = "OIDC trust for read-only dbt compilation from trusted upstream P7 branch pushes."
  disabled                  = false

  depends_on = [
    google_project_service.week7_iam,
    google_project_service.week7_iam_credentials,
    google_project_service.week7_sts,
  ]
}

resource "google_iam_workload_identity_pool_provider" "week7_ci_github" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.week7_ci[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions"
  display_name                       = "DataForge GitHub P7 CI"
  description                        = "Rejects pull_request/fork tokens; accepts only upstream P7 feature branch and main pushes."

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.event_name"          = "assertion.event_name"
    "attribute.ref"                 = "assertion.ref"
    "attribute.workflow_ref"        = "assertion.workflow_ref"
  }

  attribute_condition = "assertion.repository_id == '1446796465' && assertion.repository_owner_id == '242334093' && assertion.event_name == 'push' && (assertion.ref == 'refs/heads/main' || assertion.ref.startsWith('refs/heads/feature/p7-')) && assertion.workflow_ref.endsWith('/.github/workflows/week7-ci.yml@' + assertion.ref)"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  depends_on = [google_iam_workload_identity_pool.week7_ci]
}

resource "google_service_account_iam_member" "week7_ci_compile_workload_identity_user" {
  count = var.week7_orchestration_enabled ? 1 : 0

  service_account_id = google_service_account.week7_ci_compile[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.week7_ci[0].name}/attribute.repository_id/1446796465"

  depends_on = [google_iam_workload_identity_pool_provider.week7_ci_github]
}

resource "google_project_iam_member" "week7_ci_compile_bigquery_job_user" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.week7_ci_compile[0].email}"
}

resource "google_project_iam_member" "week7_ci_compile_service_usage_consumer" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.week7_ci_compile[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_ci_compile_silver_metadata" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.silver.dataset_id
  role       = "roles/bigquery.metadataViewer"
  member     = "serviceAccount:${google_service_account.week7_ci_compile[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_ci_compile_ops_metadata" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.ops.dataset_id
  role       = "roles/bigquery.metadataViewer"
  member     = "serviceAccount:${google_service_account.week7_ci_compile[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_ci_compile_gold_metadata" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.gold.dataset_id
  role       = "roles/bigquery.metadataViewer"
  member     = "serviceAccount:${google_service_account.week7_ci_compile[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_ci_compile_target_metadata" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.dbt_week7[0].dataset_id
  role       = "roles/bigquery.metadataViewer"
  member     = "serviceAccount:${google_service_account.week7_ci_compile[0].email}"
}

resource "google_project_iam_custom_role" "week7_scheduler_workflow_execution_create" {
  count = var.week7_orchestration_enabled && var.week7_scheduler_enabled ? 1 : 0

  project     = var.project_id
  role_id     = "dataforge_week7_workflow_execution_create"
  title       = "DataForge Week-7 workflow execution caller"
  description = "Allows the dedicated Week-7 Scheduler identity to create workflow executions only."
  permissions = ["workflows.executions.create"]
  stage       = "GA"
}

resource "google_project_iam_custom_role" "week7_manifest_reader" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project     = var.project_id
  role_id     = "dataforge_week7_manifest_reader"
  title       = "DataForge Week-7 manifest reader"
  description = "Read-only access to exact Week-5 manifest generations used by the Week-7 workflow."
  permissions = ["storage.objects.get"]
  stage       = "GA"
}

resource "google_project_iam_custom_role" "week7_cloud_run_operation_reader" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project     = var.project_id
  role_id     = "dataforge_week7_cloud_run_operation_reader"
  title       = "DataForge Week-7 Cloud Run operation reader"
  description = "Read the long-running operation returned for the two approved Week-7 Cloud Run Jobs."
  permissions = ["run.operations.get"]
  stage       = "GA"
}

resource "google_project_iam_custom_role" "week7_cloud_run_job_runner" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project     = var.project_id
  role_id     = "dataforge_week7_cloud_run_job_runner"
  title       = "DataForge Week-7 Cloud Run Job runner"
  description = "Run the two approved Week-7 Jobs with argument overrides; no job configuration or IAM updates."
  permissions = ["run.jobs.run", "run.jobs.runWithOverrides"]
  stage       = "GA"
}

resource "google_cloud_run_v2_job" "week7_dbt" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project             = var.project_id
  name                = "dataforge-week7-dbt"
  location            = var.region
  deletion_protection = true

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week7"
  }

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.week7_dbt_runtime[0].email
      max_retries     = 0
      timeout         = "240s"

      containers {
        name    = "dbt"
        image   = var.week7_dbt_image
        command = ["dbt"]
        args    = ["build", "--target", "dev"]

        env {
          name  = "DBT_DATAFORGE_PROJECT_ID"
          value = var.project_id
        }

        env {
          name  = "DBT_DATAFORGE_LOCATION"
          value = var.region
        }

        env {
          name  = "DBT_DATAFORGE_SOURCE_DATASET"
          value = "silver"
        }

        env {
          name  = "DBT_DATAFORGE_CONTROL_DATASET"
          value = "ops"
        }

        env {
          name  = "DBT_DATAFORGE_TARGET_DATASET"
          value = "dbt_week7"
        }

        env {
          name  = "DBT_DATAFORGE_FULL_REFRESH_DATASET"
          value = "dbt_week7_full"
        }

        env {
          name  = "DBT_DATAFORGE_GOLD_DATASET"
          value = "gold_week7"
        }

        env {
          name  = "DBT_BIGQUERY_MAXIMUM_BYTES_BILLED"
          value = "268435456"
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.run,
    google_project_service.artifact_registry,
    google_artifact_registry_repository.week7,
    google_bigquery_dataset.dbt_week7,
    google_bigquery_dataset.dbt_week7_full,
    google_bigquery_dataset.gold_week7,
    google_bigquery_table.week7_publish_lock,
    google_bigquery_table.week7_publish_events,
    google_bigquery_table.week7_publication_pointer,
  ]
}

resource "google_workflows_workflow" "week7" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project                 = var.project_id
  name                    = "dataforge-week7-orchestrator"
  region                  = var.region
  description             = "Runs one immutable Week-5 batch, then candidate dbt build/tests and a guarded publication step."
  service_account         = google_service_account.week7_workflow[0].id
  source_contents         = file("${path.module}/../../workflows/week7_workflow.yaml")
  call_log_level          = "LOG_ERRORS_ONLY"
  execution_history_level = "EXECUTION_HISTORY_BASIC"
  deletion_protection     = true

  labels = {
    application = "dataforge"
    environment = "synthetic-dev"
    phase       = "week7"
  }

  user_env_vars = {
    DATAFORGE_PROJECT_ID    = var.project_id
    DATAFORGE_REGION        = var.region
    DATAFORGE_BRONZE_BUCKET = var.bucket_name
    DATAFORGE_WEEK5_JOB     = "dataforge-week5-processor"
    DATAFORGE_WEEK7_DBT_JOB = "dataforge-week7-dbt"
  }

  depends_on = [
    google_project_service.workflows,
    google_cloud_run_v2_job.week5_processor,
    google_cloud_run_v2_job.week7_dbt,
  ]
}

resource "google_cloud_scheduler_job" "week7" {
  count = var.week7_orchestration_enabled && var.week7_scheduler_enabled ? 1 : 0

  project          = var.project_id
  region           = var.region
  name             = "dataforge-week7-no-new-batch"
  description      = "Paused-by-default Week-7 workflow trigger; submits no batch because the source bridge is local."
  schedule         = var.week7_schedule
  time_zone        = "UTC"
  paused           = var.week7_scheduler_paused
  attempt_deadline = "60s"

  retry_config {
    retry_count = 0
  }

  http_target {
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.week7[0].id}/executions"
    http_method = "POST"
    body        = base64encode(jsonencode({ argument = jsonencode({ no_new_batch = true, trigger = "scheduler" }) }))

    headers = {
      "Content-Type" = "application/json"
    }

    oauth_token {
      service_account_email = google_service_account.week7_scheduler[0].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    google_project_service.cloud_scheduler,
    google_project_service.workflow_executions,
    google_project_iam_member.week7_scheduler_workflow_execution_create,
  ]
}

resource "google_storage_bucket_iam_member" "week7_workflow_manifest_viewer" {
  count = var.week7_orchestration_enabled ? 1 : 0

  bucket = google_storage_bucket.bronze.name
  role   = google_project_iam_custom_role.week7_manifest_reader[0].name
  member = "serviceAccount:${google_service_account.week7_workflow[0].email}"

  condition {
    title       = "week7-manifest-objects-only"
    description = "Allow the workflow to read only exact Week-5 manifest objects, not Parquet or other Bronze data."
    expression  = "resource.type == 'storage.googleapis.com/Object' && resource.name.startsWith('projects/_/buckets/${var.bucket_name}/objects/manifests/week5/batch_id=') && resource.name.endsWith('/manifest.json')"
  }
}

resource "google_cloud_run_v2_job_iam_member" "week7_workflow_week5_runner" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.week5_processor[0].name
  role     = google_project_iam_custom_role.week7_cloud_run_job_runner[0].name
  member   = "serviceAccount:${google_service_account.week7_workflow[0].email}"
}

resource "google_cloud_run_v2_job_iam_member" "week7_workflow_dbt_runner" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.week7_dbt[0].name
  role     = google_project_iam_custom_role.week7_cloud_run_job_runner[0].name
  member   = "serviceAccount:${google_service_account.week7_workflow[0].email}"
}

resource "google_project_iam_member" "week7_workflow_cloud_run_operation_reader" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project = var.project_id
  role    = google_project_iam_custom_role.week7_cloud_run_operation_reader[0].name
  member  = "serviceAccount:${google_service_account.week7_workflow[0].email}"
}

resource "google_service_account_iam_member" "week7_workflow_week5_act_as" {
  count = var.week7_orchestration_enabled ? 1 : 0

  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.week7_workflow[0].email}"
}

resource "google_service_account_iam_member" "week7_workflow_dbt_act_as" {
  count = var.week7_orchestration_enabled ? 1 : 0

  service_account_id = google_service_account.week7_dbt_runtime[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.week7_workflow[0].email}"
}

resource "google_service_account_iam_member" "week7_scheduler_creator_act_as" {
  count = var.week7_orchestration_enabled && var.week7_scheduler_enabled && var.week7_scheduler_creator_member != null ? 1 : 0

  service_account_id = google_service_account.week7_scheduler[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = var.week7_scheduler_creator_member
}

resource "google_project_iam_member" "week7_scheduler_workflow_execution_create" {
  count = var.week7_orchestration_enabled && var.week7_scheduler_enabled ? 1 : 0

  project = var.project_id
  role    = google_project_iam_custom_role.week7_scheduler_workflow_execution_create[0].name
  member  = "serviceAccount:${google_service_account.week7_scheduler[0].email}"
}

resource "google_project_iam_member" "week7_workflow_logging_writer" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.week7_workflow[0].email}"
}

resource "google_project_iam_member" "week7_dbt_bigquery_job_user" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_project_iam_member" "week7_dbt_service_usage_consumer" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_project_iam_member" "week7_workflow_bigquery_job_user" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.week7_workflow[0].email}"
}

resource "google_project_iam_member" "week7_workflow_service_usage_consumer" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.week7_workflow[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_dbt_silver_reader" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.silver.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_dbt_week5_gold_reader" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.gold.dataset_id
  table_id   = "week5_order_controls"
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_dbt_ops_metadata_reader" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.ops.dataset_id
  role       = "roles/bigquery.metadataViewer"
  member     = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_dbt_week5_events_reader" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.ops.dataset_id
  table_id   = "week5_run_events"
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_dbt_checkpoints_reader" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.ops.dataset_id
  table_id   = "pipeline_checkpoints"
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_dbt_incremental_writer" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.dbt_week7[0].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_dbt_full_refresh_writer" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.dbt_week7_full[0].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_dbt_gold_writer" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.gold_week7[0].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_dbt_lock_writer" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.ops.dataset_id
  table_id   = google_bigquery_table.week7_publish_lock[0].table_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_dbt_events_writer" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.ops.dataset_id
  table_id   = google_bigquery_table.week7_publish_events[0].table_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.week7_dbt_runtime[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_workflow_events_reader" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.ops.dataset_id
  table_id   = google_bigquery_table.week7_publish_events[0].table_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_workflow[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_workflow_pointer_reader" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.gold_week7[0].dataset_id
  table_id   = google_bigquery_table.week7_publication_pointer[0].table_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_workflow[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_workflow_ops_metadata_reader" {
  count = var.week7_orchestration_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.ops.dataset_id
  role       = "roles/bigquery.metadataViewer"
  member     = "serviceAccount:${google_service_account.week7_workflow[0].email}"
}
