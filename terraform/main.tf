##############################################################################
# main.tf - Root Terraform Configuration
# Knowledge Base & Questionnaire Platform on GCP
##############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }

  # Uncomment and configure for remote state
  # backend "gcs" {
  #   bucket = "YOUR_TERRAFORM_STATE_BUCKET"
  #   prefix = "terraform/state"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

##############################################################################
# Random suffix for globally unique resource names
##############################################################################
resource "random_id" "suffix" {
  byte_length = 4
}

##############################################################################
# Modules
##############################################################################

module "project_services" {
  source     = "./modules/project_services"
  project_id = var.project_id
}

module "iam" {
  source     = "./modules/iam"
  project_id = var.project_id
  region     = var.region
  suffix     = random_id.suffix.hex

  depends_on = [module.project_services]
}

module "networking" {
  source     = "./modules/networking"
  project_id = var.project_id
  region     = var.region
  suffix     = random_id.suffix.hex

  depends_on = [module.project_services]
}

module "storage" {
  source          = "./modules/storage"
  project_id      = var.project_id
  region          = var.region
  suffix          = random_id.suffix.hex
  environment     = var.environment
  ingestion_sa    = module.iam.ingestion_sa_email
  app_sa          = module.iam.app_sa_email

  depends_on = [module.project_services, module.iam]
}

module "bigquery" {
  source          = "./modules/bigquery"
  project_id      = var.project_id
  region          = var.region
  suffix          = random_id.suffix.hex
  environment     = var.environment
  app_sa          = module.iam.app_sa_email
  reporting_sa    = module.iam.reporting_sa_email

  depends_on = [module.project_services, module.iam]
}

module "vertex_ai" {
  source              = "./modules/vertex_ai"
  project_id          = var.project_id
  region              = var.region
  suffix              = random_id.suffix.hex
  environment         = var.environment
  ingestion_sa        = module.iam.ingestion_sa_email
  app_sa              = module.iam.app_sa_email
  document_bucket     = module.storage.document_bucket_name
  processed_bucket    = module.storage.processed_bucket_name

  depends_on = [module.project_services, module.iam, module.storage]
}

module "cloud_run" {
  source              = "./modules/cloud_run"
  project_id          = var.project_id
  region              = var.region
  suffix              = random_id.suffix.hex
  environment         = var.environment
  app_sa              = module.iam.app_sa_email
  ingestion_sa        = module.iam.ingestion_sa_email
  vpc_connector       = module.networking.vpc_connector_id
  document_bucket     = module.storage.document_bucket_name
  evidence_bucket     = module.storage.evidence_bucket_name
  bq_dataset          = module.bigquery.main_dataset_id
  vertex_index_endpoint = module.vertex_ai.index_endpoint_id

  depends_on = [module.project_services, module.iam, module.networking, module.storage, module.bigquery, module.vertex_ai]
}

module "pubsub" {
  source          = "./modules/pubsub"
  project_id      = var.project_id
  region          = var.region
  suffix          = random_id.suffix.hex
  ingestion_sa    = module.iam.ingestion_sa_email
  app_sa          = module.iam.app_sa_email

  depends_on = [module.project_services, module.iam]
}

module "cloud_functions" {
  source              = "./modules/cloud_functions"
  project_id          = var.project_id
  region              = var.region
  suffix              = random_id.suffix.hex
  environment         = var.environment
  ingestion_sa        = module.iam.ingestion_sa_email
  document_bucket     = module.storage.document_bucket_name
  processed_bucket    = module.storage.processed_bucket_name
  functions_bucket    = module.storage.functions_bucket_name
  ingestion_topic     = module.pubsub.ingestion_topic_id
  bq_dataset          = module.bigquery.main_dataset_id

  depends_on = [module.project_services, module.iam, module.storage, module.pubsub, module.bigquery]
}

module "firestore" {
  source          = "./modules/firestore"
  project_id      = var.project_id
  region          = var.region
  app_sa          = module.iam.app_sa_email

  depends_on = [module.project_services, module.iam]
}

module "secret_manager" {
  source          = "./modules/secret_manager"
  project_id      = var.project_id
  region          = var.region
  app_sa          = module.iam.app_sa_email
  ingestion_sa    = module.iam.ingestion_sa_email

  depends_on = [module.project_services, module.iam]
}

module "monitoring" {
  source          = "./modules/monitoring"
  project_id      = var.project_id
  region          = var.region
  environment     = var.environment
  notification_email = var.notification_email

  depends_on = [module.project_services, module.cloud_run, module.cloud_functions]
}
