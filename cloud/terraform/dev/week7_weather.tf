# Additive Mini-project 3 infrastructure. Every resource is opt-in; the
# accepted Week 4/5/7 jobs, datasets, workflow, and IAM bindings are untouched.

resource "google_bigquery_dataset" "week7_weather_landing" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  dataset_id  = "weather_mini3"
  location    = var.region
  description = "Mini-project 3 weather source landing and append-only execution receipts; separate from commerce datasets."
  labels = {
    application = "dataforge"
    phase       = "week7"
    domain      = "weather"
  }
}

resource "google_bigquery_dataset" "week7_weather_candidate" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  dataset_id  = "dbt_weather_mini3"
  location    = var.region
  description = "Isolated Mini-project 3 weather dbt candidates; no order/payment dependencies."
  labels = {
    application = "dataforge"
    phase       = "week7"
    domain      = "weather"
  }
}

resource "google_bigquery_dataset" "week7_weather_candidate_full" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  dataset_id  = "dbt_weather_mini3_full"
  location    = var.region
  description = "Isolated full-refresh comparison target for Mini-project 3 weather dbt models."
  labels = {
    application = "dataforge"
    phase       = "week7"
    domain      = "weather"
  }
}

resource "google_bigquery_dataset" "week7_weather_gold" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  dataset_id  = "gold_weather_mini3"
  location    = var.region
  description = "Versioned Mini-project 3 weather Gold and atomic current-publication pointer."
  labels = {
    application = "dataforge"
    phase       = "week7"
    domain      = "weather"
  }
}

resource "google_bigquery_dataset" "week7_scd2_proof_input" {
  count                       = var.week7_weather_enabled ? 1 : 0
  project                     = var.project_id
  dataset_id                  = "dbt_scd2_proof_input"
  location                    = var.region
  default_table_expiration_ms = 604800000
  description                 = "Seven-day isolated synthetic input for the Week-7 dbt snapshot history proof. Never authoritative commerce data."
  labels = {
    application = "dataforge"
    phase       = "week7"
    domain      = "scd2-proof"
  }
}

resource "google_bigquery_dataset" "week7_scd2_proof_history" {
  count                       = var.week7_weather_enabled ? 1 : 0
  project                     = var.project_id
  dataset_id                  = "dbt_scd2_proof_history"
  location                    = var.region
  default_table_expiration_ms = 604800000
  description                 = "Seven-day isolated synthetic dbt snapshot output for the Week-7 SCD2 proof. Never authoritative commerce history."
  labels = {
    application = "dataforge"
    phase       = "week7"
    domain      = "scd2-proof"
  }
}

