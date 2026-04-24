##############################################################################
# environments/prod/terraform.tfvars
##############################################################################

project_id   = "your-project-id-prod"
region       = "us-central1"
environment  = "prod"

notification_email = "ops-alerts@yourdomain.com"

gemini_model    = "gemini-1.5-pro-002"
embedding_model = "text-embedding-004"

questionnaire_admin_users = [
  "admin@yourdomain.com",
]

allowed_origins = [
  "https://kb-questionnaire.yourdomain.com",
  "https://admin.kb-questionnaire.yourdomain.com",
]

cloud_run_min_instances = 1    # Keep warm in prod
cloud_run_max_instances = 20

document_retention_days = 365
bq_data_retention_days  = 0    # Indefinite retention in prod

enable_data_catalog = true
firestore_location  = "nam5"

labels = {
  project     = "kb-questionnaire"
  managed_by  = "terraform"
  environment = "prod"
  owner       = "platform-team"
  cost-center = "engineering"
}
