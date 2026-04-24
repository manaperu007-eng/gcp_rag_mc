##############################################################################
# modules/cloud_run/main.tf
# Cloud Run services: API, Web App, Ingestion Worker, Admin Dashboard
##############################################################################

variable "project_id"             { type = string }
variable "region"                 { type = string }
variable "suffix"                 { type = string }
variable "environment"            { type = string }
variable "app_sa"                 { type = string }
variable "ingestion_sa"           { type = string }
variable "vpc_connector"          { type = string }
variable "document_bucket"        { type = string }
variable "evidence_bucket"        { type = string }
variable "bq_dataset"             { type = string }
variable "vertex_index_endpoint"  { type = string }

variable "min_instances" {
  type    = number
  default = 0
}

variable "max_instances" {
  type    = number
  default = 10
}

variable "allowed_origins" {
  type    = list(string)
  default = ["*"]
}

variable "gemini_model" {
  type    = string
  default = "gemini-1.5-pro-002"
}

variable "embedding_model" {
  type    = string
  default = "text-embedding-004"
}

##############################################################################
# 1. API Backend Service
# FastAPI/Python — handles auth, questionnaire CRUD, response submission,
# AI chat interface, signed URL generation for file uploads
##############################################################################

resource "google_cloud_run_v2_service" "api" {
  project  = var.project_id
  name     = "kb-api-${var.suffix}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  labels = {
    env        = var.environment
    managed_by = "terraform"
    component  = "api"
  }

  template {
    service_account = var.app_sa

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    vpc_access {
      connector = var.vpc_connector
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/kb-app-images/kb-api:latest"

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
        cpu_idle = true
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "REGION"
        value = var.region
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "BQ_DATASET"
        value = var.bq_dataset
      }
      env {
        name  = "DOCUMENT_BUCKET"
        value = var.document_bucket
      }
      env {
        name  = "EVIDENCE_BUCKET"
        value = var.evidence_bucket
      }
      env {
        name  = "VERTEX_INDEX_ENDPOINT"
        value = var.vertex_index_endpoint
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "EMBEDDING_MODEL"
        value = var.embedding_model
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = join(",", var.allowed_origins)
      }
      env {
        name = "DB_SECRET"
        value_source {
          secret_key_ref {
            secret  = "kb-db-password"
            version = "latest"
          }
        }
      }
      env {
        name = "JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = "kb-jwt-secret"
            version = "latest"
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 10
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        period_seconds    = 30
        failure_threshold = 3
      }
    }

    annotations = {
      "autoscaling.knative.dev/maxScale" = tostring(var.max_instances)
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# Allow unauthenticated access to API (JWT-protected internally)
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

##############################################################################
# 2. Web Frontend Service
# React SPA served via nginx
##############################################################################

resource "google_cloud_run_v2_service" "web" {
  project  = var.project_id
  name     = "kb-web-${var.suffix}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  labels = {
    env        = var.environment
    managed_by = "terraform"
    component  = "web"
  }

  template {
    service_account = var.app_sa

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/kb-app-images/kb-web:latest"

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      ports {
        container_port = 3000
      }

      env {
        name  = "REACT_APP_API_URL"
        value = "https://kb-api-${var.suffix}-placeholder.run.app"
      }
      env {
        name  = "REACT_APP_ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "REACT_APP_PROJECT_ID"
        value = var.project_id
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

##############################################################################
# 3. Document Ingestion Worker Service
# Processes PDFs, DOCX, XLSX via Document AI + Vertex AI
##############################################################################

resource "google_cloud_run_v2_service" "ingestion" {
  project  = var.project_id
  name     = "kb-ingestion-${var.suffix}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"   # Only Pub/Sub push

  labels = {
    env        = var.environment
    managed_by = "terraform"
    component  = "ingestion"
  }

  template {
    service_account = var.ingestion_sa

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    vpc_access {
      connector = var.vpc_connector
      egress    = "ALL_TRAFFIC"
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/kb-app-images/kb-ingestion:latest"

      resources {
        limits = {
          cpu    = "4"
          memory = "8Gi"
        }
        cpu_idle          = false  # Keep CPU always on during processing
        startup_cpu_boost = true
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "REGION"
        value = var.region
      }
      env {
        name  = "DOCUMENT_BUCKET"
        value = var.document_bucket
      }
      env {
        name  = "BQ_DATASET"
        value = var.bq_dataset
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "EMBEDDING_MODEL"
        value = var.embedding_model
      }
      env {
        name  = "VERTEX_INDEX_ENDPOINT"
        value = var.vertex_index_endpoint
      }
    }

    timeout = "3600s"  # 1 hour for large documents
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

resource "google_cloud_run_v2_service_iam_member" "ingestion_pubsub" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ingestion.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.ingestion_sa}"
}

##############################################################################
# 4. Admin Dashboard + Reporting Service
##############################################################################

resource "google_cloud_run_v2_service" "admin" {
  project  = var.project_id
  name     = "kb-admin-${var.suffix}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  labels = {
    env        = var.environment
    managed_by = "terraform"
    component  = "admin"
  }

  template {
    service_account = var.app_sa

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    vpc_access {
      connector = var.vpc_connector
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/kb-app-images/kb-admin:latest"

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
        cpu_idle = true
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "REGION"
        value = var.region
      }
      env {
        name  = "BQ_DATASET"
        value = var.bq_dataset
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name = "ADMIN_JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = "kb-admin-jwt-secret"
            version = "latest"
          }
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

resource "google_cloud_run_v2_service_iam_member" "admin_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.admin.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

##############################################################################
# 5. Chat Interface Service (Vertex AI Gemini chat backend)
##############################################################################

resource "google_cloud_run_v2_service" "chat" {
  project  = var.project_id
  name     = "kb-chat-${var.suffix}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  labels = {
    env        = var.environment
    managed_by = "terraform"
    component  = "chat"
  }

  template {
    service_account = var.app_sa

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    vpc_access {
      connector = var.vpc_connector
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/kb-app-images/kb-chat:latest"

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
        cpu_idle = true
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "REGION"
        value = var.region
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "VERTEX_INDEX_ENDPOINT"
        value = var.vertex_index_endpoint
      }
      env {
        name  = "BQ_DATASET"
        value = var.bq_dataset
      }
      env {
        name  = "FIRESTORE_DB"
        value = "(default)"
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

resource "google_cloud_run_v2_service_iam_member" "chat_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.chat.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

##############################################################################
# Cloud Run Job: Batch report generation
##############################################################################

resource "google_cloud_run_v2_job" "report_generator" {
  project  = var.project_id
  name     = "kb-report-gen-${var.suffix}"
  location = var.region

  labels = {
    env        = var.environment
    managed_by = "terraform"
  }

  template {
    template {
      service_account = var.app_sa

      timeout = "3600s"

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/kb-app-images/kb-report-gen:latest"

        resources {
          limits = {
            cpu    = "4"
            memory = "4Gi"
          }
        }

        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "BQ_DATASET"
          value = var.bq_dataset
        }
        env {
          name  = "REGION"
          value = var.region
        }
      }
    }
  }
}

##############################################################################
# Cloud Scheduler: trigger nightly report generation
##############################################################################

resource "google_cloud_scheduler_job" "nightly_reports" {
  project     = var.project_id
  region      = var.region
  name        = "kb-nightly-reports-${var.suffix}"
  description = "Triggers nightly batch report generation"
  schedule    = "0 3 * * *"
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.report_generator.name}:run"

    oauth_token {
      service_account_email = var.app_sa
    }
  }
}

##############################################################################
# Outputs
##############################################################################

output "api_service_url"       { value = google_cloud_run_v2_service.api.uri }
output "web_app_url"           { value = google_cloud_run_v2_service.web.uri }
output "ingestion_service_url" { value = google_cloud_run_v2_service.ingestion.uri }
output "admin_service_url"     { value = google_cloud_run_v2_service.admin.uri }
output "chat_service_url"      { value = google_cloud_run_v2_service.chat.uri }
output "ingestion_service_name"{ value = google_cloud_run_v2_service.ingestion.name }