resource "google_bigquery_table" "week7_weather_landing" {
  count                    = var.week7_weather_enabled ? 1 : 0
  project                  = var.project_id
  dataset_id               = google_bigquery_dataset.week7_weather_landing[0].dataset_id
  table_id                 = "weather_landing"
  description              = "Typed, partitioned landing rows keyed by request_id, province_id, and observation_date."
  deletion_protection      = true
  require_partition_filter = true
  schema = jsonencode([
    { name = "province_id", type = "STRING", mode = "REQUIRED" },
    { name = "observation_date", type = "DATE", mode = "REQUIRED" },
    { name = "precipitation_mm", type = "FLOAT64", mode = "NULLABLE" },
    { name = "temp_max_c", type = "FLOAT64", mode = "NULLABLE" },
    { name = "source", type = "STRING", mode = "REQUIRED" },
    { name = "model", type = "STRING", mode = "REQUIRED" },
    { name = "request_id", type = "STRING", mode = "REQUIRED" },
    { name = "source_sha256", type = "STRING", mode = "REQUIRED" },
    { name = "manifest_uri", type = "STRING", mode = "REQUIRED" },
    { name = "manifest_generation", type = "INT64", mode = "REQUIRED" },
    { name = "landed_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
  time_partitioning {
    type  = "DAY"
    field = "observation_date"
  }
  clustering = ["province_id", "request_id"]
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_bigquery_table" "week7_weather_execution_ledger" {
  count               = var.week7_weather_enabled ? 1 : 0
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.week7_weather_landing[0].dataset_id
  table_id            = "weather_execution_ledger"
  description         = "Append-only terminal Workflows execution evidence for the Mini-project 3 weather pipeline."
  deletion_protection = true
  schema = jsonencode([
    { name = "event_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "workflow_run_id", type = "STRING", mode = "REQUIRED" },
    { name = "workflow_execution_name", type = "STRING", mode = "REQUIRED" },
    { name = "trigger", type = "STRING", mode = "REQUIRED" },
    { name = "observation_date", type = "DATE", mode = "NULLABLE" },
    { name = "status", type = "STRING", mode = "REQUIRED" },
    { name = "request_id", type = "STRING", mode = "NULLABLE" },
    { name = "manifest_uri", type = "STRING", mode = "NULLABLE" },
    { name = "manifest_generation", type = "INT64", mode = "NULLABLE" },
    { name = "source_sha256", type = "STRING", mode = "NULLABLE" },
    { name = "row_count", type = "INT64", mode = "NULLABLE" },
    { name = "publication_version", type = "INT64", mode = "NULLABLE" },
    { name = "published_sha256", type = "STRING", mode = "NULLABLE" },
    { name = "error_category", type = "STRING", mode = "NULLABLE" }
  ])
  time_partitioning {
    type  = "DAY"
    field = "event_at"
  }
  clustering = ["workflow_run_id", "status"]
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_bigquery_table" "week7_weather_versions" {
  count               = var.week7_weather_enabled ? 1 : 0
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.week7_weather_gold[0].dataset_id
  table_id            = "weather_daily_versions"
  description         = "Append-only, versioned weather Gold rows; never joined into commerce financial controls."
  deletion_protection = true
  schema = jsonencode([
    { name = "publication_version", type = "INT64", mode = "REQUIRED" },
    { name = "publication_run_id", type = "STRING", mode = "REQUIRED" },
    { name = "published_sha256", type = "STRING", mode = "REQUIRED" },
    { name = "published_row_count", type = "INT64", mode = "REQUIRED" },
    { name = "published_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "candidate_dataset", type = "STRING", mode = "REQUIRED" },
    { name = "province_id", type = "STRING", mode = "REQUIRED" },
    { name = "observation_date", type = "DATE", mode = "REQUIRED" },
    { name = "precipitation_mm", type = "FLOAT64", mode = "NULLABLE" },
    { name = "temp_max_c", type = "FLOAT64", mode = "NULLABLE" },
    { name = "precipitation_condition", type = "STRING", mode = "REQUIRED" },
    { name = "source", type = "STRING", mode = "REQUIRED" },
    { name = "model", type = "STRING", mode = "REQUIRED" },
    { name = "request_id", type = "STRING", mode = "REQUIRED" },
    { name = "source_sha256", type = "STRING", mode = "REQUIRED" },
    { name = "manifest_uri", type = "STRING", mode = "REQUIRED" },
    { name = "manifest_generation", type = "INT64", mode = "REQUIRED" },
    { name = "landed_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
  time_partitioning {
    type  = "DAY"
    field = "observation_date"
  }
  clustering = ["province_id", "publication_version"]
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_bigquery_table" "week7_weather_publication_pointer" {
  count               = var.week7_weather_enabled ? 1 : 0
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.week7_weather_gold[0].dataset_id
  table_id            = "weather_publication_pointer"
  description         = "Singleton currentness fence for versioned Mini-project 3 weather Gold."
  deletion_protection = true
  schema = jsonencode([
    { name = "singleton_id", type = "INT64", mode = "REQUIRED" },
    { name = "publication_version", type = "INT64", mode = "REQUIRED" },
    { name = "publication_run_id", type = "STRING", mode = "NULLABLE" },
    { name = "published_sha256", type = "STRING", mode = "NULLABLE" },
    { name = "published_row_count", type = "INT64", mode = "REQUIRED" },
    { name = "publication_is_current", type = "BOOL", mode = "REQUIRED" },
    { name = "updated_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_bigquery_table" "week7_weather_published_view" {
  count               = var.week7_weather_enabled ? 1 : 0
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.week7_weather_gold[0].dataset_id
  table_id            = "published_weather_daily"
  description         = "Current version of the isolated Mini-project 3 weather Gold, selected by its singleton publication pointer."
  deletion_protection = true

  labels = {
    application = "dataforge"
    phase       = "week7"
    domain      = "weather"
  }

  view {
    query          = <<-SQL
      SELECT
        versions.publication_version,
        versions.publication_run_id,
        versions.published_sha256,
        versions.published_row_count,
        versions.published_at,
        versions.candidate_dataset,
        versions.province_id,
        versions.observation_date,
        versions.precipitation_mm,
        versions.temp_max_c,
        versions.precipitation_condition,
        versions.source,
        versions.model,
        versions.request_id,
        versions.source_sha256,
        versions.manifest_uri,
        versions.manifest_generation,
        versions.landed_at
      FROM `${var.project_id}.gold_weather_mini3.weather_daily_versions` AS versions
      JOIN `${var.project_id}.gold_weather_mini3.weather_publication_pointer` AS pointer
        ON pointer.singleton_id = 1
       AND pointer.publication_is_current = TRUE
       AND versions.publication_version = pointer.publication_version
    SQL
    use_legacy_sql = false
  }

  depends_on = [
    google_bigquery_table.week7_weather_versions,
    google_bigquery_table.week7_weather_publication_pointer
  ]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "week7_weather_ingest" {
  count        = var.week7_weather_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "dataforge-week7-weather-ingest"
  display_name = "DataForge Week-7 weather API and typed landing job"
  description  = "Finite, allowlisted Mini-project 3 API/Bronze/landing job; no service-account key."
}

resource "google_service_account" "week7_weather_dbt" {
  count        = var.week7_weather_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "dataforge-week7-weather-dbt"
  display_name = "DataForge Week-7 weather dbt job"
  description  = "Finite Mini-project 3 dbt build, tests, and weather-only publication; no service-account key."
}

resource "google_service_account" "week7_weather_workflow" {
  count        = var.week7_weather_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "dataforge-week7-weather-wf"
  display_name = "DataForge Week-7 weather Workflow"
  description  = "Orchestrates only the two weather jobs and records the Mini-project 3 execution receipt."
}

resource "google_service_account" "week7_weather_scheduler" {
  count        = var.week7_weather_enabled && var.week7_weather_scheduler_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "dataforge-w7-weather-scheduler"
  display_name = "DataForge Week-7 weather Scheduler caller"
  description  = "May create an execution only for the Mini-project 3 weather Workflow."
}

resource "google_service_account" "week7_weather_airflow" {
  count        = var.week7_weather_enabled ? 1 : 0
  project      = var.project_id
  account_id   = "dataforge-week7-airflow"
  display_name = "DataForge Week-7 Airflow integration caller"
  description  = "Optional local Airflow caller with access to the two weather jobs and published weather Gold only."
}

resource "google_cloud_run_v2_job" "week7_weather_ingest" {
  count               = var.week7_weather_enabled ? 1 : 0
  project             = var.project_id
  name                = "dataforge-week7-weather-ingest"
  location            = var.region
  deletion_protection = true

  labels = {
    application = "dataforge"
    phase       = "week7"
    domain      = "weather"
  }

  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = google_service_account.week7_weather_ingest[0].email
      timeout         = "600s"
      max_retries     = 0

      containers {
        name    = "weather-ingest"
        image   = var.week7_weather_ingest_image
        command = ["python", "/app/cloud/jobs/week7_weather/weather_job.py"]
        args    = ["--help"]

        env {
          name  = "DATAFORGE_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "DATAFORGE_WEATHER_BUCKET"
          value = var.bucket_name
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
}

resource "google_cloud_run_v2_job" "week7_weather_dbt" {
  count               = var.week7_weather_enabled ? 1 : 0
  project             = var.project_id
  name                = "dataforge-week7-weather-dbt"
  location            = var.region
  deletion_protection = true

  labels = {
    application = "dataforge"
    phase       = "week7"
    domain      = "weather"
  }

  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = google_service_account.week7_weather_dbt[0].email
      timeout         = "1800s"
      max_retries     = 0

      containers {
        name  = "dbt"
        image = var.week7_weather_dbt_image
        args  = ["--help"]

        env {
          name  = "DBT_DATAFORGE_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "DBT_DATAFORGE_LOCATION"
          value = var.region
        }
        env {
          name  = "DBT_DATAFORGE_WEATHER_DATASET"
          value = "dbt_weather_mini3"
        }
        env {
          name  = "DBT_DATAFORGE_WEATHER_FULL_DATASET"
          value = "dbt_weather_mini3_full"
        }
        env {
          name  = "DBT_DATAFORGE_GOLD_DATASET"
          value = "gold_weather_mini3"
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
}

resource "google_project_iam_custom_role" "week7_weather_ingest_storage" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "dataforge_week7_weather_ingest_storage"
  title       = "DataForge Week-7 weather prefix reader/writer"
  description = "Create-only writes and exact-object reads under the Mini-project 3 prefix."
  permissions = ["storage.objects.create", "storage.objects.get"]
  stage       = "GA"
}

resource "google_project_iam_custom_role" "week7_weather_manifest_reader" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "dataforge_week7_weather_manifest_reader"
  title       = "DataForge Week-7 weather manifest reader"
  description = "Read exact weather manifests and execution receipts without listing or writing objects."
  permissions = ["storage.objects.get"]
  stage       = "GA"
}

resource "google_project_iam_custom_role" "week7_weather_landing_writer" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "dataforge_week7_weather_landing_writer"
  title       = "DataForge Week-7 weather landing writer"
  description = "Read and merge rows only in the Mini-project 3 landing table."
  permissions = ["bigquery.tables.get", "bigquery.tables.getData", "bigquery.tables.updateData"]
  stage       = "GA"
}

resource "google_project_iam_custom_role" "week7_weather_model_writer" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "dataforge_week7_weather_model_writer"
  title       = "DataForge Week-7 weather model writer"
  description = "Create, replace, and clean up weather candidate and synthetic SCD2 proof tables in isolated datasets; no Gold or commerce table access."
  permissions = [
    "bigquery.datasets.get",
    "bigquery.tables.create",
    "bigquery.tables.delete",
    "bigquery.tables.get",
    "bigquery.tables.getData",
    "bigquery.tables.list",
    "bigquery.tables.update",
    "bigquery.tables.updateData"
  ]
  stage = "GA"
}

resource "google_project_iam_custom_role" "week7_weather_workflow_job_runner" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "dataforge_week7_weather_job_runner"
  title       = "DataForge Week-7 weather job runner"
  description = "Invoke the two weather jobs with bounded argument overrides."
  permissions = ["run.jobs.run", "run.jobs.runWithOverrides"]
  stage       = "GA"
}

resource "google_project_iam_custom_role" "week7_weather_operation_reader" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "dataforge_week7_weather_operation_reader"
  title       = "DataForge Week-7 weather operation reader"
  description = "Read Cloud Run long-running operation results for weather jobs."
  permissions = ["run.operations.get"]
  stage       = "GA"
}

# Workflows grants executions.create at project scope; keep this one-permission
# role bound only to the temporary, dedicated Mini3 Scheduler service account.
resource "google_project_iam_custom_role" "week7_weather_scheduler_create" {
  count       = var.week7_weather_enabled && var.week7_weather_scheduler_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "dataforge_week7_weather_execution_create"
  title       = "DataForge Week-7 weather execution creator"
  description = "Project-scoped Workflows execution permission for the temporary Mini3 Scheduler caller."
  permissions = ["workflows.executions.create"]
  stage       = "GA"
}

resource "google_project_iam_custom_role" "week7_weather_scheduler_reader" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "dataforge_week7_weather_scheduler_reader"
  title       = "DataForge Week-7 weather Scheduler state reader"
  description = "Read Scheduler state for the single Mini-project 3 job so Airflow can refuse concurrent scheduling."
  permissions = ["cloudscheduler.jobs.get"]
  stage       = "GA"
}

resource "google_project_iam_custom_role" "week7_weather_gold_writer" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "dataforge_week7_weather_gold_writer"
  title       = "DataForge Week-7 weather Gold writer"
  description = "Read and atomically update weather publication versions and pointer."
  permissions = [
    "bigquery.datasets.get",
    "bigquery.tables.get",
    "bigquery.tables.getData",
    "bigquery.tables.updateData"
  ]
  stage = "GA"
}

resource "google_project_iam_custom_role" "week7_weather_ledger_writer" {
  count       = var.week7_weather_enabled ? 1 : 0
  project     = var.project_id
  role_id     = "dataforge_week7_weather_ledger_writer"
  title       = "DataForge Week-7 weather execution ledger writer"
  description = "Append one terminal execution row to the Mini-project 3 ledger."
  permissions = ["bigquery.tables.get", "bigquery.tables.getData", "bigquery.tables.updateData"]
  stage       = "GA"
}

resource "google_service_account_iam_member" "week7_weather_workflow_ingest_act_as" {
  count              = var.week7_weather_enabled ? 1 : 0
  service_account_id = google_service_account.week7_weather_ingest[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"
}

resource "google_service_account_iam_member" "week7_weather_workflow_dbt_act_as" {
  count              = var.week7_weather_enabled ? 1 : 0
  service_account_id = google_service_account.week7_weather_dbt[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"
}

resource "google_service_account_iam_member" "week7_weather_airflow_ingest_act_as" {
  count              = var.week7_weather_enabled ? 1 : 0
  service_account_id = google_service_account.week7_weather_ingest[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.week7_weather_airflow[0].email}"
}

resource "google_service_account_iam_member" "week7_weather_airflow_dbt_act_as" {
  count              = var.week7_weather_enabled ? 1 : 0
  service_account_id = google_service_account.week7_weather_dbt[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.week7_weather_airflow[0].email}"
}

resource "google_service_account_iam_member" "week7_weather_airflow_impersonation" {
  count              = var.week7_weather_enabled && var.week7_weather_airflow_impersonator_member != null ? 1 : 0
  service_account_id = google_service_account.week7_weather_airflow[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = var.week7_weather_airflow_impersonator_member
}

resource "google_service_account_iam_member" "week7_weather_scheduler_creator_act_as" {
  count              = var.week7_weather_enabled && var.week7_weather_scheduler_enabled && var.week7_weather_scheduler_creator_member != null ? 1 : 0
  service_account_id = google_service_account.week7_weather_scheduler[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = var.week7_weather_scheduler_creator_member
}

resource "google_project_iam_member" "week7_weather_ingest_bigquery_job_user" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.week7_weather_ingest[0].email}"
}

resource "google_project_iam_member" "week7_weather_ingest_service_usage_consumer" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.week7_weather_ingest[0].email}"
}

resource "google_project_iam_member" "week7_weather_dbt_bigquery_job_user" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.week7_weather_dbt[0].email}"
}

resource "google_project_iam_member" "week7_weather_dbt_service_usage_consumer" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.week7_weather_dbt[0].email}"
}

resource "google_project_iam_member" "week7_weather_workflow_bigquery_job_user" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"
}

resource "google_project_iam_member" "week7_weather_workflow_service_usage_consumer" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"
}

resource "google_project_iam_member" "week7_weather_workflow_logging_writer" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"
}

resource "google_project_iam_member" "week7_weather_airflow_bigquery_job_user" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.week7_weather_airflow[0].email}"
}

