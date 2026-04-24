##############################################################################
# environments/staging/terraform.tfvars
##############################################################################

project_id   = "your-project-id-staging"
region       = "us-central1"
environment  = "staging"

notification_email = "staging-alerts@yourdomain.com"

gemini_model    = "gemini-1.5-pro-002"
embedding_model = "text-embedding-004"

questionnaire_admin_users = [
  "staging-admin@yourdomain.com",
  "qa-lead@yourdomain.com",
]

allowed_origins = [
  "https://staging.kb-questionnaire.yourdomain.com",
]

cloud_run_min_instances = 0
cloud_run_max_instances = 5

document_retention_days = 180
bq_data_retention_days  = 0

enable_data_catalog = false
firestore_location  = "nam5"

labels = {
  project     = "kb-questionnaire"
  managed_by  = "terraform"
  environment = "staging"
  owner       = "platform-team"
}
