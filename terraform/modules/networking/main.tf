##############################################################################
# modules/networking/main.tf
# VPC, Subnet, Serverless VPC Access Connector
##############################################################################

variable "project_id" { type = string }
variable "region"     { type = string }
variable "suffix"     { type = string }

##############################################################################
# VPC Network
##############################################################################

resource "google_compute_network" "main" {
  project                 = var.project_id
  name                    = "kb-vpc-${var.suffix}"
  auto_create_subnetworks = false
  description             = "KB Questionnaire platform VPC"
}

##############################################################################
# Subnets
##############################################################################

resource "google_compute_subnetwork" "app" {
  project                  = var.project_id
  name                     = "kb-app-subnet"
  ip_cidr_range            = "10.10.0.0/24"
  region                   = var.region
  network                  = google_compute_network.main.id
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_subnetwork" "connector" {
  project                  = var.project_id
  name                     = "kb-connector-subnet"
  ip_cidr_range            = "10.10.1.0/28"
  region                   = var.region
  network                  = google_compute_network.main.id
  private_ip_google_access = true
}

##############################################################################
# Cloud NAT (for outbound internet from private resources)
##############################################################################

resource "google_compute_router" "main" {
  project = var.project_id
  name    = "kb-router-${var.suffix}"
  region  = var.region
  network = google_compute_network.main.id
}

resource "google_compute_router_nat" "main" {
  project                            = var.project_id
  name                               = "kb-nat-${var.suffix}"
  router                             = google_compute_router.main.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

##############################################################################
# Serverless VPC Access Connector (Cloud Run → VPC)
##############################################################################

resource "google_vpc_access_connector" "main" {
  project       = var.project_id
  name          = "kb-connector-${var.suffix}"
  region        = var.region
  ip_cidr_range = "10.10.2.0/28"
  network       = google_compute_network.main.name
  min_instances = 2
  max_instances = 10
  machine_type  = "e2-micro"
}

##############################################################################
# Firewall Rules
##############################################################################

# Allow internal traffic within VPC
resource "google_compute_firewall" "allow_internal" {
  project = var.project_id
  name    = "kb-allow-internal"
  network = google_compute_network.main.name

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "icmp"
  }

  source_ranges = ["10.10.0.0/16"]
  description   = "Allow internal VPC traffic"
}

# Allow health checks from Google LB ranges
resource "google_compute_firewall" "allow_health_checks" {
  project = var.project_id
  name    = "kb-allow-health-checks"
  network = google_compute_network.main.name

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "8080"]
  }

  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"]
  description   = "Allow GCP health checks"
}

##############################################################################
# Private Service Connection (for managed services like SQL if needed later)
##############################################################################

resource "google_compute_global_address" "private_ip_range" {
  project       = var.project_id
  name          = "kb-private-ip-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.main.id
}

##############################################################################
# Outputs
##############################################################################

output "vpc_id"            { value = google_compute_network.main.id }
output "vpc_name"          { value = google_compute_network.main.name }
output "app_subnet_id"     { value = google_compute_subnetwork.app.id }
output "vpc_connector_id"  { value = google_vpc_access_connector.main.id }
output "vpc_connector_name"{ value = google_vpc_access_connector.main.name }