resource "google_project_iam_member" "week7_weather_airflow_service_usage_consumer" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.week7_weather_airflow[0].email}"
}

resource "google_project_iam_member" "week7_weather_workflow_operation_reader" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = google_project_iam_custom_role.week7_weather_operation_reader[0].name
  member  = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"
}

resource "google_project_iam_member" "week7_weather_airflow_operation_reader" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = google_project_iam_custom_role.week7_weather_operation_reader[0].name
  member  = "serviceAccount:${google_service_account.week7_weather_airflow[0].email}"
}

resource "google_project_iam_member" "week7_weather_airflow_scheduler_reader" {
  count   = var.week7_weather_enabled ? 1 : 0
  project = var.project_id
  role    = google_project_iam_custom_role.week7_weather_scheduler_reader[0].name
  member  = "serviceAccount:${google_service_account.week7_weather_airflow[0].email}"
}

resource "google_project_iam_member" "week7_weather_scheduler_execution_creator" {
  count   = var.week7_weather_enabled && var.week7_weather_scheduler_enabled ? 1 : 0
  project = var.project_id
  role    = google_project_iam_custom_role.week7_weather_scheduler_create[0].name
  member  = "serviceAccount:${google_service_account.week7_weather_scheduler[0].email}"
}

resource "google_storage_bucket_iam_member" "week7_weather_ingest_storage" {
  count  = var.week7_weather_enabled ? 1 : 0
  bucket = var.bucket_name
  role   = google_project_iam_custom_role.week7_weather_ingest_storage[0].name
  member = "serviceAccount:${google_service_account.week7_weather_ingest[0].email}"

  condition {
    title       = "week7-weather-prefix-create-and-read"
    description = "Only immutable Mini-project 3 raw, Parquet, manifest, and execution-receipt objects."
    expression  = "resource.name.startsWith('projects/_/buckets/${var.bucket_name}/objects/weather_mini3/v1/')"
  }
}

