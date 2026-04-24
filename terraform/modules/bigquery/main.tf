##############################################################################
# modules/bigquery/main.tf
# Dataset, Tables, and Views for KB Questionnaire platform
##############################################################################

variable "project_id"    { type = string }
variable "region"        { type = string }
variable "suffix"        { type = string }
variable "environment"   { type = string }
variable "app_sa"        { type = string }
variable "reporting_sa"  { type = string }

locals {
  bq_location = upper(var.region) == "US-CENTRAL1" ? "US" : var.region
}

##############################################################################
# Main Dataset
##############################################################################

resource "google_bigquery_dataset" "main" {
  project                    = var.project_id
  dataset_id                 = "kb_questionnaire_${var.environment}"
  friendly_name              = "KB Questionnaire Platform"
  description                = "Stores knowledge base documents, questionnaires, responses, and analytics"
  location                   = local.bq_location
  delete_contents_on_destroy = var.environment != "prod"

  labels = {
    env        = var.environment
    managed_by = "terraform"
  }

  access {
    role          = "OWNER"
    special_group = "projectOwners"
  }
  access {
    role          = "WRITER"
    user_by_email = var.app_sa
  }
  access {
    role          = "READER"
    user_by_email = var.reporting_sa
  }
}

##############################################################################
# Table: documents
# Tracks every ingested source document
##############################################################################

resource "google_bigquery_table" "documents" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "documents"
  description = "Source documents ingested into the knowledge base"

  deletion_protection = var.environment == "prod"

  time_partitioning {
    type  = "DAY"
    field = "ingested_at"
  }

  labels = { managed_by = "terraform" }

  schema = jsonencode([
    { name = "document_id",     type = "STRING",    mode = "REQUIRED", description = "UUID for the document" },
    { name = "file_name",       type = "STRING",    mode = "REQUIRED", description = "Original filename" },
    { name = "file_type",       type = "STRING",    mode = "REQUIRED", description = "pdf | docx | xlsx" },
    { name = "gcs_uri",         type = "STRING",    mode = "REQUIRED", description = "GCS URI of raw file" },
    { name = "processed_uri",   type = "STRING",    mode = "NULLABLE", description = "GCS URI of processed JSON" },
    { name = "title",           type = "STRING",    mode = "NULLABLE", description = "Extracted or provided title" },
    { name = "author",          type = "STRING",    mode = "NULLABLE", description = "Document author" },
    { name = "language",        type = "STRING",    mode = "NULLABLE", description = "Detected language code" },
    { name = "page_count",      type = "INTEGER",   mode = "NULLABLE", description = "Number of pages/sheets" },
    { name = "word_count",      type = "INTEGER",   mode = "NULLABLE", description = "Approximate word count" },
    { name = "tags",            type = "STRING",    mode = "REPEATED", description = "Classification tags" },
    { name = "category",        type = "STRING",    mode = "NULLABLE", description = "Document category" },
    { name = "status",          type = "STRING",    mode = "REQUIRED", description = "pending | processing | ready | failed" },
    { name = "error_message",   type = "STRING",    mode = "NULLABLE", description = "Error detail if status=failed" },
    { name = "chunk_count",     type = "INTEGER",   mode = "NULLABLE", description = "Number of text chunks generated" },
    { name = "ingested_at",     type = "TIMESTAMP", mode = "REQUIRED", description = "Ingestion timestamp" },
    { name = "processed_at",    type = "TIMESTAMP", mode = "NULLABLE", description = "Processing completion timestamp" },
    { name = "uploaded_by",     type = "STRING",    mode = "NULLABLE", description = "User email who uploaded" },
    { name = "kb_ids",          type = "STRING",    mode = "REPEATED", description = "Knowledge base IDs this doc belongs to" }
  ])
}

##############################################################################
# Table: document_chunks
# Vector-search indexed chunks from processed documents
##############################################################################

