locals {
  airflow_secret_ids = toset([
    "fernet_key",
    "metadata_db_password",
    "admin_password",
  ])
  airflow_startup_script = var.airflow_startup_script != null ? var.airflow_startup_script : file("${path.module}/../../../deploy/airflow_vm/startup.sh")
}

resource "google_project_service" "compute" {
  count   = var.enable_vm ? 1 : 0
  project = var.project_id
  service = "compute.googleapis.com"

  disable_on_destroy = false
}

resource "google_project_service" "iap" {
  count   = var.enable_vm ? 1 : 0
  project = var.project_id
  service = "iap.googleapis.com"

  disable_on_destroy = false
}

resource "google_project_service" "secretmanager" {
  count   = var.enable_secrets ? 1 : 0
  project = var.project_id
  service = "secretmanager.googleapis.com"

  disable_on_destroy = false
}

resource "google_project_iam_member" "airflow_vm_logging_writer" {
  count   = var.enable_vm ? 1 : 0
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${var.airflow_service_account_email}"
}

resource "google_compute_network" "airflow" {
  count                   = var.enable_vm ? 1 : 0
  project                 = var.project_id
  name                    = "dataforge-week7-airflow"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.compute]
}

resource "google_compute_subnetwork" "airflow" {
  count                    = var.enable_vm ? 1 : 0
  project                  = var.project_id
  name                     = "dataforge-week7-airflow"
  region                   = var.region
  network                  = google_compute_network.airflow[0].id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
}

resource "google_compute_router" "airflow" {
  count   = var.enable_vm ? 1 : 0
  project = var.project_id
  name    = "dataforge-week7-airflow"
  region  = var.region
  network = google_compute_network.airflow[0].id

  bgp {
    asn = 64514
  }
}

resource "google_compute_router_nat" "airflow" {
  count                              = var.enable_vm ? 1 : 0
  project                            = var.project_id
  name                               = "dataforge-week7-airflow-egress"
  router                             = google_compute_router.airflow[0].name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.airflow[0].id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

resource "google_compute_firewall" "airflow_iap" {
  count       = var.enable_vm ? 1 : 0
  project     = var.project_id
  name        = "dataforge-week7-airflow-iap"
  network     = google_compute_network.airflow[0].name
  description = "Only IAP TCP forwarding can reach Airflow SSH and UI ports."
  direction   = "INGRESS"
  priority    = 1000
  source_ranges = [
    "35.235.240.0/20",
  ]
  target_service_accounts = [var.airflow_service_account_email]

  allow {
    protocol = "tcp"
    ports    = ["22", "8080"]
  }
}

resource "google_compute_instance" "airflow" {
  count                     = var.enable_vm ? 1 : 0
  project                   = var.project_id
  name                      = "dataforge-week7-airflow"
  zone                      = var.zone
  machine_type              = var.machine_type
  allow_stopping_for_update = false
  deletion_protection       = false
  tags                      = ["dataforge-week7-airflow"]

  labels = {
    application = "dataforge"
    phase       = "week7"
    destroy_by  = try(replace(substr(var.destroy_by, 0, 10), "-", "_"), "unset")
  }

  boot_disk {
    auto_delete = true
    initialize_params {
      image = var.boot_image
      size  = var.boot_disk_size_gb
      type  = "pd-standard"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.airflow[0].id
    # Deliberately no access_config: the VM has no external IP.
  }

  service_account {
    email  = var.airflow_service_account_email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin               = "TRUE"
    block-project-ssh-keys       = "TRUE"
    dataforge-airflow-image      = var.airflow_image
    dataforge-weather-cloud-enabled = tostring(var.weather_cloud_enabled)
    destroy_by                   = var.destroy_by
  }

  metadata_startup_script = local.airflow_startup_script

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
  }

  shielded_instance_config {
    enable_secure_boot         = true
    enable_vtpm                = true
    enable_integrity_monitoring = true
  }

  lifecycle {
    precondition {
      condition = (
        timecmp(var.destroy_by, timestamp()) > 0 &&
        timecmp(var.destroy_by, timeadd(timestamp(), "120h")) <= 0
      )
      error_message = "destroy_by must be in the future and no more than the approved 120-hour VM lifetime."
    }
  }

  depends_on = [
    google_compute_router_nat.airflow,
    google_compute_firewall.airflow_iap,
    google_project_iam_member.airflow_vm_logging_writer,
    google_secret_manager_secret_version.airflow,
  ]
}
