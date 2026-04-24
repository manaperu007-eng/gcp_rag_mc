-- ==============================================================================
-- backend/bigquery/schema.sql
-- Full DDL for the KB Questionnaire Platform
-- Run once per environment: replace ${PROJECT_ID} and ${DATASET} with real values
-- ==============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- Dataset
-- ─────────────────────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS `${PROJECT_ID}.${DATASET}`
  OPTIONS (
    location         = "US",
    description      = "KB Questionnaire Platform — main dataset"
  );


-- ─────────────────────────────────────────────────────────────────────────────
-- 1. users
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.users` (
  user_id        STRING  NOT NULL,
  email          STRING  NOT NULL,
  display_name   STRING,
  role           STRING  NOT NULL,   -- admin | reviewer | respondent
  region         STRING,
  country        STRING,
  city           STRING,
  department     STRING,
  password_hash  STRING,             -- NULL for SSO-only accounts
  is_active      BOOL    NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMP NOT NULL,
  last_login_at  TIMESTAMP
)
CLUSTER BY role, region
OPTIONS (description = "Platform users with RBAC and geographic attributes");


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. knowledge_bases
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.knowledge_bases` (
  kb_id          STRING    NOT NULL,
  name           STRING    NOT NULL,
  description    STRING,
  document_count INT64     NOT NULL DEFAULT 0,
  created_by     STRING,
  created_at     TIMESTAMP NOT NULL,
  updated_at     TIMESTAMP,
  is_active      BOOL      NOT NULL DEFAULT TRUE
)
OPTIONS (description = "Named knowledge base collections that group documents");


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. documents
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.documents` (
  document_id    STRING    NOT NULL,
  file_name      STRING    NOT NULL,
  file_type      STRING    NOT NULL,   -- pdf | docx | doc | xlsx | xls
  gcs_uri        STRING    NOT NULL,
  processed_uri  STRING,
  title          STRING,
  author         STRING,
  language       STRING,
  category       STRING,
  tags           ARRAY<STRING>,
  kb_ids         ARRAY<STRING>,
  status         STRING    NOT NULL DEFAULT 'pending',
    -- pending | processing | ready | failed | deleted
  error_message  STRING,
  page_count     INT64,
  word_count     INT64,
  chunk_count    INT64,
  uploaded_by    STRING,
  ingested_at    TIMESTAMP NOT NULL,
  processed_at   TIMESTAMP
)
PARTITION BY DATE(ingested_at)
CLUSTER BY status, file_type
OPTIONS (
  partition_expiration_days = NULL,
  description = "Document registry — one row per uploaded file"
);


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. document_chunks
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.document_chunks` (
  chunk_id       STRING    NOT NULL,
  document_id    STRING    NOT NULL,
  chunk_index    INT64     NOT NULL,
  content        STRING    NOT NULL,
  page_number    INT64,
  section_title  STRING,
  token_count    INT64,
  embedding_id   STRING,             -- matches datapoint_id in Vertex Vector Search
  created_at     TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY document_id
OPTIONS (description = "Text chunks derived from documents for RAG retrieval");


-- ─────────────────────────────────────────────────────────────────────────────
-- 5. questionnaires
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.questionnaires` (
  questionnaire_id  STRING    NOT NULL,
  title             STRING    NOT NULL,
  description       STRING,
  kb_id             STRING,
  passing_score     FLOAT64,
  time_limit_mins   INT64,
  due_date          TIMESTAMP,
  geographic_scope  STRING,           -- global | region | country | city
  allowed_regions   ARRAY<STRING>,
  status            STRING    NOT NULL DEFAULT 'draft',
    -- draft | published | archived
  version           INT64     NOT NULL DEFAULT 1,
  total_questions   INT64,
  created_by        STRING,
  created_at        TIMESTAMP NOT NULL,
  published_at      TIMESTAMP,
  updated_at        TIMESTAMP
)
PARTITION BY DATE(created_at)
CLUSTER BY status
OPTIONS (description = "Questionnaire definitions");


-- ─────────────────────────────────────────────────────────────────────────────
-- 6. questions
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.questions` (
  question_id         STRING    NOT NULL,
  questionnaire_id    STRING    NOT NULL,
  question_text       STRING    NOT NULL,
  question_type       STRING    NOT NULL,
    -- free_text | file_upload | true_false | rating |
    -- multiple_choice | multi_select | date | number
  is_required         BOOL      NOT NULL DEFAULT TRUE,
  order_index         INT64     NOT NULL,
  section             STRING,
  help_text           STRING,
  options             STRUCT<
    choices             ARRAY<STRING>,
    min_rating          INT64,
    max_rating          INT64,
    rating_labels       ARRAY<STRING>,
    allowed_file_types  ARRAY<STRING>,
    max_file_size_mb    INT64
  >,
  parent_question_id  STRING,        -- for conditional/branching logic
  kb_context          STRING,
  ai_generated        BOOL      NOT NULL DEFAULT FALSE,
  source_chunk_ids    ARRAY<STRING>,
  created_at          TIMESTAMP NOT NULL,
  updated_at          TIMESTAMP
)
CLUSTER BY questionnaire_id
OPTIONS (description = "Individual questions belonging to a questionnaire");


-- ─────────────────────────────────────────────────────────────────────────────
-- 7. user_assignments
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.user_assignments` (
  assignment_id     STRING    NOT NULL,
  questionnaire_id  STRING    NOT NULL,
  user_id           STRING    NOT NULL,
  user_email        STRING,
  user_name         STRING,
  region            STRING,
  country           STRING,
  city              STRING,
  department        STRING,
  status            STRING    NOT NULL DEFAULT 'not_started',
    -- not_started | in_progress | submitted | reviewed
  completion_pct    FLOAT64   NOT NULL DEFAULT 0.0,
  score             FLOAT64,
  assigned_at       TIMESTAMP NOT NULL,
  started_at        TIMESTAMP,
  submitted_at      TIMESTAMP,
  due_date          TIMESTAMP
)
PARTITION BY DATE(assigned_at)
CLUSTER BY questionnaire_id, status, region
OPTIONS (description = "Which users are assigned which questionnaires and their progress");


-- ─────────────────────────────────────────────────────────────────────────────
-- 8. responses
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.responses` (
  response_id      STRING    NOT NULL,
  assignment_id    STRING    NOT NULL,
  questionnaire_id STRING    NOT NULL,
  question_id      STRING    NOT NULL,
  user_id          STRING    NOT NULL,
  question_type    STRING    NOT NULL,
  answer_text      STRING,
  answer_boolean   BOOL,
  answer_number    FLOAT64,
  answer_choices   ARRAY<STRING>,
  answer_date      DATE,
  file_uploads     ARRAY<STRUCT<
    file_id          STRING,
    file_name        STRING,
    gcs_uri          STRING,
    file_size_bytes  INT64,
    content_type     STRING
  >>,
  ai_hint_used     BOOL      NOT NULL DEFAULT FALSE,
  channel          STRING    NOT NULL DEFAULT 'web',   -- web | chat
  responded_at     TIMESTAMP NOT NULL,
  updated_at       TIMESTAMP,
  is_draft         BOOL      NOT NULL DEFAULT FALSE
)
PARTITION BY DATE(responded_at)
CLUSTER BY assignment_id, question_id
OPTIONS (description = "Individual question answers — supports all question types");


-- ─────────────────────────────────────────────────────────────────────────────
-- 9. audit_logs
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.audit_logs` (
  log_id         STRING    NOT NULL,
  timestamp      TIMESTAMP NOT NULL,
  action         STRING    NOT NULL,
  user_id        STRING,
  user_email     STRING,
  resource_type  STRING,
  resource_id    STRING,
  details        STRING    -- JSON blob
)
PARTITION BY DATE(timestamp)
CLUSTER BY action, user_id
OPTIONS (
  partition_expiration_days = 1095,  -- 3-year retention
  description = "Immutable audit trail for all platform events"
);


-- =============================================================================
-- VIEWS
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- vw_questionnaire_completion
-- Used by: admin /reports/completion
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW `${PROJECT_ID}.${DATASET}.vw_questionnaire_completion` AS
SELECT
  q.title                   AS questionnaire_title,
  q.status                  AS questionnaire_status,
  ua.region,
  ua.country,
  ua.city,
  ua.department,
  COUNT(*)                                                          AS total_assigned,
  COUNTIF(ua.status = 'submitted')                                  AS total_submitted,
  COUNTIF(ua.status = 'not_started')                               AS total_not_started,
  COUNTIF(ua.status = 'in_progress')                               AS total_in_progress,
  ROUND(
    SAFE_DIVIDE(COUNTIF(ua.status = 'submitted'), COUNT(*)) * 100, 2
  )                                                                 AS completion_rate_pct,
  ROUND(AVG(ua.completion_pct), 2)                                 AS avg_completion_pct,
  ROUND(AVG(ua.score), 2)                                          AS avg_score,
  MIN(ua.assigned_at)                                              AS first_assigned,
  MAX(ua.submitted_at)                                             AS last_submitted
FROM `${PROJECT_ID}.${DATASET}.user_assignments` ua
JOIN `${PROJECT_ID}.${DATASET}.questionnaires`   q
  ON ua.questionnaire_id = q.questionnaire_id
GROUP BY
  q.title, q.status, ua.region, ua.country, ua.city, ua.department;


-- ─────────────────────────────────────────────────────────────────────────────
-- vw_overdue_assignments
-- Used by: admin /reports/overdue  +  dashboard stats
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW `${PROJECT_ID}.${DATASET}.vw_overdue_assignments` AS
SELECT
  ua.assignment_id,
  ua.user_id,
  ua.user_email,
  ua.user_name,
  ua.region,
  ua.country,
  ua.department,
  q.title                                  AS questionnaire_title,
  ua.due_date,
  ua.status,
  ua.completion_pct,
  DATE_DIFF(CURRENT_DATE(), DATE(ua.due_date), DAY) AS days_overdue
FROM `${PROJECT_ID}.${DATASET}.user_assignments` ua
JOIN `${PROJECT_ID}.${DATASET}.questionnaires`   q
  ON ua.questionnaire_id = q.questionnaire_id
WHERE
  ua.due_date < CURRENT_TIMESTAMP()
  AND ua.status NOT IN ('submitted', 'reviewed');


-- ─────────────────────────────────────────────────────────────────────────────
-- vw_response_summary
-- Used by: admin /reports/response-summary/{questionnaire_id}
-- Per-question answer statistics
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW `${PROJECT_ID}.${DATASET}.vw_response_summary` AS
SELECT
  r.questionnaire_id,
  r.question_id,
  q.question_text,
  q.question_type,
  q.section,
  COUNT(DISTINCT r.assignment_id)                AS total_responses,
  COUNTIF(r.is_draft = FALSE)                    AS final_responses,
  COUNTIF(r.ai_hint_used = TRUE)                 AS ai_hint_count,
  COUNTIF(r.channel = 'chat')                    AS chat_channel_count,
  COUNTIF(r.channel = 'web')                     AS web_channel_count,
  -- Free text / numeric
  AVG(r.answer_number)                           AS avg_number_answer,
  MIN(r.answer_number)                           AS min_number_answer,
  MAX(r.answer_number)                           AS max_number_answer,
  -- True/False breakdown
  COUNTIF(r.answer_boolean = TRUE)               AS true_count,
  COUNTIF(r.answer_boolean = FALSE)              AS false_count
FROM `${PROJECT_ID}.${DATASET}.responses` r
JOIN `${PROJECT_ID}.${DATASET}.questions` q
  ON r.question_id = q.question_id
WHERE r.is_draft = FALSE
GROUP BY
  r.questionnaire_id, r.question_id,
  q.question_text, q.question_type, q.section;
