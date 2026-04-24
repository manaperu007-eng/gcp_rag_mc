##############################################################################
# modules/secret_manager/main.tf
# Secret Manager secrets for sensitive config values
##############################################################################

variable "project_id"    { type = string }
variable "region"        { type = string }
variable "app_sa"        { type = string }
variable "ingestion_sa"  { type = string }

##############################################################################
# Secrets (values are set manually or via CI/CD — not in Terraform)
##############################################################################

locals {
  secrets = {
    "kb-jwt-secret"        = "JWT signing secret for API authentication"
    "kb-admin-jwt-secret"  = "JWT signing secret for admin panel authentication"
    "kb-db-password"       = "Database password (if Cloud SQL added later)"
    "kb-sendgrid-api-key"  = "SendGrid API key for email notifications"
    "kb-firebase-config"   = "Firebase client config JSON for frontend auth"
    "kb-vertex-api-key"    = "Vertex AI API key (fallback for non-ADC environments)"
    "kb-encryption-key"    = "AES-256 key for encrypting PII in BigQuery"
    "kb-webhook-secret"    = "Secret for validating incoming webhook requests"
  }
}

resource "google_secret_manager_secret" "secrets" {
  for_each = local.secrets

  project   = var.project_id
  secret_id = each.key

  replication {
    auto {}
  }

  labels = {
    managed_by  = "terraform"
    description = replace(lower(each.value), " ", "-")
  }
}

##############################################################################
# IAM: grant app SA access to secrets it needs
##############################################################################

locals {
  app_sa_secrets = [
    "kb-jwt-secret",
    "kb-admin-jwt-secret",
    "kb-db-password",
    "kb-firebase-config",
    "kb-encryption-key",
    "kb-webhook-secret",
  ]

  ingestion_sa_secrets = [
    "kb-vertex-api-key",
    "kb-sendgrid-api-key",
    "kb-encryption-key",
  ]
}

resource "google_secret_manager_secret_iam_member" "app_sa_access" {
  for_each = toset(local.app_sa_secrets)

  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.app_sa}"

  depends_on = [google_secret_manager_secret.secrets]
}

resource "google_secret_manager_secret_iam_member" "ingestion_sa_access" {
  for_each = toset(local.ingestion_sa_secrets)

  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.ingestion_sa}"

  depends_on = [google_secret_manager_secret.secrets]
}

##############################################################################
# Placeholder versions — replace with actual values before apply
# These create empty versions so Cloud Run can reference the secrets
##############################################################################

resource "google_secret_manager_secret_version" "jwt_placeholder" {
  secret      = google_secret_manager_secret.secrets["kb-jwt-secret"].id
  secret_data = "REPLACE_ME_jwt_secret_min_32_chars_long"

  lifecycle {
    ignore_changes = [secret_data]  # Don't overwrite once set
  }
}

resource "google_secret_manager_secret_version" "admin_jwt_placeholder" {
  secret      = google_secret_manager_secret.secrets["kb-admin-jwt-secret"].id
  secret_data = "REPLACE_ME_admin_jwt_secret_min_32_chars"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret_version" "encryption_key_placeholder" {
  secret      = google_secret_manager_secret.secrets["kb-encryption-key"].id
  secret_data = "REPLACE_ME_32_byte_hex_key_for_aes256"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

##############################################################################
# Outputs
##############################################################################

output "secret_ids" {
  value = {
    for k, s in google_secret_manager_secret.secrets : k => s.secret_id
  }
}

output "jwt_secret_id"           { value = google_secret_manager_secret.secrets["kb-jwt-secret"].secret_id }
output "admin_jwt_secret_id"     { value = google_secret_manager_secret.secrets["kb-admin-jwt-secret"].secret_id }
output "sendgrid_secret_id"      { value = google_secret_manager_secret.secrets["kb-sendgrid-api-key"].secret_id }
output "firebase_config_secret_id" { value = google_secret_manager_secret.secrets["kb-firebase-config"].secret_id }
