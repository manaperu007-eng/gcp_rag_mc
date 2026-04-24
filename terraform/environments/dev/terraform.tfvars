##############################################################################
# environments/dev/terraform.tfvars
##############################################################################

project_id   = "your-project-id-dev"
region       = "us-central1"
environment  = "dev"

notification_email = "dev-alerts@yourdomain.com"

gemini_model    = "gemini-1.5-pro-002"
embedding_model = "text-embedding-004"

questionnaire_admin_users = [
  "dev-admin@yourdomain.com",
]

allowed_origins = ["*"]

cloud_run_min_instances = 0
cloud_run_max_instances = 3

document_retention_days = 90
bq_data_retention_days  = 0

enable_data_catalog = false
firestore_location  = "nam5"

labels = {
  project     = "kb-questionnaire"
  managed_by  = "terraform"
  environment = "dev"
  owner       = "platform-team"
}
