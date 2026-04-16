"""Unity Catalog volume uploads/downloads (same paths as claim documents)."""
import logging
import uuid
from typing import Optional

from config import DATABRICKS_HOST, VOLUME_PATH
from databricks_auth import get_auth_token


def safe_volume_filename(file_name: str) -> str:
    return file_name.replace("/", "_").replace("\\", "_")


def _put_bytes_to_volume(volume_file_path: str, content: bytes) -> None:
    import httpx as _httpx

    api_path = f"/api/2.0/fs/files{volume_file_path}"
    token = get_auth_token()
    resp = _httpx.put(
        f"{DATABRICKS_HOST}{api_path}",
        headers={"Authorization": f"Bearer {token}"},
        content=content,
        timeout=60,
    )
    resp.raise_for_status()


def upload_to_volume(content: bytes, claim_id: int, file_name: str) -> str:
    """Persist under claim_<id>/ (same layout as document uploads)."""
    safe_name = safe_volume_filename(file_name)
    volume_file_path = f"{VOLUME_PATH}/claim_{claim_id}/{safe_name}"
    _put_bytes_to_volume(volume_file_path, content)
    return volume_file_path


def upload_to_volume_new_claim_staging(content: bytes, file_name: str) -> str:
    """Stage new-claim preview images until the claim row exists."""
    safe_name = safe_volume_filename(file_name)
    staging_id = str(uuid.uuid4())
    volume_file_path = f"{VOLUME_PATH}/new_claim_preview/{staging_id}/{safe_name}"
    _put_bytes_to_volume(volume_file_path, content)
    return volume_file_path


def try_stage_new_claim_image(content: bytes, file_name: str) -> Optional[str]:
    """Save to staging; return path or None if volume write fails (AI can still run)."""
    try:
        return upload_to_volume_new_claim_staging(content, file_name)
    except Exception as e:
        logging.warning("Staging new-claim damage image to volume failed (continuing with AI only): %s", e)
        return None


def is_valid_preview_staging_path(path: str) -> bool:
    prefix = f"{VOLUME_PATH}/new_claim_preview/"
    return isinstance(path, str) and path.startswith(prefix) and ".." not in path


def download_from_volume(volume_path: str) -> tuple[bytes, str]:
    import httpx as _httpx

    api_path = f"/api/2.0/fs/files{volume_path}"
    token = get_auth_token()
    resp = _httpx.get(
        f"{DATABRICKS_HOST}{api_path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "application/octet-stream")
    return resp.content, content_type
