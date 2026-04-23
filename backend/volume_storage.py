"""Unity Catalog volume uploads/downloads (same paths as claim documents)."""
import logging
import time
import uuid
from typing import Optional, Tuple

from config import VOLUME_PATH
from databricks_auth import get_auth_token, w

_logger = logging.getLogger(__name__)


def ensure_uc_volume_directory(directory_path: str) -> None:
    """Ensure a Unity Catalog volume directory exists (creates parents; idempotent if already present).

    Uses Files API PUT /api/2.0/fs/directories — same as ``WorkspaceClient.files.create_directory``.
    """
    if not isinstance(directory_path, str) or not directory_path.startswith("/Volumes/"):
        raise ValueError("directory_path must be an absolute UC volume path starting with /Volumes/")
    if ".." in directory_path:
        raise ValueError("invalid directory_path")
    w.files.create_directory(directory_path)


def safe_volume_filename(file_name: str) -> str:
    return file_name.replace("/", "_").replace("\\", "_")


def _put_bytes_to_volume(volume_file_path: str, content: bytes) -> None:
    import httpx as _httpx

    api_path = f"/api/2.0/fs/files{volume_file_path}"
    token = get_auth_token()
    resp = _httpx.put(
        f"{w.config.host}{api_path}",
        headers={"Authorization": f"Bearer {token}"},
        content=content,
        timeout=60,
    )
    resp.raise_for_status()


def upload_to_volume(content: bytes, claim_id: int, file_name: str) -> str:
    """Persist under claim_<id>/ (same layout as document uploads)."""
    safe_name = safe_volume_filename(file_name)
    claim_dir = f"{VOLUME_PATH}/claim_{claim_id}"
    ensure_uc_volume_directory(claim_dir)
    volume_file_path = f"{claim_dir}/{safe_name}"
    _put_bytes_to_volume(volume_file_path, content)
    return volume_file_path


def upload_claim_document_with_retry(
    content: bytes,
    claim_id: int,
    file_name: str,
    *,
    attempts: int = 2,
) -> Tuple[Optional[str], Optional[str]]:
    """Upload to UC Volume with retries. Returns (storage_path, error_message_if_failed)."""
    last_err: Optional[str] = None
    for i in range(attempts):
        try:
            path = upload_to_volume(content, claim_id, file_name)
            return path, None
        except Exception as e:
            last_err = str(e)
            _logger.warning(
                "Volume upload attempt %s/%s failed for claim=%s file=%s: %s",
                i + 1,
                attempts,
                claim_id,
                file_name,
                e,
            )
            if i + 1 < attempts:
                time.sleep(0.5 * (i + 1))
    return None, last_err


def upload_to_volume_new_claim_staging(content: bytes, file_name: str) -> str:
    """Stage new-claim preview images until the claim row exists."""
    safe_name = safe_volume_filename(file_name)
    staging_id = str(uuid.uuid4())
    staging_dir = f"{VOLUME_PATH}/new_claim_preview/{staging_id}"
    ensure_uc_volume_directory(staging_dir)
    volume_file_path = f"{staging_dir}/{safe_name}"
    _put_bytes_to_volume(volume_file_path, content)
    return volume_file_path


def try_stage_new_claim_image(content: bytes, file_name: str) -> Optional[str]:
    """Save to staging; return path or None if volume write fails (AI can still run)."""
    try:
        return upload_to_volume_new_claim_staging(content, file_name)
    except Exception as e:
        _logger.warning("Staging new-claim damage image to volume failed (continuing with AI only): %s", e)
        return None


def is_valid_preview_staging_path(path: str) -> bool:
    prefix = f"{VOLUME_PATH}/new_claim_preview/"
    return isinstance(path, str) and path.startswith(prefix) and ".." not in path


def download_from_volume(volume_path: str) -> tuple[bytes, str]:
    import httpx as _httpx

    api_path = f"/api/2.0/fs/files{volume_path}"
    token = get_auth_token()
    resp = _httpx.get(
        f"{w.config.host}{api_path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "application/octet-stream")
    return resp.content, content_type
