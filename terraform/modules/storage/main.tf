##############################################################################
# modules/storage/main.tf
# Cloud Storage Buckets for documents, evidence, reports, and functions
##############################################################################

variable "project_id"   { type = string }
variable "region"       { type = string }
variable "suffix"       { type = string }
variable "environment"  { type = string }
variable "ingestion_sa" { type = string }
variable "app_sa"       { type = string }

variable "document_retention_days" {
  type    = number
  default = 365
}

##############################################################################
# 1. Raw Document Uploads (PDF, DOCX, XLSX)
##############################################################################

resource "google_storage_bucket" "documents" {
  project                     = var.project_id
  name                        = "${var.project_id}-kb-documents-${var.suffix}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = var.environment != "prod"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = var.document_retention_days
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age                = var.document_retention_days + 365
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }

  cors {
    origin          = ["*"]
    method          = ["GET", "POST", "PUT", "HEAD"]
    response_header = ["*"]
    max_age_seconds = 3600
  }

  labels = {
    purpose    = "document-ingestion"
    managed_by = "terraform"
    env        = var.environment
  }
}

# Allow ingestion SA full access to upload documents
resource "google_storage_bucket_iam_member" "documents_ingestion_admin" {
  bucket = google_storage_bucket.documents.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.ingestion_sa}"
}

# Allow app SA to read documents
resource "google_storage_bucket_iam_member" "documents_app_viewer" {
  bucket = google_storage_bucket.documents.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.app_sa}"
}

##############################################################################
# 2. Processed Documents (chunks, metadata, embeddings JSON)
##############################################################################

resource "google_storage_bucket" "processed" {
  project                     = var.project_id
  name                        = "${var.project_id}-kb-processed-${var.suffix}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = var.environment != "prod"

  versioning {
    enabled = true
  }

  labels = {
    purpose    = "processed-documents"
    managed_by = "terraform"
    env        = var.environment
  }
}

resource "google_storage_bucket_iam_member" "processed_ingestion_admin" {
  bucket = google_storage_bucket.processed.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.ingestion_sa}"
}

resource "google_storage_bucket_iam_member" "processed_app_admin" {
  bucket = google_storage_bucket.processed.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.app_sa}"
}

##############################################################################
# 3. Evidence File Uploads (questionnaire file-upload answers)
##############################################################################

resource "google_storage_bucket" "evidence" {
  project                     = var.project_id
  name                        = "${var.project_id}-kb-evidence-${var.suffix}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = var.environment != "prod"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 1825 # 5 years for compliance
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  cors {
    origin          = ["*"]
    method          = ["GET", "POST", "PUT", "HEAD"]
    response_header = ["*"]
    max_age_seconds = 3600
  }

  labels = {
    purpose    = "evidence-uploads"
    managed_by = "terraform"
    env        = var.environment
  }
}

resource "google_storage_bucket_iam_member" "evidence_app_admin" {
  bucket = google_storage_bucket.evidence.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.app_sa}"
}

##############################################################################
# 4. Generated Reports (CSV, PDF exports for admin)
##############################################################################

resource "google_storage_bucket" "reports" {
  project                     = var.project_id
  name                        = "${var.project_id}-kb-reports-${var.suffix}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = var.environment != "prod"

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    purpose    = "admin-reports"
    managed_by = "terraform"
    env        = var.environment
  }
}

resource "google_storage_bucket_iam_member" "reports_app_admin" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.app_sa}"
}

##############################################################################
# 5. Cloud Functions Source Code
##############################################################################

resource "google_storage_bucket" "functions" {
  project                     = var.project_id
  name                        = "${var.project_id}-kb-functions-${var.suffix}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = true

  labels = {
    purpose    = "function-source"
    managed_by = "terraform"
    env        = var.environment
  }
}

##############################################################################
# 6. Vertex AI Pipeline Staging Bucket
##############################################################################

resource "google_storage_bucket" "vertex_staging" {
  project                     = var.project_id
  name                        = "${var.project_id}-kb-vertex-staging-${var.suffix}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = true

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    purpose    = "vertex-ai-staging"
    managed_by = "terraform"
    env        = var.environment
  }
}

resource "google_storage_bucket_iam_member" "vertex_staging_app_admin" {
  bucket = google_storage_bucket.vertex_staging.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.app_sa}"
}

resource "google_storage_bucket_iam_member" "vertex_staging_ingestion_admin" {
  bucket = google_storage_bucket.vertex_staging.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.ingestion_sa}"
}

##############################################################################
# Pub/Sub notification: trigger ingestion on new document upload
##############################################################################

resource "google_storage_notification" "document_upload" {
  bucket         = google_storage_bucket.documents.name
  payload_format = "JSON_API_V1"
  topic          = "projects/${var.project_id}/topics/kb-doc-ingestion-${var.suffix}"
  event_types    = ["OBJECT_FINALIZE"]

  custom_attributes = {
    bucket_type = "documents"
  }

  # Topic must exist before this — managed via depends_on in root module
  depends_on = [google_storage_bucket.documents]
}

##############################################################################
# Outputs
##############################################################################

output "document_bucket_name"       { value = google_storage_bucket.documents.name }
output "document_bucket_url"        { value = google_storage_bucket.documents.url }
output "processed_bucket_name"      { value = google_storage_bucket.processed.name }
output "processed_bucket_url"       { value = google_storage_bucket.processed.url }
output "evidence_bucket_name"       { value = google_storage_bucket.evidence.name }
output "evidence_bucket_url"        { value = google_storage_bucket.evidence.url }
output "reports_bucket_name"        { value = google_storage_bucket.reports.name }
output "reports_bucket_url"         { value = google_storage_bucket.reports.url }
output "functions_bucket_name"      { value = google_storage_bucket.functions.name }
output "vertex_staging_bucket_name" { value = google_storage_bucket.vertex_staging.name }
