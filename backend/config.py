"""Shared environment-backed settings."""
import os

DATABRICKS_PROFILE = os.getenv("DATABRICKS_PROFILE", "DEFAULT")
DATABRICKS_HOST = os.getenv("DATABRICKS_HOST", "https://adb-3011697725699826.6.azuredatabricks.net")
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "databricks-llama-4-maverick")
REFINE_LLM_ENDPOINT = os.getenv("REFINE_LLM_ENDPOINT", "databricks-gpt-oss-120b")
VOLUME_PATH = os.getenv("VOLUME_PATH", "/Volumes/fema/default/filestore")

DATABASE_NAME = "disaster_recovery_db"
PROJECT_ID = "disaster-recovery"
BRANCH_ID = "production"
ENDPOINT_ID = "primary"

# Env-var fallbacks when Databricks CLI is not available
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN")
LAKEBASE_HOST = os.getenv("PGHOST")
LAKEBASE_USER = os.getenv("PGUSER")
LAKEBASE_PASSWORD = os.getenv("PGPASSWORD")

# Same cap for preview and any shared upload path
MAX_IMAGE_UPLOAD_BYTES = 15 * 1024 * 1024
