"""Shared environment-backed settings."""
import os

LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "databricks-llama-4-maverick")
REFINE_LLM_ENDPOINT = os.getenv("REFINE_LLM_ENDPOINT", "databricks-gpt-oss-120b")
VOLUME_PATH = os.getenv("VOLUME_PATH", "/Volumes/fema/default/filestore")

# Lakebase connection — env vars are auto-injected by Databricks Apps when a
# postgres resource is declared in app.yaml.
ENDPOINT_NAME = os.getenv(
    "ENDPOINT_NAME",
    "projects/disaster-recovery/branches/production/endpoints/primary",
)
PGUSER = os.getenv("PGUSER", "")
PGHOST = os.getenv("PGHOST", "")
PGPORT = os.getenv("PGPORT", "5432")
PGDATABASE = os.getenv("PGDATABASE", "disaster_recovery_db")
PGSSLMODE = os.getenv("PGSSLMODE", "require")

# Same cap for preview and any shared upload path
MAX_IMAGE_UPLOAD_BYTES = 15 * 1024 * 1024
