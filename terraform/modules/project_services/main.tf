##############################################################################
# modules/project_services/main.tf
# Enable all required GCP APIs
##############################################################################

variable "project_id" {
  type = string
}

locals {
  services = [
    # Core compute & serverless
    "run.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudbuild.googleapis.com",
    "appengine.googleapis.com",

    # Storage
    "storage.googleapis.com",
    "storage-component.googleapis.com",

    # Data & Analytics
    "bigquery.googleapis.com",
    "bigquerystorage.googleapis.com",
    "bigquerydatatransfer.googleapis.com",
    "dataflow.googleapis.com",

    # AI / ML
    "aiplatform.googleapis.com",
    "discoveryengine.googleapis.com",
    "documentai.googleapis.com",
    "translate.googleapis.com",

    # Messaging
    "pubsub.googleapis.com",

    # Networking
    "compute.googleapis.com",
    "vpcaccess.googleapis.com",
    "servicenetworking.googleapis.com",

    # Identity & Security
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudkms.googleapis.com",
    "identitytoolkit.googleapis.com",
    "firebase.googleapis.com",

    # Firestore (NoSQL for sessions/chat state)
    "firestore.googleapis.com",

    # Monitoring & Logging
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "cloudtrace.googleapis.com",
    "clouderrorreporting.googleapis.com",

    # Artifact Registry (container images)
    "artifactregistry.googleapis.com",

    # Scheduler (periodic tasks)
    "cloudscheduler.googleapis.com",

    # Tasks (async jobs)
    "cloudtasks.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.services)

  project                    = var.project_id
  service                    = each.value
  disable_dependent_services = false
  disable_on_destroy         = false
}
