# KB Questionnaire Platform — GCP Infrastructure

> **Terraform-managed GCP infrastructure** for a knowledge-base-powered questionnaire platform with AI-assisted document ingestion, multi-format question types, web + chat interfaces, and geographic admin reporting.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [GCP Services Used](#gcp-services-used)
3. [Module Structure](#module-structure)
4. [Data Flow](#data-flow)
5. [BigQuery Schema](#bigquery-schema)
6. [Question Types Supported](#question-types-supported)
7. [Prerequisites](#prerequisites)
8. [Deployment](#deployment)
9. [Secrets Setup](#secrets-setup)
10. [Post-Deploy Steps](#post-deploy-steps)
11. [CI/CD](#cicd)
12. [Cost Estimate](#cost-estimate)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          GCP Project                                     │
│                                                                           │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────────────────────┐ │
│  │  Web Frontend│    │  Chat UI     │    │     Admin Dashboard          │ │
│  │  (React SPA) │    │  (Gemini)    │    │     (Reports & Filters)      │ │
│  │  Cloud Run   │    │  Cloud Run   │    │     Cloud Run                │ │
│  └──────┬───────┘    └──────┬───────┘    └──────────────┬───────────────┘ │
│         │                  │                            │                 │
│         └──────────────────┼────────────────────────────┘                 │
│                            │                                              │
│                    ┌───────▼────────┐                                     │
│                    │   API Backend  │                                     │
│                    │   (FastAPI)    │                                     │
│                    │   Cloud Run    │                                     │
│                    └───────┬────────┘                                     │
│                            │                                              │
│          ┌─────────────────┼──────────────────┐                           │
│          │                 │                  │                           │
│   ┌──────▼──────┐  ┌───────▼──────┐  ┌───────▼──────┐                   │
│   │  BigQuery   │  │  Firestore   │  │  Vertex AI   │                   │
│   │  (Analytics │  │  (Sessions / │  │  (Gemini +   │                   │
│   │   + Reports)│  │   Progress)  │  │  Vector Search│                  │
│   └─────────────┘  └──────────────┘  └──────┬───────┘                   │
│                                              │                           │
│  ┌───────────────────────────────────────────┘                           │
│  │         Document Ingestion Pipeline                                    │
│  │                                                                        │
│  │  GCS (raw docs) → Pub/Sub → Cloud Run Ingestion Worker               │
│  │       → Document AI (parse PDF/DOCX/XLSX)                            │
│  │       → Gemini (chunk + enrich)                                       │
│  │       → Vertex AI Embeddings → Vector Search Index                   │
│  │       → GCS (processed) + BigQuery (metadata)                        │
│  └───────────────────────────────────────────                            │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │  Supporting: Secret Manager │ Cloud Monitoring │ Artifact Registry   │ │
│  │              VPC + NAT      │ Cloud Scheduler  │ Cloud Functions     │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## GCP Services Used

| Service | Purpose |
|---|---|
| **Cloud Run (v2)** | API backend, web frontend, chat service, ingestion worker, admin dashboard |
| **Cloud Run Jobs** | Nightly batch report generation |
| **Vertex AI — Gemini** | Document Q&A, question generation from KB, chat interface |
| **Vertex AI — Vector Search** | Semantic search over document embeddings |
| **Vertex AI — RAG Engine** | Managed retrieval-augmented generation pipeline |
| **Document AI** | Structured parsing of PDF, DOCX, XLSX documents |
| **Cloud Storage** | Raw documents, processed chunks, evidence uploads, reports |
| **BigQuery** | Questionnaire analytics, response storage, admin reports |
| **Firestore** | Chat session state, real-time user progress cache |
| **Pub/Sub** | Event-driven ingestion, questionnaire events, notifications |
| **Cloud Functions (Gen 2)** | Document classifier, notification sender, completion tracker, signed URLs |
| **Secret Manager** | JWT secrets, API keys, encryption keys |
| **VPC + Serverless Connector** | Private networking for Cloud Run → GCP services |
| **Cloud NAT** | Outbound internet access for private resources |
| **Artifact Registry** | Docker images for all Cloud Run services |
| **Cloud Scheduler** | Nightly index refresh, report generation triggers |
| **Cloud Monitoring** | Dashboards, uptime checks, alert policies |
| **Cloud Logging** | Log sinks to BigQuery and GCS for audit trail |
| **IAM** | Least-privilege service accounts per component |

---

## Module Structure

```
terraform/
├── main.tf                          # Root: providers, module wiring
├── variables.tf                     # Global input variables
├── outputs.tf                       # Root outputs
├── terraform.tfvars.example         # Template — copy to terraform.tfvars
├── .gitignore
│
├── environments/
│   ├── dev/terraform.tfvars
│   ├── staging/terraform.tfvars
│   └── prod/terraform.tfvars
│
└── modules/
    ├── project_services/            # Enables all required GCP APIs
    ├── iam/                         # Service accounts + Artifact Registry
    ├── networking/                  # VPC, subnets, NAT, VPC connector
    ├── storage/                     # 6 GCS buckets (docs, processed, evidence…)
    ├── bigquery/                    # Dataset, 7 tables, 3 views, scheduled query
    ├── vertex_ai/                   # Vector Search, RAG corpus, Document AI
    ├── pubsub/                      # 5 topics + subscriptions + Avro schema
    ├── cloud_run/                   # 5 services + 1 job + schedulers
    ├── cloud_functions/             # 4 Gen 2 functions (event-driven)
    ├── firestore/                   # Native DB + indexes + backup
    ├── secret_manager/              # 8 secrets + IAM
    └── monitoring/                  # Alerts, dashboard, log sinks, metrics
```

---

## Data Flow

### Document Ingestion Flow
```
1. Admin uploads PDF/DOCX/XLSX → GCS (documents bucket)
2. GCS triggers Cloud Function (doc_classifier)
3. Classifier publishes message → Pub/Sub (kb-doc-ingestion topic)
4. Pub/Sub push → Ingestion Worker (Cloud Run)
5. Ingestion Worker:
   a. Calls Document AI → extracts structured text
   b. Calls Gemini → chunks text, generates metadata
   c. Calls text-embedding-004 → generates embeddings
   d. Upserts embeddings → Vertex AI Vector Search
   e. Saves chunks + metadata → GCS (processed bucket)
   f. Writes document record → BigQuery (documents table)
   g. Publishes completion event → Pub/Sub (questionnaire-events)
```

### Questionnaire Answer Flow (Web)
```
1. User logs in → Firebase Auth → JWT issued by API
2. API queries BigQuery → returns ONLY unanswered questions for this user
3. User answers question:
   - Free text / True-False / Rating / Multiple choice → POST to API
   - File upload → API calls Cloud Function for signed GCS URL → upload direct
4. API writes response → BigQuery (responses table)
5. API publishes event → Pub/Sub (questionnaire-events)
6. Cloud Function (completion_tracker) → updates completion_pct in BigQuery
7. Firestore updated with answered question IDs (for chat deduplication)
```

### Chat Interface Flow
```
1. User opens chat → Chat Service (Cloud Run) creates Firestore session
2. Chat service queries:
   a. Firestore: already-answered question IDs for this user+questionnaire
   b. BigQuery: next unanswered question
3. Chat presents question in natural language
4. User answers via chat → Chat service:
   a. Validates answer format against question type
   b. Calls Gemini for free-text answer interpretation if needed
   c. Writes response → API (same path as web)
5. Chat moves to next unanswered question automatically
6. On completion → notification published → Cloud Function sends email
```

### Admin Reporting Flow
```
1. Admin logs into Admin Dashboard (Cloud Run)
2. Dashboard queries BigQuery views:
   - vw_questionnaire_completion: completion rates by region/country/city
   - vw_response_summary: per-question statistics
   - vw_overdue_assignments: users with past-due questionnaires
3. Admin applies geographic filters (region, country, city, department)
4. Admin exports report → Cloud Run Job generates CSV/PDF → GCS (reports)
5. Cloud Scheduler triggers nightly report job at 03:00 UTC
```

---

## BigQuery Schema

| Table | Description |
|---|---|
| `documents` | Ingested source files with processing status |
| `document_chunks` | Text chunks linked to Vector Search embedding IDs |
| `knowledge_bases` | Named KB groups of related documents |
| `questionnaires` | Questionnaire definitions (title, status, geographic scope) |
| `questions` | Individual questions with type config and KB context |
| `user_assignments` | User → questionnaire assignments with completion tracking |
| `responses` | All question answers (text, boolean, number, choices, files) |
| `users` | User profiles with region/country/city/department |
| `audit_logs` | Full audit trail, partitioned by day |
| `vw_questionnaire_completion` | **VIEW**: completion rates by geo + department |
| `vw_response_summary` | **VIEW**: per-question answer statistics |
| `vw_overdue_assignments` | **VIEW**: overdue users sorted by days past due |

---

## Question Types Supported

| Type | `question_type` value | Answer field in BigQuery |
|---|---|---|
| Free text (short/long) | `free_text` | `answer_text` |
| File upload / evidence | `file_upload` | `file_uploads[]` (GCS URIs) |
| True / False | `true_false` | `answer_boolean` |
| Star / numeric rating | `rating` | `answer_number` |
| Single choice | `multiple_choice` | `answer_choices[0]` |
| Multi-select | `multi_select` | `answer_choices[]` |
| Date | `date` | `answer_date` |
| Numeric input | `number` | `answer_number` |

---

## Prerequisites

- **Terraform** ≥ 1.5
- **Google Cloud SDK** (`gcloud`) authenticated
- GCP project with **billing enabled**
- Owner or Editor role on the project (for initial apply)
- (Optional) Workload Identity Federation configured for CI/CD

---

## Deployment

### 1. Clone and configure

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your project_id, region, notification_email, etc.
```

### 2. Authenticate

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

### 3. Initialize

```bash
terraform init
```

### 4. Plan

```bash
terraform plan -var-file="environments/dev/terraform.tfvars"
```

### 5. Apply

```bash
terraform apply -var-file="environments/dev/terraform.tfvars"
```

---

## Secrets Setup

After `terraform apply`, populate the placeholder secrets:

```bash
# JWT secret (min 32 chars)
echo -n "$(openssl rand -base64 48)" | \
  gcloud secrets versions add kb-jwt-secret --data-file=-

# Admin JWT secret
echo -n "$(openssl rand -base64 48)" | \
  gcloud secrets versions add kb-admin-jwt-secret --data-file=-

# Encryption key (32 bytes hex for AES-256)
echo -n "$(openssl rand -hex 32)" | \
  gcloud secrets versions add kb-encryption-key --data-file=-

# SendGrid API key
echo -n "SG.YOUR_SENDGRID_KEY" | \
  gcloud secrets versions add kb-sendgrid-api-key --data-file=-

# Firebase web config (JSON string)
echo -n '{"apiKey":"...","authDomain":"...","projectId":"..."}' | \
  gcloud secrets versions add kb-firebase-config --data-file=-
```

---

## Post-Deploy Steps

1. **Push container images** to Artifact Registry for each Cloud Run service:
   - `kb-api`, `kb-web`, `kb-ingestion`, `kb-admin`, `kb-chat`, `kb-report-gen`

2. **Update Pub/Sub push endpoint** in the `kb-doc-ingestion` subscription to point to the actual ingestion Cloud Run URL.

3. **Deploy the Vertex AI Vector Search index** — initial index build requires uploading embeddings JSON to `gs://YOUR_PROJECT-kb-processed-SUFFIX/embeddings/`.

4. **Configure Firebase Authentication** in the GCP console for user sign-in methods.

5. **Seed BigQuery tables** with initial admin user records via the API.

6. **Upload function source zips** to the functions GCS bucket:
   - `functions/doc_classifier.zip`
   - `functions/notification_sender.zip`
   - `functions/completion_tracker.zip`
   - `functions/signed_url_gen.zip`

---

## CI/CD

The `.github/workflows/terraform.yml` pipeline:

| Event | Environment | Action |
|---|---|---|
| PR to `main` or `staging` | Detected from branch | Plan only + PR comment |
| Push to `staging` | staging | Plan + Apply |
| Push to `main` | prod | Plan + Apply |
| Manual dispatch | User-selected | Plan + Apply |

Uses **Workload Identity Federation** — no long-lived service account keys needed.

Set these GitHub repository secrets:

| Secret | Description |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider resource name |
| `GCP_TERRAFORM_SA` | Terraform service account email |
| `TF_STATE_BUCKET` | GCS bucket for Terraform state |
| `GCP_PROJECT_ID_DEV` | Dev project ID |
| `GCP_PROJECT_ID_STAGING` | Staging project ID |
| `GCP_PROJECT_ID_PROD` | Prod project ID |

---

## Cost Estimate (Dev environment, low traffic)

| Service | Estimated monthly cost |
|---|---|
| Cloud Run (scale-to-zero) | ~$5–20 |
| Vertex AI Vector Search | ~$50–100 |
| Vertex AI Gemini API | ~$10–50 (usage-based) |
| Document AI | ~$5–15 (per 1K pages) |
| BigQuery | ~$5–10 (storage + queries) |
| Cloud Storage | ~$1–5 |
| Pub/Sub | ~$1–5 |
| Firestore | ~$1–5 |
| Cloud Functions | ~$1–5 |
| Monitoring | Free tier |
| **Total (dev estimate)** | **~$80–215/month** |

> Production costs scale with Gemini API usage, document volume, and user load.