resource "google_bigquery_table" "document_chunks" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "document_chunks"
  description = "Text chunks from documents with embedding metadata"

  deletion_protection = var.environment == "prod"

  labels = { managed_by = "terraform" }

  schema = jsonencode([
    { name = "chunk_id",       type = "STRING",    mode = "REQUIRED", description = "UUID for chunk" },
    { name = "document_id",    type = "STRING",    mode = "REQUIRED", description = "FK to documents table" },
    { name = "chunk_index",    type = "INTEGER",   mode = "REQUIRED", description = "Chunk position within document" },
    { name = "content",        type = "STRING",    mode = "REQUIRED", description = "Chunk text content" },
    { name = "page_number",    type = "INTEGER",   mode = "NULLABLE", description = "Source page number" },
    { name = "section_title",  type = "STRING",    mode = "NULLABLE", description = "Section heading if detected" },
    { name = "token_count",    type = "INTEGER",   mode = "NULLABLE", description = "Token count of chunk" },
    { name = "embedding_id",   type = "STRING",    mode = "NULLABLE", description = "ID in Vertex AI Vector Search index" },
    { name = "created_at",     type = "TIMESTAMP", mode = "REQUIRED", description = "Timestamp of chunk creation" }
  ])
}

##############################################################################
# Table: knowledge_bases
##############################################################################

resource "google_bigquery_table" "knowledge_bases" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "knowledge_bases"
  description = "Knowledge bases grouping related documents"

  deletion_protection = var.environment == "prod"

  labels = { managed_by = "terraform" }

  schema = jsonencode([
    { name = "kb_id",          type = "STRING",    mode = "REQUIRED" },
    { name = "name",           type = "STRING",    mode = "REQUIRED" },
    { name = "description",    type = "STRING",    mode = "NULLABLE" },
    { name = "document_count", type = "INTEGER",   mode = "NULLABLE" },
    { name = "created_by",     type = "STRING",    mode = "NULLABLE" },
    { name = "created_at",     type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "updated_at",     type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "is_active",      type = "BOOLEAN",   mode = "REQUIRED" }
  ])
}

##############################################################################
# Table: questionnaires
##############################################################################

resource "google_bigquery_table" "questionnaires" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "questionnaires"
  description = "Questionnaire definitions"

  deletion_protection = var.environment == "prod"

  labels = { managed_by = "terraform" }

  schema = jsonencode([
    { name = "questionnaire_id",  type = "STRING",    mode = "REQUIRED" },
    { name = "title",             type = "STRING",    mode = "REQUIRED" },
    { name = "description",       type = "STRING",    mode = "NULLABLE" },
    { name = "kb_id",             type = "STRING",    mode = "NULLABLE", description = "Associated knowledge base" },
    { name = "version",           type = "INTEGER",   mode = "REQUIRED" },
    { name = "status",            type = "STRING",    mode = "REQUIRED", description = "draft | published | archived" },
    { name = "total_questions",   type = "INTEGER",   mode = "NULLABLE" },
    { name = "passing_score",     type = "FLOAT",     mode = "NULLABLE" },
    { name = "time_limit_mins",   type = "INTEGER",   mode = "NULLABLE" },
    { name = "due_date",          type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "geographic_scope",  type = "STRING",    mode = "NULLABLE", description = "global | region | country | city" },
    { name = "allowed_regions",   type = "STRING",    mode = "REPEATED", description = "Region filter list" },
    { name = "created_by",        type = "STRING",    mode = "NULLABLE" },
    { name = "created_at",        type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "published_at",      type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "updated_at",        type = "TIMESTAMP", mode = "NULLABLE" }
  ])
}

##############################################################################
# Table: questions
##############################################################################