resource "google_storage_bucket_iam_member" "week7_weather_workflow_storage_reader" {
  count  = var.week7_weather_enabled ? 1 : 0
  bucket = var.bucket_name
  role   = google_project_iam_custom_role.week7_weather_manifest_reader[0].name
  member = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"

  condition {
    title       = "week7-weather-prefix-read"
    description = "Read only Mini-project 3 manifests and invocation receipts."
    expression  = "resource.name.startsWith('projects/_/buckets/${var.bucket_name}/objects/weather_mini3/v1/')"
  }
}

resource "google_storage_bucket_iam_member" "week7_weather_airflow_storage_reader" {
  count  = var.week7_weather_enabled ? 1 : 0
  bucket = var.bucket_name
  role   = google_project_iam_custom_role.week7_weather_manifest_reader[0].name
  member = "serviceAccount:${google_service_account.week7_weather_airflow[0].email}"

  condition {
    title       = "week7-airflow-weather-prefix-read"
    description = "Read only Mini-project 3 manifests and invocation receipts."
    expression  = "resource.name.startsWith('projects/_/buckets/${var.bucket_name}/objects/weather_mini3/v1/')"
  }
}

resource "google_bigquery_table_iam_member" "week7_weather_ingest_landing_writer" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_weather_landing[0].dataset_id
  table_id   = google_bigquery_table.week7_weather_landing[0].table_id
  role       = google_project_iam_custom_role.week7_weather_landing_writer[0].name
  member     = "serviceAccount:${google_service_account.week7_weather_ingest[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_weather_dbt_landing_reader" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_weather_landing[0].dataset_id
  table_id   = google_bigquery_table.week7_weather_landing[0].table_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_weather_dbt[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_weather_workflow_pointer_reader" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_weather_gold[0].dataset_id
  table_id   = google_bigquery_table.week7_weather_publication_pointer[0].table_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_weather_workflow_versions_reader" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_weather_gold[0].dataset_id
  table_id   = google_bigquery_table.week7_weather_versions[0].table_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_weather_workflow_published_view_reader" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_weather_gold[0].dataset_id
  table_id   = google_bigquery_table.week7_weather_published_view[0].table_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"

  depends_on = [google_bigquery_table.week7_weather_published_view]
}

