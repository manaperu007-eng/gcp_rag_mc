##############################################################################
# outputs.tf - Root Outputs
##############################################################################

output "project_id" {
  description = "GCP project ID"
  value       = var.project_id
}

output "region" {
  description = "Deployment region"
  value       = var.region
}

# ------ Storage ------
output "document_bucket_name" {
  description = "Cloud Storage bucket for raw document uploads (PDF, DOCX, XLSX)"
  value       = module.storage.document_bucket_name
}

output "processed_bucket_name" {
  description = "Cloud Storage bucket for processed document chunks and embeddings"
  value       = module.storage.processed_bucket_name
}

output "evidence_bucket_name" {
  description = "Cloud Storage bucket for questionnaire evidence file uploads"
  value       = module.storage.evidence_bucket_name
}

output "reports_bucket_name" {
  description = "Cloud Storage bucket for exported reports"
  value       = module.storage.reports_bucket_name
}

# ------ BigQuery ------
output "bigquery_dataset_id" {
  description = "Main BigQuery dataset ID"
  value       = module.bigquery.main_dataset_id
}

output "bigquery_dataset_location" {
  description = "BigQuery dataset location"
  value       = module.bigquery.dataset_location
}

# ------ Vertex AI ------
output "vertex_ai_index_id" {
  description = "Vertex AI Vector Search index ID"
  value       = module.vertex_ai.index_id
}

output "vertex_ai_index_endpoint" {
  description = "Vertex AI Vector Search index endpoint ID"
  value       = module.vertex_ai.index_endpoint_id
}

# ------ Cloud Run ------
output "api_service_url" {
  description = "URL for the main API backend (Cloud Run)"
  value       = module.cloud_run.api_service_url
}

output "web_app_url" {
  description = "URL for the web frontend (Cloud Run)"
  value       = module.cloud_run.web_app_url
}

output "ingestion_service_url" {
  description = "URL for the document ingestion service (Cloud Run)"
  value       = module.cloud_run.ingestion_service_url
}

output "admin_service_url" {
  description = "URL for the admin reporting service (Cloud Run)"
  value       = module.cloud_run.admin_service_url
}

# ------ Pub/Sub ------
output "ingestion_topic" {
  description = "Pub/Sub topic for document ingestion events"
  value       = module.pubsub.ingestion_topic_id
}

output "questionnaire_events_topic" {
  description = "Pub/Sub topic for questionnaire response events"
  value       = module.pubsub.questionnaire_events_topic_id
}

# ------ IAM ------
output "app_sa_email" {
  description = "Application service account email"
  value       = module.iam.app_sa_email
}

output "ingestion_sa_email" {
  description = "Document ingestion service account email"
  value       = module.iam.ingestion_sa_email
}

# ------ Monitoring ------
output "monitoring_dashboard_url" {
  description = "Link to the Cloud Monitoring dashboard"
  value       = module.monitoring.dashboard_url
}

# ------ Firestore ------
output "firestore_database_id" {
  description = "Firestore database ID for session/chat state"
  value       = module.firestore.database_id
}