resource "google_bigquery_table" "questions" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "questions"
  description = "Individual questions within questionnaires"

  deletion_protection = var.environment == "prod"

  labels = { managed_by = "terraform" }

  schema = jsonencode([
    { name = "question_id",        type = "STRING",    mode = "REQUIRED" },
    { name = "questionnaire_id",   type = "STRING",    mode = "REQUIRED" },
    { name = "parent_question_id", type = "STRING",    mode = "NULLABLE", description = "For conditional sub-questions" },
    { name = "question_text",      type = "STRING",    mode = "REQUIRED" },
    { name = "question_type",      type = "STRING",    mode = "REQUIRED", description = "free_text | file_upload | true_false | rating | multiple_choice | multi_select | date | number" },
    { name = "is_required",        type = "BOOLEAN",   mode = "REQUIRED" },
    { name = "order_index",        type = "INTEGER",   mode = "REQUIRED" },
    { name = "section",            type = "STRING",    mode = "NULLABLE", description = "Section/category grouping" },
    { name = "help_text",          type = "STRING",    mode = "NULLABLE", description = "Guidance shown to users" },
    { name = "kb_context",         type = "STRING",    mode = "NULLABLE", description = "Relevant KB chunk IDs for AI hint" },
    {
      name = "options",
      type = "RECORD",
      mode = "NULLABLE",
      description = "Configuration for structured question types",
      fields = [
        { name = "choices",        type = "STRING",  mode = "REPEATED" },
        { name = "min_rating",     type = "INTEGER", mode = "NULLABLE" },
        { name = "max_rating",     type = "INTEGER", mode = "NULLABLE" },
        { name = "rating_labels",  type = "STRING",  mode = "REPEATED" },
        { name = "allowed_file_types", type = "STRING", mode = "REPEATED" },
        { name = "max_file_size_mb",   type = "INTEGER", mode = "NULLABLE" }
      ]
    },
    { name = "ai_generated",       type = "BOOLEAN",   mode = "NULLABLE", description = "Whether question was AI-generated from KB" },
    { name = "source_chunk_ids",   type = "STRING",    mode = "REPEATED", description = "KB chunk IDs used to generate question" },
    { name = "created_at",         type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "updated_at",         type = "TIMESTAMP", mode = "NULLABLE" }
  ])
}

##############################################################################
# Table: user_assignments
# Which users are assigned which questionnaires
##############################################################################

resource "google_bigquery_table" "user_assignments" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "user_assignments"
  description = "Assignment of questionnaires to users"

  deletion_protection = var.environment == "prod"

  time_partitioning {
    type  = "DAY"
    field = "assigned_at"
  }

  labels = { managed_by = "terraform" }

  schema = jsonencode([
    { name = "assignment_id",      type = "STRING",    mode = "REQUIRED" },
    { name = "questionnaire_id",   type = "STRING",    mode = "REQUIRED" },
    { name = "user_id",            type = "STRING",    mode = "REQUIRED" },
    { name = "user_email",         type = "STRING",    mode = "NULLABLE" },
    { name = "user_name",          type = "STRING",    mode = "NULLABLE" },
    { name = "region",             type = "STRING",    mode = "NULLABLE" },
    { name = "country",            type = "STRING",    mode = "NULLABLE" },
    { name = "city",               type = "STRING",    mode = "NULLABLE" },
    { name = "department",         type = "STRING",    mode = "NULLABLE" },
    { name = "status",             type = "STRING",    mode = "REQUIRED", description = "not_started | in_progress | submitted | reviewed" },
    { name = "completion_pct",     type = "FLOAT",     mode = "NULLABLE" },
    { name = "score",              type = "FLOAT",     mode = "NULLABLE" },
    { name = "assigned_at",        type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "started_at",         type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "submitted_at",       type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "due_date",           type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "reminder_sent_at",   type = "TIMESTAMP", mode = "NULLABLE" }
  ])
}

##############################################################################
# Table: responses
# Individual question answers
##############################################################################

resource "google_bigquery_table" "responses" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "responses"
  description = "Individual question responses from users"

  deletion_protection = var.environment == "prod"

  time_partitioning {
    type  = "DAY"
    field = "responded_at"
  }

  clustering = ["questionnaire_id", "user_id"]

  labels = { managed_by = "terraform" }

  schema = jsonencode([
    { name = "response_id",       type = "STRING",    mode = "REQUIRED" },
    { name = "assignment_id",     type = "STRING",    mode = "REQUIRED" },
    { name = "questionnaire_id",  type = "STRING",    mode = "REQUIRED" },
    { name = "question_id",       type = "STRING",    mode = "REQUIRED" },
    { name = "user_id",           type = "STRING",    mode = "REQUIRED" },
    { name = "question_type",     type = "STRING",    mode = "REQUIRED" },
    { name = "answer_text",       type = "STRING",    mode = "NULLABLE", description = "For free_text responses" },
    { name = "answer_boolean",    type = "BOOLEAN",   mode = "NULLABLE", description = "For true_false responses" },
    { name = "answer_number",     type = "FLOAT",     mode = "NULLABLE", description = "For rating/number responses" },
    { name = "answer_choices",    type = "STRING",    mode = "REPEATED", description = "For multiple_choice/multi_select" },
    { name = "answer_date",       type = "DATE",      mode = "NULLABLE", description = "For date responses" },
    {
      name = "file_uploads",
      type = "RECORD",
      mode = "REPEATED",
      description = "Evidence files uploaded",
      fields = [
        { name = "file_id",        type = "STRING", mode = "REQUIRED" },
        { name = "file_name",      type = "STRING", mode = "REQUIRED" },
        { name = "gcs_uri",        type = "STRING", mode = "REQUIRED" },
        { name = "file_size_bytes",type = "INTEGER",mode = "NULLABLE" },
        { name = "content_type",   type = "STRING", mode = "NULLABLE" }
      ]
    },
    { name = "ai_hint_used",      type = "BOOLEAN",   mode = "NULLABLE" },
    { name = "channel",           type = "STRING",    mode = "NULLABLE", description = "web | chat" },
    { name = "responded_at",      type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "updated_at",        type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "is_draft",          type = "BOOLEAN",   mode = "NULLABLE" }
  ])
}