resource "google_bigquery_table_iam_member" "week7_weather_airflow_ledger_reader" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_weather_landing[0].dataset_id
  table_id   = google_bigquery_table.week7_weather_execution_ledger[0].table_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_weather_airflow[0].email}"
}

resource "google_bigquery_table_iam_member" "week7_weather_workflow_ledger_writer" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_weather_landing[0].dataset_id
  table_id   = google_bigquery_table.week7_weather_execution_ledger[0].table_id
  role       = google_project_iam_custom_role.week7_weather_ledger_writer[0].name
  member     = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_weather_dbt_candidate_writer" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_weather_candidate[0].dataset_id
  role       = google_project_iam_custom_role.week7_weather_model_writer[0].name
  member     = "serviceAccount:${google_service_account.week7_weather_dbt[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_weather_dbt_candidate_full_writer" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_weather_candidate_full[0].dataset_id
  role       = google_project_iam_custom_role.week7_weather_model_writer[0].name
  member     = "serviceAccount:${google_service_account.week7_weather_dbt[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_weather_dbt_gold_writer" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_weather_gold[0].dataset_id
  role       = google_project_iam_custom_role.week7_weather_gold_writer[0].name
  member     = "serviceAccount:${google_service_account.week7_weather_dbt[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_weather_dbt_scd2_input_writer" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_scd2_proof_input[0].dataset_id
  role       = google_project_iam_custom_role.week7_weather_model_writer[0].name
  member     = "serviceAccount:${google_service_account.week7_weather_dbt[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_weather_dbt_scd2_history_writer" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_scd2_proof_history[0].dataset_id
  role       = google_project_iam_custom_role.week7_weather_model_writer[0].name
  member     = "serviceAccount:${google_service_account.week7_weather_dbt[0].email}"
}

