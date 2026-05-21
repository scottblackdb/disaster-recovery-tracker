"""Shared environment-backed settings."""
import os

LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "databricks-llama-4-maverick")
REFINE_LLM_ENDPOINT = os.getenv("REFINE_LLM_ENDPOINT", "databricks-gpt-oss-120b")

# SQL warehouse ID for Statement Execution — read only from the WAREHOUSE_ID environment variable.
WAREHOUSE_ID = (os.getenv("WAREHOUSE_ID") or "").strip()
VOLUME_PATH = os.getenv("VOLUME_PATH", "/Volumes/fema/default/filestore")

# Lakebase connection — env vars are auto-injected by Databricks Apps when a
# postgres resource is declared in app.yaml.
ENDPOINT_NAME = os.getenv(
    "ENDPOINT_NAME",
    "projects/disaster-recovery-tracker/branches/production/endpoints/primary",
)
# Used when ENDPOINT_NAME (or the app.yaml postgres resource) is not present in the workspace.
LAKEBASE_ENDPOINT_FALLBACK = (
    "projects/disaster-recovery/branches/production/endpoints/primary"
)
PGUSER = os.getenv("PGUSER", "")
PGHOST = os.getenv("PGHOST", "")
PGPORT = os.getenv("PGPORT", "5432")
PGDATABASE = os.getenv("PGDATABASE", "databricks_postgres")
PGSSLMODE = os.getenv("PGSSLMODE", "require")

# Same cap for preview and any shared upload path
MAX_IMAGE_UPLOAD_BYTES = 15 * 1024 * 1024