##############################################################################
# Table: users
##############################################################################

resource "google_bigquery_table" "users" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "users"
  description = "Platform users with profile and geographic metadata"

  deletion_protection = var.environment == "prod"

  labels = { managed_by = "terraform" }

  schema = jsonencode([
    { name = "user_id",      type = "STRING",    mode = "REQUIRED" },
    { name = "email",        type = "STRING",    mode = "REQUIRED" },
    { name = "display_name", type = "STRING",    mode = "NULLABLE" },
    { name = "role",         type = "STRING",    mode = "REQUIRED", description = "admin | reviewer | respondent" },
    { name = "region",       type = "STRING",    mode = "NULLABLE" },
    { name = "country",      type = "STRING",    mode = "NULLABLE" },
    { name = "city",         type = "STRING",    mode = "NULLABLE" },
    { name = "department",   type = "STRING",    mode = "NULLABLE" },
    { name = "is_active",    type = "BOOLEAN",   mode = "REQUIRED" },
    { name = "created_at",   type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "last_login_at",type = "TIMESTAMP", mode = "NULLABLE" }
  ])
}

##############################################################################
# Table: audit_logs
##############################################################################

resource "google_bigquery_table" "audit_logs" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "audit_logs"
  description = "Audit trail for all significant platform actions"

  deletion_protection = var.environment == "prod"

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }

  labels = { managed_by = "terraform" }

  schema = jsonencode([
    { name = "log_id",       type = "STRING",    mode = "REQUIRED" },
    { name = "timestamp",    type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "user_id",      type = "STRING",    mode = "NULLABLE" },
    { name = "user_email",   type = "STRING",    mode = "NULLABLE" },
    { name = "action",       type = "STRING",    mode = "REQUIRED", description = "e.g. DOCUMENT_UPLOADED, RESPONSE_SUBMITTED" },
    { name = "resource_type",type = "STRING",    mode = "NULLABLE" },
    { name = "resource_id",  type = "STRING",    mode = "NULLABLE" },
    { name = "ip_address",   type = "STRING",    mode = "NULLABLE" },
    { name = "user_agent",   type = "STRING",    mode = "NULLABLE" },
    { name = "details",      type = "JSON",      mode = "NULLABLE" }
  ])
}

##############################################################################
# Analytics Views
##############################################################################

resource "google_bigquery_table" "vw_questionnaire_completion" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "vw_questionnaire_completion"
  description = "Admin view: questionnaire completion rates with geographic breakdown"

  deletion_protection = false

  view {
    query = <<-SQL
      SELECT
        q.title                                         AS questionnaire_title,
        q.status                                        AS questionnaire_status,
        ua.region,
        ua.country,
        ua.city,
        ua.department,
        COUNT(DISTINCT ua.user_id)                     AS total_assigned,
        COUNTIF(ua.status = 'submitted')               AS total_submitted,
        COUNTIF(ua.status = 'not_started')             AS total_not_started,
        COUNTIF(ua.status = 'in_progress')             AS total_in_progress,
        SAFE_DIVIDE(
          COUNTIF(ua.status = 'submitted'),
          COUNT(DISTINCT ua.user_id)
        ) * 100                                        AS completion_rate_pct,
        AVG(ua.completion_pct)                         AS avg_completion_pct,
        AVG(ua.score)                                  AS avg_score,
        MIN(ua.assigned_at)                            AS first_assigned,
        MAX(ua.submitted_at)                           AS last_submitted
      FROM `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.user_assignments` ua
      JOIN `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.questionnaires` q
        ON ua.questionnaire_id = q.questionnaire_id
      GROUP BY 1,2,3,4,5,6
    SQL
    use_legacy_sql = false
  }

  labels = { managed_by = "terraform", type = "view" }
}

