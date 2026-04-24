##############################################################################
# modules/vertex_ai/main.tf
# Vertex AI: Vector Search index, RAG corpus, and Model Garden config
##############################################################################

variable "project_id"       { type = string }
variable "region"           { type = string }
variable "suffix"           { type = string }
variable "environment"      { type = string }
variable "ingestion_sa"     { type = string }
variable "app_sa"           { type = string }
variable "document_bucket"  { type = string }
variable "processed_bucket" { type = string }

variable "embedding_model" {
  type    = string
  default = "text-embedding-004"
}

variable "gemini_model" {
  type    = string
  default = "gemini-1.5-pro-002"
}

##############################################################################
# Vertex AI Vector Search Index
# Stores dense embeddings for semantic KB search
##############################################################################

resource "google_vertex_ai_index" "kb_embeddings" {
  project      = var.project_id
  region       = var.region
  display_name = "kb-embeddings-${var.environment}"
  description  = "Vector index for knowledge base document chunk embeddings"

  metadata {
    contents_delta_uri = "gs://${var.processed_bucket}/embeddings/"
    config {
      dimensions                  = 768  # text-embedding-004 output dimensions
      approximate_neighbors_count = 150
      distance_measure_type       = "DOT_PRODUCT_DISTANCE"
      shard_size                  = "SHARD_SIZE_MEDIUM"

      algorithm_config {
        tree_ah_config {
          leaf_node_embedding_count    = 1000
          leaf_nodes_to_search_percent = 10
        }
      }
    }
  }

  index_update_method = "STREAM_UPDATE"

  labels = {
    env        = var.environment
    managed_by = "terraform"
  }
}

##############################################################################
# Vertex AI Index Endpoint
# Deploys the Vector Search index for serving
##############################################################################

resource "google_vertex_ai_index_endpoint" "kb_endpoint" {
  project      = var.project_id
  region       = var.region
  display_name = "kb-endpoint-${var.environment}"
  description  = "Endpoint for KB vector search"

  # Public endpoint — swap to private_service_connect_config for prod
  public_endpoint_enabled = true

  labels = {
    env        = var.environment
    managed_by = "terraform"
  }
}

resource "google_vertex_ai_index_endpoint_deployed_index" "kb_deployed" {
  index_endpoint  = google_vertex_ai_index_endpoint.kb_endpoint.id
  index           = google_vertex_ai_index.kb_embeddings.id
  deployed_index_id = "kb_deployed_${var.environment}"
  display_name    = "KB Deployed Index (${var.environment})"

  dedicated_resources {
    machine_spec {
      machine_type = var.environment == "prod" ? "e2-standard-16" : "e2-standard-2"
    }
    min_replica_count = var.environment == "prod" ? 2 : 1
    max_replica_count = var.environment == "prod" ? 5 : 2
  }

  depends_on = [
    google_vertex_ai_index.kb_embeddings,
    google_vertex_ai_index_endpoint.kb_endpoint
  ]
}

##############################################################################
# Vertex AI RAG Corpus (Vertex AI Search & Conversation)
# Managed RAG pipeline for document Q&A
##############################################################################

resource "google_vertex_ai_rag_corpus" "kb_corpus" {
  project      = var.project_id
  location     = var.region
  display_name = "kb-rag-corpus-${var.environment}"
  description  = "RAG corpus containing all knowledge base documents"

  vertex_ai_search_config {
    serving_config = "projects/${var.project_id}/locations/global/collections/default_collection/engines/kb-engine-${var.suffix}/servingConfigs/default_serving_config"
  }
}

##############################################################################
# Vertex AI Feature Store (for user preference / session features)
##############################################################################

resource "google_vertex_ai_feature_online_store" "user_features" {
  project      = var.project_id
  provider     = google-beta
  name         = "kb_user_features_${var.suffix}"
  region       = var.region

  optimized {}

  labels = {
    env        = var.environment
    managed_by = "terraform"
  }
}

##############################################################################
# Document AI Processor (for PDF / DOCX parsing)
##############################################################################

resource "google_document_ai_processor" "document_parser" {
  project      = var.project_id
  location     = "us"  # Document AI is US/EU only
  display_name = "KB Document Parser"
  type         = "FORM_PARSER_PROCESSOR"
}

resource "google_document_ai_processor" "ocr_processor" {
  project      = var.project_id
  location     = "us"
  display_name = "KB OCR Processor"
  type         = "OCR_PROCESSOR"
}

##############################################################################
# Vertex AI Workbench (optional: for data scientists to explore the KB)
##############################################################################

resource "google_workbench_instance" "ds_notebook" {
  count    = var.environment == "prod" ? 0 : 1  # Only in non-prod
  project  = var.project_id
  location = "${var.region}-a"
  name     = "kb-ds-notebook-${var.suffix}"

  gce_setup {
    machine_type = "n1-standard-4"

    data_disks {
      disk_size_gb = 100
      disk_type    = "PD_STANDARD"
    }

    service_accounts {
      email = var.ingestion_sa
    }

    metadata = {
      terraform = "true"
    }
  }

  labels = {
    env        = var.environment
    managed_by = "terraform"
  }
}

##############################################################################
# Cloud Scheduler: Nightly index rebuild
##############################################################################

resource "google_cloud_scheduler_job" "index_refresh" {
  project     = var.project_id
  region      = var.region
  name        = "kb-index-refresh-${var.suffix}"
  description = "Triggers nightly Vector Search index update from processed embeddings"
  schedule    = "0 2 * * *"  # 2 AM daily
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-aiplatform.googleapis.com/v1/${google_vertex_ai_index.kb_embeddings.name}:upsertDatapoints"

    oauth_token {
      service_account_email = var.ingestion_sa
    }
  }
}

##############################################################################
# Outputs
##############################################################################

output "index_id"               { value = google_vertex_ai_index.kb_embeddings.id }
output "index_name"             { value = google_vertex_ai_index.kb_embeddings.name }
output "index_endpoint_id"      { value = google_vertex_ai_index_endpoint.kb_endpoint.id }
output "index_endpoint_name"    { value = google_vertex_ai_index_endpoint.kb_endpoint.name }
output "rag_corpus_id"          { value = google_vertex_ai_rag_corpus.kb_corpus.id }
output "document_parser_id"     { value = google_document_ai_processor.document_parser.id }
output "ocr_processor_id"       { value = google_document_ai_processor.ocr_processor.id }
output "gemini_model"           { value = var.gemini_model }
output "embedding_model"        { value = var.embedding_model }
