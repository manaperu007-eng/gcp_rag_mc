##############################################################################
# modules/pubsub/main.tf
# Pub/Sub topics and subscriptions for event-driven pipeline
##############################################################################

variable "project_id"    { type = string }
variable "region"        { type = string }
variable "suffix"        { type = string }
variable "ingestion_sa"  { type = string }
variable "app_sa"        { type = string }

##############################################################################
# 1. Document Ingestion Topic
# Triggered when new file lands in documents bucket
##############################################################################

resource "google_pubsub_topic" "doc_ingestion" {
  project = var.project_id
  name    = "kb-doc-ingestion-${var.suffix}"

  message_retention_duration = "86600s"  # ~24 hours

  labels = { managed_by = "terraform", pipeline = "ingestion" }
}

resource "google_pubsub_subscription" "doc_ingestion_worker" {
  project = var.project_id
  name    = "kb-doc-ingestion-worker-${var.suffix}"
  topic   = google_pubsub_topic.doc_ingestion.name

  ack_deadline_seconds       = 600   # 10 min processing window
  message_retention_duration = "86600s"
  retain_acked_messages      = false

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 5
  }

  push_config {
    push_endpoint = "https://kb-ingestion-PLACEHOLDER.run.app/ingest"  # Updated post Cloud Run deploy

    oidc_token {
      service_account_email = var.ingestion_sa
    }

    attributes = {
      x-goog-version = "v1"
    }
  }
}

# IAM: GCS can publish to ingestion topic (for bucket notifications)
resource "google_pubsub_topic_iam_member" "gcs_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.doc_ingestion.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${data.google_project.project.number}@gs-project-accounts.iam.gserviceaccount.com"
}

resource "google_pubsub_topic_iam_member" "ingestion_sa_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.doc_ingestion.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.ingestion_sa}"
}

##############################################################################
# 2. Questionnaire Events Topic
# Fired on response submission, assignment, reminder triggers
##############################################################################

resource "google_pubsub_topic" "questionnaire_events" {
  project = var.project_id
  name    = "kb-questionnaire-events-${var.suffix}"

  message_retention_duration = "604800s"  # 7 days

  labels = { managed_by = "terraform", pipeline = "questionnaire" }
}

resource "google_pubsub_subscription" "questionnaire_events_worker" {
  project = var.project_id
  name    = "kb-questionnaire-events-worker-${var.suffix}"
  topic   = google_pubsub_topic.questionnaire_events.name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
  retain_acked_messages      = false

  retry_policy {
    minimum_backoff = "5s"
    maximum_backoff = "60s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 5
  }
}

resource "google_pubsub_topic_iam_member" "app_sa_q_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.questionnaire_events.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.app_sa}"
}

##############################################################################
# 3. Notifications Topic
# Email reminders, completion notifications, admin alerts
##############################################################################

resource "google_pubsub_topic" "notifications" {
  project = var.project_id
  name    = "kb-notifications-${var.suffix}"

  message_retention_duration = "86600s"

  labels = { managed_by = "terraform", pipeline = "notifications" }
}

resource "google_pubsub_subscription" "notifications_worker" {
  project = var.project_id
  name    = "kb-notifications-worker-${var.suffix}"
  topic   = google_pubsub_topic.notifications.name

  ack_deadline_seconds       = 30
  message_retention_duration = "86600s"
  retain_acked_messages      = false

  retry_policy {
    minimum_backoff = "5s"
    maximum_backoff = "120s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 3
  }
}

##############################################################################
# 4. BQ Streaming Topic
# Events streamed to BigQuery for real-time analytics
##############################################################################

resource "google_pubsub_topic" "bq_streaming" {
  project = var.project_id
  name    = "kb-bq-streaming-${var.suffix}"

  labels = { managed_by = "terraform", pipeline = "analytics" }

  schema_settings {
    schema   = google_pubsub_schema.response_event.id
    encoding = "JSON"
  }
}

resource "google_pubsub_schema" "response_event" {
  project    = var.project_id
  name       = "kb-response-event-schema-${var.suffix}"
  type       = "AVRO"
  definition = jsonencode({
    type      = "record"
    name      = "ResponseEvent"
    namespace = "com.kb.questionnaire"
    fields = [
      { name = "response_id",      type = "string" },
      { name = "questionnaire_id", type = "string" },
      { name = "question_id",      type = "string" },
      { name = "user_id",          type = "string" },
      { name = "question_type",    type = "string" },
      { name = "channel",          type = ["null", "string"], default = null },
      { name = "responded_at",     type = "string" }
    ]
  })
}

# BigQuery subscription for streaming inserts
resource "google_pubsub_subscription" "bq_streaming_sub" {
  project = var.project_id
  name    = "kb-bq-streaming-sub-${var.suffix}"
  topic   = google_pubsub_topic.bq_streaming.name

  bigquery_config {
    table            = "${var.project_id}.kb_questionnaire_dev.responses"
    use_topic_schema = true
    write_metadata   = false
  }
}

##############################################################################
# 5. Dead-Letter Topic
##############################################################################

resource "google_pubsub_topic" "dead_letter" {
  project = var.project_id
  name    = "kb-dead-letter-${var.suffix}"

  message_retention_duration = "604800s"  # 7 days for investigation

  labels = { managed_by = "terraform", pipeline = "dlq" }
}

resource "google_pubsub_subscription" "dead_letter_monitor" {
  project = var.project_id
  name    = "kb-dead-letter-monitor-${var.suffix}"
  topic   = google_pubsub_topic.dead_letter.name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
  retain_acked_messages      = false
}

##############################################################################
# Data source for project number (needed for GCS SA IAM)
##############################################################################

data "google_project" "project" {
  project_id = var.project_id
}

##############################################################################
# Outputs
##############################################################################

output "ingestion_topic_id"           { value = google_pubsub_topic.doc_ingestion.id }
output "ingestion_topic_name"         { value = google_pubsub_topic.doc_ingestion.name }
output "questionnaire_events_topic_id"{ value = google_pubsub_topic.questionnaire_events.id }
output "questionnaire_events_topic_name" { value = google_pubsub_topic.questionnaire_events.name }
output "notifications_topic_id"       { value = google_pubsub_topic.notifications.id }
output "bq_streaming_topic_id"        { value = google_pubsub_topic.bq_streaming.id }
output "dead_letter_topic_id"         { value = google_pubsub_topic.dead_letter.id }