resource "google_bigquery_table" "vw_response_summary" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "vw_response_summary"
  description = "Admin view: per-question response statistics"

  deletion_protection = false

  view {
    query = <<-SQL
      SELECT
        r.questionnaire_id,
        r.question_id,
        q.question_text,
        q.question_type,
        q.section,
        COUNT(DISTINCT r.user_id)                       AS total_respondents,
        COUNTIF(r.answer_text IS NOT NULL
          OR r.answer_boolean IS NOT NULL
          OR r.answer_number IS NOT NULL
          OR ARRAY_LENGTH(r.answer_choices) > 0
          OR r.answer_date IS NOT NULL
          OR ARRAY_LENGTH(r.file_uploads) > 0)          AS answered_count,
        AVG(r.answer_number)                            AS avg_rating,
        COUNTIF(r.answer_boolean = TRUE)                AS true_count,
        COUNTIF(r.answer_boolean = FALSE)               AS false_count,
        COUNTIF(r.ai_hint_used = TRUE)                  AS ai_hint_used_count,
        MIN(r.responded_at)                             AS first_response,
        MAX(r.responded_at)                             AS last_response
      FROM `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.responses` r
      JOIN `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.questions` q
        ON r.question_id = q.question_id
      GROUP BY 1,2,3,4,5
    SQL
    use_legacy_sql = false
  }

  labels = { managed_by = "terraform", type = "view" }
}

resource "google_bigquery_table" "vw_overdue_assignments" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.main.dataset_id
  table_id   = "vw_overdue_assignments"
  description = "Admin view: users who have overdue incomplete questionnaires"

  deletion_protection = false

  view {
    query = <<-SQL
      SELECT
        ua.assignment_id,
        ua.user_id,
        ua.user_email,
        ua.user_name,
        ua.region,
        ua.country,
        ua.department,
        q.title                  AS questionnaire_title,
        ua.due_date,
        ua.status,
        ua.completion_pct,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), ua.due_date, DAY) AS days_overdue
      FROM `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.user_assignments` ua
      JOIN `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.questionnaires` q
        ON ua.questionnaire_id = q.questionnaire_id
      WHERE ua.due_date < CURRENT_TIMESTAMP()
        AND ua.status NOT IN ('submitted', 'reviewed')
      ORDER BY days_overdue DESC
    SQL
    use_legacy_sql = false
  }

  labels = { managed_by = "terraform", type = "view" }
}

##############################################################################
# Scheduled Query: daily completion snapshot
##############################################################################

resource "google_bigquery_data_transfer_config" "daily_snapshot" {
  project                = var.project_id
  display_name           = "Daily Completion Snapshot"
  location               = local.bq_location
  data_source_id         = "scheduled_query"
  schedule               = "every 24 hours"
  destination_dataset_id = google_bigquery_dataset.main.dataset_id
  service_account_name   = var.app_sa

  params = {
    query = <<-SQL
      INSERT INTO `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.audit_logs`
        (log_id, timestamp, action, details)
      VALUES (
        GENERATE_UUID(),
        CURRENT_TIMESTAMP(),
        'DAILY_SNAPSHOT',
        TO_JSON(STRUCT(
          (SELECT COUNT(*) FROM `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.user_assignments`
           WHERE status = 'submitted') AS submitted_count,
          (SELECT COUNT(*) FROM `${var.project_id}.${google_bigquery_dataset.main.dataset_id}.user_assignments`
           WHERE status != 'submitted') AS pending_count
        ))
      )
    SQL
  }
}

##############################################################################
# Outputs
##############################################################################

output "main_dataset_id"   { value = google_bigquery_dataset.main.dataset_id }
output "dataset_location"  { value = local.bq_location }
output "documents_table"   { value = google_bigquery_table.documents.table_id }
output "responses_table"   { value = google_bigquery_table.responses.table_id }
output "questions_table"   { value = google_bigquery_table.questions.table_id }
output "assignments_table" { value = google_bigquery_table.user_assignments.table_id }
