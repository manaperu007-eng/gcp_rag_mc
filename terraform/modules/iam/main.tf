##############################################################################
# modules/iam/main.tf
# Service Accounts & IAM bindings
##############################################################################

variable "project_id" { type = string }
variable "region"     { type = string }
variable "suffix"     { type = string }

##############################################################################
# Service Accounts
##############################################################################

resource "google_service_account" "app" {
  project      = var.project_id
  account_id   = "kb-app-sa-${var.suffix}"
  display_name = "KB Questionnaire App Service Account"
  description  = "Used by API, web, and admin Cloud Run services"
}

resource "google_service_account" "ingestion" {
  project      = var.project_id
  account_id   = "kb-ingestion-sa-${var.suffix}"
  display_name = "KB Document Ingestion Service Account"
  description  = "Used by document ingestion pipeline and Cloud Functions"
}

resource "google_service_account" "reporting" {
  project      = var.project_id
  account_id   = "kb-reporting-sa-${var.suffix}"
  display_name = "KB Reporting Service Account"
  description  = "Used for BigQuery reporting and Looker Studio / Data Studio"
}

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = "kb-scheduler-sa-${var.suffix}"
  display_name = "KB Scheduler Service Account"
  description  = "Used by Cloud Scheduler to invoke Cloud Run jobs"
}

##############################################################################
# App SA roles
##############################################################################

locals {
  app_roles = [
    "roles/run.invoker",
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",
    "roles/storage.objectAdmin",
    "roles/aiplatform.user",
    "roles/firestore.user",
    "roles/secretmanager.secretAccessor",
    "roles/pubsub.publisher",
    "roles/pubsub.subscriber",
    "roles/cloudtasks.enqueuer",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/cloudtrace.agent",
  ]

  ingestion_roles = [
    "roles/storage.objectAdmin",
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",
    "roles/aiplatform.user",
    "roles/documentai.apiUser",
    "roles/pubsub.publisher",
    "roles/pubsub.subscriber",
    "roles/secretmanager.secretAccessor",
    "roles/logging.logWriter",
  ]

  reporting_roles = [
    "roles/bigquery.dataViewer",
    "roles/bigquery.jobUser",
    "roles/storage.objectViewer",
    "roles/logging.logWriter",
  ]

  scheduler_roles = [
    "roles/run.invoker",
    "roles/cloudscheduler.jobRunner",
  ]
}

resource "google_project_iam_member" "app_roles" {
  for_each = toset(local.app_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.app.email}"
}

resource "google_project_iam_member" "ingestion_roles" {
  for_each = toset(local.ingestion_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_project_iam_member" "reporting_roles" {
  for_each = toset(local.reporting_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.reporting.email}"
}

resource "google_project_iam_member" "scheduler_roles" {
  for_each = toset(local.scheduler_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

##############################################################################
# Artifact Registry (container images for Cloud Run)
##############################################################################

resource "google_artifact_registry_repository" "app" {
  project       = var.project_id
  location      = var.region
  repository_id = "kb-app-images"
  format        = "DOCKER"
  description   = "Docker images for the KB Questionnaire platform"

  labels = {
    managed_by = "terraform"
  }
}

resource "google_artifact_registry_repository_iam_member" "app_sa_reader" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.app.email}"
}

resource "google_artifact_registry_repository_iam_member" "ingestion_sa_reader" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.ingestion.email}"
}

##############################################################################
# Outputs
##############################################################################

output "app_sa_email"       { value = google_service_account.app.email }
output "app_sa_id"          { value = google_service_account.app.id }
output "ingestion_sa_email" { value = google_service_account.ingestion.email }
output "ingestion_sa_id"    { value = google_service_account.ingestion.id }
output "reporting_sa_email" { value = google_service_account.reporting.email }
output "scheduler_sa_email" { value = google_service_account.scheduler.email }
output "artifact_registry"  { value = google_artifact_registry_repository.app.name }
