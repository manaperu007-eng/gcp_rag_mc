##############################################################################
# modules/monitoring/main.tf
# Cloud Monitoring: dashboards, alert policies, uptime checks, log sinks
##############################################################################

variable "project_id"          { type = string }
variable "region"              { type = string }
variable "environment"         { type = string }
variable "notification_email"  { type = string }

##############################################################################
# Notification Channel (email)
##############################################################################

resource "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  display_name = "KB Platform Admin Email"
  type         = "email"

  labels = {
    email_address = var.notification_email
  }
}

##############################################################################
# Uptime Checks
##############################################################################

resource "google_monitoring_uptime_check_config" "api_health" {
  project      = var.project_id
  display_name = "KB API Health Check"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = "kb-api-placeholder.run.app"
    }
  }
}

resource "google_monitoring_uptime_check_config" "chat_health" {
  project      = var.project_id
  display_name = "KB Chat Service Health Check"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = "kb-chat-placeholder.run.app"
    }
  }
}

##############################################################################
# Alert Policies
##############################################################################

# Alert: Cloud Run API error rate > 5%
resource "google_monitoring_alert_policy" "api_error_rate" {
  project      = var.project_id
  display_name = "KB API High Error Rate"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "API 5xx error rate > 5%"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.05

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields    = ["resource.label.service_name"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  alert_strategy {
    auto_close = "1800s"
  }

  documentation {
    content   = "The KB API service is reporting a high 5xx error rate (>5%). Check Cloud Run logs and Vertex AI connectivity."
    mime_type = "text/markdown"
  }
}

# Alert: Ingestion pipeline failures
resource "google_monitoring_alert_policy" "ingestion_failures" {
  project      = var.project_id
  display_name = "KB Document Ingestion Failures"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Dead-letter topic message count > 0"

    condition_threshold {
      filter          = "resource.type = \"pubsub_subscription\" AND metric.type = \"pubsub.googleapis.com/subscription/num_undelivered_messages\" AND resource.labels.subscription_id = monitoring.regex.full_match(\"kb-dead-letter.*\")"
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "Messages are accumulating in the dead-letter topic, indicating ingestion pipeline failures. Check Cloud Functions logs."
    mime_type = "text/markdown"
  }
}

# Alert: Cloud Run request latency > 5s
resource "google_monitoring_alert_policy" "high_latency" {
  project      = var.project_id
  display_name = "KB API High Latency"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "P95 latency > 5000ms"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND metric.type = \"run.googleapis.com/request_latencies\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 5000

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["resource.label.service_name"]
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "API P95 latency has exceeded 5 seconds. Check Cloud Run scaling limits and Vertex AI response times."
    mime_type = "text/markdown"
  }
}