resource "google_bigquery_dataset_iam_member" "week7_weather_airflow_gold_reader" {
  count      = var.week7_weather_enabled ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.week7_weather_gold[0].dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.week7_weather_airflow[0].email}"
}

resource "google_cloud_run_v2_job_iam_member" "week7_weather_workflow_ingest_runner" {
  count    = var.week7_weather_enabled ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.week7_weather_ingest[0].name
  role     = google_project_iam_custom_role.week7_weather_workflow_job_runner[0].name
  member   = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"
}

resource "google_cloud_run_v2_job_iam_member" "week7_weather_workflow_dbt_runner" {
  count    = var.week7_weather_enabled ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.week7_weather_dbt[0].name
  role     = google_project_iam_custom_role.week7_weather_workflow_job_runner[0].name
  member   = "serviceAccount:${google_service_account.week7_weather_workflow[0].email}"
}

resource "google_cloud_run_v2_job_iam_member" "week7_weather_airflow_ingest_runner" {
  count    = var.week7_weather_enabled ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.week7_weather_ingest[0].name
  role     = google_project_iam_custom_role.week7_weather_workflow_job_runner[0].name
  member   = "serviceAccount:${google_service_account.week7_weather_airflow[0].email}"
}

resource "google_cloud_run_v2_job_iam_member" "week7_weather_airflow_dbt_runner" {
  count    = var.week7_weather_enabled ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.week7_weather_dbt[0].name
  role     = google_project_iam_custom_role.week7_weather_workflow_job_runner[0].name
  member   = "serviceAccount:${google_service_account.week7_weather_airflow[0].email}"
}

