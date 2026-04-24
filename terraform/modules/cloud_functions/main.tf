##############################################################################
# modules/cloud_functions/main.tf
# Cloud Functions Gen 2 for event-driven lightweight tasks
##############################################################################

variable "project_id"       { type = string }
variable "region"           { type = string }
variable "suffix"           { type = string }
variable "environment"      { type = string }
variable "ingestion_sa"     { type = string }
variable "document_bucket"  { type = string }
variable "processed_bucket" { type = string }
variable "functions_bucket" { type = string }
variable "ingestion_topic"  { type = string }
variable "bq_dataset"       { type = string }

##############################################################################
# Helper: placeholder zip for each function
# In real use, replace with actual source archives in GCS
##############################################################################

locals {
  functions = {
    doc_classifier = {
      description    = "Classifies uploaded documents (PDF/DOCX/XLSX) and triggers ingestion pipeline"
      entry_point    = "classify_document"
      runtime        = "python311"
      trigger_bucket = var.document_bucket
      memory         = "1Gi"
      cpu            = "1"
      timeout        = 540
      source_path    = "functions/doc_classifier.zip"
    }
    notification_sender = {
      description    = "Sends email notifications for assignments, reminders, and completions"
      entry_point    = "send_notification"
      runtime        = "python311"
      trigger_topic  = "kb-notifications-${var.suffix}"
      memory         = "256Mi"
      cpu            = "0.333"
      timeout        = 60
      source_path    = "functions/notification_sender.zip"
    }
    completion_tracker = {
      description   = "Updates completion percentages in real-time when responses are saved"
      entry_point   = "track_completion"
      runtime       = "python311"
      trigger_topic = "kb-questionnaire-events-${var.suffix}"
      memory        = "256Mi"
      cpu           = "0.333"
      timeout       = 60
      source_path   = "functions/completion_tracker.zip"
    }
  }
}

##############################################################################
# 1. Document Classifier Function (triggered by GCS object creation)
##############################################################################

resource "google_cloudfunctions2_function" "doc_classifier" {
  project     = var.project_id
  name        = "kb-doc-classifier-${var.suffix}"
  location    = var.region
  description = "Classifies and routes newly uploaded documents"

  build_config {
    runtime     = "python311"
    entry_point = "classify_document"

    source {
      storage_source {
        bucket = var.functions_bucket
        object = "functions/doc_classifier.zip"
      }
    }
  }

  service_config {
    min_instance_count             = 0
    max_instance_count             = 10
    available_memory               = "1Gi"
    available_cpu                  = "1"
    timeout_seconds                = 540
    service_account_email          = var.ingestion_sa
    all_traffic_on_latest_revision = true

    environment_variables = {
      PROJECT_ID       = var.project_id
      REGION           = var.region
      DOCUMENT_BUCKET  = var.document_bucket
      PROCESSED_BUCKET = var.processed_bucket
      BQ_DATASET       = var.bq_dataset
      ENVIRONMENT      = var.environment
    }
  }

  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.storage.object.v1.finalized"
    retry_policy   = "RETRY_POLICY_RETRY"

    event_filters {
      attribute = "bucket"
      value     = var.document_bucket
    }
  }

  labels = {
    managed_by = "terraform"
    env        = var.environment
  }
}

##############################################################################
# 2. Notification Sender Function (triggered by Pub/Sub)
##############################################################################

