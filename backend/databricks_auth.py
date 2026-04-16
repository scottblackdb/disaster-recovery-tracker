"""Databricks authentication via the SDK WorkspaceClient.

WorkspaceClient auto-detects credentials from the environment:
- On Databricks Apps: uses DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET (service principal)
- Locally: uses ~/.databrickscfg profile or DATABRICKS_TOKEN env var
"""
import logging

from databricks.sdk import WorkspaceClient

_logger = logging.getLogger(__name__)

# Single shared client — Config() auto-detects auth method from env.
w = WorkspaceClient()


def get_auth_token() -> str:
    """Return a fresh Databricks OAuth token via the SDK."""
    headers = w.config.authenticate()
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    raise RuntimeError("Could not obtain Databricks auth token from WorkspaceClient")
