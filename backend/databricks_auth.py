"""Databricks CLI JSON helpers and OAuth token for Files API / Lakebase.

Falls back to environment variables when the CLI is not installed or not authenticated.
"""
import json
import logging
import shutil
import subprocess

from config import DATABRICKS_PROFILE, DATABRICKS_TOKEN

_logger = logging.getLogger(__name__)

_cli_available: bool | None = None


def _is_cli_available() -> bool:
    global _cli_available
    if _cli_available is None:
        _cli_available = shutil.which("databricks") is not None
    return _cli_available


def cli_json(args: list[str]) -> dict:
    """Run a `databricks` CLI command and return parsed JSON output.

    Raises RuntimeError if the CLI is not available or the command fails.
    """
    if not _is_cli_available():
        raise RuntimeError("Databricks CLI is not installed")
    result = subprocess.run(
        ["databricks"] + args + ["--profile", DATABRICKS_PROFILE, "--output", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"CLI error: {result.stderr}")
    return json.loads(result.stdout)


def get_auth_token() -> str:
    """Return a Databricks OAuth/PAT token, preferring the CLI when available."""
    if _is_cli_available():
        try:
            token_info = cli_json(["auth", "token"])
            return token_info.get("access_token") or token_info.get("token_value")
        except RuntimeError:
            _logger.warning("CLI auth failed, falling back to DATABRICKS_TOKEN env var")

    if DATABRICKS_TOKEN:
        return DATABRICKS_TOKEN

    raise RuntimeError(
        "No Databricks credentials available. Either install/authenticate the Databricks CLI "
        "or set the DATABRICKS_TOKEN environment variable."
    )