resource "google_workflows_workflow" "week7_weather" {
  count           = var.week7_weather_enabled ? 1 : 0
  project         = var.project_id
  name            = "dataforge-week7-weather-orchestrator"
  region          = var.region
  description     = "Mini-project 3 Open-Meteo API to private Bronze, typed BigQuery landing, dbt weather Gold, and execution ledger."
  service_account = google_service_account.week7_weather_workflow[0].id
  source_contents = file("${path.module}/../../workflows/week7_weather_workflow.yaml")

  user_env_vars = {
    DATAFORGE_PROJECT_ID         = var.project_id
    DATAFORGE_REGION             = var.region
    DATAFORGE_BRONZE_BUCKET      = var.bucket_name
    DATAFORGE_WEATHER_INGEST_JOB = google_cloud_run_v2_job.week7_weather_ingest[0].name
    DATAFORGE_WEATHER_DBT_JOB    = google_cloud_run_v2_job.week7_weather_dbt[0].name
  }

  labels = {
    application = "dataforge"
    phase       = "week7"
    domain      = "weather"
  }

  depends_on = [
    google_project_service.workflows,
    google_cloud_run_v2_job.week7_weather_ingest,
    google_cloud_run_v2_job.week7_weather_dbt,
    google_cloud_run_v2_job_iam_member.week7_weather_workflow_ingest_runner,
    google_cloud_run_v2_job_iam_member.week7_weather_workflow_dbt_runner
  ]
}