# Alert: BigQuery slot utilization
resource "google_monitoring_alert_policy" "bq_slot_utilization" {
  project      = var.project_id
  display_name = "KB BigQuery High Slot Utilization"
  combiner     = "OR"
  enabled      = var.environment == "prod"

  conditions {
    display_name = "BQ slot utilization > 80%"

    condition_threshold {
      filter          = "resource.type = \"bigquery_project\" AND metric.type = \"bigquery.googleapis.com/slot/utilization\""
      duration        = "600s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.80

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "BigQuery slot utilization is above 80%. Consider purchasing additional slots or optimizing queries."
    mime_type = "text/markdown"
  }
}

# Alert: GCS storage cost spike (bytes stored > threshold)
resource "google_monitoring_alert_policy" "storage_size" {
  project      = var.project_id
  display_name = "KB Storage Usage High"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Document bucket > 100GB"

    condition_threshold {
      filter          = "resource.type = \"gcs_bucket\" AND metric.type = \"storage.googleapis.com/storage/total_bytes\""
      duration        = "3600s"
      comparison      = "COMPARISON_GT"
      threshold_value = 107374182400  # 100 GB in bytes

      aggregations {
        alignment_period   = "3600s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "Document storage has exceeded 100GB. Review document retention policies."
    mime_type = "text/markdown"
  }
}

# Alert: Uptime check failure
resource "google_monitoring_alert_policy" "uptime_failure" {
  project      = var.project_id
  display_name = "KB Service Uptime Failure"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Uptime check failing"

    condition_threshold {
      filter          = "metric.type = \"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type = \"uptime_url\""
      duration        = "300s"
      comparison      = "COMPARISON_LT"
      threshold_value = 1

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_TRUE"
        group_by_fields    = ["resource.label.host"]
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "A KB platform service is failing its uptime check. Immediate investigation required."
    mime_type = "text/markdown"
  }
}

##############################################################################
# Custom Dashboard
##############################################################################

resource "google_monitoring_dashboard" "main" {
  project        = var.project_id
  dashboard_json = jsonencode({
    displayName = "KB Questionnaire Platform — ${upper(var.environment)}"
    mosaicLayout = {
      columns = 12
      tiles = [
        # Row 1: API metrics
        {
          width = 4, height = 4, xPos = 0, yPos = 0
          widget = {
            title = "API Request Rate"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type = \"cloud_run_revision\" AND metric.type = \"run.googleapis.com/request_count\""
                    aggregation = {
                      alignmentPeriod = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 4, yPos = 0
          widget = {
            title = "API P95 Latency (ms)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type = \"cloud_run_revision\" AND metric.type = \"run.googleapis.com/request_latencies\""
                    aggregation = {
                      alignmentPeriod = "60s"
                      perSeriesAligner = "ALIGN_PERCENTILE_95"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 8, yPos = 0
          widget = {
            title = "5xx Error Rate"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type = \"cloud_run_revision\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\""
                    aggregation = {
                      alignmentPeriod = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        # Row 2: Ingestion metrics
        {
          width = 4, height = 4, xPos = 0, yPos = 4
          widget = {
            title = "Pub/Sub Ingestion Message Age (s)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type = \"pubsub_subscription\" AND metric.type = \"pubsub.googleapis.com/subscription/oldest_unacked_message_age\""
                    aggregation = {
                      alignmentPeriod = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 4, yPos = 4
          widget = {
            title = "Dead Letter Message Count"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type = \"pubsub_subscription\" AND metric.type = \"pubsub.googleapis.com/subscription/num_undelivered_messages\""
                    aggregation = {
                      alignmentPeriod = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 8, yPos = 4
          widget = {
            title = "Cloud Run Instance Count"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type = \"cloud_run_revision\" AND metric.type = \"run.googleapis.com/container/instance_count\""
                    aggregation = {
                      alignmentPeriod = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        }
      ]
    }
  })
}

##############################################################################
# Log Sinks → BigQuery (for long-term audit log retention)
##############################################################################

resource "google_bigquery_dataset" "logs" {
  project     = var.project_id
  dataset_id  = "kb_platform_logs_${var.environment}"
  location    = "US"
  description = "Cloud Logging export for audit and access logs"

  delete_contents_on_destroy = var.environment != "prod"
}

resource "google_logging_project_sink" "bq_audit_sink" {
  project                = var.project_id
  name                   = "kb-audit-logs-bq-${var.environment}"
  destination            = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${google_bigquery_dataset.logs.dataset_id}"
  filter                 = "resource.type = (\"cloud_run_revision\" OR \"cloudfunctions.googleapis.com/CloudFunction\" OR \"pubsub_subscription\") AND severity >= WARNING"
  unique_writer_identity = true

  bigquery_options {
    use_partitioned_tables = true
  }
}

# Grant the sink SA write access to the logs dataset
resource "google_bigquery_dataset_iam_member" "sink_writer" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.logs.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_logging_project_sink.bq_audit_sink.writer_identity
}

# Log sink → Cloud Storage for long-term archival
resource "google_logging_project_sink" "gcs_archive_sink" {
  project                = var.project_id
  name                   = "kb-logs-archive-${var.environment}"
  destination            = "storage.googleapis.com/kb-logs-archive-placeholder"
  filter                 = "resource.type = \"cloud_run_revision\" AND severity >= ERROR"
  unique_writer_identity = true
}

##############################################################################
# Log-based Metric: track document ingestion count
##############################################################################

resource "google_logging_metric" "documents_ingested" {
  project     = var.project_id
  name        = "kb_documents_ingested"
  description = "Count of successfully ingested documents"
  filter      = "resource.type = \"cloud_run_revision\" AND jsonPayload.event = \"DOCUMENT_INGESTED\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    display_name = "Documents Ingested"
  }
}

resource "google_logging_metric" "responses_submitted" {
  project     = var.project_id
  name        = "kb_responses_submitted"
  description = "Count of questionnaire responses submitted"
  filter      = "resource.type = \"cloud_run_revision\" AND jsonPayload.event = \"RESPONSE_SUBMITTED\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    display_name = "Responses Submitted"
  }
}

##############################################################################
# Outputs
##############################################################################

output "dashboard_url" {
  value = "https://console.cloud.google.com/monitoring/dashboards/custom/${google_monitoring_dashboard.main.id}?project=${var.project_id}"
}
output "notification_channel_id" { value = google_monitoring_notification_channel.email.name }
output "logs_dataset_id"         { value = google_bigquery_dataset.logs.dataset_id }
