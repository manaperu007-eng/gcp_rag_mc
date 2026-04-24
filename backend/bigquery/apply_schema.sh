#!/usr/bin/env bash
# ==============================================================================
# backend/bigquery/apply_schema.sh
# Apply (or update) the BigQuery schema for the KB Platform.
# Usage:
#   ./apply_schema.sh <PROJECT_ID> <DATASET> [LOCATION]
# Example:
#   ./apply_schema.sh my-gcp-project kb_platform_dev US
# ==============================================================================

set -euo pipefail

PROJECT_ID="${1:?Usage: $0 <PROJECT_ID> <DATASET> [LOCATION]}"
DATASET="${2:?Usage: $0 <PROJECT_ID> <DATASET> [LOCATION]}"
LOCATION="${3:-US}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_FILE="${SCRIPT_DIR}/schema.sql"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  KB Platform — BigQuery Schema Apply"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Project  : ${PROJECT_ID}"
echo "  Dataset  : ${DATASET}"
echo "  Location : ${LOCATION}"
echo "  Schema   : ${SCHEMA_FILE}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Substitute placeholders
RESOLVED_SQL=$(sed \
  -e "s/\${PROJECT_ID}/${PROJECT_ID}/g" \
  -e "s/\${DATASET}/${DATASET}/g" \
  "${SCHEMA_FILE}")

echo ""
echo "▶ Applying schema..."

echo "${RESOLVED_SQL}" | bq query \
  --use_legacy_sql=false \
  --project_id="${PROJECT_ID}" \
  --location="${LOCATION}"

echo ""
echo "✅ Schema applied successfully."
echo ""

# List created tables
echo "Tables in ${PROJECT_ID}.${DATASET}:"
bq ls --format=pretty "${PROJECT_ID}:${DATASET}"
