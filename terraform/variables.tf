##############################################################################
# variables.tf - Global Variables
##############################################################################

variable "project_id" {
  description = "The GCP project ID"
  type        = string
}

variable "region" {
  description = "The default GCP region for resources"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "notification_email" {
  description = "Email address to receive monitoring alerts"
  type        = string
  default     = "admin@example.com"
}

variable "gemini_model" {
  description = "Vertex AI Gemini model to use for document processing and chat"
  type        = string
  default     = "gemini-1.5-pro-002"
}

variable "embedding_model" {
  description = "Vertex AI embedding model for vector search"
  type        = string
  default     = "text-embedding-004"
}

variable "questionnaire_admin_users" {
  description = "List of user emails to grant admin access"
  type        = list(string)
  default     = []
}

variable "allowed_origins" {
  description = "CORS allowed origins for the API"
  type        = list(string)
  default     = ["*"]
}

variable "cloud_run_min_instances" {
  description = "Minimum Cloud Run instances (0 = scale to zero)"
  type        = number
  default     = 0
}

variable "cloud_run_max_instances" {
  description = "Maximum Cloud Run instances"
  type        = number
  default     = 10
}

variable "document_retention_days" {
  description = "Number of days to retain source documents in Cloud Storage"
  type        = number
  default     = 365
}

variable "bq_data_retention_days" {
  description = "Number of days to retain BigQuery table data (0 = indefinite)"
  type        = number
  default     = 0
}

variable "enable_data_catalog" {
  description = "Enable Google Cloud Data Catalog for metadata management"
  type        = bool
  default     = false
}

variable "firestore_location" {
  description = "Firestore database location"
  type        = string
  default     = "nam5"
}

variable "labels" {
  description = "Common labels to apply to all resources"
  type        = map(string)
  default = {
    project     = "kb-questionnaire"
    managed_by  = "terraform"
  }
}