resource "google_cloudfunctions2_function" "notification_sender" {
  project     = var.project_id
  name        = "kb-notification-sender-${var.suffix}"
  location    = var.region
  description = "Sends email/SMS alerts for questionnaire events"

  build_config {
    runtime     = "python311"
    entry_point = "send_notification"

    source {
      storage_source {
        bucket = var.functions_bucket
        object = "functions/notification_sender.zip"
      }
    }
  }

  service_config {
    min_instance_count             = 0
    max_instance_count             = 20
    available_memory               = "256Mi"
    available_cpu                  = "0.333"
    timeout_seconds                = 60
    service_account_email          = var.ingestion_sa
    all_traffic_on_latest_revision = true

    environment_variables = {
      PROJECT_ID  = var.project_id
      ENVIRONMENT = var.environment
    }

    secret_environment_variables {
      key        = "SENDGRID_API_KEY"
      project_id = var.project_id
      secret     = "kb-sendgrid-api-key"
      version    = "latest"
    }
  }

  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    retry_policy   = "RETRY_POLICY_RETRY"

    event_filters {
      attribute = "type"
      value     = "google.cloud.pubsub.topic.v1.messagePublished"
    }

    pubsub_topic = "projects/${var.project_id}/topics/kb-notifications-${var.suffix}"
  }

  labels = {
    managed_by = "terraform"
    env        = var.environment
  }
}

##############################################################################
# 3. Completion Tracker Function (triggered by questionnaire events Pub/Sub)
##############################################################################

resource "google_cloudfunctions2_function" "completion_tracker" {
  project     = var.project_id
  name        = "kb-completion-tracker-${var.suffix}"
  location    = var.region
  description = "Tracks and updates questionnaire completion percentages in BigQuery"

  build_config {
    runtime     = "python311"
    entry_point = "track_completion"

    source {
      storage_source {
        bucket = var.functions_bucket
        object = "functions/completion_tracker.zip"
      }
    }
  }

  service_config {
    min_instance_count             = 0
    max_instance_count             = 50
    available_memory               = "256Mi"
    available_cpu                  = "0.333"
    timeout_seconds                = 60
    service_account_email          = var.ingestion_sa
    all_traffic_on_latest_revision = true

    environment_variables = {
      PROJECT_ID  = var.project_id
      BQ_DATASET  = var.bq_dataset
      ENVIRONMENT = var.environment
    }
  }

  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    retry_policy   = "RETRY_POLICY_RETRY"

    pubsub_topic = "projects/${var.project_id}/topics/kb-questionnaire-events-${var.suffix}"
  }

  labels = {
    managed_by = "terraform"
    env        = var.environment
  }
}

##############################################################################
# 4. Signed URL Generator Function
# Creates short-lived GCS signed URLs for secure evidence uploads
##############################################################################

resource "google_cloudfunctions2_function" "signed_url_gen" {
  project     = var.project_id
  name        = "kb-signed-url-gen-${var.suffix}"
  location    = var.region
  description = "Generates signed upload URLs for evidence file uploads"

  build_config {
    runtime     = "python311"
    entry_point = "generate_signed_url"

    source {
      storage_source {
        bucket = var.functions_bucket
        object = "functions/signed_url_gen.zip"
      }
    }
  }

  service_config {
    min_instance_count             = 0
    max_instance_count             = 30
    available_memory               = "128Mi"
    available_cpu                  = "0.167"
    timeout_seconds                = 30
    service_account_email          = var.ingestion_sa
    all_traffic_on_latest_revision = true

    environment_variables = {
      PROJECT_ID      = var.project_id
      EVIDENCE_BUCKET = "kb-evidence-placeholder"
      EXPIRY_MINUTES  = "15"
    }
  }

  labels = {
    managed_by = "terraform"
    env        = var.environment
  }
}

# Public invoker for the signed URL generator (auth enforced by JWT in function)
resource "google_cloud_run_v2_service_iam_member" "signed_url_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloudfunctions2_function.signed_url_gen.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

##############################################################################
# Outputs
##############################################################################

output "doc_classifier_url"    { value = google_cloudfunctions2_function.doc_classifier.service_config[0].uri }
output "notification_fn_url"   { value = google_cloudfunctions2_function.notification_sender.service_config[0].uri }
output "completion_tracker_url"{ value = google_cloudfunctions2_function.completion_tracker.service_config[0].uri }
output "signed_url_gen_url"    { value = google_cloudfunctions2_function.signed_url_gen.service_config[0].uri }
