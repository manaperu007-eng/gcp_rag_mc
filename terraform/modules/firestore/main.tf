##############################################################################
# modules/firestore/main.tf
# Firestore for chat session state, user progress cache, and real-time updates
##############################################################################

variable "project_id"         { type = string }
variable "region"             { type = string }
variable "app_sa"             { type = string }

variable "firestore_location" {
  type    = string
  default = "nam5"  # Multi-region US
}

##############################################################################
# Firestore Database
##############################################################################

resource "google_firestore_database" "main" {
  project                     = var.project_id
  name                        = "(default)"
  location_id                 = var.firestore_location
  type                        = "FIRESTORE_NATIVE"
  concurrency_mode            = "OPTIMISTIC"
  app_engine_integration_mode = "DISABLED"

  delete_protection_state = "DELETE_PROTECTION_ENABLED"
  deletion_policy         = "DELETE"
}

##############################################################################
# Firestore Indexes for common query patterns
#
# Collections used:
#  - chat_sessions    : {session_id} -> messages[], user_id, questionnaire_id
#  - user_progress    : {user_id}    -> {questionnaire_id} -> answered_question_ids[]
#  - active_sessions  : {session_id} -> last_active, user_id
#  - notifications    : {user_id}    -> {notification_id} -> ...
##############################################################################

# Index: chat_sessions by user_id + created_at
resource "google_firestore_index" "chat_sessions_by_user" {
  project    = var.project_id
  collection = "chat_sessions"
  database   = google_firestore_database.main.name

  fields {
    field_path = "user_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}

# Index: chat_sessions by questionnaire_id + user_id
resource "google_firestore_index" "chat_sessions_by_questionnaire" {
  project    = var.project_id
  collection = "chat_sessions"
  database   = google_firestore_database.main.name

  fields {
    field_path = "questionnaire_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "user_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "last_active"
    order      = "DESCENDING"
  }
}

# Index: user_progress by questionnaire_id
resource "google_firestore_index" "progress_by_questionnaire" {
  project    = var.project_id
  collection = "user_progress"
  database   = google_firestore_database.main.name

  fields {
    field_path = "questionnaire_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "updated_at"
    order      = "DESCENDING"
  }
}

# Index: notifications by user_id + is_read + created_at
resource "google_firestore_index" "notifications_by_user" {
  project    = var.project_id
  collection = "notifications"
  database   = google_firestore_database.main.name

  fields {
    field_path = "user_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "is_read"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}

##############################################################################
# Firestore IAM
##############################################################################

resource "google_project_iam_member" "firestore_app_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${var.app_sa}"
}

##############################################################################
# Firestore Backup (for prod)
##############################################################################

resource "google_firestore_backup_schedule" "weekly_backup" {
  project  = var.project_id
  database = google_firestore_database.main.name

  retention = "8467200s"  # 98 days

  weekly_recurrence {
    day = "SUNDAY"
  }
}

##############################################################################
# Outputs
##############################################################################

output "database_id"       { value = google_firestore_database.main.name }
output "database_location" { value = google_firestore_database.main.location_id }