resource "google_cloud_scheduler_job" "week7_weather" {
  count            = var.week7_weather_enabled && var.week7_weather_scheduler_enabled ? 1 : 0
  project          = var.project_id
  region           = var.region
  name             = "dataforge-week7-weather-daily"
  description      = "Temporary, bounded daily Mini-project 3 API-to-Gold demonstration; remove after the timed proof."
  schedule         = var.week7_weather_schedule
  time_zone        = "Asia/Ho_Chi_Minh"
  paused           = var.week7_weather_scheduler_paused
  attempt_deadline = "180s"

  retry_config {
    retry_count = 0
  }

  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.week7_weather[0].id}/executions"
    body = base64encode(jsonencode({
      argument = jsonencode({ trigger = "scheduler" })
    }))
    headers = {
      "Content-Type" = "application/json"
    }
    oauth_token {
      service_account_email = google_service_account.week7_weather_scheduler[0].email
    }
  }

  depends_on = [
    google_project_service.cloud_scheduler,
    google_project_iam_member.week7_weather_scheduler_execution_creator,
    google_service_account_iam_member.week7_weather_scheduler_creator_act_as
  ]
}

resource "google_project_service" "week7_weather_monitoring" {
  count   = var.week7_weather_enabled && (var.week7_weather_notification_channel_enabled || var.week7_weather_alert_enabled) ? 1 : 0
  project = var.project_id
  service = "monitoring.googleapis.com"

  disable_on_destroy = false
}

resource "google_monitoring_notification_channel" "week7_weather_email_test" {
  count        = var.week7_weather_enabled && var.week7_weather_notification_channel_enabled ? 1 : 0
  project      = var.project_id
  display_name = "DataForge Mini3 one-off failure test"
  type         = "email"
  description  = "Temporary user-approved destination for one controlled Mini3 failure notification; remove after verification."
  enabled      = true

  labels = {
    email_address = var.week7_weather_notification_email
  }

  depends_on = [google_project_service.week7_weather_monitoring]
}

resource "google_monitoring_alert_policy" "week7_weather_failure" {
  count        = var.week7_weather_enabled && var.week7_weather_alert_enabled ? 1 : 0
  project      = var.project_id
  display_name = "DataForge Week-7 Mini3 controlled failure test"
  combiner     = "OR"
  enabled      = true
  notification_channels = concat(
    var.week7_weather_notification_channel_ids,
    var.week7_weather_notification_channel_enabled
    ? [google_monitoring_notification_channel.week7_weather_email_test[0].name]
    : []
  )
  documentation {
    content   = "One controlled Mini-project 3 failure was injected to verify email delivery. This policy is temporary; disable/delete it after verifying the single notification. NO_NEW_BATCH and source-not-ready are normal outcomes."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "One controlled Mini3 failure event"
    condition_matched_log {
      filter = <<-EOT
        severity >= ERROR
        AND resource.type = "workflows.googleapis.com/Workflow"
        AND jsonPayload.event="DATAFORGE_WEATHER_CONTROLLED_ALERT_TEST"
      EOT
    }
  }

  alert_strategy {
    auto_close           = "3600s"
    notification_prompts = ["OPENED"]
    notification_rate_limit {
      period = "3600s"
    }
  }

  depends_on = [
    google_project_service.week7_weather_monitoring,
    google_cloud_run_v2_job.week7_weather_ingest,
    google_cloud_run_v2_job.week7_weather_dbt,
    google_workflows_workflow.week7_weather,
    google_monitoring_notification_channel.week7_weather_email_test
  ]
}

output "week7_weather_jobs" {
  value = var.week7_weather_enabled ? {
    ingest = google_cloud_run_v2_job.week7_weather_ingest[0].name
    dbt    = google_cloud_run_v2_job.week7_weather_dbt[0].name
  } : null
}

output "week7_weather_workflow" {
  value = try(google_workflows_workflow.week7_weather[0].id, null)
}

output "week7_weather_scheduler" {
  value = try(google_cloud_scheduler_job.week7_weather[0].id, null)
}
